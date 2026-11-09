---
title: 音乐资源
description: 无损音乐、专辑合集、OST原声等音乐资源分享
head:
  - - meta
    - name: keywords
      content: 无损音乐,FLAC,专辑下载,OST,音乐合集
---

# 🎵 音乐

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'music')
</script>

音乐资源，主打无损品质。

---

## 🎧 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :link="r.link"
  :code="r.code"
  :size="r.size"
  :note="r.note"
/>
