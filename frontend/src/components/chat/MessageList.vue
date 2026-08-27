<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'
import ChatMessage from './ChatMessage.vue'
import type { Message } from '@/types'

const props = defineProps<{ messages: Message[]; isStreaming: boolean }>()

const scrollRef = ref<HTMLElement | null>(null)

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(scrollToBottom)

// Deep watch: streaming tokens mutate the last message's content in place,
// and switching conversations swaps the whole array.
watch(
  () => props.messages,
  () => scrollToBottom(),
  { deep: true },
)

watch(
  () => props.isStreaming,
  () => {
    if (props.isStreaming) nextTick(scrollToBottom)
  },
)
</script>

<template>
  <div ref="scrollRef" class="messages-area">
    <div class="messages-container">
      <ChatMessage
        v-for="(msg, idx) in messages"
        :key="msg.timestamp + '-' + msg.role + '-' + idx"
        :message="msg"
        :is-streaming="isStreaming && msg.role === 'assistant' && idx === messages.length - 1"
      />
      <div v-if="messages.length === 0" class="messages-empty">
        <span class="empty-icon">💬</span>
        <p class="empty-text">发送一条消息开始对话</p>
        <p class="empty-hint">支持本地论文库检索与 arXiv 联网搜索</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* .messages-area / .messages-container layout comes from base.css */
.messages-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 90px 20px;
  text-align: center;
  color: var(--main-muted);
  animation: msgSlideIn 0.3s var(--ease);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 14px;
  opacity: 0.45;
}

.empty-text {
  font-size: 14.5px;
  font-weight: 500;
}

.empty-hint {
  font-size: 12.5px;
  opacity: 0.6;
}
</style>
