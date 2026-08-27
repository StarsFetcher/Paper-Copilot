import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { SearchMode } from '@/types'
import { checkHealth, fetchStats } from '@/api/stats'

export const useUiStore = defineStore('ui', () => {
  // --- State ---
  const sidebarCollapsed = ref(false)
  const backendOnline = ref(false)
  const paperCount = ref(0)
  const searchMode = ref<SearchMode>('auto')

  // Modal flags
  const uploadOpen = ref(false)
  const scanOpen = ref(false)
  const paperSelectOpen = ref(false)
  const paperManagerOpen = ref(false)

  let healthTimer: ReturnType<typeof setInterval> | null = null

  // --- Actions ---
  async function doHealthCheck() {
    backendOnline.value = await checkHealth()
  }

  async function refreshPaperCount() {
    try {
      const stats = await fetchStats()
      if (stats && typeof stats.papers_count === 'number') {
        paperCount.value = stats.papers_count
      }
    } catch {
      // ignore
    }
  }

  function startHealthPolling() {
    doHealthCheck()
    refreshPaperCount()
    healthTimer = setInterval(() => {
      doHealthCheck()
      refreshPaperCount()
    }, 30000)
  }

  function stopHealthPolling() {
    if (healthTimer) {
      clearInterval(healthTimer)
      healthTimer = null
    }
  }

  function setSearchMode(mode: SearchMode) {
    searchMode.value = mode
  }

  // --- Computed equivalent: active conversation is in conversations store ---
  // We just re-export it from here for convenience in HomeView

  return {
    sidebarCollapsed,
    backendOnline,
    paperCount,
    searchMode,
    uploadOpen,
    scanOpen,
    paperSelectOpen,
    paperManagerOpen,
    doHealthCheck,
    refreshPaperCount,
    startHealthPolling,
    stopHealthPolling,
    setSearchMode,
  }
})
