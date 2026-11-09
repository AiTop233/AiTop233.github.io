---
title: 电子书资源
description: 技术、文学、社科等电子书网盘资源合集，涵盖 PDF、EPUB、MOBI 格式，附阅读与推送建议
head:
  - - meta
    - name: keywords
      content: 电子书,PDF下载,编程书籍,文学书籍,EPUB,MOBI,技术书籍
---

# 📚 电子书

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'ebooks')

// 旧条目是单链接（link/code），新条目可以是多盘（links）
const linksOf = (r) => (r.links && r.links.length ? r.links : [{ url: r.link, code: r.code }])
</script>

电子书以技术类为主，兼顾文学与社科，格式以 PDF、EPUB、MOBI 居多，目前收录 {{ resources.length }} 本。手机阅读建议选 EPUB（能重排、省电），要做笔记或打印选 PDF；往 Kindle 推送前记得先转格式。

---

## 📖 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :links="linksOf(r)"
  :size="r.size"
  :note="r.note"
/>
