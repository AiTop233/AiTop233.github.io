---
title: B站付费课程
description: B站付费课程资源合集 - 250+ 门优质知识付费课程，涵盖理财、编程、摄影、设计、历史、哲学、音乐、健身等
head:
  - - meta
    - name: keywords
      content: B站课程,付费课程,知识付费,编程教程,摄影课程,历史课程,哲学课程,理财课程
---

# 🎬 B站付费课程

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'bilibili')

// 旧条目是单链接（link/code），新条目可以是多盘（links）
const linksOf = (r) => (r.links && r.links.length ? r.links : [{ url: r.link, code: r.code }])
</script>

B站付费课程资源合集，涵盖 **{{ resources.length }}** 门优质课程。

::: tip 📊 领域分布
编程开发 · 理财经济 · 摄影设计 · 历史人文 · 哲学心理 · 音乐艺术 · 健身运动 · 职场技能 · 语言学习
:::

---

## 📚 全部课程

<ResourceCard
  v-for="r in resources"
  :key="r.link || r.title"
  :title="r.title"
  :links="linksOf(r)"
  :size="r.size"
  :note="r.note"
/>
