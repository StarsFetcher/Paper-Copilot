<script setup lang="ts">
import { ref } from 'vue'
import { NModal, NProgress, useMessage } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { uploadPdf } from '@/api/upload'
import type { UploadResult } from '@/types'

type UploadStatus = 'idle' | 'uploading' | 'success' | 'error'

const ui = useUiStore()
const msg = useMessage()
const MAX_SIZE_MB = 50

const dragOver = ref(false)
const status = ref<UploadStatus>('idle')
const progress = ref(0)
const fileName = ref('')
const result = ref<UploadResult | null>(null)
const error = ref('')

function reset() {
  status.value = 'idle'
  progress.value = 0
  fileName.value = ''
  result.value = null
  error.value = ''
}

function close() {
  ui.uploadOpen = false
  if (status.value === 'success') ui.refreshPaperCount()
  reset()
}

function validateAndUpload(file: File) {
  if (status.value === 'uploading') return
  if (!file.name.toLowerCase().endsWith('.pdf')) { msg.error('仅支持 PDF 格式文件'); return }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) { msg.error(`文件过大，上限为 ${MAX_SIZE_MB} MB`); return }

  status.value = 'uploading'
  fileName.value = file.name
  progress.value = 0

  uploadPdf(
    file,
    (pct) => { progress.value = pct },
    (data) => { status.value = 'success'; result.value = data; progress.value = 100; msg.success('入库成功: ' + data.file_name) },
    (err) => { status.value = 'error'; error.value = err; msg.error(err) },
  )
}

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) validateAndUpload(files[0])
}

function handleFilePick(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) validateAndUpload(input.files[0])
}
</script>

<template>
  <NModal v-model:show="ui.uploadOpen" @after-leave="reset" style="max-width: 520px;">
    <div class="upload-root">
      <!-- Header -->
      <div class="upload-header">
        <div class="upload-header-left">
          <span class="upload-header-icon">📄</span>
          <div>
            <h3 class="upload-title">上传论文 PDF</h3>
            <p class="upload-subtitle">支持拖拽上传，自动解析章节并向量化</p>
          </div>
        </div>
        <button class="upload-close-btn" @click="close">✕</button>
      </div>

      <div class="upload-body">
        <!-- Idle: Drop zone -->
        <div
          v-if="status === 'idle'"
          class="drop-zone"
          :class="{ dragover: dragOver }"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="handleDrop"
        >
          <div class="drop-icon-box">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
          </div>
          <p class="drop-text">拖拽 PDF 文件到此处</p>
          <p class="drop-or">或</p>
          <label class="btn-file-pick">
            选择文件
            <input type="file" accept=".pdf" @change="handleFilePick" hidden>
          </label>
          <p class="drop-limit">仅支持 PDF，最大 {{ MAX_SIZE_MB }} MB</p>
        </div>

        <!-- Uploading -->
        <div v-if="status === 'uploading'" class="uploading-section">
          <div class="uploading-file">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/>
            </svg>
            <span>{{ fileName }}</span>
          </div>
          <NProgress :percentage="progress" :height="8" :border-radius="4" :color="'#6c5ce7'" />
          <div class="progress-pct">{{ progress }}%</div>
        </div>

        <!-- Success -->
        <div v-if="status === 'success'" class="result-section">
          <div class="result-icon-wrap success-icon">✓</div>
          <h4>上传成功</h4>
          <div class="result-grid" v-if="result">
            <div class="result-cell">
              <span class="result-label">文件名</span>
              <span class="result-val">{{ result.file_name }}</span>
            </div>
            <div class="result-cell">
              <span class="result-label">页数</span>
              <span class="result-val">{{ result.page_count }} 页</span>
            </div>
            <div class="result-cell">
              <span class="result-label">切片数</span>
              <span class="result-val">{{ result.chunk_count }}</span>
            </div>
            <div class="result-cell">
              <span class="result-label">耗时</span>
              <span class="result-val">{{ result.elapsed_seconds }} 秒</span>
            </div>
            <div class="result-cell full-width" v-if="result.sections_detected.length">
              <span class="result-label">检测章节</span>
              <span class="result-val">{{ result.sections_detected.join(', ') }}</span>
            </div>
          </div>
        </div>

        <!-- Error -->
        <div v-if="status === 'error'" class="result-section">
          <div class="result-icon-wrap error-icon">✕</div>
          <h4>上传失败</h4>
          <p class="error-text">{{ error }}</p>
        </div>
      </div>

      <!-- Footer -->
      <div class="upload-footer">
        <button class="btn-cancel" @click="close">{{ status === 'success' ? '完成' : '关闭' }}</button>
        <button v-if="status === 'success'" class="btn-primary" @click="reset">继续上传</button>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.upload-root {
  min-width: 440px;
  max-width: 520px;
  background: var(--main-surface);
  border-radius: var(--radius-lg);
}

/* Header */
.upload-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 24px 28px 0; flex-shrink: 0;
}
.upload-header-left { display: flex; align-items: flex-start; gap: 14px; }
.upload-header-icon { font-size: 28px; line-height: 1; margin-top: 2px; }
.upload-title { font-size: 18px; font-weight: 700; color: var(--main-heading); margin: 0 0 4px; letter-spacing: -0.3px; }
.upload-subtitle { font-size: 13px; color: var(--main-muted); margin: 0; }
.upload-close-btn {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: var(--main-bg); color: var(--main-muted); font-size: 14px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.15s var(--ease); flex-shrink: 0;
}
.upload-close-btn:hover { background: var(--main-border); color: var(--main-text); }

/* Body */
.upload-body { padding: 20px 28px 0; }

/* Drop zone */
.drop-zone {
  border: 2px dashed var(--main-border); border-radius: var(--radius-md);
  padding: 36px 24px; text-align: center; transition: all 0.25s var(--ease);
  background: var(--main-bg);
}
.drop-zone.dragover { border-color: var(--accent); background: var(--accent-light); transform: scale(1.01); }
.drop-icon-box { margin-bottom: 14px; display: flex; justify-content: center; }
.drop-text { font-size: 14px; color: var(--main-text); margin: 0 0 6px; font-weight: 500; }
.drop-or { color: var(--main-muted); font-size: 13px; margin: 8px 0; }
.drop-limit { color: var(--main-muted); font-size: 11px; margin-top: 14px; }

.btn-file-pick {
  display: inline-block; padding: 10px 30px; background: var(--accent-gradient);
  color: #fff; border-radius: var(--radius-sm); font-size: 14px; font-weight: 600;
  cursor: pointer; transition: all 0.2s var(--ease);
  box-shadow: 0 2px 8px rgba(108,92,231,0.25);
}
.btn-file-pick:hover { box-shadow: 0 4px 16px rgba(108,92,231,0.4); transform: translateY(-1px); filter: brightness(1.06); }

/* Uploading */
.uploading-section { text-align: center; }
.uploading-file { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: var(--main-text); margin-bottom: 16px; }
.progress-pct { text-align: center; margin-top: 8px; color: var(--accent); font-weight: 700; font-size: 14px; }

/* Result */
.result-section { text-align: center; }
.result-icon-wrap { width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 700; margin: 0 auto 12px; }
.success-icon { background: #dcfce7; color: #16a34a; }
.error-icon { background: #fecaca; color: #dc2626; }
.result-section h4 { font-size: 16px; font-weight: 700; margin: 0 0 16px; color: var(--main-heading); }
.error-text { color: var(--danger); font-size: 13.5px; word-break: break-all; margin: 0; }

.result-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px; text-align: left;
}
.result-cell {
  background: var(--main-bg); border-radius: var(--radius-sm);
  padding: 12px 14px; display: flex; flex-direction: column; gap: 4px;
}
.result-cell.full-width { grid-column: 1 / -1; }
.result-label { font-size: 11.5px; color: var(--main-muted); }
.result-val { font-size: 13.5px; font-weight: 600; color: var(--main-text); word-break: break-all; }

/* Footer */
.upload-footer {
  display: flex; gap: 10px; justify-content: flex-end;
  padding: 16px 28px 20px; flex-shrink: 0;
}

/* Buttons */
.btn-cancel, .btn-primary {
  padding: 10px 22px; border-radius: var(--radius-sm); font-size: 14px;
  font-weight: 600; transition: all 0.15s var(--ease); border: none; cursor: pointer;
}
.btn-cancel { background: var(--main-bg); color: var(--main-text); border: 1px solid var(--main-border); }
.btn-cancel:hover { background: var(--main-border); }
.btn-primary {
  background: var(--accent-gradient); color: #fff;
  box-shadow: 0 2px 8px rgba(108,92,231,0.25);
}
.btn-primary:hover { box-shadow: 0 4px 14px rgba(108,92,231,0.4); filter: brightness(1.06); }
</style>
