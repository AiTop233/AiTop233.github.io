# 后端工程：网盘中控台

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
  - `web/inbox.py`：浏览器上传的字节 → inbox 目录树 → 「资源」列表（落盘清洗、按顶层目录分组，阶段 2）
  - `web/jobs.py`：上传任务进度板（内存态，管道 `progress` 事件 → `GET /api/jobs/{id}` / `GET /api/batches/{id}` 快照，阶段 2）
  - `web/convention.py`：目录约定解析（`网盘@远端目录` → 规则，阶段 2）
  - `sources/base.py`、`sources/link.py`、`sources/pansou.py`：资源发现（阶段 3，未实现）
  - `transforms/base.py`、`transforms/name.py`：资源加工（阶段 3，未实现）
  - `core/line.py`：产线编排（发现 → 获取 → 加工 → 投放，阶段 3，未实现）
  - `web/static/`：SPA 前端（index.html / app.js / styles.css，免构建）
- 与 ARCHITECTURE 模块分类的对应：drivers / writers / core / cli / watcher / web / config 一一对应，目录一致。
- 运行时第三方依赖（阶段 2 起放宽零依赖，AGENTS §11 条款 2）：`fastapi`、`uvicorn`（版本锁定在 requirements.txt）。

## 2. 接口与契约

- 代码位置：`drivers/base.py`、`writers/base.py`、`core/pipeline.py`、`web/api.py`
- Driver 基类（语义对齐 alist 的 Driver 接口，裁剪为本项目所需子集）：
  - `auth_check() -> dict`：校验登录态，返回账号与容量摘要；失效抛 `AuthError`
  - `mkdir(remote_dir) -> dict`：建目录，已存在视为成功（幂等），父目录自动创建
  - `upload(local_path, remote_dir, *, overwrite=True, on_progress=None) -> dict`：分片上传，返回远端路径与大小；秒传命中时跳过字节上传
  - `share(remote_path, *, pwd=None, period_days=0) -> dict`：创建分享链接，返回链接、提取码、有效期；`pwd=None` 按各盘默认（百度随机 4 位、夸克不带，D-014），返回的 `pwd` 为空串即该盘无提取码
  - `publish(local_path, remote_dir, **kwargs) -> dict`：mkdir + upload + share 一步到位
  - `list(remote_dir) -> list`：列目录（阶段 1 仅百度完整实现，夸克按需）
  - `delete(remote_path) -> dict`：删远端文件或整个目录（服务端递归），返回 `{path, deleted, missing}`；`missing=True` 表示远端本来就没有（幂等，不算失败）。基类默认实现报 `PUP-107`「驱动不支持删除」，百度/夸克已实现；根目录拒绝（`PUP-108`）
- Writer 基类：
  - `auth_check() -> dict`：凭证可用性检查
  - `append_task(task) -> dict`：向目标文档写入**一节**；`task = {title, filename, date, items: [{pan, link, pwd}]}`，`items` **只含成功的网盘**、按驱动注册顺序排列（版式与插入位置按 PRD F3：h2「YYMMDD 标题名」小节插最顶 + 每个成功盘一行「盘名：链接?pwd=提取码」）
- core 公开函数（未来 Web / 桌面 / MCP 入口共用）：
  - `publish_task(local_path, targets, *, title=None, writer_names=None, force=False, date_dir=False, period_days=0, on_progress=None, progress=None) -> dict`：**多盘上传任务**；`local_path` 可以是**单个文件或一个文件夹**；`targets = [{pan, remote_dir}]`，逐盘跑单盘管道（某盘失败不影响其他盘），全部跑完后**只写一次**文档；返回 `{group_id, title, items, failed, writers}`
    - `progress`：结构化进度旁路（回调收到字典事件，形状见本节「进度事件」）；回调抛异常一律吞掉，**进度不许反噬上传**
    - `on_progress`：驱动级 `(已传字节, 文件大小)` 回调，CLI 进度条沿用
    - 每盘落点为 `remote_dir/[日期/]标题/` 的资源文件夹，文件夹内按本地相对路径镜像；单文件也建这一层
    - **同名资源文件夹已存在 → 抛 `UploadError`（码 `PUP-3xx`）并提示换标题**，不合并、不覆盖；重传走 `group_id` 复用，不触发该检查
    - 重传（`force=True`）时，网盘上已存在且大小一致的文件跳过，只补缺的和坏的
  - `publish_file(local_path, pan, remote_dir, *, …) -> dict`：单盘特例（watcher 与既有调用方），内部转 `publish_task` 的单个 target
  - `check_all() -> dict`：各网盘与写入端登录态体检
- 错误契约：对外只抛 `ProjectError` 子类（`AuthError` / `UploadError` / `ShareError` / `WriterError` / `ConfigError`），携带 `code`、上游 `errno` 与「怎么办」恢复指引；不向调用方裸抛网络异常。

### 阶段 3 契约草案（设计，未实现；语义见 `SOURCES.md`）

- `Source` 基类（`sources/base.py`，与 Driver 同样用 `@register` 登记）：
  - `name: str`；`kinds: set[str]`（如 `{"search"}`）
  - `discover(query: dict, *, limit: int = 20) -> list[Candidate]`：只产出元数据，**不下载、不上传**（AC-09）
  - `Candidate = {source, ref, title, pan, pwd, size, file_count, created_at, score, extra}`；`ref` 是「怎么拿到它」的凭据（本地路径 / `pan + share_id` / 搜索结果的唯一 id）
- `Transform` 基类（`transforms/base.py`）：
  - `order: int`；`apply(res: Resource, *, ctx: dict) -> Resource`：只改名字与结构，**不改内容**（F8 边界）
  - `Resource = {title, files: [{rel, size, abs?}], pan, remote_path?}`；纯函数，不抛网络异常
- Driver 增量（向后兼容，不改既有方法签名）：
  - `capabilities: frozenset[str] = {"mkdir", "upload", "share", "list"}`；转存源加 `"save_share"`，能服务端改名加 `"rename"`
  - `supports(cap) -> bool`
  - `resolve_share(url, pwd="") -> {pan, share_id, name, files, size}`：解析分享链接（不落地）
  - `save_share(resolved, dest_dir) -> {path, task_id}`：转存进本账号（服务端操作）
  - `rename(remote_path, new_name) -> {path}`：服务端改名
  - 三者默认抛 `UploadError(code="PUP-42x", hint="该网盘不支持转存/改名")`，**不用异常探测能力**（AC-10）
- `run_line(line_cfg, *, ledger, progress=None) -> dict`：一条产线跑一轮，返回 `{line, picked, acquired, published, failed, skipped}`；内部串行、单轮上限、连续失败停机（AC-11）
- 台账增量（`uploads` 表，迁移同 I-017 的 `_migrate()` 套路）：
  - `origin TEXT`（`local` / `link` / `search`）、`source_ref TEXT`（原分享链接，脱敏后可展示）、`line TEXT`（产线名）
  - 目的：同一资源既能查「我传的」也能查「我转的」，重传与巡检都要靠它
- 热度表（阶段 3 第二段）：
  - `heat_sample(id, kw, sampled_at, total, new_links, unique_sources, alive_links)`，唯一索引 `(kw, sampled_at)`
  - `heat_score(kw, day, velocity, breadth, alive_rate, heat_pct, confidence)`：每天算一次落库，榜直接读表，不在请求里现算
  - 分发落地页事件：`share_view(slug, at, kind)`，`kind ∈ view / intent / copy`
- REST 草案：`POST /api/links`（粘贴链接 → 候选）、`POST /api/search`（关键词 → 候选池）、`GET /api/candidates?line=`、`POST /api/lines/{name}/run`、`GET /api/lines`、`GET /api/heat?days=7`

- REST API（阶段 2，全部挂 `/api/*`，只监听 127.0.0.1）：
  - `POST /api/upload`（multipart：`files` 多值 + `paths`［JSON 数组，与 files 一一对应的相对路径，空则退回文件名］+ `pans`［JSON 数组，每项 `{pan, dir}`，`dir` 留空回退配置］+ `title` + `date_dir` + `doc` + `sync`）；旧字段 `file`（单值）仍收
    - 落盘：`data/inbox/<时间戳-随机>/<相对路径>`，逐段清洗（去掉 `\ / : * ? " < > |`、丢 `..`），保留拖进来的目录结构
    - 分组（D-007）：每个**顶层目录** = 一个资源；无目录的散文件合成一个资源（只有一个时就地当资源）。「资源」= 一个以标题命名的网盘文件夹 = 飞书一节
    - 标题：只有一个资源时表单 `title` 生效；多个资源时各用各自名字，`title` 忽略（前端已禁用输入框）
    - 默认（`sync` 缺省）：落盘分组后建 batch + 每资源一个 job，后台**串行**跑，立刻 `202 {batch_id, status:"running", count, resources:[{job_id, title, kind, file_count, size}]}`
    - `sync=1`：同步逐资源跑完，返回 `{count, resources:[{group_id, title, items, failed, writers}]}`（测试与 curl 用）
    - 拒收：没有文件 `PUP-401`；`paths` 与文件数不符 / 不是 JSON `PUP-411`；写入 inbox 失败（磁盘满、Windows 路径过长）`PUP-413`；空内容 `PUP-414`
  - `GET /api/jobs/{job_id}` → 单资源进度快照 `{id, status, stage, title, filename, kind, file_count, size, pans, writer, steps, result, error, created_at, updated_at}`；`status ∈ running/done/failed`，未知任务 404 信封。job 只在内存（进程退出即丢），最终事实看台账
  - `GET /api/batches/{batch_id}` → 整批快照 `{batch_id, status, count, ok, failed, created_at, resources:[job 快照…]}`；`status ∈ running/done`（任一资源未结束即 running）
  - `GET /api/options` → `{pans: [{name, default_dir}]}`：表单把 `default_dir` 回填进目录框（配置缺项给空串，不报错）
  - `GET /api/uploads?limit=&status=` → 台账记录列表（按 `group_id` 聚合展示，`status=failed` 即「待修」）；`POST /api/uploads/{id}/retry` → 失败项重传（只重跑该「资源 × 网盘」，跳过已成功的文件）
  - `POST /api/uploads/{id}/delete-remote` → 删掉这条记录的远端目录（`remote_path`），台账行置 `deleted`、`link`/`pwd` 清空（行保留可追溯）；已删过的再调返回 `skipped`；远端本来就不存在时 `missing:true` 也算成功（幂等）
  - `POST /api/remote/delete`（JSON `{pan, path}`）→ 按显式路径删远端目录，用于台账里查不到的路径（如整批验收目录）；该前缀下的成功记录一并标 `deleted`（返回 `records` 为受影响行数）。两道闸：`pan` 必须是已注册网盘（否则 `PUP-405`），`path` 不许是根目录（`PUP-108`）
  - `GET /api/status` → 各网盘与写入端登录态体检（三灯）
  - `GET /api/rules` / `PUT /api/rules`（阶段 1 固定规则）；约定目录模式下由 convention 扫描动态生成（F5）
  - `GET /api/config` / `PUT /api/config` → 白名单配置项（默认目录、飞书 doc_token、监控参数）
  - 错误信封：`{code, msg, hint}`，HTTP 状态 4xx/5xx；前端直接展示 msg + hint
- 进度事件（`publish_task(progress=…)` → `web/jobs.py` 聚合，BACKEND 与前端共用同一套字段）：

| 事件 | 字段 | 时机 |
|---|---|---|
| `scanning` | `kind`、`file_count`、`size`、`title`、`pans` | 资源归一完成后（任务板据此建各盘行） |
| `checking` | `pan`、`path` | 单盘开头，查台账去重与同名冲突前 |
| `skipped` | `pan`、`link`、`path` | 台账已有 success 记录，直接复用链接 |
| `mkdir` | `pan`、`path` | 资源文件夹建好 |
| `uploading` | `pan`、`file_index`、`file`、`bytes_done`、`bytes_total` | 每个文件开始时一次 + 驱动每次字节回调（`bytes_*` 按**整个资源**累计） |
| `sharing` | `pan`、`path` | 文件传完，创建分享链接 |
| `done` | `pan`、`link`、`pwd`、`path` | 单盘成功 |
| `failed` | `pan` 或 `writer`、`code`、`msg`、`hint` | 单盘 / 写入端失败（不中断其他盘） |
| `writing` / `done` / `failed` | `writer`（`done`/`failed` 同 `pan` 字段位） | 写入端开始 / 成功 / 失败 |
| `finished` | — | 任务收尾（任务板随后置 `status=done`） |

  整体阶段由任务板推导：`queued`（未扫描）→ `uploading`（还有盘未结束）→ `writing`（盘都结束且写入端在写）→ `finalizing` → `finished`；任务级异常走 `fail(code,msg,hint)` 置 `status=failed`。

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

- 代码位置：`watcher.py`、`web/api.py`（Web 上传任务线程）、`web/inbox.py`（接收与分组）、`web/jobs.py`（进度板）
- 任务清单：
  - 目录监控循环（轮询，间隔默认 5 秒，可配置）
  - Web 上传任务：每个 `POST /api/upload` 起一个 daemon 线程，按提交顺序**逐个资源**跑 `publish_task`，整批跑完即退；每个资源自建、自关 SQLite 连接（连接不跨线程）
- 重入 / 锁：监控循环有单实例文件锁 `data/watch.lock`，防止双开导致重复上传。Web 侧是**全局单并发**（D-007）：`threading.Lock` 以「资源」为粒度加锁，同一时刻整个进程只有一个上传任务在动网盘与台账；第二个批次在锁外排队，页面显示「排队中」。理由：驱动单线程顺序传、台账是无 WAL 的单文件 SQLite（并发写会 `database is locked`）、网盘分享接口易被限频，且同名文件夹检查是「查了再建」，并发会撞。进度板 `JobStore` 用 `threading.RLock` 保护读写，整批登记后再统一淘汰（按最大批大小抬高保留量）
- 死信与重试：单文件失败重试 3 次（退避 5 / 15 / 60 秒），仍失败台账记 `failed`；连续失败 5 个文件则停止循环并醒目提示；不做自动无限重试。Web 任务失败写 `job.error`（`{code,msg,hint}`）并照常写台账；**一个资源失败不中断同批其他资源**；进度板只保留最近 50 个任务 / 10 个批次

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
