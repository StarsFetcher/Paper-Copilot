import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import type { Conversation, Message, PaperRef } from '@/types'
import { uuid, truncate } from '@/utils/format'
import { useSseStream } from '@/composables/useSseStream'

const STORAGE_KEY = 'paper-copilot-conversations'

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const data = JSON.parse(raw)
    return Array.isArray(data) ? data : []
  } catch {
    return []
  }
}

function saveConversations(convs: Conversation[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(convs))
  } catch {
    // ignore
  }
}

export const useConversationsStore = defineStore('conversations', () => {
  const conversations = ref<Conversation[]>(loadConversations())
  const activeConversationId = ref<string | null>(null)
  const isStreaming = ref(false)
  let streamController: AbortController | null = null

  // --- Getters ---
  const sortedConversations = computed(() =>
    conversations.value.slice().sort((a, b) => b.updatedAt - a.updatedAt),
  )

  const activeConversation = computed(() => {
    if (!activeConversationId.value) return null
    const found = conversations.value.filter((c) => c.id === activeConversationId.value)
    return found.length > 0 ? found[0] : null
  })

  const selectedPapers = computed(() => {
    const conv = activeConversation.value
    if (!conv || !conv.selectedPapers) return []
    return conv.selectedPapers.slice()
  })

  // --- Persistence ---
  watch(
    conversations,
    (val) => saveConversations(val),
    { deep: true },
  )

  // --- Actions ---
  function createConversation() {
    if (isStreaming.value) return
    const c: Conversation = {
      id: uuid(),
      title: '',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }
    conversations.value.unshift(c)
    activeConversationId.value = c.id
  }

  function selectConversation(id: string) {
    if (isStreaming.value) return
    activeConversationId.value = id
  }

  function requestDelete(id: string) {
    return id
  }

  function confirmDelete(id: string) {
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConversationId.value === id) {
      activeConversationId.value = conversations.value.length > 0 ? conversations.value[0].id : null
    }
  }

  function clearAll() {
    conversations.value = []
    activeConversationId.value = null
  }

  function rename(id: string, title: string) {
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) {
      conv.title = title
      conv.updatedAt = Date.now()
    }
  }

  function togglePaper(paperId: string, title: string) {
    const conv = activeConversation.value
    if (!conv) return
    if (!conv.selectedPapers) conv.selectedPapers = []
    const idx = conv.selectedPapers.findIndex(p => p.paper_id === paperId)
    if (idx >= 0) {
      conv.selectedPapers.splice(idx, 1)
    } else {
      conv.selectedPapers.push({ paper_id: paperId, title: title || paperId })
    }
  }

  function removePaper(paperId: string) {
    const conv = activeConversation.value
    if (!conv || !conv.selectedPapers) return
    const idx = conv.selectedPapers.findIndex(p => p.paper_id === paperId)
    if (idx >= 0) conv.selectedPapers.splice(idx, 1)
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      const area = document.querySelector('.messages-area')
      if (area) area.scrollTop = area.scrollHeight
    })
  }

  function sendMessage(rawQuery: string, searchMode: string) {
    if (!rawQuery || !rawQuery.trim() || isStreaming.value) return

    // Ensure active conversation
    if (!activeConversation.value) {
      createConversation()
    }
    const conv = activeConversation.value
    if (!conv) return

    const trimmed = rawQuery.trim()

    // Prepend selected papers to query context
    const papers = conv.selectedPapers
    let finalQuery = trimmed
    if (papers && papers.length > 0) {
      const paperNames = papers.map((p) => p.title).join(', ')
      finalQuery = '[参考论文: ' + paperNames + '] ' + trimmed
    }

    if (!conv.title) {
      conv.title = truncate(trimmed, 30)
    }

    // Push user message
    conv.messages.push({
      role: 'user',
      content: finalQuery,
      timestamp: Date.now(),
    })

    // Push assistant placeholder
    conv.messages.push({
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    })
    conv.updatedAt = Date.now()

    scrollToBottom()

    isStreaming.value = true

    const { connect } = useSseStream()
    streamController = connect({
      url: '/api/chat',
      body: { query: finalQuery, stream: true, search_mode: searchMode },
      onEvent: (evt) => {
        // CRITICAL: always read from reactive conv.messages, NOT a captured variable
        const msgs = conv.messages
        const lastMsg = msgs[msgs.length - 1]
        if (lastMsg && lastMsg.role === 'assistant' && evt.type === 'token') {
          lastMsg.content += (evt.content as string) || ''
        }
        conv.updatedAt = Date.now()
        scrollToBottom()
      },
      onDone: () => {
        isStreaming.value = false
        streamController = null
        const msgs = conv.messages
        const lastMsg = msgs[msgs.length - 1]
        if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.content.trim()) {
          msgs.splice(msgs.length - 1, 1, {
            role: 'assistant',
            content: '抱歉，未能生成回复。请稍后重试。',
            timestamp: Date.now(),
          })
        }
        conv.updatedAt = Date.now()
        scrollToBottom()
      },
      onError: (err) => {
        isStreaming.value = false
        streamController = null
        const msgs = conv.messages
        const lastMsg = msgs[msgs.length - 1]
        if (lastMsg && lastMsg.role === 'assistant') {
          if (!lastMsg.content.trim()) {
            msgs.splice(msgs.length - 1, 1, {
              role: 'assistant',
              content: '⚠️ ' + err,
              timestamp: Date.now(),
            })
          } else {
            lastMsg.content += '\n\n⚠️ *' + err + '*'
          }
        }
        conv.updatedAt = Date.now()
        scrollToBottom()
      },
    })
  }

  function stopStreaming() {
    if (streamController) {
      streamController.abort()
      streamController = null
      isStreaming.value = false
    }
  }

  // Initialize: select first conversation if any, otherwise create one
  if (sortedConversations.value.length > 0 && !activeConversationId.value) {
    activeConversationId.value = sortedConversations.value[0].id
  } else if (sortedConversations.value.length === 0) {
    // Auto-create a conversation on first visit so the chat UI is immediately visible
    createConversation()
  }

  return {
    conversations,
    activeConversationId,
    isStreaming,
    sortedConversations,
    activeConversation,
    selectedPapers,
    createConversation,
    selectConversation,
    requestDelete,
    confirmDelete,
    clearAll,
    rename,
    togglePaper,
    removePaper,
    sendMessage,
    stopStreaming,
  }
})
