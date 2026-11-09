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

## 2026-11-09（第六次会话记录）
- 做了：I-004 人验收通过，合并 main（80af384）、分支已删；验收结果回填、看板重整（[core]/[drivers] 阶段 1 清空）
- 停在：main；开工 I-005 飞书 Writer
- 下次：I-005 代码（mock 测试先行）→ 人侧准备：飞书开放平台建自建应用拿 app_id/app_secret 存 secrets/feishu_app.json + 文档授权给应用 → 真实验收（上传 --doc feishu → 文档出现一行可点击链接）

## 2026-11-09（第七次会话记录）
- 做了：I-005 实现并转「待验收」——writers/feishu.py（tenant_access_token + docx 追加带超链接块），8 例新测（全套 67 例绿）、变异检查过；分支 I-005-feishu-writer 未合并
- A6 单测调整：feishu 注册后「未启用」提示改用不存在写入端名验证（原语义不变）
- 停在：main；等 I-005 人验收（人侧前置：飞书应用 + secrets/feishu_app.json + config.toml [feishu].doc_token + 文档授权）
- 下次：I-005 验收通过后合并 → I-006 监控自动上传收尾 B1

## 2026-11-09（第八次会话记录）
- 做了：I-006 实现并转「待验收」——watcher（轮询/稳定判定/重试/熔停/单实例锁）+ panup watch 子命令；8 例新测（全套 75 例绿）+ 变异检查；真实验收：监控目录丢 5 文件全部自动上传到 /panup验收-监控/26/11/09（含失败自动补传），运行期无重复
- 真实运行抓出三个 bug（单测没暴露）：JsonLogger 实例不可调用、夸克多级目录需逐级建、cli 项目根算错致台账落 src/data——均已修复合并进 I-006 分支
- B1 代码全部完成；两条分支待验收：I-005（writers）、I-006（watcher，分支叠加在 I-005 上）
- 停在：main；等飞书应用配置后一并验收 I-005 + I-006-A3
- 下次：验收通过 → 按链序合并两条分支 → B1 收尾（更新 BACKEND 密钥清单）；之后进入「后续阶段」选题

## 2026-11-09（第九次会话记录 · 规划）
- 做了：规划访谈 + 阶段 2 立项——Web 端提前（本地网页管理台 F4 + 目录约定自动化 F5）；技术栈 FastAPI + uvicorn + 免构建 SPA（零依赖条款修订为「依赖最小集合」）；目录约定 `网盘@远端目录`（`__` 分隔层级、一律加年/月/日、文件名不编码）；新建 FRONTEND.md / DESIGN_SYSTEM.md；PRD / ARCHITECTURE / BACKEND / AGENTS / DECISIONLOG（D-002）/ 看板同步完成；B2 四个 issue（I-007～I-010）已建待办
- 待办提醒：PRD「需求质量清单」新增 F4 / F5 条目后需人复勾；requirements.txt 将在 I-007 落地（fastapi / uvicorn 锁版本）
- 停在：main；声明回到执行模式
- 下次：开工 I-007（Web 服务骨架）；并行等飞书应用验收 B1 尾巴

## 2026-11-09（第十次会话记录）
- 做了：飞书写权限复探——写仍 1770032（读正常），诊断收敛为「应用在目标文档上没有可编辑权限」：读通 + 写禁说明版本已发布、只读范围已生效，缺的是文档侧授权；修复步骤已列给人。I-007 实现并转「待验收」——web/api.py（FastAPI 骨架 + {code,msg,hint} 错误信封 + 回环锁死）、页面壳（四标签 + 状态灯区）、core.check_all（BACKEND §2 声明的公开函数落地）、serve 子命令、requirements.txt；14 例新测（全套 73 例绿）+ 变异检查 + 真实起服自验（三灯真实返回、404 信封、局域网口拒连）
- [补空白] TestClient 需要 httpx（starlette 传递依赖）：装为测试依赖并在 requirements.txt 注明「非运行时」，运行时仍只有 fastapi + uvicorn（AGENTS §11 条款 2 集合不变）
- 停在：main（转待验收例外）；分支 I-007-web-skeleton 未合并
- 下次：人验收 I-007（浏览器开 http://127.0.0.1:8256）→ I-008 上传 + 记录 SPA；飞书权限修好后一并验收 I-005 / I-006

## 2026-11-09（第十一次会话记录）
- 做了：飞书权限修复（人把文档应用改「可编辑」）后真实验收 I-005（3 行格式正确、链接可点击；A4 两类报错实测带指引、上传不受阻）与 I-006（A2～A4：甲乙丙自动上传含日期目录、丙 → 文档行、重启不重传）；两分支按链序合并 main（f2c736a、ad4cbbe）、分支已删——B1 全部完成
- 验收抓出：I-006 分支建得早、未含 I-005 后期三个 feishu 修复——监控甲/乙上传成功但文档行 404；链合并后丙验证通过（教训记入 I-006 过程记录：源分支修 bug 后叠加分支要再 merge 源分支）
- 人指出追加行写法与其文档版式不符（其版式：h2「YYMMDD 主题」插最顶 +「盘名：链接」行、pwd 内嵌 URL、无时间无文件名行）→ 记 I-012（[writers]）；涉 PRD F3 格式，转待办前需规划模式改 PRD F3 + DECISIONLOG
- 停在：main；B1 完成；B2 进行中（I-007 待验收）
- 下次：规划模式改 PRD F3 + DECISIONLOG（D-003）→ I-012 转待办并实施「固定更新规则」；I-007 浏览器验收；I-008 开工

## 2026-11-09（第十二次会话记录）
- 做了：D-003 落地——I-012「固定更新规则」实现并转「待验收」：feishu.append_record 改为向文档最顶插小节（h2「YYMMDD 文件名」+「盘名：链接?pwd=提取码」行；插在首个标题块前、无标题块则 0），writers/base 契约说明同步；测试重写 14 例（全套 81 例绿）+ 变异检查；真实自验：夸克 / 百度 CLI 各传一个 + 监控丢一个，文档顶部三节最新在最前、pwd 内嵌、链接可点
- 过程：① 代删文档末尾旧行踩 batch_delete 参数坑（body 需 start_index + end_index 且 end_index 为开区间），文档已清干净（API 形状记入 I-012 过程记录）；② 期间误把 main 快进到未验收提交，已用 update-ref 挪回 bc86d9e——教训：转「待验收」前不在 main 上做任何 merge 动作
- 停在：main（转待验收例外）；分支 I-012-feishu-section-rule 未合并
- 下次：人验收 I-012（文档顶部三节 + 点链接）→ 合并收尾；I-007 浏览器验收；I-008 开工

## 2026-11-09（第十三次会话记录）
- 做了：I-012 人验收通过（A2～A5 全部核验、链接可点），合并 main（aa7e293）、验收结果表回填、看板移入已完成；I-007 验收前按回程护栏合并 main——`cli.py` 冲突两边保留（watch + serve 并存）、修正 `test_output_sorted_by_name` 对全局 writer 注册表的隐式依赖（89 例绿，提交 c9d1e73），起 127.0.0.1:8256 实机给人看，三灯全绿（百度「在阴天大雨」/ 夸克 / 飞书）
- [补空白] 环境：本机 `pip` 指向 anaconda、`python` 是另一套 3.13，装依赖必须 `python -m pip install -r requirements.txt`（已记 I-007 过程记录）
- 停在：main；I-007 待人验收（分支 I-007-web-skeleton）
- 下次：人验收 I-007（A2 页面壳 / A3 Ctrl+C / A4 一条命令起服）→ I-008；另：人提出「标题名由他开工前给定、需协定传递方式」，讨论中，定案后记想法并走规划模式改 PRD F3
