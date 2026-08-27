<script setup lang="ts">
import { ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { useConversationsStore } from '@/stores/conversations'
import { fetchLibraryPapers } from '@/api/library'
import type { LibraryPaper } from '@/types'

const ui = useUiStore()
const conv = useConversationsStore()

const papersList = ref<LibraryPaper[]>([])
const loading = ref(false)

async function loadPapers() {
  if (!ui.paperSelectOpen) return
  loading.value = true
  try {
    papersList.value = await fetchLibraryPapers()
  } catch {
    papersList.value = []
  } finally {
    loading.value = false
  }
}

watch(() => ui.paperSelectOpen, (open) => {
  if (open) loadPapers()
})

function isSelected(paperId: string): boolean {
  return conv.selectedPapers.some(p => p.paper_id === paperId)
}

function togglePaper(paperId: string, title: string) {
  conv.togglePaper(paperId, title)
}

function close() {
  ui.paperSelectOpen = false
}
</script>

<template>
  <NModal v-model:show="ui.paperSelectOpen" style="max-width: 560px;">
    <div class="select-root">
      <!-- Header -->
      <div class="select-header">
        <div class="select-header-left">
          <span class="select-header-icon">📎</span>
          <div>
            <h3 class="select-title">选择参考论文</h3>
            <p class="select-subtitle">勾选本次对话要聚焦的论文（可多选）</p>
          </div>
        </div>
        <button class="select-close-btn" @click="close">✕</button>
      </div>

      <!-- Body -->
      <div class="select-body">
        <div v-if="loading" class="select-loading">正在加载论文列表…</div>

        <div v-else-if="papersList.length > 0" class="paper-list">
          <div
            v-for="p in papersList"
            :key="p.paper_id"
            class="paper-row"
            :class="{ selected: isSelected(p.paper_id) }"
            @click="togglePaper(p.paper_id, p.title || p.paper_id)"
          >
            <span class="custom-checkbox" :class="{ checked: isSelected(p.paper_id) }">
              <span v-if="isSelected(p.paper_id)">✓</span>
            </span>
            <div class="paper-info">
              <span class="paper-title">{{ p.title || p.paper_id }}</span>
              <span class="paper-authors">{{ p.authors || '未知作者' }}</span>
            </div>
          </div>
        </div>

        <div v-else class="select-empty">
          <p>知识库中暂无论文</p>
          <p class="hint">请先上传 PDF 论文</p>
        </div>
      </div>

      <!-- Footer -->
      <div class="select-footer">
        <span v-if="conv.selectedPapers.length > 0" class="selected-count">
          已选 {{ conv.selectedPapers.length }} 篇
        </span>
        <span v-else style="flex:1"></span>
        <button class="btn-cancel" @click="close">取消</button>
        <button class="btn-primary" @click="close">确认选择</button>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.select-root {
  min-width: 440px;
  max-width: 560px;
  background: var(--main-surface);
  border-radius: var(--radius-lg);
}

/* Header */
.select-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 24px 28px 0; flex-shrink: 0;
}
.select-header-left { display: flex; align-items: flex-start; gap: 14px; }
.select-header-icon { font-size: 28px; line-height: 1; margin-top: 2px; }
.select-title { font-size: 18px; font-weight: 700; color: var(--main-heading); margin: 0 0 4px; letter-spacing: -0.3px; }
.select-subtitle { font-size: 13px; color: var(--main-muted); margin: 0; }
.select-close-btn {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: var(--main-bg); color: var(--main-muted); font-size: 14px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.15s var(--ease); flex-shrink: 0;
}
.select-close-btn:hover { background: var(--main-border); color: var(--main-text); }

/* Body */
.select-body { padding: 16px 28px 0; }
.select-loading { text-align: center; padding: 36px; color: var(--main-muted); font-size: 14px; }
.select-empty { text-align: center; padding: 40px 24px; color: var(--main-muted); }
.select-empty p { font-size: 14px; margin: 0; }
.select-empty .hint { font-size: 12px; opacity: 0.5; margin-top: 4px; }

/* Paper list */
.paper-list {
  max-height: 340px; overflow-y: auto;
  border: 1px solid var(--main-border); border-radius: var(--radius-sm);
}
.paper-row {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; cursor: pointer;
  transition: all 0.15s var(--ease);
  border-bottom: 1px solid var(--main-border);
}
.paper-row:last-child { border-bottom: none; }
.paper-row:hover { background: #fafaff; }
.paper-row.selected { background: var(--accent-light); }
.paper-info {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column; gap: 3px;
}
.paper-title {
  font-size: 13.5px; font-weight: 600; color: var(--main-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.paper-authors {
  font-size: 11.5px; color: var(--main-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* Custom checkbox */
.custom-checkbox {
  width: 18px; height: 18px; border-radius: 5px;
  border: 2px solid var(--main-border);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: all 0.2s var(--ease);
  font-size: 11px; font-weight: 700; color: transparent;
}
.custom-checkbox.checked {
  background: var(--accent); border-color: var(--accent); color: #fff;
}

/* Footer */
.select-footer {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 28px 20px; flex-shrink: 0;
}
.selected-count {
  font-size: 13px; color: var(--accent); font-weight: 700;
  background: var(--accent-light); padding: 4px 14px; border-radius: 20px;
}
.btn-cancel, .btn-primary {
  padding: 10px 22px; border-radius: var(--radius-sm); font-size: 14px;
  font-weight: 600; transition: all 0.15s var(--ease); border: none; cursor: pointer;
}
.btn-cancel { background: var(--main-bg); color: var(--main-text); border: 1px solid var(--main-border); }
.btn-cancel:hover { background: var(--main-border); }
.btn-primary { background: var(--accent-gradient); color: #fff; box-shadow: 0 2px 8px rgba(108,92,231,0.25); }
.btn-primary:hover { box-shadow: 0 4px 14px rgba(108,92,231,0.4); filter: brightness(1.06); }
</style>
