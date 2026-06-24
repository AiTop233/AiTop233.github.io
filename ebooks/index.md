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
const resources = [
  {
    title: '程序员的自我修养 — 链接、装载与库',
    link: 'https://pan.baidu.com/s/1example_ebook1',
    code: 'b2p8',
    size: '28MB',
    note: 'PDF 高清版 · 经典计算机书籍',
  },
  {
    title: 'SICP 计算机程序的构造和解释 (第2版)',
    link: 'https://pan.quark.cn/s/example_ebook2',
    code: '',
    size: '15MB',
    note: 'EPUB + PDF 双格式',
  },
  {
    title: '人类简史 Sapiens (中文版)',
    link: 'https://www.aliyundrive.com/s/example_ebook3',
    code: 'x5k9',
    size: '8MB',
    note: 'MOBI 格式 · 适合 Kindle 阅读',
  },
]
</script>

电子书资源，涵盖技术、文学、社科等多个领域。

---

## 📖 资源列表

<ResourceCard
  v-for="r in resources"
  :key="r.title"
  :title="r.title"
  :link="r.link"
  :code="r.code"
  :size="r.size"
  :note="r.note"
/>

---

::: info 添加资源
在 `ebooks/` 下创建新的 `.md` 文件，使用 `<ResourceCard>` 组件添加。
:::
