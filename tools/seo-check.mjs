#!/usr/bin/env node
/**
 * SEO 自查：直接检查构建产物，而不是检查配置。
 *
 * 为什么要这一步：上一版的 canonical 写死在配置里，构建不报错、页面能打开、
 * 看上去一切正常，但搜索引擎认为每页都是首页的副本。这类问题只有把产物读出来
 * 才看得见，所以把它做成断言。
 *
 * 用法：npm run seo:check（先 npm run build）
 */

import { readFileSync, readdirSync, existsSync } from 'fs'
import { join, relative } from 'path'

const DIST = '.vitepress/dist'
const SITE = 'https://aitop233.github.io'

const problems = []
const checks = []
const fail = (msg) => problems.push(msg)
const pass = (msg) => checks.push(msg)

if (!existsSync(DIST)) {
  console.error(`没有找到 ${DIST}，先跑 npm run build`)
  process.exit(2)
}

function walk(dir, acc = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'assets') continue
      walk(full, acc)
    } else if (e.name.endsWith('.html')) {
      acc.push(full)
    }
  }
  return acc
}

const files = walk(DIST)
const pages = files.filter((f) => !f.endsWith('404.html'))

/** 取某个标签的属性；找不到返回 null */
function meta(html, attr, name) {
  const re = new RegExp(`<meta[^>]+${attr}="${name}"[^>]+content="([^"]*)"`, 'i')
  const alt = new RegExp(`<meta[^>]+content="([^"]*)"[^>]+${attr}="${name}"`, 'i')
  return (html.match(re) || html.match(alt) || [])[1] ?? null
}

function canonical(html) {
  return (html.match(/<link[^>]+rel="canonical"[^>]+href="([^"]*)"/i) || [])[1] ?? null
}

function linkHref(html, rel) {
  const re = new RegExp(`<link[^>]+rel="${rel}"[^>]+href="([^"]*)"`, 'i')
  const alt = new RegExp(`<link[^>]+href="([^"]*)"[^>]+rel="${rel}"`, 'i')
  return (html.match(re) || html.match(alt) || [])[1] ?? null
}

const titles = new Map()
const canonicals = new Map()

for (const file of pages) {
  const html = readFileSync(file, 'utf8')
  const rel = relative(DIST, file).replace(/\\/g, '/')

  // 1. 每页必须有且只有一个 canonical，且指向自己
  const canon = canonical(html)
  const all = html.match(/rel="canonical"/g) || []
  if (!canon) {
    fail(`${rel}: 缺少 canonical`)
  } else if (all.length > 1) {
    fail(`${rel}: canonical 出现 ${all.length} 次`)
  } else {
    const expected = rel === 'index.html'
      ? `${SITE}/`
      : `${SITE}/${rel.replace(/index\.html$/, '').replace(/\.html$/, '')}`
    if (canon.replace(/\/$/, '') !== expected.replace(/\/$/, '')) {
      fail(`${rel}: canonical 指向 ${canon}，应为 ${expected}`)
    }
    if (canonicals.has(canon)) {
      fail(`${rel}: canonical 与 ${canonicals.get(canon)} 重复`)
    }
    canonicals.set(canon, rel)
  }

  // 2. 标题唯一且非空（重复标题在搜索结果里会互相挤掉）
  const t = (html.match(/<title>([\s\S]*?)<\/title>/) || [])[1]?.trim()
  if (!t) fail(`${rel}: <title> 为空`)
  else if (titles.has(t)) fail(`${rel}: 标题「${t}」与 ${titles.get(t)} 重复`)
  else titles.set(t, rel)

  // 3. 描述要有，且长度合适（太短等于没写，太长被截断）
  const desc = meta(html, 'name', 'description')
  if (!desc) fail(`${rel}: 缺少 description`)
  else if (desc.length < 20) fail(`${rel}: description 过短（${desc.length} 字）`)

  // 4. 分享卡片三件套
  for (const [attr, name] of [['property', 'og:title'], ['property', 'og:image'], ['property', 'og:url']]) {
    if (!meta(html, attr, name)) fail(`${rel}: 缺少 ${name}`)
  }

  // 5. 结构化数据必须能解析（拼错的 JSON-LD 会被静默忽略）
  const blocks = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
  if (!blocks.length) fail(`${rel}: 没有 JSON-LD`)
  blocks.forEach((b, i) => {
    try {
      JSON.parse(b[1])
    } catch {
      fail(`${rel}: 第 ${i + 1} 段 JSON-LD 不是合法 JSON`)
    }
  })

  // 6. 页面要有 h1，且只有一个
  const h1 = (html.match(/<h1[\s>]/g) || []).length
  if (h1 !== 1) fail(`${rel}: h1 有 ${h1} 个，应为 1 个`)

  // 7. favicon 指向的文件必须真的存在
  const icon = linkHref(html, 'icon')
  if (icon && icon.startsWith('/')) {
    if (!existsSync(join(DIST, icon))) fail(`${rel}: favicon ${icon} 不存在`)
  }
}

// 8. sitemap 覆盖所有页面、无重复、无 404
const sitemapPath = join(DIST, 'sitemap.xml')
if (!existsSync(sitemapPath)) {
  fail('缺少 sitemap.xml')
} else {
  const xml = readFileSync(sitemapPath, 'utf8')
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1])
  if (new Set(locs).size !== locs.length) fail('sitemap 有重复 URL')
  if (locs.some((l) => l.includes('404'))) fail('sitemap 里不应该有 404')
  for (const file of pages) {
    const rel = relative(DIST, file).replace(/\\/g, '/')
    const url = rel === 'index.html'
      ? `${SITE}/`
      : `${SITE}/${rel.replace(/index\.html$/, '').replace(/\.html$/, '')}`
    if (!locs.includes(url)) fail(`sitemap 漏了 ${url}`)
  }
  if (locs.length !== pages.length) fail(`sitemap ${locs.length} 条，页面 ${pages.length} 个`)
  pass(`sitemap 覆盖 ${locs.length} 个页面`)
}

// 9. robots 要指向 sitemap，且别把资源目录挡掉
const robotsPath = join(DIST, 'robots.txt')
if (!existsSync(robotsPath)) {
  fail('缺少 robots.txt')
} else {
  const txt = readFileSync(robotsPath, 'utf8')
  if (!/Sitemap:\s*https?:\/\//i.test(txt)) fail('robots.txt 没有 Sitemap 行')
  if (/Disallow:\s*\/assets/i.test(txt)) fail('robots.txt 屏蔽了 /assets，Google 会渲染不完整')
}

// 10. 404 必须 noindex
const p404 = join(DIST, '404.html')
if (existsSync(p404) && !readFileSync(p404, 'utf8').includes('noindex')) {
  fail('404.html 没有 noindex，会被当成正常页面收录')
}

// 11. 资源卡必须真的渲染进 HTML（JS 渲染的内容爬虫可能看不到）
const geek = readFileSync(join(DIST, 'geektime/index.html'), 'utf8')
const cardCount = (geek.match(/class="card-title[\s"]/g) || []).length
if (cardCount < 100) fail(`极客时间页只渲染出 ${cardCount} 条资源卡，SSR 可能失效`)
else pass(`极客时间页 SSR 渲染 ${cardCount} 条资源卡`)
const h3Count = (geek.match(/<h3[^>]+class="card-title[\s"]/g) || []).length
if (h3Count !== cardCount) fail(`资源卡有 ${cardCount} 个，但只有 ${h3Count} 个用了 h3`)

console.log(`\n检查 ${pages.length} 个页面\n`)
checks.forEach((c) => console.log(`  ok  ${c}`))
if (problems.length) {
  console.log(`\n发现 ${problems.length} 个问题：`)
  problems.forEach((p) => console.log(`  !!  ${p}`))
  process.exit(1)
}
console.log('\n全部通过\n')
