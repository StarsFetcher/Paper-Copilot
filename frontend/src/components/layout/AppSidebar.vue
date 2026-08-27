<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useUiStore } from '@/stores/ui'
import { useConversationsStore } from '@/stores/conversations'
import { storeToRefs } from 'pinia'
import { NModal, NInput, NDialog, NDropdown, useDialog, useMessage } from 'naive-ui'
import ConversationItem from './ConversationItem.vue'
import SidebarFooter from './SidebarFooter.vue'

const ui = useUiStore()
const conv = useConversationsStore()
const { sidebarCollapsed } = storeToRefs(ui)
const { sortedConversations, conversations } = storeToRefs(conv)

const dialog = useDialog()
const message = useMessage()

// Rename modal
const showRenameModal = ref(false)
const renameValue = ref('')
const renameTargetId = ref<string | null>(null)

function openRenameModal(id: string) {
  const c = conversations.value.find(x => x.id === id)
  if (!c) return
  renameTargetId.value = id
  renameValue.value = c.title || ''
  showRenameModal.value = true
}

function confirmRename() {
  const name = renameValue.value.trim()
  if (!name || !renameTargetId.value) return
  conv.rename(renameTargetId.value, name)
  showRenameModal.value = false
  renameTargetId.value = null
  renameValue.value = ''
}

// Delete
function requestDelete(id: string) {
  dialog.warning({
    title: '确认删除',
    content: '确定要删除这个会话吗？此操作不可撤销。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => conv.confirmDelete(id),
  })
}

function requestClearAll() {
  dialog.warning({
    title: '清空所有对话',
    content: `确定要删除全部 ${conversations.value.length} 个会话吗？此操作不可撤销。`,
    positiveText: '全部清空',
    negativeText: '取消',
    onPositiveClick: () => {
      conv.clearAll()
      message.success('所有对话已清空')
    },
  })
}

// Context menu
const ctxMenuX = ref(0)
const ctxMenuY = ref(0)
const ctxMenuConvId = ref<string | null>(null)
const showCtxMenu = ref(false)

function openCtxMenu(e: MouseEvent, convId: string) {
  ctxMenuX.value = e.clientX
  ctxMenuY.value = e.clientY
  ctxMenuConvId.value = convId
  showCtxMenu.value = true
}

const ctxMenuOptions = [
  { label: '✏️ 重命名', key: 'rename' },
  { label: '🗑 删除对话', key: 'delete' },
]

function handleCtxSelect(key: string) {
  showCtxMenu.value = false
  if (!ctxMenuConvId.value) return
  if (key === 'rename') openRenameModal(ctxMenuConvId.value)
  else if (key === 'delete') requestDelete(ctxMenuConvId.value)
}

// Scan & Upload
const scanning = ref(false)
function handleScan() {
  if (scanning.value) return
  ui.scanOpen = true
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
    <!-- Header -->
    <div class="sidebar-header">
      <div class="logo">
        <span class="logo-icon">📄</span>
        <span class="logo-text" v-show="!sidebarCollapsed">Paper-Copilot</span>
      </div>
      <button class="btn-icon btn-toggle" @click="sidebarCollapsed = !sidebarCollapsed"
        :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'">
        <span v-if="sidebarCollapsed">☰</span>
        <span v-else>✕</span>
      </button>
    </div>

    <!-- Upload button -->
    <button class="btn-upload" @click="ui.uploadOpen = true" v-show="!sidebarCollapsed">
      <span>📄</span> 上传论文
    </button>

    <!-- Scan button -->
    <button class="btn-scan" @click="handleScan" :disabled="scanning" v-show="!sidebarCollapsed">
      <span>📂</span> {{ scanning ? '扫描中…' : '扫描入库' }}
    </button>

    <!-- Paper Manager button -->
    <button class="btn-upload" @click="ui.paperManagerOpen = true" v-show="!sidebarCollapsed" style="border-style:solid;">
      <span>📋</span> 管理论文
    </button>

    <!-- New Chat -->
    <button class="btn-new-chat" @click="conv.createConversation()" v-show="!sidebarCollapsed">
      <span>＋</span> 新建对话
    </button>

    <!-- Conversation list -->
    <div class="conversation-list" v-show="!sidebarCollapsed">
      <div v-if="sortedConversations.length === 0" class="empty-conversations">
        <p>暂无历史会话</p>
        <p class="hint">点击上方按钮开始新的对话</p>
      </div>

      <ConversationItem
        v-for="c in sortedConversations"
        :key="c.id"
        :conv="c"
        :active="c.id === conv.activeConversationId"
        @select="conv.selectConversation"
        @contextmenu="openCtxMenu"
      />

      <button v-if="sortedConversations.length > 0" class="btn-clear-all" @click="requestClearAll">
        🗑 清空所有对话
      </button>
    </div>

    <!-- Footer -->
    <SidebarFooter />
  </aside>

  <!-- Context menu (manual positioning via NDropdown with x/y) -->
  <NDropdown
    :options="ctxMenuOptions"
    :show="showCtxMenu"
    :x="ctxMenuX"
    :y="ctxMenuY"
    placement="bottom-start"
    @select="handleCtxSelect"
    @clickoutside="showCtxMenu = false"
  />

  <!-- Rename Modal -->
  <NModal v-model:show="showRenameModal" title="✏️ 重命名对话">
    <div style="padding: 24px;">
      <NInput
        v-model:value="renameValue"
        placeholder="输入新名称…"
        maxlength="50"
        @keyup.enter="confirmRename"
      />
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px;">
        <button class="btn-cancel" @click="showRenameModal = false">取消</button>
        <button class="btn-primary" @click="confirmRename" :disabled="!renameValue.trim()">确认</button>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
/* Shared button styles for modals */
.btn-cancel {
  padding: 10px 22px;
  border-radius: var(--radius-sm);
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 14px;
  font-weight: 500;
  border: 1px solid var(--main-border);
  transition: all 0.15s var(--ease);
}
.btn-cancel:hover { background: var(--main-border); }
.btn-primary {
  padding: 10px 22px;
  border-radius: var(--radius-sm);
  background: var(--accent-gradient);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.15s var(--ease);
  box-shadow: 0 2px 8px rgba(108,92,231,0.25);
}
.btn-primary:hover {
  box-shadow: 0 4px 14px rgba(108,92,231,0.4);
  transform: translateY(-1px);
  filter: brightness(1.06);
}
.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>
