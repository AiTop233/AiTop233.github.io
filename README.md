# 资源站（VitePress）

原 `D:/Coding/ZCode/18线资源（Github网站）`，2026-11-09 以 `git subtree` 并入本仓库，提交历史完整保留。

- 线上：<https://aitop233.github.io>（GitHub Pages，由站点仓库的 Actions 构建）
- 远端仓库：`https://github.com/AiTop233/AiTop233.github.io`（部署源，仍未变）
- 技术栈：VitePress 1.x + 原生 Vue 组件，无后端

## 目录

```
site/
├── data/resources.json        ← 唯一内容源（540 条：分类 / 标题 / 链接（可多盘）/ 提取码 / 备注）
├── index.md                   ← 首页（分类卡片，数量从 JSON 算）
├── bilibili/ geektime/ movies/ ebooks/ tutorials/ software/ music/
│   └── index.md               ← 分类页：import JSON，只负责渲染
├── .vitepress/
│   ├── config.ts              ← 导航、侧边栏、sitemap
│   └── theme/                 ← ResourceCard 组件与自定义样式
├── tools/
│   ├── add.mjs                ← 追加资源（唯一写入点）
│   ├── extract.mjs            ← 一次性迁移工具：从旧 markdown 内联数组抽 JSON
│   ├── gen-assets.py          ← 生成 favicon / 分享图（产物已提交，改了才需要重跑）
│   ├── seo-check.mjs          ← 检查构建产物的 SEO（canonical / sitemap / 结构化数据）
│   └── ping.mjs               ← 把 sitemap 主动推给百度 / IndexNow
└── .github/workflows/deploy.yml  ← 站点仓库的构建部署（在本仓库不生效，见下）
```

## 加一条资源

```bash
cd site
npm run add -- --category movies --title "片名" \
  --link https://pan.quark.cn/s/xxxx --code 8x2k --size 12.5GB --note "4K 中字"
```

- 分类只能是 `bilibili / geektime / movies / ebooks / tutorials / software / music`
- 极客时间要带 `--group column`（专栏课）或 `--group video`（视频课）
- 一个资源同时传了多个盘时用 `--links`（卡片会按盘列出多条，各带各的提取码）：

```bash
npm run add -- --category movies --title "片名" --links '[
  {"pan":"baidu","url":"https://pan.baidu.com/s/xxx","code":"k9x2"},
  {"pan":"quark","url":"https://pan.quark.cn/s/yyy"}
]'
```

  数据结构上 `links` 是权威，`link` / `code` 保留成第一条的镜像，旧读法照常可用
- 按链接去重：任意一条链接已存在就跳过（退出码 2），加 `--force` 才替换
- 批量：`npm run add -- --json '[{...},{...}]'` 或 `--json -` 从 stdin 读
- 先看会改什么：加 `--dry-run`
- 写完跑 `npm run build` 自查，再提交

## SEO

改配置时最容易被忽略的一点：**每页的 canonical 必须是它自己**。上一版把 canonical 写死成
`https://aitop233.github.io`，等于告诉搜索引擎「所有分类页都是首页的副本」，这是整站不被单独收录的头号原因。

现在这些都从 `config.ts` 一处生成，`SITE` 常量换域名时全部跟着走：

| 项目 | 做法 |
|---|---|
| canonical / og:url | `transformHead` 按页面路径生成，一页一个，不再重复 |
| 分享卡片 | og:title / description / image（1200×630，`public/og-cover.png`） |
| 结构化数据 | 首页 `WebSite`+`SearchAction`，分类页 `CollectionPage` + `BreadcrumbList` |
| 标题层级 | 每条资源是 `<h3>` 且带锚点（`#java并发-a1b2`），可深链；`ignore-header` 让它不进右侧大纲 |
| sitemap | 扫实际产出的 HTML，带 `lastmod`，新增分类页不会漏 |
| robots | `Allow: /`，不屏蔽 `/assets/`（Google 要抓 CSS 才能完整渲染） |
| 404 | `noindex`，不进 sitemap |

```bash
npm run verify      # 构建 + 检查，提交前跑一遍
npm run assets      # 改了站点名/主色后重新生成图标与分享图
```

自查脚本检查的是**产物**而不是配置，覆盖：canonical 唯一且指向自己、标题不重复、description 长度、
JSON-LD 可解析、h1 唯一、favicon 存在、sitemap 覆盖所有页面、资源卡是否真的 SSR 进了 HTML。

### 主动提交（可选）

```bash
npm run ping -- --dry-run                 # 先看会提交哪些 URL
BAIDU_TOKEN=xxx npm run ping              # 百度站长平台的 token
INDEXNOW_KEY=xxx npm run ping             # 还需先建 public/<key>.txt，内容就是这串 key
```

GitHub Pages 的服务器在境外，百度抓取间隔很长，主动推送能把收录从天级压到小时级。两个通道独立，没配就跳过。

## 本地预览

```bash
cd site
npm ci          # 首次；已装过可跳过
npm run dev     # http://localhost:5173
npm run preview # 预览构建产物
```

> 本机 `npm run build` 若报 `safe-delete ... ETIMEDOUT`，是当前沙箱的删除拦截：先 `rm -rf .vitepress/dist .vitepress/cache` 再构建即可，与项目无关。

## 部署（两个仓库的关系）

`site/` 是本仓库里的**编辑副本**，线上仍由 `AiTop233.github.io` 仓库发布：

```bash
git subtree push --prefix=site site-pages main
```

`site-pages` 指向 `https://github.com/AiTop233/AiTop233.github.io.git`。这条命令把 `site/` 下的提交原样推过去，站点仓库收到 push 后由 `.github/workflows/deploy.yml` 构建并发布到 Pages。

- 已核对：`git subtree split --prefix=site` 的结果与站点仓库 HEAD 完全一致（`ffe0389`），可安全快进
- `site/.github/workflows/deploy.yml` 在**本仓库**不会被触发（GitHub 只读根目录的 `.github/workflows`）；它属于站点仓库
- 若以后改回 Vercel：在 Vercel 建项目时 Root Directory 填 `site`，其余走默认的 VitePress 预设即可

## 与 panup 的关系（待接）

`data/resources.json` 是为同步准备的写入点：panup 上传成功后把「标题 + 分享链接 + 提取码 + 大小」通过 `tools/add.mjs` 追加即可，不需要改页面。映射规则（哪个目录进哪个分类、多盘资源显示哪条链接）尚未定，见 `docs/issues/I-026.md`。
