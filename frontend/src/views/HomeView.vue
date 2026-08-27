<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useUiStore } from '@/stores/ui'
import { useConversationsStore } from '@/stores/conversations'
import { storeToRefs } from 'pinia'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ChatView from '@/components/chat/ChatView.vue'
import UploadModal from '@/components/modals/UploadModal.vue'
import ScanModal from '@/components/modals/ScanModal.vue'
import PaperSelectModal from '@/components/modals/PaperSelectModal.vue'
import PaperManagerModal from '@/components/modals/PaperManagerModal.vue'

const ui = useUiStore()
const conv = useConversationsStore()
const { searchMode } = storeToRefs(ui)
const { activeConversation, isStreaming } = storeToRefs(conv)

onMounted(() => {
  ui.startHealthPolling()
})

onUnmounted(() => {
  ui.stopHealthPolling()
})
</script>

<template>
  <AppSidebar />
  <main class="main-area">
    <EmptyState v-if="!activeConversation" />
    <ChatView v-else
      :is-streaming="isStreaming"
      :search-mode="searchMode"
      @update:search-mode="ui.setSearchMode($event as any)" />
  </main>

  <!-- Modals -->
  <UploadModal />
  <ScanModal />
  <PaperSelectModal />
  <PaperManagerModal />
</template>

<style scoped>
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--main-bg);
  min-width: 0;
  position: relative;
}
</style>
