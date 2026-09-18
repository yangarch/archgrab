export type Platform = 'instagram' | 'x' | 'youtube'

export type MediaType = 'video' | 'image' | 'audio'

export interface FormatOption {
  id: string
  ext: string
  width?: number | null
  height?: number | null
  fps?: number | null
  filesize?: number | null
  filesize_approx?: boolean
  vcodec?: string | null
  acodec?: string | null
  note?: string | null
  needs_mux?: boolean
  /** 서버가 만드는 표시용 라벨 (예: "1440×1800 · jpg · 원본") */
  label: string
}

export interface MediaItem {
  id: string
  index: number
  type: MediaType
  title?: string | null
  thumbnail?: string | null
  duration?: number | null
  width?: number | null
  height?: number | null
  formats: FormatOption[]
}

export interface MediaInfo {
  platform: Platform
  kind: string
  source_url: string
  key: string
  title?: string | null
  uploader?: string | null
  uploader_url?: string | null
  description?: string | null
  taken_at?: string | null
  items: MediaItem[]
  engine: string
  used_cookies: boolean
  /** 엔진이 가져오지 못한 항목 수 — 조용히 버리지 않는다 */
  missing_items: number
  notice?: string | null
}

export interface CookieStatus {
  platform: Platform
  present: boolean
  entries: number
  updated_at?: number | null
  earliest_expiry?: number | null
  expired: boolean
}

export interface ApiErrorPayload {
  code: string
  message: string
  detail?: string | null
}

export type JobStatus = 'queued' | 'downloading' | 'packaging' | 'done' | 'error' | 'canceled'

export interface JobProgress {
  done_bytes: number
  total_bytes?: number | null
  percent: number
  current?: string | null
  index: number
  count: number
}

export interface JobFile {
  name: string
  size: number
  token: string
  content_type: string
}

export interface Job {
  id: string
  status: JobStatus
  url: string
  platform?: Platform | null
  title?: string | null
  progress: JobProgress
  files: JobFile[]
  error_code?: string | null
  error_message?: string | null
  created_at: string
  finished_at?: string | null
  expires_at?: string | null
}

export interface JobRequest {
  url: string
  item_ids?: string[] | null
  format_ids?: Record<string, string> | null
  audio_only?: boolean
}

/** 버튼에 표시할 다운로드 진행 상태 */
export interface DownloadState {
  status: 'starting' | 'running' | 'done' | 'error'
  percent: number
}
