---
title: 教程资源
description: 编程、设计、语言学习等各类教程网盘资源合集
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
</script>

各类教程资源，持续更新中。

---

## 📺 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :link="r.link"
  :code="r.code"
  :size="r.size"
  :note="r.note"
/>
