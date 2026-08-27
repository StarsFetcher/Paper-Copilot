// Type definitions for Paper-Copilot frontend

export interface PaperRef {
  paper_id: string
  title: string
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
  selectedPapers?: PaperRef[]
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

export interface PaperInfo {
  name: string
  size: number
  last_modified: string
}

export interface LibraryPaper {
  paper_id: string
  title: string
  authors?: string
  status?: string
  quality_score?: number
  relevance_score?: number
  storage_path?: string
}

export interface UploadResult {
  file_name: string
  page_count: number
  chunk_count: number
  elapsed_seconds: number
  sections_detected: string[]
}

export type SearchMode = 'auto' | 'local' | 'arxiv'

export interface SseChatEvent {
  type: 'token' | 'status' | 'done' | 'error'
  content?: string
}
