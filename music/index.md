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
const resources = [
  {
    title: '周杰伦 全专辑 FLAC 无损合集',
    link: 'https://pan.baidu.com/s/1example_music1',
    code: 'w8k2',
    size: '12GB',
    note: 'FLAC 无损 · 含全部录音室专辑',
  },
  {
    title: 'Hans Zimmer 汉斯·季默 电影原声精选',
    link: 'https://pan.quark.cn/s/example_music2',
    code: '',
    size: '6.5GB',
    note: 'FLAC + MP3 · 50首经典配乐',
  },
]
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
