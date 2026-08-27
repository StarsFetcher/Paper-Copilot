<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { NModal, NTag, NSpin, NPopconfirm, useMessage } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { fetchLibraryPapers, deleteLibraryPaper, batchDeleteLibraryPapers } from '@/api/library'
import type { LibraryPaper } from '@/types'

const ui = useUiStore()
const message = useMessage()

const papers = ref<LibraryPaper[]>([])
const loading = ref(false)
const deleting = ref(false)
const selectedIds = ref<string[]>([])
const deleteTarget = ref<string | null>(null)

const allSelected = computed(() =>
  papers.value.length > 0 && selectedIds.value.length === papers.value.length,
)

const selectedCount = computed(() => selectedIds.value.length)

async function loadPapers() {
  if (!ui.paperManagerOpen) return
  loading.value = true
  try {
    papers.value = await fetchLibraryPapers()
  } catch (e: any) {
    message.error(e.message || '获取论文列表失败')
    papers.value = []
  } finally {
    loading.value = false
  }
}

watch(() => ui.paperManagerOpen, (open) => {
  if (open) { selectedIds.value = []; deleteTarget.value = null; loadPapers() }
})

function toggleSelect(id: string) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function toggleAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = papers.value.map(p => p.paper_id)
  }
}

async function handleSingleDelete(paperId: string) {
  deleting.value = true
  try {
    await deleteLibraryPaper(paperId)
    message.success('论文已删除')
    papers.value = papers.value.filter(p => p.paper_id !== paperId)
    selectedIds.value = selectedIds.value.filter(id => id !== paperId)
    ui.refreshPaperCount()
  } catch (e: any) {
    message.error(e.message || '删除失败')
  } finally {
    deleting.value = false
    deleteTarget.value = null
  }
}

async function batchDelete() {
  if (selectedIds.value.length === 0) return
  deleting.value = true
  try {
    const result = await batchDeleteLibraryPapers(selectedIds.value, true)
    let msg = `${result.deleted} 篇已删除`
    if (result.errors?.length) msg += `，${result.errors.length} 篇失败`
    message.success(msg)
    await loadPapers()
    ui.refreshPaperCount()
    selectedIds.value = []
  } catch (e: any) {
    message.error(e.message || '批量删除失败')
  } finally {
    deleting.value = false
  }
}

type StatusKey = 'stored' | 'analyzed' | 'screened' | 'discovered'
const statusConfig: Record<string, { label: string; bg: string; text: string; icon: string }> = {
  stored:    { label: '已入库',   bg: '#dcfce7', text: '#166534', icon: '📚' },
  analyzed:  { label: '已分析',   bg: '#ede9fe', text: '#6c5ce7', icon: '🔬' },
  screened:  { label: '已筛选',   bg: '#e0f2fe', text: '#075985', icon: '✅' },
  discovered:{ label: '已发现',   bg: '#fef3c7', text: '#92400e', icon: '🔍' },
}

function statusInfo(s: string) {
  return statusConfig[s] || statusConfig.discovered
}

const totalCount = computed(() => papers.value.length)
const analyzedCount = computed(() => papers.value.filter(p => p.status === 'analyzed' || p.status === 'stored').length)
</script>

<template>
  <NModal
    v-model:show="ui.paperManagerOpen"
    style="max-width: 700px;"
    :mask-closable="!deleting"
  >
    <div class="manager-root">
      <!-- Header -->
      <div class="manager-header">
        <div class="manager-header-left">
          <span class="manager-header-icon">📋</span>
          <div>
            <h3 class="manager-title">论文库管理</h3>
            <p class="manager-subtitle" v-if="!loading">
              {{ totalCount }} 篇论文
              <template v-if="analyzedCount > 0">
                · {{ analyzedCount }} 篇已分析
              </template>
            </p>
          </div>
        </div>
        <button class="manager-close-btn" @click="ui.paperManagerOpen = false" :disabled="deleting">✕</button>
      </div>

      <div class="manager-body">
        <!-- Skeleton loading -->
        <div v-if="loading" class="loading-skeleton">
          <div v-for="i in 4" :key="i" class="skeleton-row">
            <div class="skeleton-checkbox"></div>
            <div class="skeleton-lines">
              <div class="skeleton-line w-60"></div>
              <div class="skeleton-line w-40"></div>
            </div>
          </div>
        </div>

        <!-- Paper list -->
        <div v-else-if="papers.length > 0" class="paper-list">
          <!-- Select all bar -->
          <div class="select-all-bar" v-if="papers.length > 1">
            <label class="select-all-label" @click.prevent="toggleAll">
              <span class="custom-checkbox" :class="{ checked: allSelected, partial: !allSelected && selectedCount > 0 }">
                <span v-if="allSelected">✓</span>
                <span v-else-if="selectedCount > 0">−</span>
              </span>
              <span class="select-all-text">
                {{ allSelected ? '取消全选' : '全选' }}
                <template v-if="!allSelected && selectedCount > 0">
                  ({{ selectedCount }}/{{ totalCount }})
                </template>
              </span>
            </label>
          </div>

          <!-- Paper cards -->
          <div
            v-for="p in papers"
            :key="p.paper_id"
            class="paper-card"
            :class="{
              selected: selectedIds.includes(p.paper_id),
              'delete-target': deleteTarget === p.paper_id,
            }"
            @click="toggleSelect(p.paper_id)"
          >
            <!-- Checkbox -->
            <span class="custom-checkbox card-checkbox" :class="{ checked: selectedIds.includes(p.paper_id) }">
              <span v-if="selectedIds.includes(p.paper_id)">✓</span>
            </span>

            <!-- Status accent bar -->
            <div class="card-accent" :style="{ background: statusInfo(p.status || 'discovered').text }"></div>

            <!-- Content -->
            <div class="card-content">
              <div class="card-title-row">
                <span class="card-title" :title="p.title || p.paper_id">
                  {{ p.title || p.paper_id }}
                </span>
              </div>
              <div class="card-meta">
                <span class="card-authors" :title="p.authors">
                  {{ p.authors || '未知作者' }}
                </span>
                <span
                  class="card-status"
                  :style="{ background: statusInfo(p.status || 'discovered').bg, color: statusInfo(p.status || 'discovered').text }"
                >
                  {{ statusInfo(p.status || 'discovered').icon }}
                  {{ statusInfo(p.status || 'discovered').label }}
                </span>
              </div>
            </div>

            <!-- Scores -->
            <div class="card-scores">
              <div v-if="p.quality_score" class="score-item" title="质量评分">
                <div class="score-ring" :style="{ '--pct': (p.quality_score / 10 * 100) + '%' }">
                  <svg viewBox="0 0 36 36">
                    <circle cx="18" cy="18" r="15" fill="none" stroke="var(--main-border)" stroke-width="3"/>
                    <circle cx="18" cy="18" r="15" fill="none" stroke="url(#scoreGrad)" stroke-width="3"
                      stroke-linecap="round"
                      :stroke-dasharray="(p.quality_score / 10 * 94.2) + ' 94.2'"
                      transform="rotate(-90 18 18)"/>
                  </svg>
                </div>
                <span class="score-num">{{ p.quality_score.toFixed(1) }}</span>
              </div>
            </div>

            <!-- Delete -->
            <button
              v-if="deleteTarget !== p.paper_id"
              class="card-delete-btn"
              @click.stop="deleteTarget = p.paper_id"
              title="删除"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
              </svg>
            </button>
            <button
              v-else
              class="card-delete-confirm"
              @click.stop="handleSingleDelete(p.paper_id)"
              :disabled="deleting"
            >确认删除</button>
            <button
              v-if="deleteTarget === p.paper_id"
              class="card-cancel-btn"
              @click.stop="deleteTarget = null"
            >取消</button>
          </div>
        </div>

        <!-- Empty -->
        <div v-else class="empty-papers">
          <div class="empty-illustration">
            <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
              <rect x="12" y="8" width="56" height="64" rx="6" stroke="var(--main-border)" stroke-width="2" fill="var(--main-bg)"/>
              <rect x="20" y="18" width="40" height="6" rx="3" fill="var(--main-border)"/>
              <rect x="20" y="30" width="32" height="4" rx="2" fill="var(--main-border)" opacity="0.5"/>
              <rect x="20" y="40" width="36" height="4" rx="2" fill="var(--main-border)" opacity="0.3"/>
              <rect x="20" y="50" width="28" height="4" rx="2" fill="var(--main-border)" opacity="0.2"/>
            </svg>
          </div>
          <p class="empty-title">还没有论文</p>
          <p class="empty-desc">上传 PDF 或搜索 arXiv 来充实你的论文库</p>
        </div>
      </div>

      <!-- Bottom bar -->
      <div class="manager-footer" v-if="papers.length > 0">
        <div class="footer-left">
          <span v-if="selectedCount > 0" class="selected-badge">
            已选 {{ selectedCount }} 篇
          </span>
        </div>
        <div class="footer-right">
          <NPopconfirm @positive-click="batchDelete" :disabled="selectedCount === 0">
            <template #trigger>
              <button class="btn-batch-delete" :disabled="selectedCount === 0 || deleting">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                </svg>
                {{ deleting ? '删除中…' : `删除选中 (${selectedCount})` }}
              </button>
            </template>
            <template #default>
              <p>确定要删除选中的 {{ selectedCount }} 篇论文吗？</p>
              <p style="font-size:12px;color:var(--main-muted);margin-top:4px;">将同时从向量索引中移除</p>
            </template>
          </NPopconfirm>
        </div>
      </div>
    </div>
  </NModal>

  <!-- SVG gradient for score rings -->
  <svg width="0" height="0" style="position:absolute">
    <defs>
      <linearGradient id="scoreGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#6c5ce7"/>
        <stop offset="100%" stop-color="#a78bfa"/>
      </linearGradient>
    </defs>
  </svg>
</template>

<style scoped>
/* ============================================================
   Root layout
   ============================================================ */
.manager-root {
  min-width: 560px;
  max-width: 700px;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
  background: var(--main-surface);
  border-radius: var(--radius-lg);
}

/* ============================================================
   Header
   ============================================================ */
.manager-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 24px 28px 0;
  flex-shrink: 0;
}
.manager-header-left {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}
.manager-header-icon {
  font-size: 28px;
  line-height: 1;
  margin-top: 2px;
}
.manager-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--main-heading);
  margin: 0 0 4px;
  letter-spacing: -0.3px;
}
.manager-subtitle {
  font-size: 13px;
  color: var(--main-muted);
  margin: 0;
}
.manager-close-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: var(--main-bg);
  color: var(--main-muted);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s var(--ease);
  flex-shrink: 0;
}
.manager-close-btn:hover {
  background: var(--main-border);
  color: var(--main-text);
}

/* ============================================================
   Body
   ============================================================ */
.manager-body {
  padding: 16px 28px 0;
  flex: 1;
  overflow-y: auto;
  min-height: 200px;
}

/* ============================================================
   Skeleton loading
   ============================================================ */
.loading-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
.skeleton-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  background: var(--main-bg);
  border-radius: var(--radius-sm);
}
.skeleton-checkbox {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: var(--main-border);
  flex-shrink: 0;
}
.skeleton-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.skeleton-line {
  height: 10px;
  border-radius: 5px;
  background: var(--main-border);
  animation: shimmer 1.5s infinite;
}
.skeleton-line.w-60 { width: 60%; }
.skeleton-line.w-40 { width: 40%; }
@keyframes shimmer {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}

/* ============================================================
   Select all bar
   ============================================================ */
.select-all-bar {
  padding: 6px 4px 10px;
  border-bottom: 1px solid var(--main-border);
  margin-bottom: 6px;
}
.select-all-label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}
.select-all-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--main-muted);
}

/* ============================================================
   Custom checkbox
   ============================================================ */
.custom-checkbox {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 2px solid var(--main-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s var(--ease);
  font-size: 11px;
  font-weight: 700;
  color: transparent;
  background: transparent;
}
.custom-checkbox.checked {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.custom-checkbox.partial {
  background: var(--accent-light);
  border-color: var(--accent);
  color: var(--accent);
}

/* ============================================================
   Paper card
   ============================================================ */
.paper-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.paper-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--main-surface);
  border: 1px solid var(--main-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.18s var(--ease);
  position: relative;
  overflow: hidden;
}
.paper-card:hover {
  border-color: #d4d0f0;
  box-shadow: 0 2px 12px rgba(108,92,231,0.06);
  transform: translateY(-1px);
}
.paper-card.selected {
  border-color: var(--accent);
  background: var(--accent-light);
}

/* Left accent */
.card-accent {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: 3px 0 0 3px;
  opacity: 0.7;
  transition: opacity 0.2s var(--ease);
}
.paper-card:hover .card-accent { opacity: 1; }

.card-checkbox {
  position: relative;
  z-index: 1;
}

.card-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.card-title-row {
  display: flex;
  align-items: center;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--main-heading);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  line-height: 1.3;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.card-authors {
  font-size: 12px;
  color: var(--main-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.card-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.2px;
  flex-shrink: 0;
}

/* ============================================================
   Score ring
   ============================================================ */
.card-scores {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.score-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.score-ring {
  width: 28px;
  height: 28px;
}
.score-ring svg {
  width: 100%;
  height: 100%;
}
.score-ring circle:last-child {
  stroke-dasharray: 94.2;
  stroke-dashoffset: 0;
  transition: stroke-dashoffset 0.6s var(--ease);
}
.score-num {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent);
  min-width: 24px;
}

/* ============================================================
   Delete buttons
   ============================================================ */
.card-delete-btn,
.card-delete-confirm,
.card-cancel-btn {
  height: 30px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s var(--ease);
  flex-shrink: 0;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
.card-delete-btn {
  width: 30px;
  background: transparent;
  color: var(--main-muted);
  opacity: 0;
}
.paper-card:hover .card-delete-btn { opacity: 0.5; }
.card-delete-btn:hover { opacity: 1 !important; color: var(--danger); background: #fee2e2; }

.card-delete-confirm {
  padding: 0 14px;
  background: var(--danger);
  color: #fff;
  animation: fadeInRight 0.2s var(--ease);
}
.card-delete-confirm:hover:not(:disabled) { background: var(--danger-hover); }
.card-delete-confirm:disabled { opacity: 0.5; }

.card-cancel-btn {
  padding: 0 12px;
  background: var(--main-bg);
  color: var(--main-muted);
  border: 1px solid var(--main-border);
  animation: fadeInRight 0.2s var(--ease);
}
.card-cancel-btn:hover { background: var(--main-border); }

.paper-card.delete-target {
  border-color: #fecaca;
  background: #fff5f5;
}

@keyframes fadeInRight {
  from { opacity: 0; transform: translateX(-6px); }
  to { opacity: 1; transform: translateX(0); }
}

/* ============================================================
   Empty state
   ============================================================ */
.empty-papers {
  text-align: center;
  padding: 48px 24px;
}
.empty-illustration { margin-bottom: 16px; }
.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--main-text);
  margin: 0 0 6px;
}
.empty-desc {
  font-size: 13px;
  color: var(--main-muted);
  margin: 0;
}

/* ============================================================
   Footer
   ============================================================ */
.manager-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px 20px;
  flex-shrink: 0;
}
.footer-left { flex: 1; }
.selected-badge {
  display: inline-flex;
  align-items: center;
  padding: 5px 14px;
  background: var(--accent-light);
  color: var(--accent);
  border-radius: 20px;
  font-size: 12.5px;
  font-weight: 700;
}
.btn-batch-delete {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 18px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #fecaca;
  background: #fff;
  color: var(--danger);
  cursor: pointer;
  transition: all 0.2s var(--ease);
}
.btn-batch-delete:hover:not(:disabled) {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}
.btn-batch-delete:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
</style>
