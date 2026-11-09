# 后端工程：网盘自动上传

> 通用规则见《后端工程规范》；本文件只写本项目与默认不同的地方。
> 每个单位都写「代码位置」；没有额外约定的单位写「按 04 默认」，不硬造。
> 目录约定：源码在 `src/panup/`，测试在 `tests/`，运行期数据在 `data/`（台账）、`logs/`（日志）、`secrets/`（凭据），三者均不入仓库。

## 1. 模块

- 代码位置：`src/panup/`
- 模块清单与职责：
  - `drivers/base.py`：Driver 基类与注册表（新网盘在此登记）
  - `drivers/baidu.py`：百度网盘客户端（移植自本人已验证的网页版接口实现，端点与参数以它为准）
  - `drivers/quark.py`：夸克网盘客户端（参考 alist quark 驱动的接口流程自建，风格对齐 baidu.py）
  - `writers/base.py`：Writer 基类与注册表
  - `writers/feishu.py`：飞书文档写入端
  - `core/pipeline.py`：上传管道（编排去重 → 建目录 → 上传 → 分享 → 写入 → 台账）
  - `core/ledger.py`：台账读写（SQLite）
  - `core/errors.py`：错误类型与项目错误码
  - `core/log.py`：JSON lines 日志
  - `config.py`：配置与密钥加载、启动校验
  - `cli.py`（含 `__main__.py`）：命令入口
  - `watcher.py`：目录监控循环（阶段 2 支持约定目录动态规则）
  - `web/api.py`：本地管理台服务端（FastAPI REST + 托管 SPA，阶段 2）
  - `web/convention.py`：目录约定解析（`网盘@远端目录` → 规则，阶段 2）
  - `web/static/`：SPA 前端（index.html / app.js / styles.css，免构建）
- 与 ARCHITECTURE 模块分类的对应：drivers / writers / core / cli / watcher / web / config 一一对应，目录一致。
- 运行时第三方依赖（阶段 2 起放宽零依赖，AGENTS §11 条款 2）：`fastapi`、`uvicorn`（版本锁定在 requirements.txt）。

## 2. 接口与契约

- 代码位置：`drivers/base.py`、`writers/base.py`、`core/pipeline.py`、`web/api.py`
- Driver 基类（语义对齐 alist 的 Driver 接口，裁剪为本项目所需子集）：
  - `auth_check() -> dict`：校验登录态，返回账号与容量摘要；失效抛 `AuthError`
  - `mkdir(remote_dir) -> dict`：建目录，已存在视为成功（幂等），父目录自动创建
  - `upload(local_path, remote_dir, *, overwrite=True, on_progress=None) -> dict`：分片上传，返回远端路径与大小；秒传命中时跳过字节上传
  - `share(remote_path, *, pwd=None, period_days=0) -> dict`：创建分享链接，返回链接、提取码、有效期
  - `publish(local_path, remote_dir, **kwargs) -> dict`：mkdir + upload + share 一步到位
  - `list(remote_dir) -> list`：列目录（阶段 1 仅百度完整实现，夸克按需）
- Writer 基类：
  - `auth_check() -> dict`：凭证可用性检查
  - `append_task(task) -> dict`：向目标文档写入**一节**；`task = {title, filename, date, items: [{pan, link, pwd}]}`，`items` **只含成功的网盘**、按驱动注册顺序排列（版式与插入位置按 PRD F3：h2「YYMMDD 标题名」小节插最顶 + 每个成功盘一行「盘名：链接?pwd=提取码」）
- core 公开函数（未来 Web / 桌面 / MCP 入口共用）：
  - `publish_task(local_path, targets, *, title=None, writer_names=None, force=False, date_dir=False, period_days=0) -> dict`：**多盘上传任务**；`local_path` 可以是**单个文件或一个文件夹**；`targets = [{pan, remote_dir}]`，逐盘跑单盘管道（某盘失败不影响其他盘），全部跑完后**只写一次**文档；返回 `{group_id, title, items, failed, writers}`
    - 每盘落点为 `remote_dir/[日期/]标题/` 的资源文件夹，文件夹内按本地相对路径镜像；单文件也建这一层
    - **同名资源文件夹已存在 → 抛 `UploadError`（码 `PUP-3xx`）并提示换标题**，不合并、不覆盖；重传走 `group_id` 复用，不触发该检查
    - 重传（`force=True`）时，网盘上已存在且大小一致的文件跳过，只补缺的和坏的
  - `publish_file(local_path, pan, remote_dir, *, …) -> dict`：单盘特例（watcher 与既有调用方），内部转 `publish_task` 的单个 target
  - `check_all() -> dict`：各网盘与写入端登录态体检
- 错误契约：对外只抛 `ProjectError` 子类（`AuthError` / `UploadError` / `ShareError` / `WriterError` / `ConfigError`），携带 `code`、上游 `errno` 与「怎么办」恢复指引；不向调用方裸抛网络异常。
- REST API（阶段 2，全部挂 `/api/*`，只监听 127.0.0.1）：
  - `POST /api/upload`（multipart：`files` 可多个 + `paths` 与之一一对应的相对路径 + `pans`［JSON 数组，每项 `{pan, dir}`］+ `title` + `date_dir` + `doc`）→ `{group_id, title, items, failed, writers}`；只传一个文件时 `paths` 就是文件名
  - `GET /api/uploads?limit=&status=` → 台账记录列表（按 `group_id` 聚合展示，`status=failed` 即「待修」）；`POST /api/uploads/{id}/retry` → 失败项重传（只重跑该「资源 × 网盘」，跳过已成功的文件）
  - `GET /api/status` → 各网盘与写入端登录态体检（三灯）
  - `GET /api/rules` / `PUT /api/rules`（阶段 1 固定规则）；约定目录模式下由 convention 扫描动态生成（F5）
  - `GET /api/config` / `PUT /api/config` → 白名单配置项（默认目录、飞书 doc_token、监控参数）
  - 错误信封：`{code, msg, hint}`，HTTP 状态 4xx/5xx；前端直接展示 msg + hint

## 3. 数据与存储

- 代码位置：`core/ledger.py`
- 存储选型：SQLite 单文件 `data/ledger.db`（标准库 `sqlite3`）
- 核心表：`uploads`（id、**group_id**（任务号，同一次上传的各盘记录相同）、local_path（资源路径：文件路径或文件夹路径）、**kind**［file / folder］、**file_count**（资源内文件数）、file_hash（资源指纹：单文件 = 文件 sha256；文件夹 = 相对路径 + 大小的摘要）、size（资源总大小）、pan、**remote_path（资源文件夹路径）**、link、pwd、**title**（任务标题，各盘行冗余存同一值）、status［success / failed / pending］、error_code、created_at、updated_at）
- 索引与去重：唯一索引 `(local_path, file_hash, pan, remote_path)` 保留（历史记录仍受约束）；**资源级去重不再靠台账**——以网盘上「同名资源文件夹是否存在」为准（单盘管道先 `list` 父目录、命中即报错），台账只负责记录与展示；`group_id` 建普通索引供记录页聚合
- 软删、迁移策略：阶段 1 无软删；建表一次成型，字段变更用 ALTER + 版本标记（见第 11 节）

## 4. 用例

- 代码位置：`core/pipeline.py`
- 事务边界：**单个文件的上传**是最小写入单元，**「一个资源 × 一个网盘」是成败单元**。资源内任一文件失败 → 该盘记 `failed`，已传成功的文件不删（留给重传复用）；一个任务含多盘时各盘独立成败，某盘失败不回滚其他盘、不阻断后续盘；单个文件分片中断 → 台账记 `pending`，下次重传整个文件（明确不做断点续传）
- 校验位置：管道入口校验资源存在且可读（文件或目录）、标题可用、网盘与目录参数合法、`targets` 非空且盘名已注册；config 启动时校验必填项
- 幂等与重传：**新上传**以「目标盘上同名资源文件夹是否存在」为准，存在即报错（`file_hash` 不再承担去重）；**重传**（`force=True` + 同一 `group_id`）跳过网盘上已存在且大小一致的文件，只传缺的和坏的；同一任务内某盘已有 `success` 记录 → 该盘直接复用链接

## 5. 后台任务

- 代码位置：`watcher.py`
- 任务清单：目录监控循环（轮询，间隔默认 5 秒，可配置）
- 重入 / 锁：单实例文件锁 `data/watch.lock`，防止双开导致重复上传
- 死信与重试：单文件失败重试 3 次（退避 5 / 15 / 60 秒），仍失败台账记 `failed`；连续失败 5 个文件则停止循环并醒目提示；不做自动无限重试

## 6. 外部依赖

- 代码位置：`drivers/baidu.py`、`drivers/quark.py`、`writers/feishu.py`
- 第三方服务：百度网盘网页接口（pan.baidu.com）、夸克网盘网页接口（drive-pc.quark.cn 等）、飞书开放平台（open.feishu.cn）
- 超时：每个 HTTP 请求 60 秒
- 重试：临时性错误（限频、5xx）按指数退避重试 3 次；`AuthError` 不重试，直接报错并给恢复指引
- 降级 / 熔断：阶段 1 不做熔断；writer 失败不阻塞上传（链接已在台账），仅记失败
- 限频：批量场景逐文件串行，间隔 ≥ 1 秒（AC-08）

## 7. 错误与状态

- 代码位置：`core/errors.py`
- 错误码目录：项目码 `PUP-1xx`（配置 / 管道）与网盘 errno 透传 `PAN-<盘>-<errno>`，常量表建在 `core/errors.py`，文档 `docs/errors.md` 执行期建；百度 errno 中文对照表随驱动移植沿用
- 对外文案与可重试性：每类错误输出「发生了什么 + 怎么办」（例：cookie 失效 → 提示重新登录并导出 cookie 到 `secrets/`）；可重试性随 code 标注（retriable / fatal）

## 8. 鉴权与权限

- 代码位置：`config.py`、`secrets/`
- 使用主体：单人自用
- 账号 / 角色 / 数据范围：无账号体系；凭据即权限——网盘 cookie（百度 BDUSS / STOKEN，夸克登录 cookie）、飞书自建应用 `app_id` / `app_secret`；数据范围 = 本人各网盘与指定飞书文档
- 明确不做：不做账号 / 角色 / 组织 / 成员邀请（多用户列 PRD「后续阶段」）

## 9. 配置与密钥

- 代码位置：`config.py`；配置模板 `config.example.toml`（入库），实际 `config.toml` 不入库
- 配置项：各网盘默认上传目录、监控根目录与「网盘 + 目标目录」映射（阶段 2 起另有约定目录模式）、监控间隔与稳定判定时长、飞书目标文档 token、日志目录、`[web] port`（默认 8256）
- 密钥来源：环境变量（`BAIDU_COOKIE` / `QUARK_COOKIE`）优先于 `secrets/` 文件（`baidu_cookies.json`、`quark_cookie.txt`、`feishu_app.json`）
- 启动检查：watch 与 upload 启动时校验必需项，缺项一次性列出全部缺失清单后退出，不用默认值顶替（AC-06 的配置面）

## 10. 日志、指标与告警

- 代码位置：`core/log.py`
- 档位：本地小工具
- 事件目录：`upload.start / upload.success / upload.failed`、`resource.conflict`（网盘已存在同名资源文件夹）、`file.skipped`（重传跳过已存在文件）、`task.started / task.finished`（含 `group_id`、盘数、成功与失败数）、`share.created`、`writer.appended / writer.failed`、`watch.file_detected / watch.dedup_skipped`、`auth.expired`
- 去向与格式：JSON lines，`logs/panup-YYYYMMDD.log`，每行 `{ts, event, level, pan, file, code, msg}`
- 保留、采样、脱敏：按天滚动保留 30 天（启动时清理过期文件）；全量记录不采样；不记录 cookie、secret、提取码（AC-05）
- 查询入口：`grep '"event":"upload.failed"' logs/*.log`
- 告警：无自动告警；watch 连续失败时在控制台输出醒目提示（见第 5 节）

## 11. 数据迁移

- 代码位置：`core/ledger.py`
- 迁移工具：无外部工具；阶段 1 建表一次成型。后续字段变更在此单位登记做法（ALTER + 版本标记）后另行实现
- 2026-11-09（I-015）：`uploads` 加 `group_id TEXT` 与 `title TEXT`；启动时检测缺列则 `ALTER TABLE ADD COLUMN`，存量行 `group_id` 回填 `legacy-<id>`、`title` 留空（记录页对空标题回退显示文件名）；不重建表、不丢数据
- 2026-11-09（I-017）：`uploads` 加 `kind TEXT`（存量行回填 `file`）与 `file_count INTEGER`（存量回填 `1`）；`remote_path` 语义由「文件路径」改为「资源文件夹路径」，**历史行保持原值不改**（记录页只展示，不参与新逻辑）；去重改由「网盘同名文件夹」判定，原唯一索引保留兜底

## 12. 测试

- 代码位置：`tests/`
- 契约测试：同一套 Driver 契约用例跑所有驱动实现（mock 上游响应），新驱动接入即受约束
- 复现测试：错误码 → 文案映射；去重与幂等（同参数二次调用返回已有记录）
- 外部依赖替身：驱动与 writer 的 HTTP 层打桩（monkeypatch 客户端请求函数），测试不真连网盘与飞书；真连只在人验收时发生
- 关键路径：publish 成功链路、去重命中、cookie 失效报错、writer 失败不阻塞上传、watch 稳定判定
