---
title: 影视资源
description: 电影、剧集、纪录片等影视类网盘资源合集
head:
  - - meta
    - name: keywords
      content: 影视资源,电影下载,剧集下载,纪录片,百度网盘,4K电影
  - - meta
    - property: og:title
      content: 影视资源 - 资源合集
---

# 🎬 影视

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const resources = data.items.filter((r) => r.category === 'movies')
</script>

影视类资源按需分类整理。

---

## 🎥 近期更新

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

## 📝 添加新资源

在 `movies/` 目录下创建新的 `.md` 文件，使用 `<ResourceCard>` 组件添加资源：

```markdown
<ResourceCard
  title="资源名称"
  link="网盘链接"
  code="提取码"
  size="文件大小"
  note="备注说明"
/>
```

::: info 说明
- `code` 和 `note` 是可选参数
- 链接支持百度网盘、夸克网盘、阿里云盘等
:::
