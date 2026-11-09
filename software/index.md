---
title: 软件资源
description: 实用工具、设计软件、开发工具等软件资源合集，标注版本号、系统要求与是否便携版
head:
  - - meta
    - name: keywords
      content: 软件下载,工具软件,设计软件,开发工具,破解软件
---

# 💻 软件

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'software')

// 旧条目是单链接（link/code），新条目可以是多盘（links）
const linksOf = (r) => (r.links && r.links.length ? r.links : [{ url: r.link, code: r.code }])
</script>

软件以 Windows 工具为主，安装包与绿色版混放，目前收录 {{ resources.length }} 个。下载前先看卡片里的备注：版本号、是否便携版、支持的系统，这几个信息比体积更有用。

---

## 🛠️ 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :links="linksOf(r)"
  :size="r.size"
  :note="r.note"
/>
