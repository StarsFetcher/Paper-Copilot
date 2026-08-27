<script setup lang="ts">
import { computed, ref } from 'vue'
import { formatTime } from '@/utils/format'
import MarkdownRenderer from './MarkdownRenderer.vue'
import type { Message } from '@/types'

const props = defineProps<{ message: Message; isStreaming: boolean }>()

const avatar = computed(() => (props.message.role === 'user' ? '👤' : '🤖'))

// While the assistant is generating its first tokens, content is still empty —
// show an animated "thinking" indicator instead of a bare blinking cursor.
const showThinking = computed(
  () => props.isStreaming && props.message.role === 'assistant' && !props.message.content.trim(),
)

const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null

async function copyContent() {
  const text = props.message.content
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Fallback for non-secure contexts (e.g. http://lan)
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
    } catch {
      // ignore
    }
    document.body.removeChild(ta)
  }
  copied.value = true
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copied.value = false
    copyTimer = null
  }, 2000)
}
</script>

<template>
  <div class="message-wrapper" :class="props.message.role">
    <div class="message-avatar">{{ avatar }}</div>
    <div class="message-body">
      <div
        class="message-bubble"
        :class="{
          'streaming-cursor': props.isStreaming && props.message.role === 'assistant' && !!props.message.content.trim(),
        }"
      >
        <!-- User query: plain text, preserve line breaks -->
        <div v-if="props.message.role === 'user'" class="user-text">{{ props.message.content }}</div>
        <!-- Assistant answer: markdown + LaTeX + code highlight -->
        <MarkdownRenderer v-else :content="props.message.content" :role="props.message.role" />

        <!-- Streaming: waiting for first token -->
        <div v-if="showThinking" class="thinking" aria-label="正在思考">
          <span></span><span></span><span></span>
        </div>

        <!-- Copy answer -->
        <button
          v-if="props.message.role === 'assistant' && props.message.content.trim()"
          class="btn-copy"
          :class="{ copied }"
          :title="copied ? '已复制' : '复制回答'"
          @click="copyContent"
        >{{ copied ? '✓' : '⧉' }}</button>
      </div>
      <div class="message-time">{{ formatTime(props.message.timestamp) }}</div>
    </div>
  </div>
</template>

<style scoped>
.message-body {
  flex: 1;
  min-width: 0;
}

/* User text — plain, preserve newlines */
.user-text {
  white-space: pre-wrap;
}

/* Streaming thinking dots */
.thinking {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 0;
}

.thinking span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.35;
  animation: thinkBounce 1.2s infinite ease-in-out;
}

.thinking span:nth-child(2) { animation-delay: 0.15s; }
.thinking span:nth-child(3) { animation-delay: 0.3s; }

@keyframes thinkBounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.35; }
  30% { transform: translateY(-5px); opacity: 1; }
}

/* Copy button — hovers in the top-right of assistant bubbles */
.btn-copy {
  position: absolute;
  top: 8px;
  right: 10px;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  background: var(--main-bg);
  border: 1px solid var(--main-border);
  color: var(--main-muted);
  opacity: 0;
  transition: opacity 0.15s var(--ease), color 0.15s var(--ease), border-color 0.15s var(--ease);
}

.message-wrapper.assistant .message-bubble:hover .btn-copy,
.btn-copy:focus-visible {
  opacity: 1;
}

.btn-copy:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.btn-copy.copied {
  opacity: 1;
  color: var(--success);
  border-color: var(--success);
}
</style>
