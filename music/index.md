---
title: 音乐资源
description: 无损音乐、专辑合集、OST 原声等音乐资源分享，以 FLAC 为主，部分附歌词与封面
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

// 旧条目是单链接（link/code），新条目可以是多盘（links）
const linksOf = (r) => (r.links && r.links.length ? r.links : [{ url: r.link, code: r.code }])
</script>

音乐以无损为主，FLAC 居多，部分专辑附带歌词与封面，目前收录 {{ resources.length }} 张。追求体积小可以自己转 320k MP3；车载 U 盘记得先确认播放器认不认 FLAC。

---

## 🎧 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :links="linksOf(r)"
  :size="r.size"
  :note="r.note"
/>
