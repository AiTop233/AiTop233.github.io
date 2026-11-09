# 前端工程：网盘自动上传

> 通用规则见《前端工程规范》；本文件只写本项目与默认不同的地方。
> 目录 / 文件：服务端 `src/panup/web/`，前端 `src/panup/web/static/`；样式与令牌见 `DESIGN_SYSTEM.md`。

## 1. 入口与路由

- 目录 / 文件：`src/panup/web/api.py`（FastAPI 应用与 REST 路由）、`src/panup/web/static/index.html` + `app.js` + `styles.css`（免构建 SPA，原生 JS）
- 路由 / 布局 / 页面壳：单页四标签（上传 / 记录 / 监控 / 设置），顶部标签切换、无路由跳转；`GET /` 返回 index.html；API 全部在 `/api/*` 下
- 权限入口：无登录（本机回环地址 127.0.0.1 单人使用；不做账号体系，与 PRD「不做」一致）

## 2. 组件边界

- 目录 / 文件：`static/app.js` 内按区块组织为独立函数组件（renderUpload / renderRecords / renderRules / renderSettings），共享 state 对象；不引入框架
- 组件目录、顶层组件：上传区（拖拽区**支持文件夹与多选** + 已选资源清单 + 表单 + **进度卡片** + 结果列表）、记录表、规则卡片列表、设置表单、状态灯条
- 选择区（I-018）：拖拽区（点击选文件 / 拖入即读）+ `[选择文件夹]`（`<input webkitdirectory>`）+ `[清空已选]` + 已选资源小标签（名字 + 文件数 + 大小）。拖放递归用 `webkitGetAsEntry()`（`readEntries` 读到空为止），拿不到就退回 `files` 平铺；前端按与后端同一套 D-007 规则算「资源数」只用于摘要与落点预览
- 进度卡片（I-019 / I-018）：标题行（任务标题 + 阶段句）、每盘一行（盘名 / 进度条 / 状态文字 / 当前文件名）、飞书一行、进展时间线（**最新在上**，最多回看 40 条）。批量时多一层：**资源清单**（资源名 / 进度条 / 状态，进度条定宽、状态右对齐），下方只展开「当前」资源的分盘明细与时间线；组件边界是 `renderBatch(batch)`，单资源时退化为原来的样子
- 结果卡片：单资源沿用旧样子；多个资源按资源分组（资源名 + 「文件夹 · N 个文件」+ 飞书写入状态），组内是各盘链接与提取码，右上角「复制全部链接」
- 浮层：无模态框（错误用顶部提示条，确认用原生 confirm）

## 3. 状态归属

- 目录 / 文件：`app.js` 顶层 `state = {status, options, picked, tasks, failures, busy, batch, batchTimer, lastResult}`
- 局部（表单输入）留在 DOM；跨区块共享数据（记录 / 规则 / 状态 / 表单选项）统一放 state，由 API 响应整体刷新；URL 不承载状态（单用户本地页）
- `state.picked` 是 `[{file, rel}]`：`rel` 是浏览器里的相对路径（拖文件夹时形如 `剧A/第1集.mp4`），上传时原样作为 `paths` 交给服务端，前端不重排、不改名
- 进度是唯一「高频」状态：`state.batch` 存最近一次批次快照，`state.batchTimer` 存 `setInterval` 句柄；任务结束必须 `clearInterval`（`stopBatchPolling()`）
- `state.lastResult` 存最后一次结果，供「复制全部链接」按资源拼文本（不把长文本塞进 DOM 属性）

## 4. 数据访问

- 目录 / 文件：`app.js` 顶部 `api()` 封装（fetch + JSON + 错误规整）；全部走 `/api/*`
- 上传用 `XMLHttpRequest`（`uploadWithProgress`）：`fetch` 拿不到上传字节进度，而「把文件交给本地服务」这一段也要给人看见；服务端 `202 {batch_id}` 后转 `GET /api/batches/{id}` 轮询（0.5 秒，一次取回整批）
- 数据层、缓存、错误分类：不做本地缓存（每次操作后重拉对应区块）；错误按 HTTP 状态 + 响应体 code/hint 归类，hint 直接展示

## 5. 运行时错误与日志

- 目录 / 文件：`app.js` `showToast()` 统一出口
- 全局错误出口：所有 fetch 失败 → toast「发生了什么 + 怎么办」；未捕获异常 → console.error + toast 通用文案
- 上报去向 / 采样 / 开关：不上报（本机工具）；服务端日志照常落 `logs/`
- trace 关联：前端不生成 trace；展示服务端返回的 code 便于对照 `docs/errors.md`

## 6. 复用单元

- 目录 / 文件：`app.js` 内 `fmtTime / fmtSize / api / showToast / esc` 工具函数；不建抽象层
- hook / composable / 工具：无框架，不用 hook

## 7. 样式与令牌

- 目录 / 文件：`static/styles.css`；语义变量（`--c-*` / `--fs-*` / `--sp-*`）定义在文件顶部，数值唯一真源在此
- 见 `DESIGN_SYSTEM.md`；本文件只写代码层约定：纯 CSS，不引框架、不用预处理器

## 8. 测试与目录

- 目录 / 文件：`tests/test_web_upload.py`（FastAPI TestClient 打桩 core）、`tests/test_batch.py`（inbox 落盘与分组、批量接口、全局单并发）、`tests/test_jobs.py`（进度板状态机）
- 测试位置、e2e、目录：API 契约测试（路由 / 状态码 / 错误信封）；SPA 交互不写自动化（人验收）；不引 e2e 框架
