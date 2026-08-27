const BASE = '' // same-origin, proxied by Vite in dev

export class ApiError extends Error {
  code: number
  constructor(code: number, message: string) {
    super(message)
    this.code = code
    this.name = 'ApiError'
  }
}

export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  const data = await resp.json()
  if (data.code !== 200) {
    throw new ApiError(data.code || resp.status, data.message || '请求失败')
  }
  return data.data as T
}

export async function requestRaw<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + url, options)
  return resp.json()
}
