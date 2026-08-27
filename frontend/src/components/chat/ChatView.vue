<script setup lang="ts">
import { useConversationsStore } from '@/stores/conversations'
import { useUiStore } from '@/stores/ui'
import { storeToRefs } from 'pinia'
import type { SearchMode } from '@/types'
import ChatHeader from './ChatHeader.vue'
import MessageList from './MessageList.vue'
import ChatInput from './ChatInput.vue'

const props = defineProps<{
  isStreaming: boolean
  searchMode: SearchMode
}>()

const emit = defineEmits<{ 'update:search-mode': [mode: SearchMode] }>()

const conv = useConversationsStore()
const ui = useUiStore()
const { activeConversation } = storeToRefs(conv)

function handleSend(query: string) {
  const q = query.trim()
  if (!q || props.isStreaming) return
  conv.sendMessage(q, props.searchMode)
}

function handleStop() {
  conv.stopStreaming()
}

function openPaperSelect() {
  ui.paperSelectOpen = true
}

function setSearchMode(mode: SearchMode) {
  emit('update:search-mode', mode)
}
</script>

<template>
  <div class="chat-view">
    <ChatHeader />
    <MessageList
      :messages="activeConversation?.messages || []"
      :is-streaming="isStreaming"
    />
    <ChatInput
      :is-streaming="isStreaming"
      :search-mode="searchMode"
      @send="handleSend"
      @stop="handleStop"
      @remove-paper="conv.removePaper"
      @open-paper-select="openPaperSelect"
      @update:search-mode="setSearchMode"
    />
  </div>
</template>
