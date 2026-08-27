<script setup lang="ts">
import { computed } from 'vue'
import { useConversationsStore } from '@/stores/conversations'
import { useUiStore } from '@/stores/ui'
import { storeToRefs } from 'pinia'

const conv = useConversationsStore()
const ui = useUiStore()
const { activeConversation, isStreaming } = storeToRefs(conv)
const { backendOnline } = storeToRefs(ui)

const title = computed(() => activeConversation.value?.title || '新对话')
const messageCount = computed(() => activeConversation.value?.messages.length || 0)
</script>

<template>
  <div class="chat-header">
    <div class="header-left">
      <span class="chat-header-title">{{ title }}</span>
      <span class="header-count">{{ messageCount }} 条消息</span>
    </div>
    <div class="header-right">
      <span v-if="isStreaming" class="status-badge streaming">
        <span class="pulse-dot"></span> 正在生成…
      </span>
      <span class="backend-status" :class="{ offline: !backendOnline }">
        <span class="status-dot" :class="{ online: backendOnline }"></span>
        {{ backendOnline ? '服务在线' : '服务离线' }}
      </span>
    </div>
  </div>
</template>

<style scoped>
/* .chat-header / .chat-header-title layout comes from base.css */

.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.header-count {
  font-size: 12px;
  color: var(--main-muted);
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-light);
  padding: 5px 12px;
  border-radius: 20px;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulseBlink 1s ease-in-out infinite;
}

@keyframes pulseBlink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.8); }
}

.backend-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 500;
  color: var(--success);
}

.backend-status.offline {
  color: var(--danger);
}
</style>
