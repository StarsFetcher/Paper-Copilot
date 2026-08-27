<script setup lang="ts">
import type { SearchMode } from '@/types'

const props = defineProps<{
  searchMode: SearchMode
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'update:search-mode': [mode: SearchMode]
}>()

const options: { value: SearchMode; icon: string; label: string; title: string }[] = [
  { value: 'auto',  icon: '✨', label: '自动',  title: '先检索本地知识库，内容不足时自动转到 arXiv 在线搜索' },
  { value: 'local', icon: '📚', label: '本地库', title: '仅检索本地论文知识库' },
  { value: 'arxiv', icon: '🌐', label: 'arXiv', title: '仅从 arXiv 在线搜索最新论文' },
]

function select(mode: SearchMode) {
  if (mode === props.searchMode || props.isStreaming) return
  emit('update:search-mode', mode)
}
</script>

<template>
  <div class="search-mode-toggle">
    <button
      v-for="opt in options"
      :key="opt.value"
      class="toggle-btn"
      :class="{ active: props.searchMode === opt.value }"
      :disabled="props.isStreaming"
      :title="opt.title"
      @click="select(opt.value)"
    >
      <span class="toggle-icon">{{ opt.icon }}</span>
      {{ opt.label }}
    </button>
  </div>
</template>

<style scoped>
.toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.toggle-btn.active {
  cursor: default;
}

.toggle-icon {
  font-size: 12px;
  line-height: 1;
}
</style>
