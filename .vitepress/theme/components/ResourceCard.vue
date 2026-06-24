<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  title: string        // 资源名称
  link: string         // 网盘链接
  code?: string        // 提取码（可选）
  size?: string        // 文件大小（可选）
  note?: string        // 备注（可选）
}>()

const copied = ref(false)

function copyCode() {
  if (!props.code) return
  navigator.clipboard.writeText(props.code)
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 2000)
}
</script>

<template>
  <div class="resource-card">
    <!-- 资源名称 -->
    <div class="card-title">
      <span class="card-icon">📦</span>
      <span>{{ title }}</span>
    </div>

    <!-- 资源信息 -->
    <div class="card-body">
      <div class="card-row link-row">
        <span class="label">🔗 链接</span>
        <a :href="link" target="_blank" rel="noopener noreferrer" class="link-text">
          {{ link }}
        </a>
      </div>

      <div v-if="code" class="card-row">
        <span class="label">🔑 提取码</span>
        <code class="code-badge">{{ code }}</code>
        <button class="copy-btn" @click="copyCode">
          {{ copied ? '✅ 已复制' : '📋 复制' }}
        </button>
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
  padding: 14px 16px;
  background: var(--vp-c-bg-soft);
  border-bottom: 1px solid var(--vp-c-border);
  font-weight: 600;
  font-size: 15px;
  color: var(--vp-c-text-1);
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
