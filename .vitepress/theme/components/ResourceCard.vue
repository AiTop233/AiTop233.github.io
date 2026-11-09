<script setup lang="ts">
import { computed, ref } from 'vue'

const PAN_NAMES: Record<string, string> = {
  baidu: '百度',
  quark: '夸克',
  uc: 'UC',
  aliyun: '阿里',
  '115': '115',
  '123': '123',
  xunlei: '迅雷',
  tianyi: '天翼',
}

const props = defineProps<{
  title: string        // 资源名称
  links: Array<{ pan?: string; url: string; code?: string }>  // 一个资源可有多条（多盘）
  size?: string        // 文件大小（可选）
  note?: string        // 备注（可选）
}>()

// 过滤掉空链接，并给盘型一个中文名（没写盘型的旧条目就不显示徽标）
const shown = computed(() =>
  (props.links || [])
    .filter((l) => l && l.url)
    .map((l) => ({ ...l, label: l.pan ? PAN_NAMES[l.pan] || l.pan : '' })),
)

// 资源名要给搜索引擎当标题用（<h3>），而不是一个纯 <div>：
// 一页两百多条资源，如果全是 div，正文里没有一个能被识别成「标题」的层级。
// 锚点由标题派生，同一页两条同名资源也能共存（加短哈希去重）。
const cardId = computed(() => {
  const slug = props.title
    .toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
  let h = 0
  for (const ch of props.title) h = (h * 31 + ch.codePointAt(0)!) >>> 0
  return `${slug || 'res'}-${h.toString(36).slice(0, 4)}`
})

const copied = ref('')

function copyCode(code?: string) {
  if (!code) return
  navigator.clipboard.writeText(code)
  copied.value = code
  setTimeout(() => {
    if (copied.value === code) copied.value = ''
  }, 2000)
}
</script>

<template>
  <div class="resource-card">
    <!-- 资源名称：用 h3，标题层级与锚点都留给搜索引擎和深链接。
         ignore-header 是 VitePress 的约定：有这个 class 的标题不进右侧大纲，
         否则一页 276 张卡会把大纲撑成一份目录。 -->
    <h3 :id="cardId" class="card-title ignore-header">
      <span class="card-icon">📦</span>
      <span class="card-name">{{ title }}</span>
      <a class="card-anchor" :href="`#${cardId}`" :aria-label="`链接到「${title}」`">#</a>
    </h3>

    <!-- 资源信息 -->
    <div class="card-body">
      <div v-for="l in shown" :key="l.url" class="link-block">
        <div class="card-row link-row">
          <span class="label">🔗 链接</span>
          <span v-if="l.label" class="pan-badge">{{ l.label }}</span>
          <a :href="l.url" target="_blank" rel="noopener noreferrer nofollow"
             :title="`打开「${title}」${l.label ? `（${l.label}网盘）` : ''}`" class="link-text">
            {{ l.url }}
          </a>
        </div>

        <div v-if="l.code" class="card-row">
          <span class="label">🔑 提取码</span>
          <code class="code-badge">{{ l.code }}</code>
          <button class="copy-btn" @click="copyCode(l.code)">
            {{ copied === l.code ? '✅ 已复制' : '📋 复制' }}
          </button>
        </div>
      </div>

      <div class="card-meta">
        <span v-if="size" class="meta-item">
          <span class="meta-icon">💾</span> {{ size }}
        </span>
        <span v-if="note" class="meta-item note-text">
          {{ note }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ---- 资源卡片 ---- */
.resource-card {
  border: 1px solid var(--vp-c-border);
  border-radius: var(--card-radius);
  background: var(--vp-c-bg);
  box-shadow: var(--card-shadow);
  margin: 16px 0;
  overflow: hidden;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

.resource-card:hover {
  box-shadow: var(--card-shadow-hover);
  border-color: #8b949e;
}

/* 标题区 */
.card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 14px 16px;
  background: var(--vp-c-bg-soft);
  border-bottom: 1px solid var(--vp-c-border);
  font-weight: 600;
  font-size: 15px;
  line-height: 1.5;
  letter-spacing: normal;
  color: var(--vp-c-text-1);
  border-top: none;
}

/* 锚点：鼠标移上去才出现，平时不干扰阅读（和正文标题的行为一致） */
.card-anchor {
  margin-left: auto;
  padding-left: 8px;
  font-weight: 400;
  color: var(--vp-c-text-3);
  text-decoration: none;
  opacity: 0;
  transition: opacity 0.1s ease;
}

.resource-card:hover .card-anchor,
.card-anchor:focus-visible {
  opacity: 1;
}

.card-name {
  word-break: break-word;
}

.card-icon {
  font-size: 18px;
}

/* 内容区 */
.card-body {
  padding: 14px 16px;
}

.card-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 14px;
}

.label {
  color: var(--vp-c-text-2);
  font-weight: 500;
  white-space: nowrap;
  min-width: 65px;
}

/* 链接 */
.link-text {
  color: var(--vp-c-brand);
  text-decoration: none;
  font-family: var(--vp-font-family-mono);
  font-size: 13px;
  word-break: break-all;
  overflow-wrap: anywhere;
  line-height: 1.5;
}

.link-text:hover {
  text-decoration: underline;
}

/* 多盘：同一资源的第二条链接与上一条隔开 */
.link-block + .link-block {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--vp-c-divider);
}

/* 盘型徽标：百度 / 夸克 …（旧条目没有盘型就不显示） */
.pan-badge {
  flex: 0 0 auto;
  padding: 1px 7px;
  font-size: 12px;
  font-weight: 600;
  color: var(--vp-c-text-2);
  background: var(--vp-c-bg-soft);
  border: 1px solid var(--vp-c-border);
  border-radius: 4px;
  white-space: nowrap;
}

/* 提取码 */
.code-badge {
  font-family: var(--vp-font-family-mono);
  font-size: 14px;
  background: var(--vp-c-success-soft);
  color: var(--vp-c-success);
  border: 1px solid #b3e8c7;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: 600;
  letter-spacing: 0.05em;
}

/* 复制按钮 */
.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--vp-c-text-2);
  background: var(--vp-c-bg-soft);
  border: 1px solid var(--vp-c-border);
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.1s ease;
  white-space: nowrap;
  font-family: var(--vp-font-family-base);
}

.copy-btn:hover {
  background: var(--vp-c-bg-mute);
  color: var(--vp-c-text-1);
}

.copy-btn:active {
  background: #e8e8e8;
}

/* 元信息 */
.card-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--vp-c-divider);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--vp-c-text-3);
}

.meta-icon {
  font-size: 14px;
}

.note-text {
  color: var(--vp-c-text-2);
  font-style: italic;
}

/* ---- 响应式 ---- */
@media (max-width: 640px) {
  .card-title {
    padding: 10px 12px;
    font-size: 14px;
  }

  .card-body {
    padding: 10px 12px;
  }

  .card-row {
    flex-wrap: wrap;
    gap: 6px;
  }

  .copy-btn {
    margin-top: 0;
  }
}
</style>
