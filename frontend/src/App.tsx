import { useCallback, useEffect, useState } from 'react'

import { ApiError, api } from './api/client'
import type { Job, MediaInfo } from './api/types'
import CookieSettings from './components/CookieSettings'
import JobCard from './components/JobCard'
import LoginGate from './components/LoginGate'
import MediaPreview from './components/MediaPreview'
import UrlInput from './components/UrlInput'

type Session = { loading: true } | { loading: false; authenticated: boolean; configured: boolean }
type View = 'main' | 'settings'

export default function App() {
  const [session, setSession] = useState<Session>({ loading: true })
  const [view, setView] = useState<View>('main')
  const [resolved, setResolved] = useState<{ info: MediaInfo; url: string } | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [jobError, setJobError] = useState<string | null>(null)

  const refreshSession = useCallback(async () => {
    try {
      setSession({ loading: false, ...(await api.me()) })
    } catch {
      setSession({ loading: false, authenticated: false, configured: true })
    }
  }, [])

  useEffect(() => {
    void refreshSession()
  }, [refreshSession])

  useEffect(() => {
    if (session.loading || !session.authenticated) return
    api.listJobs().then(setJobs, () => setJobs([]))
  }, [session])

  async function startDownload(itemIds: string[]) {
    if (!resolved) return
    setSubmitting(true)
    setJobError(null)
    try {
      const { job_id } = await api.createJob({
        url: resolved.url,
        item_ids: itemIds.length === resolved.info.items.length ? null : itemIds,
      })
      const job = await api.getJob(job_id)
      setJobs((current) => [job, ...current])
    } catch (caught) {
      setJobError(caught instanceof ApiError ? caught.message : '작업 생성에 실패했습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  if (session.loading) return <div className="app muted">불러오는 중…</div>

  if (!session.authenticated) {
    return <LoginGate configured={session.configured} onAuthenticated={refreshSession} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>archgrab</h1>
        <span className="muted small hide-narrow">인스타그램 · X · 유튜브 원본 다운로더</span>
        <span className="spacer" />
        <button
          className="small"
          onClick={() => setView(view === 'main' ? 'settings' : 'main')}
        >
          {view === 'main' ? '설정' : '돌아가기'}
        </button>
        <button
          className="small"
          onClick={async () => {
            await api.logout()
            void refreshSession()
          }}
        >
          로그아웃
        </button>
      </header>

      {view === 'settings' ? (
        <CookieSettings />
      ) : (
        <div className="stack">
          <UrlInput
            onResolved={(info, url) => {
              setResolved({ info, url })
              setJobError(null)
            }}
            onNeedsCookies={() => setView('settings')}
          />

          {resolved && (
            <MediaPreview info={resolved.info} busy={submitting} onDownload={startDownload} />
          )}

          {jobError && <div className="error small">{jobError}</div>}

          {jobs.length > 0 && (
            <div className="card">
              <div className="row" style={{ alignItems: 'baseline', marginBottom: 10 }}>
                <strong style={{ fontSize: 14 }}>작업</strong>
                <span className="spacer" />
                <span className="muted small">보관 기간이 지나면 자동 삭제됩니다</span>
              </div>
              <div className="rows">
                {jobs.map((job) => (
                  <JobCard key={job.id} initial={job} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
