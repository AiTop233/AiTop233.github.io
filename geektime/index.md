---
title: 极客时间课程
description: 极客时间课程资源合集 - 276门优质IT技术课程，涵盖专栏课与视频课，百度网盘下载
head:
  - - meta
    - name: keywords
      content: 极客时间,IT课程,技术课程,编程教程,架构,Java,Python,Go,前端,AI
---

# ⏰ 极客时间课程

<script setup>
// 数据在 data/resources.json，页面只负责渲染（同步由 tools/add.mjs 写入）
import data from '../data/resources.json'
const columnCourses = data.items.filter((r) => r.category === 'geektime' && r.group === 'column')
const videoCourses = data.items.filter((r) => r.category === 'geektime' && r.group === 'video')
</script>

极客时间课程资源合集，涵盖 **{{ columnCourses.length + videoCourses.length }}** 门优质课程（专栏课 {{ columnCourses.length }} 门 + 视频课 {{ videoCourses.length }} 门）。

::: tip 📊 领域分布
Java · Python · Go · C++ · Rust · JavaScript · Vue · React · Kotlin · Swift · Linux · Kubernetes · Docker · 微服务 · 架构 · 算法 · AI/ML · 大数据 · 数据库 · 前端 · 后端 · 运维 · 安全 · 测试 · 产品 · 管理
:::

---

## 📖 专栏课（{{ columnCourses.length }}门）

<ResourceCard
  v-for="r in columnCourses"
  :key="r.link"
  :title="r.title"
  :link="r.link"
  :code="r.code"
  :note="r.note"
/>

---

## 🎥 视频课（{{ videoCourses.length }}门）

<ResourceCard
  v-for="r in videoCourses"
  :key="r.link"
  :title="r.title"
  :link="r.link"
  :code="r.code"
  :note="r.note"
/>
