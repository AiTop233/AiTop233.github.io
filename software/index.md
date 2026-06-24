---
title: 软件资源
description: 实用工具、设计软件、开发工具等软件资源合集
head:
  - - meta
    - name: keywords
      content: 软件下载,工具软件,设计软件,开发工具,破解软件
---

# 💻 软件

<script setup>
const resources = [
  {
    title: 'JetBrains 全家桶 2024.2',
    link: 'https://pan.baidu.com/s/1example_sw1',
    code: 'j9t3',
    size: '5.2GB',
    note: '含激活工具 · Windows/Mac/Linux',
  },
  {
    title: 'Adobe Creative Cloud 2024 套装',
    link: 'https://pan.quark.cn/s/example_sw2',
    code: '',
    size: '28GB',
    note: 'PS/AI/PR/AE · 一键安装版',
  },
]
</script>

实用软件合集，按需取用。

---

## 🛠️ 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :link="r.link"
  :code="r.code"
  :size="r.size"
  :note="r.note"
/>
