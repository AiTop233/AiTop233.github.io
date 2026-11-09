---
title: 教程资源
description: 编程、设计、语言学习等视频教程网盘资源合集，按类型整理，标注体积与网盘类型
head:
  - - meta
    - name: keywords
      content: 教程,编程教程,设计教程,视频教程,网盘下载
---

# 🎓 教程

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'tutorials')

// 旧条目是单链接（link/code），新条目可以是多盘（links）
const linksOf = (r) => (r.links && r.links.length ? r.links : [{ url: r.link, code: r.code }])
</script>

教程类以视频课为主，覆盖编程、设计与语言学习，目前收录 {{ resources.length }} 套。视频课动辄几十 GB，建议先存到自己网盘再挑需要的章节下载，别一次性全拉到本地。

---

## 📺 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :links="linksOf(r)"
  :size="r.size"
  :note="r.note"
/>
