#!/usr/bin/env node
/**
 * 往 data/resources.json 追加一条（或一批）资源。
 *
 * 这是站点内容唯一的写入点：手工用、脚本用、panup 同步也用同一个入口，
 * 免得两边各写一套追加逻辑、各写各的格式。
 *
 * 用法：
 *   node tools/add.mjs --category movies --title "片名" --link https://pan.quark.cn/s/xxx \
 *                      [--pan quark] [--code 8x2k] [--size 12.5GB] [--note 4K] [--group column]
 *   node tools/add.mjs --category movies --title "片名" \
 *                      --links '[{"pan":"baidu","url":"https://pan.baidu.com/s/x","code":"k9x2"},{"pan":"quark","url":"https://pan.quark.cn/s/y"}]'
 *   node tools/add.mjs --json -            # 从 stdin 读数组（批量同步用）
 *   node tools/add.mjs --file batch.json   # 从文件读数组
 *   加 --dry-run 只看会改什么，不落盘；--force 允许链接重复（会替换旧条目）
 *
 * 一个资源可以有多条链接（同一次上传的百度 + 夸克）：写 `links` 数组，
 * `link` / `code` 自动保留成第一条的镜像，旧读法不受影响。
 *
 * 退出码：0 有写入（或 dry-run 正常）；2 全部被去重跳过；1 参数/数据有错。
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const DATA = resolve(ROOT, 'data/resources.json')

/** 站点分类 → 展示名；新增分类时这里和 .vitepress/config.ts 一起加 */
export const CATEGORIES = {
  bilibili: 'B站付费课程',
  geektime: '极客时间',
  movies: '影视',
  ebooks: '电子书',
  tutorials: '教程',
  software: '软件',
  music: '音乐',
}

const GROUPS = { geektime: ['column', 'video'] }

function parseArgs(argv) {
  const out = { _: [] }
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i]
    if (!a.startsWith('--')) { out._.push(a); continue }
    const key = a.slice(2)
    if (key === 'dry-run' || key === 'force') { out[key] = true; continue }
    const val = argv[i + 1]
    if (val === undefined || val.startsWith('--')) {
      throw new Error(`--${key} 缺少取值`)
    }
    out[key] = val
    i += 1
  }
  return out
}

function cleanLinks(item, title, where) {
  const raw = Array.isArray(item.links) && item.links.length
    ? item.links
    : [{ pan: item.pan, url: item.link, code: item.code }]

  const links = raw.map((l, i) => {
    const url = String(l.url || l.link || '').trim()
    if (!/^https?:\/\//i.test(url)) {
      throw new Error(`${where}: 「${title}」第 ${i + 1} 条链接不是 http(s) 链接`)
    }
    const out = { url }
    const pan = String(l.pan || '').trim()
    if (pan) out.pan = pan
    const code = String(l.code || '').trim()
    if (code) out.code = code
    return out
  })

  const seen = new Set()
  const unique = links.filter((l) => {
    if (seen.has(l.url)) return false
    seen.add(l.url)
    return true
  })
  if (!unique.length) throw new Error(`${where}: 「${title}」没有可用链接`)
  return unique
}

function clean(item, where) {
  const category = String(item.category || '').trim()
  if (!CATEGORIES[category]) {
    throw new Error(`${where}: 未知分类「${category}」，可选 ${Object.keys(CATEGORIES).join(' / ')}`)
  }
  const title = String(item.title || '').trim()
  if (!title) throw new Error(`${where}: 缺 title`)

  const out = { category }
  const group = item.group ? String(item.group).trim() : ''
  if (group) {
    const allowed = GROUPS[category]
    if (!allowed) throw new Error(`${where}: 分类「${category}」没有分组`)
    if (!allowed.includes(group)) throw new Error(`${where}: 「${category}」的分组只能是 ${allowed.join(' / ')}`)
    out.group = group
  }
  out.title = title
  // links 是权威结构（一个资源可多盘）；link / code 保留成第一条的镜像，方便旧工具读
  out.links = cleanLinks(item, title, where)
  out.link = out.links[0].url
  if (out.links[0].code) out.code = out.links[0].code

  for (const f of ['size', 'note']) {
    const v = item[f]
    if (v === undefined || v === null) continue
    const s = String(v).trim()
    if (s) out[f] = s
  }
  return out
}

/** 一条记录涉及的全部链接（兼容只有 link 的旧条目） */
function urlsOf(item) {
  if (Array.isArray(item.links) && item.links.length) return item.links.map((l) => l.url)
  return item.link ? [item.link] : []
}

function readPayload(args) {
  if (args.file) {
    return JSON.parse(readFileSync(resolve(process.cwd(), args.file), 'utf8'))
  }
  if (args.json === '-') {
    return JSON.parse(readFileSync(0, 'utf8'))
  }
  if (args.json) return JSON.parse(args.json)
  return null
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  const payload = readPayload(args)
  const incoming = payload
    ? (Array.isArray(payload) ? payload : payload.items || [payload])
    : [{ category: args.category, title: args.title, link: args.link,
         links: args.links ? JSON.parse(args.links) : undefined,
         pan: args.pan, code: args.code, size: args.size, note: args.note,
         group: args.group }]

  if (!incoming.length) {
    console.error('没有要写的条目')
    return 1
  }

  const data = JSON.parse(readFileSync(DATA, 'utf8'))
  data.items = data.items || []

  // 去重按「任一条链接命中」算：同一个资源先发夸克、后补百度，不该变成两张卡片
  const byUrl = new Map()
  data.items.forEach((it) => urlsOf(it).forEach((u) => byUrl.set(u, it)))

  const fresh = []
  let skipped = 0
  incoming.forEach((raw, i) => {
    const item = clean(raw, `第 ${i + 1} 条`)
    const hit = urlsOf(item).some((u) => byUrl.has(u))
    if (hit && !args.force) { skipped += 1; return }
    if (hit && args.force) {
      const old = urlsOf(item).map((u) => byUrl.get(u)).filter(Boolean)
      data.items = data.items.filter((it) => !old.includes(it))
    }
    urlsOf(item).forEach((u) => byUrl.set(u, item))
    fresh.push(item)
  })

  if (!fresh.length) {
    console.log(`全部已存在，跳过 ${skipped} 条，未改动`)
    return 2
  }

  data.items.push(...fresh)
  data.counts = data.items.reduce((acc, it) => {
    acc[it.category] = (acc[it.category] || 0) + 1
    return acc
  }, {})
  data.updated = new Date().toISOString().slice(0, 10)

  if (args['dry-run']) {
    console.log(`[dry-run] 将新增 ${fresh.length} 条（跳过重复 ${skipped} 条）：`)
    fresh.forEach((it) => console.log(`  + ${it.category}${it.group ? `/${it.group}` : ''} · ${it.title}`))
    return 0
  }

  writeFileSync(DATA, JSON.stringify(data, null, 2) + '\n', 'utf8')
  console.log(`新增 ${fresh.length} 条（跳过重复 ${skipped} 条）→ data/resources.json`)
  fresh.forEach((it) => console.log(`  + ${it.category}${it.group ? `/${it.group}` : ''} · ${it.title}`))
  console.log('下一步：npm run build 自查，再 git add/commit/push 让 GitHub Actions 发布')
  return 0
}

try {
  process.exitCode = main()
} catch (e) {
  console.error(`写不进去：${e.message}`)
  process.exitCode = 1
}
