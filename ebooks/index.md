---
title: 电子书资源
description: 技术、文学、社科等各类电子书网盘资源合集 - PDF/EPUB/MOBI 格式
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

电子书资源，涵盖技术、文学、社科等多个领域。

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

---

::: info 添加资源
在 `ebooks/` 下创建新的 `.md` 文件，使用 `<ResourceCard>` 组件添加。
:::
