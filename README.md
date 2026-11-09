# 资源站（VitePress）

原 `D:/Coding/ZCode/18线资源（Github网站）`，2026-11-09 以 `git subtree` 并入本仓库，提交历史完整保留。

- 线上：<https://aitop233.github.io>（GitHub Pages，由站点仓库的 Actions 构建）
- 远端仓库：`https://github.com/AiTop233/AiTop233.github.io`（部署源，仍未变）
- 技术栈：VitePress 1.x + 原生 Vue 组件，无后端

## 目录

```
site/
├── data/resources.json        ← 唯一内容源（540 条：分类 / 标题 / 链接 / 提取码 / 备注）
├── index.md                   ← 首页（分类卡片，数量从 JSON 算）
├── bilibili/ geektime/ movies/ ebooks/ tutorials/ software/ music/
│   └── index.md               ← 分类页：import JSON，只负责渲染
├── .vitepress/
│   ├── config.ts              ← 导航、侧边栏、sitemap
│   └── theme/                 ← ResourceCard 组件与自定义样式
├── tools/
│   ├── add.mjs                ← 追加资源（唯一写入点）
│   └── extract.mjs            ← 一次性迁移工具：从旧 markdown 内联数组抽 JSON
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
- 按 `--link` 去重：已存在的链接直接跳过（退出码 2），加 `--force` 才会覆盖
- 批量：`npm run add -- --json '[{...},{...}]'` 或 `--json -` 从 stdin 读
- 先看会改什么：加 `--dry-run`
- 写完跑 `npm run build` 自查，再提交

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
