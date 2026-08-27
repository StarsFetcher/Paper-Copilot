<script setup lang="ts">
import { ref, watch, onMounted, onUpdated, nextTick } from 'vue'
import { renderMarkdown, highlightCodeBlocks } from '@/utils/markdown'
import { escapeHtml } from '@/utils/format'

const props = defineProps<{ content: string; role: 'user' | 'assistant' }>()

const renderedHtml = ref('')
const elRef = ref<HTMLElement | null>(null)

async function updateRendered() {
  const target = props.content

  // User messages are plain text — escape and show as-is (newlines preserved by CSS)
  if (props.role === 'user') {
    renderedHtml.value = escapeHtml(target)
    return
  }

  const html = await renderMarkdown(target)
  // Streaming guard: markdown rendering is async, and during SSE token streaming
  // older renders can resolve after newer ones — drop stale results.
  if (target !== props.content) return
  renderedHtml.value = html

  await nextTick()
  if (elRef.value) highlightCodeBlocks(elRef.value)
}

watch(() => props.content, updateRendered, { immediate: true })
onMounted(() => { if (elRef.value) highlightCodeBlocks(elRef.value) })
onUpdated(() => { if (elRef.value) highlightCodeBlocks(elRef.value) })
</script>

<template>
  <div ref="elRef" class="markdown-body" v-html="renderedHtml"></div>
</template>

<style>
/* ============================================================
   MarkdownRenderer — non-scoped styles (v-html content cannot
   receive scoped attribute selectors). Uses design tokens from
   tokens.css so the rendered markdown matches the app theme.
   ============================================================ */

.markdown-body {
  font-size: 14.5px;
  line-height: 1.75;
  color: var(--main-text);
  word-break: break-word;
  white-space: normal;
}

/* User plain text bubble */
.markdown-body p {
  margin: 0 0 0.6em;
}
.markdown-body > :last-child {
  margin-bottom: 0;
}

/* --- Headings --- */
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  color: var(--main-heading);
  font-weight: 650;
  line-height: 1.4;
  margin: 1.2em 0 0.5em;
}
.markdown-body h1 { font-size: 1.45em; padding-bottom: 0.3em; border-bottom: 1px solid var(--main-border); }
.markdown-body h2 { font-size: 1.28em; padding-bottom: 0.25em; border-bottom: 1px solid var(--main-border); }
.markdown-body h3 { font-size: 1.14em; }
.markdown-body h4 { font-size: 1.02em; }
.markdown-body h5 { font-size: 0.95em; }
.markdown-body h6 { font-size: 0.88em; color: var(--main-muted); }
.markdown-body h1:first-child,
.markdown-body h2:first-child {
  margin-top: 0;
}

/* --- Lists --- */
.markdown-body ul,
.markdown-body ol {
  margin: 0.4em 0 0.8em;
  padding-left: 1.6em;
}
.markdown-body li {
  margin: 0.25em 0;
}
.markdown-body li > ul,
.markdown-body li > ol {
  margin: 0.15em 0;
}

/* --- Inline code --- */
.markdown-body code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 0.88em;
  background: var(--accent-light);
  color: #5a4bd1;
  padding: 0.15em 0.45em;
  border-radius: var(--radius-xs);
  word-break: break-word;
}

/* --- Code blocks (highlight.js) --- */
.markdown-body pre {
  background: #f5f6fb;
  border: 1px solid var(--main-border);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  margin: 0.8em 0;
  overflow-x: auto;
  line-height: 1.6;
}
.markdown-body pre code {
  background: transparent;
  color: #383a42;
  padding: 0;
  font-size: 13px;
  border-radius: 0;
  white-space: pre;
  word-break: normal;
  display: block;
}

/* Minimal light hljs palette (hljs CSS is not globally imported) */
.markdown-body .hljs-keyword,
.markdown-body .hljs-selector-tag,
.markdown-body .hljs-literal,
.markdown-body .hljs-section,
.markdown-body .hljs-link { color: #c678dd; }
.markdown-body .hljs-string,
.markdown-body .hljs-title,
.markdown-body .hljs-name,
.markdown-body .hljs-type,
.markdown-body .hljs-attribute,
.markdown-body .hljs-symbol,
.markdown-body .hljs-bullet,
.markdown-body .hljs-addition { color: #98c379; }
.markdown-body .hljs-number,
.markdown-body .hljs-meta { color: #d19a66; }
.markdown-body .hljs-built_in,
.markdown-body .hljs-builtin-name,
.markdown-body .hljs-function .hljs-title { color: #61afef; }
.markdown-body .hljs-comment,
.markdown-body .hljs-quote { color: #a0a1a7; font-style: italic; }
.markdown-body .hljs-variable,
.markdown-body .hljs-template-variable,
.markdown-body .hljs-tag,
.markdown-body .hljs-regexp,
.markdown-body .hljs-deletion { color: #e06c75; }
.markdown-body .hljs-attr,
.markdown-body .hljs-params { color: #383a42; }
.markdown-body .hljs-emphasis { font-style: italic; }
.markdown-body .hljs-strong { font-weight: 600; }

/* --- Blockquote --- */
.markdown-body blockquote {
  margin: 0.8em 0;
  padding: 0.4em 1em;
  border-left: 3px solid var(--accent);
  background: var(--accent-light);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  color: var(--main-text);
}
.markdown-body blockquote p {
  margin: 0.3em 0;
}

/* --- Table --- */
.markdown-body table {
  border-collapse: collapse;
  margin: 0.8em 0;
  font-size: 0.95em;
  width: 100%;
  display: block;
  overflow-x: auto;
}
.markdown-body th,
.markdown-body td {
  border: 1px solid var(--main-border);
  padding: 8px 14px;
  text-align: left;
  white-space: nowrap;
}
.markdown-body th {
  background: var(--accent-light);
  color: var(--main-heading);
  font-weight: 650;
}
.markdown-body tr:nth-child(even) td {
  background: #fafbff;
}

/* --- Links / emphasis / hr --- */
.markdown-body a {
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: border-color 0.15s var(--ease);
}
.markdown-body a:hover {
  border-bottom-color: var(--accent);
}
.markdown-body strong {
  color: var(--main-heading);
  font-weight: 650;
}
.markdown-body hr {
  border: none;
  border-top: 1px solid var(--main-border);
  margin: 1.2em 0;
}
.markdown-body img {
  max-width: 100%;
  border-radius: var(--radius-sm);
}

/* --- KaTeX --- */
.markdown-body .katex-display {
  margin: 0.8em 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 4px 0;
}
.markdown-body .katex {
  font-size: 1.08em;
}
</style>
