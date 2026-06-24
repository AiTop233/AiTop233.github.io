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
const resources = [
  {
    title: 'CS50 哈佛计算机科学导论 (2024)',
    link: 'https://pan.baidu.com/s/1example_tut1',
    code: 'h4n7',
    size: '22GB',
    note: '中英字幕 · 含全部作业材料',
  },
  {
    title: 'Blender 3D 建模完全教程',
    link: 'https://pan.quark.cn/s/example_tut2',
    code: '',
    size: '18GB',
    note: '从入门到精通 · 含项目文件',
  },
]
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
