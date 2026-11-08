# DEVLOG

## 2026-11-09
- 做了：立项会话——按规范建文档层（PRD / ARCHITECTURE / BACKEND / 看板 + I-001～I-006 / AGENTS）；访谈确认产品形态（CLI + 监控自动化）、网盘接入（cookie 方案，参考 alist）、飞书先行；对标 pantools.cn 调研完成
- 环境确认：系统 Python 3.13.9，零第三方依赖起步；git 全局署名已报人确认
- 停在：git init 待做——等人选公开面路线、确认署名与 .gitignore 清单
- 下次：完成建仓（首提交 + 回程护栏）→ 按 AGENTS.md 开工做 I-001（项目骨架：配置 / 密钥 / 错误 / 日志底座）

## 2026-11-09（第二次会话记录）
- 做了：git 建仓（公开面 B 私有仓、署名与 .gitignore 经人确认、首提交 4fa3f42、回程护栏装好）；I-001 完成（整单模型验收）——config / errors / log 底座 + config.example.toml，单测 13 例全绿、变异检查通过，合并 58754c6
- [补空白] config.py 复用 core/errors.py 的统一错误类型（零依赖叶子，仅错误类型）——ARCHITECTURE 模块表 config 行「允许依赖 —」需补注「core.errors（仅错误类型）」，待规划模式同步后追加 [已同步]
- 停在：main；B1 继续
- 下次：I-002 百度驱动移植（drivers/baidu.py）。人验收 A2～A6 需要百度登录态：把 cookie 放 secrets/baidu_cookies.json 或环境变量 BAIDU_COOKIE

## 2026-11-09（第三次会话记录）
- 做了：I-002（百度驱动）与 I-003（夸克驱动）实现并转「待验收」——Driver 基类 + 注册表、契约测试 25 例新增（全套 38 例绿）、两个变异检查均红→还原→绿；两条分支叠加（I-003 基于 I-002 分支），均未合并，等验收
- 关键来源：百度=移植本人已验证实现；夸克=alist drivers/quark_uc（上传/列目录/建目录）+ 社区分享接口（/share → /task 轮询 → /share/password），端点已写进各驱动 docstring
- 待验收：I-002、I-003（整单人验收，需要两个网盘的真实 cookie）
- 停在：main；等 I-002 / I-003 验收
- 下次：验收通过后按链序合并 → I-004 上传管道 + CLI（依赖两条驱动在 main）

## 2026-11-09（第四次会话记录）
- 做了：I-002 / I-003 真实验收通过（登录助手弹窗扫码取 cookie → secrets/；真实上传 + 分享链接由人打开确认「正常」）；两分支按链序合并 main、已删分支；38 例单测绿
- [补空白] 新增 `panup/login_helper.py`（登录助手：本机 Playwright 弹官方登录窗口，cookie 落 secrets/）——属入口类薄壳，ARCHITECTURE 模块表待补注
- I-004 验收标准修订：新增 A7（`--date-dir` 按日期建远端子目录），人原话已记录
- 停在：main；B1 剩 I-004 → I-005 → I-006
- 下次：I-004 上传管道 + CLI（台账、去重、status 子命令；驱动已在 main）

## 2026-11-09（第五次会话记录）
- 做了：I-004 实现并转「待验收」——管道（去重/日期子目录/writer 挂载点）+ SQLite 台账 + CLI（upload/status/check），21 例新测（全套 59 例绿），真实验收 A2～A7 全过（含 /panup验收/26/11/09 日期目录）
- Git Bash 教训：`--dir` 会吃 MSYS 路径转换，命令需 `MSYS_NO_PATHCONV=1` 前缀（已写进 I-004 怎么验收；AGENTS 常用命令补注待规划确认）
- 停在：main；等 I-004 人验收
- 下次：I-005 飞书 Writer 代码先行（mock 测试可写）；**人验收前需要你在飞书开放平台建自建应用**（app_id/app_secret → secrets/feishu_app.json，并把目标文档授权给应用）——到时我列步骤
