import { request } from './client'
import type { PaperInfo, LibraryPaper } from '@/types'

export async function fetchPapersList(): Promise<PaperInfo[]> {
  const data = await request<{ papers: PaperInfo[]; count: number }>('/api/papers')
  return data.papers || []
}

export async function fetchLibraryPapers(): Promise<LibraryPaper[]> {
  const data = await request<{ papers: LibraryPaper[]; count: number }>('/api/library/papers')
  return data.papers || []
}

export async function deleteLibraryPaper(paperId: string): Promise<void> {
  await fetch('/api/library/papers/' + encodeURIComponent(paperId), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  })
}

export async function batchDeleteLibraryPapers(
  paperIds: string[],
  deleteFiles = true,
): Promise<{ deleted: number; errors: { paper_id: string; error: string }[] }> {
  const resp = await fetch('/api/library/papers/batch-delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_ids: paperIds, delete_files: deleteFiles }),
  })
  const data = await resp.json()
  return data.data
}
