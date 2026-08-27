<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { useConversationsStore } from '@/stores/conversations'
import SearchModeToggle from './SearchModeToggle.vue'
import type { SearchMode } from '@/types'

const props = defineProps<{ isStreaming: boolean; searchMode: SearchMode }>()
const emit = defineEmits<{
  send: [query: string]
  stop: []
  'open-paper-select': []
  'remove-paper': [name: string]
  'update:search-mode': [mode: SearchMode]
}>()

const conv = useConversationsStore()
const { selectedPapers } = storeToRefs(conv)

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function doSend() {
  if (props.isStreaming) return
  const t = text.value.trim()
  if (!t) return
  // Delegate sending to the parent (ChatView wires conv.sendMessage)
  emit('send', t)
  text.value = ''
  resetHeight()
  nextTick(() => textareaRef.value?.focus())
}

function onKeydown(e: KeyboardEvent) {
  // Enter sends, Shift+Enter inserts a newline.
  // e.isComposing: ignore Enter while IME is composing (e.g. pinyin candidates)
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    doSend()
  }
}

function onInput(e: Event) {
  const ta = e.target as HTMLTextAreaElement
  text.value = ta.value
  // Auto-resize, capped at 180px (matches the .chat-textarea max-height in base.css)
  ta.style.height = 'auto'
  ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'
}

function resetHeight() {
  const el = textareaRef.value
  if (el) el.style.height = 'auto'
}

// Refocus the textarea after generation finishes so the user can keep typing
watch(
  () => props.isStreaming,
  (streaming) => {
    if (!streaming) nextTick(() => textareaRef.value?.focus())
  },
)
</script>

<template>
  <div class="chat-input-area">
    <!-- Selected reference papers -->
    <div class="paper-tags" v-if="selectedPapers.length > 0">
      <span v-for="p in selectedPapers" :key="p.paper_id" class="paper-tag">
        📄 {{ p.title }}
        <span class="tag-remove" title="移除参考论文" @click="emit('remove-paper', p.paper_id)">✕</span>
      </span>
    </div>

    <!-- Search mode toggle -->
    <SearchModeToggle
      :is-streaming="isStreaming"
      :search-mode="searchMode"
      @update:search-mode="emit('update:search-mode', $event)"
    />

    <!-- Input container -->
    <div class="input-container">
      <button
        class="btn-attach"
        :class="{ 'has-selection': selectedPapers.length > 0 }"
        @click="emit('open-paper-select')"
        :title="selectedPapers.length > 0 ? `已选 ${selectedPapers.length} 篇参考论文` : '选择参考论文'"
      >📎</button>
      <textarea
        ref="textareaRef"
        v-model="text"
        class="chat-textarea"
        rows="1"
        :placeholder="isStreaming ? '正在生成回复…' : '输入您的问题… (Enter 发送, Shift+Enter 换行)'"
        :disabled="isStreaming"
        @keydown="onKeydown"
        @input="onInput"
      ></textarea>
      <button
        v-if="!isStreaming"
        class="btn-send"
        :disabled="!text.trim()"
        @click="doSend"
        title="发送 (Enter)"
      >➤</button>
      <button
        v-else
        class="btn-send stop"
        @click="emit('stop')"
        title="停止生成"
      >■</button>
    </div>
  </div>
</template>

<style scoped>
/* All styles come from base.css (.chat-input-area, .paper-tags, .input-container,
   .btn-attach, .chat-textarea, .btn-send, .search-mode-toggle, .toggle-btn) */
</style>
