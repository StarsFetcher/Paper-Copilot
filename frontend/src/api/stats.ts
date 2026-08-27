import { requestRaw } from './client'

export interface HealthData {
  status: string
  storage_ready: boolean
  papers_count: number
  vector_count: number
}

export async function checkHealth(): Promise<boolean> {
  try {
    const d = await requestRaw<{ code: number }>('/api/health')
    return d.code === 200
  } catch {
    return false
  }
}

export interface StatsData {
  papers_count: number
  vector_count: number
}

export async function fetchStats(): Promise<StatsData> {
  return requestRaw('/api/stats')
}
