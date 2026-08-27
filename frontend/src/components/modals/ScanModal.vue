<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { NModal, NProgress } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { useSseStream } from '@/composables/useSseStream'

const ui = useUiStore()

interface ScanState {
  running: boolean; pct: number; total: number
  scanned: number; processed: number; skipped: number; errors: number
  statusMessage: string
}

const state = ref<ScanState>({
  running: false, pct: 0, total: 0,
  scanned: 0, processed: 0, skipped: 0, errors: 0,
  statusMessage: '',
})

const logs = ref<{ text: string; cls: string }[]>([])
const logRef = ref<HTMLElement | null>(null)
const streamCtrl = ref<AbortController | null>(null)
const paused = ref(false)

function addLog(text: string, cls = '') {
  logs.value.push({ text, cls })
  if (logs.value.length > 200) logs.value.splice(0, logs.value.length - 200)
  nextTick(() => { if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight })
}

const doneCount = computed(() => state.value.processed + state.value.skipped + state.value.errors)
const isComplete = computed(() => !state.value.running && !paused.value && state.value.total > 0)

function startScan() {
  state.value.running = true
  paused.value = false
  if (logs.value.length === 0) {
    state.value.statusMessage = '正在收集文件列表…'
  }
  addLog(paused.value ? '▶ 继续扫描…' : '▶ 开始扫描…', 'info')

  const { connect } = useSseStream()
  streamCtrl.value = connect({
    url: '/api/scan?stream=true&force=false', method: 'POST',
    onEvent: (evt) => {
      switch (evt.type) {
        case 'start':
          state.value.total = (evt.total as number) || 0
          state.value.statusMessage = (evt.message as string) || ''
          addLog(state.value.statusMessage, 'info')
          break
        case 'skip':
          state.value.skipped = (evt.skipped as number) || 0
          state.value.processed = (evt.processed as number) || 0
          state.value.errors = (evt.errors as number) || 0
          state.value.scanned = (evt.scanned as number) || 0
          state.value.pct = state.value.total > 0 ? Math.round(doneCount.value / state.value.total * 100) : 0
          state.value.statusMessage = (evt.message as string) || ''
          addLog((evt.file as string || '') + ' — ' + (evt.message as string || ''), 'skip')
          break
        case 'process':
          state.value.scanned = (evt.scanned as number) || 0
          state.value.pct = state.value.total > 0 ? Math.round(doneCount.value / state.value.total * 100) : 0
          state.value.statusMessage = (evt.message as string) || ''
          addLog((evt.file as string || '') + ' — ' + (evt.message as string || ''), 'process')
          break
        case 'done':
          state.value.processed = (evt.processed as number) || 0
          state.value.skipped = (evt.skipped as number) || 0
          state.value.errors = (evt.errors as number) || 0
          state.value.scanned = (evt.scanned as number) || 0
          state.value.statusMessage = (evt.message as string) || ''
          addLog((evt.file as string || '') + ' — ' + (evt.message as string || ''), 'done')
          break
        case 'error':
          state.value.errors = (evt.errors as number) || 0
          state.value.scanned = (evt.scanned as number) || 0
          state.value.statusMessage = (evt.message as string) || ''
          addLog((evt.file as string || '') + ' — ' + (evt.message as string || ''), 'error')
          break
        case 'complete':
          state.value.running = false
          paused.value = false
          state.value.processed = (evt.processed as number) || 0
          state.value.skipped = (evt.skipped as number) || 0
          state.value.errors = (evt.errors as number) || 0
          state.value.scanned = (evt.scanned as number) || 0
          state.value.pct = 100
          state.value.total = (evt.total as number) || 0
          state.value.statusMessage = (evt.message as string) || ''
          addLog('━━━ ' + (evt.message as string || '') + ' ━━━', 'info')
          ui.refreshPaperCount()
          break
      }
    },
    onDone: () => {
      if (!paused.value) state.value.running = false
    },
    onError: (err) => {
      if (!paused.value) {
        state.value.running = false
        addLog('网络错误: ' + err, 'error')
      }
    },
  })
}

function pauseScan() {
  paused.value = true
  state.value.running = false
  if (streamCtrl.value) {
    streamCtrl.value.abort()
    streamCtrl.value = null
  }
  state.value.statusMessage = '已暂停 — 点击继续扫描'
  addLog('⏸ 扫描已暂停', 'info')
}

function resumeScan() {
  startScan()
}

function close() {
  if (state.value.running && !paused.value) return
  ui.scanOpen = false
}

watch(() => ui.scanOpen, (open) => {
  if (open) { paused.value = false; startScan() }
})
</script>

<template>
  <NModal v-model:show="ui.scanOpen" :mask-closable="!state.running" style="max-width: 600px;">
    <div class="scan-root">
      <!-- Header -->
      <div class="scan-header">
        <div class="scan-header-left">
          <span class="scan-header-icon">📂</span>
          <div>
            <h3 class="scan-title">扫描入库</h3>
            <p class="scan-subtitle" v-if="state.total > 0">
              已处理 {{ doneCount }} / {{ state.total }} 个文件
            </p>
            <p class="scan-subtitle" v-else>正在扫描本地论文目录…</p>
          </div>
        </div>
        <button class="scan-close-btn" @click="close" :disabled="state.running">✕</button>
      </div>

      <!-- Body -->
      <div class="scan-body">
        <!-- Progress bar -->
        <div class="scan-progress-section">
          <NProgress
            :percentage="state.pct"
            :height="6"
            :border-radius="3"
            :color="isComplete ? '#2ecc71' : '#6c5ce7'"
          />
          <div class="progress-label">{{ state.statusMessage || '准备中…' }}</div>
        </div>

        <!-- Stat chips -->
        <div class="stat-chips" v-if="state.total > 0">
          <span class="stat-chip done">
            <span class="chip-dot"></span>
            入库 {{ state.processed }}
          </span>
          <span class="stat-chip skip">
            <span class="chip-dot"></span>
            跳过 {{ state.skipped }}
          </span>
          <span class="stat-chip error" v-if="state.errors > 0">
            <span class="chip-dot"></span>
            失败 {{ state.errors }}
          </span>
        </div>

        <!-- Log panel -->
        <div ref="logRef" class="scan-log-panel">
          <div v-for="(log, idx) in logs" :key="idx" class="log-line" :class="log.cls">
            <span class="log-prefix">›</span> {{ log.text }}
          </div>
          <div v-if="logs.length === 0 && state.running" class="log-placeholder">
            等待扫描开始…
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="scan-footer">
        <div class="footer-left">
          <span v-if="paused" class="paused-badge">⏸ 已暂停</span>
        </div>
        <div class="footer-right">
          <button
            v-if="state.running"
            class="btn-pause"
            @click="pauseScan"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
            暂停
          </button>
          <button
            v-if="paused"
            class="btn-resume"
            @click="resumeScan"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            继续扫描
          </button>
          <button class="btn-close" @click="close" :disabled="state.running && !paused">
            {{ state.running ? '扫描中…' : '关闭' }}
          </button>
        </div>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.scan-root {
  min-width: 480px;
  max-width: 600px;
  background: var(--main-surface);
  border-radius: var(--radius-lg);
}

/* Header */
.scan-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 24px 28px 0; flex-shrink: 0;
}
.scan-header-left { display: flex; align-items: flex-start; gap: 14px; }
.scan-header-icon { font-size: 28px; line-height: 1; margin-top: 2px; }
.scan-title { font-size: 18px; font-weight: 700; color: var(--main-heading); margin: 0 0 4px; letter-spacing: -0.3px; }
.scan-subtitle { font-size: 13px; color: var(--main-muted); margin: 0; }
.scan-close-btn {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: var(--main-bg); color: var(--main-muted); font-size: 14px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.15s var(--ease); flex-shrink: 0;
}
.scan-close-btn:hover:not(:disabled) { background: var(--main-border); color: var(--main-text); }
.scan-close-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Body */
.scan-body { padding: 20px 28px 0; }

/* Progress */
.scan-progress-section { margin-bottom: 14px; }
.progress-label {
  display: flex; justify-content: space-between;
  font-size: 13px; color: var(--main-muted); margin-top: 6px;
}

/* Stat chips */
.stat-chips { display: flex; gap: 10px; margin-bottom: 14px; }
.stat-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 12px; border-radius: 14px; font-size: 12.5px; font-weight: 600;
}
.stat-chip.done { background: #dcfce7; color: #166534; }
.stat-chip.skip { background: #f1f5f9; color: #475569; }
.stat-chip.error { background: #fecaca; color: #991b1b; }
.chip-dot { width: 6px; height: 6px; border-radius: 50%; }
.stat-chip.done .chip-dot { background: #22c55e; }
.stat-chip.skip .chip-dot { background: #94a3b8; }
.stat-chip.error .chip-dot { background: #ef4444; }

/* Log panel */
.scan-log-panel {
  background: #1a1b2e; border-radius: var(--radius-sm);
  padding: 14px 16px; max-height: 280px; min-height: 80px; overflow-y: auto;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 12.5px; line-height: 1.8;
}
.log-line { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.log-prefix { opacity: 0.4; margin-right: 6px; }
.log-line.info  { color: #94a3b8; }
.log-line.skip  { color: #64748b; }
.log-line.process { color: #e2e8f0; }
.log-line.done  { color: #4ade80; }
.log-line.error { color: #f87171; }
.log-placeholder { color: #475569; text-align: center; padding: 20px; }

/* Footer */
.scan-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 28px 20px; flex-shrink: 0;
}
.footer-left { flex: 1; }
.footer-right { display: flex; gap: 8px; }

.paused-badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 14px; background: #fef3c7; color: #92400e;
  border-radius: 20px; font-size: 12.5px; font-weight: 700;
}

/* Buttons */
.btn-close, .btn-pause, .btn-resume {
  padding: 10px 20px; border-radius: var(--radius-sm); font-size: 14px;
  font-weight: 600; cursor: pointer; transition: all 0.15s var(--ease);
  display: inline-flex; align-items: center; gap: 6px; border: none;
}
.btn-close {
  background: var(--main-bg); color: var(--main-text);
  border: 1px solid var(--main-border);
}
.btn-close:hover:not(:disabled) { background: var(--main-border); }
.btn-close:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-pause {
  background: #fef3c7; color: #92400e;
}
.btn-pause:hover { background: #fde68a; }

.btn-resume {
  background: var(--accent-gradient); color: #fff;
  box-shadow: 0 2px 8px rgba(108,92,231,0.3);
}
.btn-resume:hover { box-shadow: 0 4px 14px rgba(108,92,231,0.45); filter: brightness(1.06); }
</style>
