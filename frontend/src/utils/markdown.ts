import { escapeHtml } from './format'

let _marked: any = null
let _katex: any = null

async function ensureMarked() {
  if (!_marked) {
    const mod = await import('marked')
    _marked = mod.marked
    _marked.setOptions?.({ breaks: true, gfm: true })
  }
  return _marked
}

async function ensureKatex() {
  if (!_katex) {
    _katex = await import('katex')
  }
  return _katex
}

export async function renderMarkdown(text: string): Promise<string> {
  if (!text) return ''

  try {
    const marked = await ensureMarked()

    // Step 1: Protect LaTeX from markdown — collect all blocks sequentially
    const latexBlocks: { raw: string; display: boolean }[] = []

    const protected_ = text
      // Display math: $$...$$  or  \[...\]  or  [...\] (LLM pseudo-LaTeX)
      .replace(/(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\[\s*\\[^\]]*\])/g, (m) => {
        latexBlocks.push({ raw: m, display: true })
        return '%%LATEX_' + (latexBlocks.length - 1) + '%%'
      })
      // Inline math: $...$  or  \(...\)
      .replace(/(\$(?!\$)[^$\n]+?\$(?!\$)|\\\([\s\S]*?\\\))/g, (m) => {
        latexBlocks.push({ raw: m, display: false })
        return '%%LATEX_' + (latexBlocks.length - 1) + '%%'
      })

    // Step 2: Render markdown
    let html: string
    if (typeof marked.parse === 'function') {
      html = (await marked.parse(protected_)) as string
    } else if (typeof marked === 'function') {
      html = marked(protected_)
    } else {
      html = escapeHtml(protected_).replace(/\n/g, '<br>')
    }

    // Step 3: Replace placeholders with KaTeX-rendered HTML
    for (let i = 0; i < latexBlocks.length; i++) {
      const block = latexBlocks[i]
      const raw = block.raw

      // Strip delimiters to get pure formula
      const formula = raw
        .replace(/^\$\$/, '')
        .replace(/\$\$$/, '') // $$...$$
        .replace(/^\\\[/, '')
        .replace(/\\\]$/, '') // \[...\]
        .replace(/^\[\s*\\/, '\\')
        .replace(/\]$/, '') // [...\] → \...
        .replace(/^\\\(/, '')
        .replace(/\\\)$/, '') // \(...\)
        .replace(/^\$/, '')
        .replace(/\$$/, '') // $...$

      let rendered: string
      try {
        const katex = await ensureKatex()
        rendered = katex.renderToString(formula.trim(), {
          displayMode: block.display,
          throwOnError: false,
          trust: true,
        })
      } catch {
        rendered = '<code>' + escapeHtml(formula) + '</code>'
      }

      html = html.split('%%LATEX_' + i + '%%').join(rendered)
    }

    return html
  } catch {
    return escapeHtml(text).replace(/\n/g, '<br>')
  }
}

export function highlightCodeBlocks(el: HTMLElement | null) {
  if (!el) return
  el.querySelectorAll('pre code').forEach((block) => {
    try {
      // Dynamic import of highlight.js
      import('highlight.js').then((hljs) => {
        hljs.default.highlightElement(block as HTMLElement)
      })
    } catch {
      // ignore
    }
  })
}
