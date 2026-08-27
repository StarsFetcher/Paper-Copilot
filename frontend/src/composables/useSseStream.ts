import type { SseChatEvent } from '@/types'

export function useSseStream() {
  function connect(opts: {
    url: string
    method?: string
    body?: unknown
    onEvent: (evt: Record<string, unknown>) => void
    onDone: () => void
    onError: (msg: string) => void
  }): AbortController {
    const controller = new AbortController()

    fetch(opts.url, {
      method: opts.method || 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text().catch(() => '')
          opts.onError('请求失败 (' + response.status + ')')
          return
        }

        const reader = response.body?.getReader()
        if (!reader) {
          opts.onError('无法读取响应流')
          return
        }

        const decoder = new TextDecoder()
        let buffer = ''

        function pump() {
          reader!
            .read()
            .then((result) => {
              if (result.done) {
                opts.onDone()
                return
              }

              buffer += decoder.decode(result.value, { stream: true })
              const lines = buffer.split('\n')
              buffer = lines.pop() || ''

              for (const line of lines) {
                const trimmed = line.trim()
                if (!trimmed || !trimmed.startsWith('data: ')) continue

                try {
                  const event = JSON.parse(trimmed.substring(6))
                  const eventType = event.type as string

                  if (eventType === 'done') {
                    opts.onDone()
                    return
                  }
                  if (eventType === 'error') {
                    opts.onError(event.content || '未知错误')
                    return
                  }
                  opts.onEvent(event)
                } catch {
                  // skip malformed lines
                }
              }

              pump()
            })
            .catch((err: Error) => {
              if (err.name === 'AbortError') {
                opts.onDone()
              } else {
                opts.onError('网络错误: ' + err.message)
              }
            })
        }

        pump()
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') {
          opts.onDone()
        } else {
          opts.onError('网络错误: ' + err.message)
        }
      })

    return controller
  }

  return { connect }
}
