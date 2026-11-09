---
title: 影视资源
description: 电影、剧集、纪录片等影视类网盘资源合集，标注体积与网盘类型，提取码可一键复制
head:
  - - meta
    - name: keywords
      content: 影视资源,电影下载,剧集下载,纪录片,百度网盘,4K电影
---

# 🎬 影视

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'movies')

// 旧条目是单链接（link/code），新条目可以是多盘（links）
const linksOf = (r) => (r.links && r.links.length ? r.links : [{ url: r.link, code: r.code }])
</script>

影视资源按类型整理，目前收录 {{ resources.length }} 部，持续补充中。每条都标注了网盘与体积，提取码点一下就能复制；同一部片在多个网盘有存档时，卡片里会并列列出，挑速度快的那个用。

---

## 🎥 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :links="linksOf(r)"
  :size="r.size"
  :note="r.note"
/>
