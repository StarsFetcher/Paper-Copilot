<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import { storeToRefs } from 'pinia'

const ui = useUiStore()
const { backendOnline, paperCount, sidebarCollapsed } = storeToRefs(ui)
</script>

<template>
  <div class="sidebar-footer" v-show="!sidebarCollapsed">
    <div class="status-dot" :class="{ online: backendOnline }"></div>
    <span class="status-text">{{ backendOnline ? '服务已连接' : '服务离线' }}</span>
    <span class="paper-count" v-if="paperCount > 0"> | 📄 {{ paperCount }} 篇论文</span>
  </div>
</template>
