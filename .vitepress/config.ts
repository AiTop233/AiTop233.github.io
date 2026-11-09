import { defineConfig } from 'vitepress'
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from 'fs'
import { fileURLToPath } from 'url'
import { join, resolve } from 'path'

// 站点根目录（.vitepress 的上一级）。sitemap 与 lastmod 都要用它。
const ROOT = fileURLToPath(new URL('..', import.meta.url))

// 换域名只改这一处：canonical / og:url / sitemap / robots 全部跟着走
const SITE = 'https://aitop233.github.io'
const SITE_NAME = '资源合集'
const SITE_DESC =
  '互联网优质资源分享 - 影视、电子书、教程、软件、音乐等网盘资源合集'
const OG_IMAGE = `${SITE}/og-cover.png`

// 分类定义 - 在这里增删分类
const categories = [
  { text: 'B站课程', link: '/bilibili/' },
  { text: '极客时间', link: '/geektime/' },
  { text: '影视', link: '/movies/' },
  { text: '电子书', link: '/ebooks/' },
  { text: '教程', link: '/tutorials/' },
  { text: '软件', link: '/software/' },
  { text: '音乐', link: '/music/' },
]

/** 相对路径 → 规范 URL。index.md → /，geektime/index.md → /geektime/ */
function pageUrl(relativePath: string): string {
  const p = relativePath.replace(/\.md$/, '')
  if (p === 'index') return `${SITE}/`
  if (p.endsWith('/index')) return `${SITE}/${p.slice(0, -'index'.length)}`
  return `${SITE}/${p}`
}

/** 页面标题（VitePress 已拼好「页名 | 站名」），用于 og:title */
function pageTitle(pageData: any): string {
  const raw = pageData.frontmatter?.title || pageData.title || SITE_NAME
  return raw.includes(SITE_NAME) ? raw : `${raw} | ${SITE_NAME}`
}

/** JSON-LD 内联时把 < 转义，避免标题里的字符提前闭合 script */
function jsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, '\\u003c')
}

export default defineConfig({
  // ==================== 站点信息 ====================
  lang: 'zh-CN',
  title: SITE_NAME,
  description: SITE_DESC,

  // ==================== 头部标签 ====================
  // 只放「全站相同」的；每页不同的（canonical / og:title / 结构化数据）
  // 由下面的 transformHead 生成，避免同一页出现两个 canonical
  head: [
    ['meta', { name: 'theme-color', content: '#ffffff' }],
    ['meta', { name: 'format-detection', content: 'telephone=no' }],
    ['meta', { property: 'og:site_name', content: SITE_NAME }],
    ['meta', { property: 'og:locale', content: 'zh_CN' }],
    ['link', { rel: 'icon', href: '/favicon.ico', sizes: '32x32' }],
    ['link', { rel: 'icon', href: '/favicon.svg', type: 'image/svg+xml' }],
    ['link', { rel: 'apple-touch-icon', href: '/apple-touch-icon.png', sizes: '180x180' }],
    // 站长平台验证：拿到自己的码后填在这里，原来那两行是占位符，等于没验证
    // ['meta', { name: 'baidu-site-verification', content: 'code-xxxxxxxx' }],
    // ['meta', { name: 'google-site-verification', content: 'xxxxxxxx' }],
  ],

  // ==================== URL 配置 ====================
  base: '/',
  srcDir: '.',
  outDir: '.vitepress/dist',
  // README.md 是项目说明，不是站点内容：不构建、不进 sitemap
  srcExclude: ['README.md', 'node_modules/**', 'dist/**'],
  cleanUrls: true,
  lastUpdated: true,

  // ==================== 主题 ====================
  appearance: {
    initialValue: 'light',
  },

  // ==================== 导航栏 ====================
  themeConfig: {
    nav: [{ text: '首页', link: '/' }, ...categories],

    sidebar: {
      '/bilibili/': sidebarCategory('B站付费课程'),
      '/geektime/': sidebarCategory('极客时间'),
      '/movies/': sidebarCategory('影视'),
      '/ebooks/': sidebarCategory('电子书'),
      '/tutorials/': sidebarCategory('教程'),
      '/software/': sidebarCategory('软件'),
      '/music/': sidebarCategory('音乐'),
    },

    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索资源' },
          modal: {
            displayDetails: '显示详情',
            resetButtonTitle: '清除',
            backButtonTitle: '返回',
            noResultsText: '没有找到相关资源',
            footer: {
              selectText: '选择',
              navigateText: '切换',
              closeText: '关闭',
            },
          },
        },
      },
    },

    footer: {
      message: '互联网资源合集 · 仅供学习交流',
      copyright: `© ${new Date().getFullYear()} AiTop233 · Powered by VitePress`,
    },

    lastUpdated: {
      text: '最后更新于',
      formatOptions: { dateStyle: 'short', timeStyle: 'short' },
    },

    outline: {
      level: [2, 3],
      label: '页面导航',
    },

    socialLinks: [{ icon: 'github', link: 'https://github.com/AiTop233' }],
  },

  // ==================== Markdown 配置 ====================
  markdown: {
    lineNumbers: true,
  },

  // ==================== 每页头部：canonical / OG / 结构化数据 ====================
  transformHead({ pageData }) {
    const url = pageUrl(pageData.relativePath)
    const isHome = url === `${SITE}/`
    const is404 = pageData.relativePath.includes('404')
    const title = pageTitle(pageData)
    const desc = pageData.frontmatter?.description || pageData.description || SITE_DESC

    const tags: any[] = [
      // 上一版把 canonical 写死成首页地址，等于告诉搜索引擎
      // 「这些页面都是首页的副本」——这是整站不被单独收录的头号原因
      ['link', { rel: 'canonical', href: url }],
      // 分类页是列表不是文章，用 article 会要求 published_time 之类的字段
      ['meta', { property: 'og:type', content: 'website' }],
      ['meta', { property: 'og:title', content: title }],
      ['meta', { property: 'og:description', content: desc }],
      ['meta', { property: 'og:url', content: url }],
      ['meta', { property: 'og:image', content: OG_IMAGE }],
      ['meta', { property: 'og:image:width', content: '1200' }],
      ['meta', { property: 'og:image:height', content: '630' }],
      ['meta', { property: 'og:image:alt', content: '网盘资源合集 · 影视、课程、电子书与教程' }],
      ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
      ['meta', { name: 'twitter:title', content: title }],
      ['meta', { name: 'twitter:description', content: desc }],
      ['meta', { name: 'twitter:image', content: OG_IMAGE }],
      [
        'meta',
        {
          name: 'robots',
          content: is404
            ? 'noindex,follow'
            : 'index,follow,max-snippet:-1,max-image-preview:large',
        },
      ],
    ]

    if (is404) return tags

    // 面包屑：搜索结果里能显示「资源合集 › 极客时间」，比裸链接点击率高
    if (!isHome) {
      tags.push([
        'script',
        { type: 'application/ld+json' },
        jsonLd({
          '@context': 'https://schema.org',
          '@type': 'BreadcrumbList',
          itemListElement: [
            { '@type': 'ListItem', position: 1, name: '首页', item: `${SITE}/` },
            {
              '@type': 'ListItem',
              position: 2,
              name: pageData.frontmatter?.title || pageData.title,
              item: url,
            },
          ],
        }),
      ])
    }

    // 首页的 WebSite + SearchAction 写在 index.md 的 frontmatter 里，
    // 这里再生成一遍就重复了
    if (isHome) return tags

    const page: Record<string, unknown> = {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: title,
      description: desc,
      url,
      inLanguage: 'zh-CN',
      isPartOf: { '@type': 'WebSite', name: SITE_NAME, url: `${SITE}/` },
    }
    if (pageData.lastUpdated) {
      page.dateModified = new Date(pageData.lastUpdated).toISOString()
    }
    tags.push(['script', { type: 'application/ld+json' }, jsonLd(page)])

    return tags
  },

  // ==================== Sitemap ====================
  // 扫实际产出的 HTML，而不是手写清单：新增分类页不会漏
  buildEnd: async ({ outDir }) => {
    const entries: { loc: string; lastmod: string; changefreq: string; priority: string }[] = []

    const walk = (dir: string) => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, e.name)
        if (e.isDirectory()) {
          if (e.name === 'assets') continue
          walk(full)
          continue
        }
        if (!e.name.endsWith('.html') || e.name === '404.html') continue

        const rel = full.slice(outDir.length + 1).replace(/\\/g, '/')
        const srcRel = rel === 'index.html'
          ? 'index.md'
          : rel.replace(/index\.html$/, 'index.md').replace(/\.html$/, '.md')
        const srcPath = resolve(ROOT, srcRel)
        const lastmod = existsSync(srcPath)
          ? statSync(srcPath).mtime.toISOString()
          : new Date().toISOString()

        const loc = rel === 'index.html'
          ? `${SITE}/`
          : `${SITE}/${rel.replace(/index\.html$/, '').replace(/\.html$/, '')}`
        const depth = loc.replace(SITE, '').split('/').filter(Boolean).length

        entries.push({
          loc,
          lastmod,
          changefreq: depth === 0 ? 'daily' : 'weekly',
          priority: depth === 0 ? '1.0' : depth > 1 ? '0.7' : '0.8',
        })
      }
    }

    walk(outDir)
    entries.sort((a, b) => b.priority.localeCompare(a.priority) || a.loc.localeCompare(b.loc))

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries.map((e) => `  <url>
    <loc>${e.loc}</loc>
    <lastmod>${e.lastmod.slice(0, 10)}</lastmod>
    <changefreq>${e.changefreq}</changefreq>
    <priority>${e.priority}</priority>
  </url>`).join('\n')}
</urlset>
`
    writeFileSync(join(outDir, 'sitemap.xml'), xml, 'utf8')
    console.log(`✅ sitemap.xml：${entries.length} 条`)

    // 404 不进 sitemap 也不该被收录；主题不提供这个钩子，构建后补一个 noindex
    const p404 = join(outDir, '404.html')
    if (existsSync(p404)) {
      const html = readFileSync(p404, 'utf8')
      if (!html.includes('name="robots"')) {
        writeFileSync(
          p404,
          html.replace('<head>', '<head>\n    <meta name="robots" content="noindex,follow">'),
          'utf8',
        )
      }
    }
  },
})

// 生成侧边栏的辅助函数
function sidebarCategory(title: string) {
  return [
    {
      text: title,
      items: [{ text: '全部资源', link: '.' }],
    },
  ]
}
