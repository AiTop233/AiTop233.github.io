import { defineConfig } from 'vitepress'
import { SitemapStream, streamToPromise } from 'sitemap'
import { createWriteStream } from 'fs'
import { resolve } from 'path'

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

export default defineConfig({
  // ==================== 站点信息 ====================
  lang: 'zh-CN',
  title: '资源合集',
  description: '互联网优质资源分享 - 影视、电子书、教程、软件、音乐等网盘资源合集',

  // ==================== SEO 头部标签 ====================
  head: [
    ['meta', { name: 'google-site-verification', content: 'YOUR_VERIFICATION_CODE' }],
    ['meta', { name: 'baidu-site-verification', content: 'YOUR_BAIDU_CODE' }],

    // Open Graph (分享到社交平台时显示)
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:site_name', content: '资源合集' }],
    ['meta', { property: 'og:locale', content: 'zh_CN' }],

    // Favicon
    ['link', { rel: 'icon', href: '/favicon.ico' }],

    // Canonical URL
    ['link', { rel: 'canonical', href: 'https://aitop233.github.io' }],
  ],

  // ==================== URL 配置 ====================
  base: '/',
  srcDir: '.',
  outDir: '.vitepress/dist',
  cleanUrls: true,
  lastUpdated: true,

  // ==================== 主题 ====================
  appearance: {
    initialValue: 'light',
  },

  // ==================== 导航栏 ====================
  themeConfig: {
    // 网站 logo
    logo: '',

    // 顶部导航
    nav: [
      { text: '首页', link: '/' },
      ...categories,
    ],

    // 侧边栏 (按分类)
    sidebar: {
      '/bilibili/': sidebarCategory('B站付费课程'),
      '/geektime/': sidebarCategory('极客时间'),
      '/movies/': sidebarCategory('影视'),
      '/ebooks/': sidebarCategory('电子书'),
      '/tutorials/': sidebarCategory('教程'),
      '/software/': sidebarCategory('软件'),
      '/music/': sidebarCategory('音乐'),
    },

    // 搜索
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

    // 页脚
    footer: {
      message: '互联网资源合集 · 仅供学习交流',
      copyright: `© ${new Date().getFullYear()} AiTop233 · Powered by VitePress`,
    },

    // 编辑链接
    editLink: {
      pattern: 'https://github.com/AiTop233/AiTop233.github.io/edit/main/:path',
      text: '在 GitHub 上编辑此页',
    },

    // 最后更新时间
    lastUpdated: {
      text: '最后更新于',
      formatOptions: { dateStyle: 'short', timeStyle: 'short' },
    },

    // 大纲
    outline: {
      level: [2, 3],
      label: '页面导航',
    },

    // 社交链接
    socialLinks: [
      { icon: 'github', link: 'https://github.com/AiTop233' },
    ],
  },

  // ==================== Markdown 配置 ====================
  markdown: {
    lineNumbers: true,
  },

  // ==================== Sitemap 自动生成 ====================
  buildEnd: async ({ outDir }) => {
    const pages = [
      { url: '/', changefreq: 'daily', priority: 1.0 },
      { url: '/bilibili/', changefreq: 'weekly', priority: 0.9 },
      { url: '/geektime/', changefreq: 'weekly', priority: 0.9 },
      { url: '/movies/', changefreq: 'weekly', priority: 0.8 },
      { url: '/ebooks/', changefreq: 'weekly', priority: 0.8 },
      { url: '/tutorials/', changefreq: 'weekly', priority: 0.8 },
      { url: '/software/', changefreq: 'weekly', priority: 0.8 },
      { url: '/music/', changefreq: 'weekly', priority: 0.8 },
    ]

    const sitemap = new SitemapStream({ hostname: 'https://aitop233.github.io' })
    const writeStream = createWriteStream(resolve(outDir, 'sitemap.xml'))

    sitemap.pipe(writeStream)
    pages.forEach(p => sitemap.write(p))
    sitemap.end()

    await streamToPromise(sitemap)
    console.log('✅ sitemap.xml 已生成')
  },

  // ==================== HTML 变换 ====================
  transformHtml: async (code, id, context) => {
    // 在页面 <head> 中注入 Schema.org 面包屑结构化数据
    if (id === 'index.md') return code
    return code
  },
})

// 生成侧边栏的辅助函数
function sidebarCategory(title: string) {
  return [
    {
      text: title,
      items: [
        { text: '全部资源', link: '.' },
      ],
    },
  ]
}
