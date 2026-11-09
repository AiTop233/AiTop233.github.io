# 前端工程：网盘自动上传

> 通用规则见《前端工程规范》；本文件只写本项目与默认不同的地方。
> 目录 / 文件：服务端 `src/panup/web/`，前端 `src/panup/web/static/`；样式与令牌见 `DESIGN_SYSTEM.md`。

## 1. 入口与路由

- 目录 / 文件：`src/panup/web/api.py`（FastAPI 应用与 REST 路由）、`src/panup/web/static/index.html` + `app.js` + `styles.css`（免构建 SPA，原生 JS）
- 路由 / 布局 / 页面壳：单页四标签（上传 / 记录 / 监控 / 设置），顶部标签切换、无路由跳转；`GET /` 返回 index.html；API 全部在 `/api/*` 下
- 权限入口：无登录（本机回环地址 127.0.0.1 单人使用；不做账号体系，与 PRD「不做」一致）

## 2. 组件边界

- 目录 / 文件：`static/app.js` 内按区块组织为独立函数组件（renderUpload / renderRecords / renderRules / renderSettings），共享 state 对象；不引入框架
- 组件目录、顶层组件：上传区（拖拽区**支持文件夹** + 表单 + 结果列表）、记录表、规则卡片列表、设置表单、状态灯条
- 浮层：无模态框（错误用顶部提示条，确认用原生 confirm）

## 3. 状态归属

- 目录 / 文件：`app.js` 顶层 `state = {records, rules, status, config}`
- 局部（表单输入）留在 DOM；跨区块共享数据（记录 / 规则 / 状态）统一放 state，由 API 响应整体刷新；URL 不承载状态（单用户本地页）

## 4. 数据访问

- 目录 / 文件：`app.js` 顶部 `api()` 封装（fetch + JSON + 错误规整）；全部走 `/api/*`
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

- 目录 / 文件：`tests/test_web_api.py`（FastAPI TestClient 打桩 core）
- 测试位置、e2e、目录：API 契约测试（路由 / 状态码 / 错误信封）；SPA 交互不写自动化（人验收）；不引 e2e 框架
