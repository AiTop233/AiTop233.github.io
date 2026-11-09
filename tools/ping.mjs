#!/usr/bin/env node
/**
 * 把 sitemap 里的 URL 主动推给搜索引擎。
 *
 * 为什么需要：sitemap 只是「告诉它去哪找」，什么时候来爬由对方决定。
 * GitHub Pages 的服务器在境外，百度的抓取间隔会拉得很长，主动推送能把
 * 收录从天级压到小时级。
 *
 * 三个通道，各自独立，没配就跳过：
 *   Baidu    —— 站长平台的 token（环境变量 BAIDU_TOKEN）
 *   IndexNow —— key 默认从 public/<key>.txt 自动认（也可用 INDEXNOW_KEY 指定）；
 *               Bing / Yandex / Seznam / Naver 共用这一个端点
 *   Bing API —— Bing Webmaster Tools 的 API 密钥（环境变量 BING_API_KEY），
 *               在 BWT「设置 → API 访问 → API 密钥」拿，每天 10000 条配额
 *
 * IndexNow 的响应码：200 已接收；202 已接收但 key 待验证；403 key 文件取不到或内容不符；
 * 422 URL 与 host 不匹配；429 提交过快。除了 200/202 都算没推成功。
 *
 * 用法：
 *   node tools/ping.mjs --dry-run      # 只列将要提交的 URL，不发请求
 *   node tools/ping.mjs                # 有几个通道跑几个
 */

import { readFileSync, existsSync, readdirSync } from 'fs'
import { join } from 'path'

const DIST = '.vitepress/dist'
const SITE = 'https://aitop233.github.io'
const HOST = new URL(SITE).host
const dryRun = process.argv.includes('--dry-run')

const sitemap = join(DIST, 'sitemap.xml')
if (!existsSync(sitemap)) {
  console.error(`没有找到 ${sitemap}，先跑 npm run build`)
  process.exit(2)
}

const urls = [...readFileSync(sitemap, 'utf8').matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1])

console.log(`共 ${urls.length} 条 URL`)
urls.forEach((u) => console.log(`  ${u}`))

if (dryRun) {
  console.log('\n--dry-run：没有发送任何请求')
  process.exit(0)
}

/**
 * key 文件名就是 key 本身，得能在线上按 /<key>.txt 取到。
 * 认不出唯一一个就返回 null，不猜——猜错了 IndexNow 只会回 403。
 */
function findIndexNowKey() {
  if (process.env.INDEXNOW_KEY) return process.env.INDEXNOW_KEY
  const candidates = readdirSync('public').filter((f) => /^[0-9a-f]{8,128}\.txt$/i.test(f))
  if (candidates.length === 1) return candidates[0].replace(/\.txt$/i, '')
  if (candidates.length > 1) {
    console.log(`public/ 下有多个 key 文件（${candidates.join(', ')}），用 INDEXNOW_KEY 指定其中一个`)
  }
  return null
}

const results = []

async function baidu() {
  const token = process.env.BAIDU_TOKEN
  if (!token) {
    console.log('\n百度：跳过（没有 BAIDU_TOKEN）')
    return
  }
  const endpoint = `http://data.zz.baidu.com/urls?site=${SITE}&token=${token}`
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: urls.join('\n'),
  })
  results.push(['百度', `${res.status} ${await res.text()}`])
}

async function indexNow() {
  const key = findIndexNowKey()
  if (!key) {
    console.log('\nIndexNow：跳过（public/ 下没有 key 文件，也没有 INDEXNOW_KEY）')
    return
  }
  // key 文件必须真的能访问到，否则接口会拒
  if (!existsSync(join('public', `${key}.txt`))) {
    console.log(`IndexNow：跳过（缺 public/${key}.txt，内容应为这串 key 本身）`)
    return
  }
  const keyLocation = `${SITE}/${key}.txt`
  const res = await fetch('https://api.indexnow.org/indexnow', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ host: HOST, key, keyLocation, urlList: urls }),
  })
  const ok = res.status === 200 || res.status === 202
  results.push([
    'IndexNow',
    `${res.status} ${res.statusText}${ok ? '' : `（key 文件是否已上线？先试 ${keyLocation}）`}`,
  ])
}

async function bingApi() {
  const apiKey = process.env.BING_API_KEY
  if (!apiKey) {
    console.log('Bing API：跳过（没有 BING_API_KEY）')
    return
  }
  const res = await fetch(
    `https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlbatch?apikey=${encodeURIComponent(apiKey)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ siteUrl: `${SITE}/`, urlList: urls }),
    },
  )
  results.push(['Bing API', `${res.status} ${(await res.text()).slice(0, 200)}`])
}

await baidu()
await indexNow()
await bingApi()

if (results.length) {
  console.log('')
  results.forEach(([name, body]) => console.log(`${name}：${body}`))
} else {
  console.log('\n没有配置任何通道，什么也没发')
}
