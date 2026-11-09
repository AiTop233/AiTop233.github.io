#!/usr/bin/env node
/**
 * 把各分类页里内联的 `const resources = [...]` 抽成 data/resources.json。
 *
 * 只在「从旧站迁移」时跑一次；之后数据以 JSON 为准，页面只负责渲染。
 * 用法：node tools/extract.mjs [--check]
 *   --check  只比对条数，不写文件（迁移后自查用）
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')

/** 页面 → 分类；geektime 有两段（专栏 / 视频）分别抽 */
const PAGES = [
  { file: 'bilibili/index.md', category: 'bilibili', vars: [['resources', null]] },
  { file: 'geektime/index.md', category: 'geektime', vars: [['columnCourses', 'column'], ['videoCourses', 'video']] },
  { file: 'movies/index.md', category: 'movies', vars: [['resources', null]] },
  { file: 'ebooks/index.md', category: 'ebooks', vars: [['resources', null]] },
  { file: 'tutorials/index.md', category: 'tutorials', vars: [['resources', null]] },
  { file: 'software/index.md', category: 'software', vars: [['resources', null]] },
  { file: 'music/index.md', category: 'music', vars: [['resources', null]] },
]

const FIELDS = ['title', 'link', 'code', 'size', 'note']

function grabArray(text, varName, file) {
  const re = new RegExp(`const\\s+${varName}\\s*=\\s*\\[([\\s\\S]*?)\\n\\]`, 'm')
  const hit = text.match(re)
  if (!hit) throw new Error(`${file}: 找不到 const ${varName} = [...]`)
  let list
  try {
    list = new Function(`return [${hit[1]}\n]`)()
  } catch (e) {
    throw new Error(`${file}: ${varName} 不是合法的对象字面量（${e.message}）`)
  }
  if (!Array.isArray(list)) throw new Error(`${file}: ${varName} 不是数组`)
  return list
}

function normalize(raw, category, group, where) {
  const item = { category }
  if (group) item.group = group
  for (const f of FIELDS) {
    const v = raw[f]
    if (v === undefined || v === null) continue
    const s = String(v).trim()
    if (s) item[f] = s
  }
  if (!item.title) throw new Error(`${where}: 有条目缺 title（${JSON.stringify(raw)}）`)
  if (!/^https?:\/\//i.test(item.link || '')) {
    throw new Error(`${where}: 「${item.title}」的 link 不是 http(s) 链接`)
  }
  return item
}

const items = []
const report = []
for (const page of PAGES) {
  const file = resolve(ROOT, page.file)
  const text = readFileSync(file, 'utf8')
  for (const [varName, group] of page.vars) {
    const list = grabArray(text, varName, page.file)
    list.forEach((raw) => items.push(normalize(raw, page.category, group, page.file)))
    report.push(`${page.category}${group ? `/${group}` : ''}: ${list.length}`)
  }
}

// 链接去重（同一分享被两处收录时留第一条）
const seen = new Set()
const unique = items.filter((it) => {
  const key = it.link
  if (seen.has(key)) return false
  seen.add(key)
  return true
})

const out = {
  version: 1,
  counts: Object.fromEntries(
    [...new Set(unique.map((i) => i.category))].map((c) => [c, unique.filter((i) => i.category === c).length]),
  ),
  items: unique,
}

console.log(report.join('\n'))
console.log(`合计 ${items.length} 条，去重后 ${unique.length} 条`)

if (!process.argv.includes('--check')) {
  mkdirSync(resolve(ROOT, 'data'), { recursive: true })
  writeFileSync(resolve(ROOT, 'data/resources.json'), JSON.stringify(out, null, 2) + '\n', 'utf8')
  console.log('已写入 data/resources.json')
}
