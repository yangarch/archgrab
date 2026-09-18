import type { ApiErrorPayload, CookieStatus, Job, JobRequest, MediaInfo } from './types'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly detail?: string | null

  constructor(code: string, message: string, status: number, detail?: string | null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.detail = detail
  }

  /** 세션이 끊겼는지 — 콘텐츠 쪽 로그인 요구와 구분해야 한다. */
  get isSessionExpired() {
    return this.status === 401 && this.code === 'LOGIN_REQUIRED'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...init,
  })

  if (!response.ok) {
    let payload: ApiErrorPayload = { code: 'INTERNAL', message: `요청 실패 (${response.status})` }
    try {
      const body = (await response.json()) as { error?: ApiErrorPayload }
      if (body.error) payload = body.error
    } catch {
      // 본문이 JSON 이 아닌 경우 기본 메시지를 쓴다
    }
    throw new ApiError(payload.code, payload.message, response.status, payload.detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  me: () => request<{ authenticated: boolean; configured: boolean }>('/auth/me'),
  login: (password: string) =>
    request<{ authenticated: boolean }>('/auth/login', json({ password })),
  logout: () => request<{ authenticated: boolean }>('/auth/logout', { method: 'POST' }),
  engines: () => request<Record<string, string | null>>('/engines'),
  cookies: () => request<CookieStatus[]>('/cookies'),
  resolve: (url: string) =>
    request<{ info: MediaInfo; cached: boolean }>('/resolve', json({ url })),
  createJob: (body: JobRequest) => request<{ job_id: string }>('/jobs', json(body)),
  listJobs: () => request<Job[]>('/jobs'),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  uploadCookies: (platform: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<CookieStatus>(`/cookies/${platform}`, { method: 'PUT', body: form })
  },
  deleteCookies: (platform: string) =>
    request<CookieStatus>(`/cookies/${platform}`, { method: 'DELETE' }),
}
