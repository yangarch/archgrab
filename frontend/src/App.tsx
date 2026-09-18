import { useCallback, useEffect, useState } from 'react'

import { ApiError, api } from './api/client'
import type { DownloadState, Job, JobStatus, MediaInfo, SaveMode } from './api/types'
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
  // 이번 세션에서 시작한 작업 — 완료 시 자동 저장 대상
  const [started, setStarted] = useState<Set<string>>(() => new Set())
  /* 버튼별 진행 상태. 서버 작업이 2~5초 걸리는데 작업 카드는 화면 밖일 수 있어,
     사용자가 누른 그 버튼이 직접 상태를 보여줘야 한다. */
  const [downloads, setDownloads] = useState<Record<string, DownloadState>>({})
  /* 요청키 → **현재** 작업 id. jobId→key 로 쌓아두면, 같은 버튼으로 새 작업을
     시작해도 이전 작업의 JobCard 가 같은 키로 done 을 계속 보고해 새 진행 상태를
     덮어쓴다(두 번째 클릭에 즉시 "저장됨"이 뜨는 거짓 피드백). 키마다 최신
     작업만 남겨 오래된 보고를 무시한다. */
  const [activeJob, setActiveJob] = useState<Record<string, string>>({})
  // 작업 id → 브라우저 저장 방식 (zip 하나 vs 낱개 전부)
  const [saveModes, setSaveModes] = useState<Record<string, SaveMode>>({})
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

  const mark = useCallback((key: string, state: DownloadState | null) => {
    setDownloads((current) => {
      const next = { ...current }
      if (state) next[key] = state
      else delete next[key]
      return next
    })
  }, [])

  async function startDownload(itemIds: string[], key: string, mode: SaveMode = 'zip') {
    if (!resolved) return
    setJobError(null)
    mark(key, { status: 'starting', percent: 0 })
    try {
      const { job_id } = await api.createJob({
        url: resolved.url,
        item_ids: itemIds.length === resolved.info.items.length ? null : itemIds,
      })
      const job = await api.getJob(job_id)
      setActiveJob((current) => ({ ...current, [key]: job_id }))
      setSaveModes((current) => ({ ...current, [job_id]: mode }))
      setStarted((current) => new Set(current).add(job_id))
      setJobs((current) => [job, ...current])
      mark(key, { status: 'running', percent: 0 })
    } catch (caught) {
      mark(key, { status: 'error', percent: 0 })
      setJobError(caught instanceof ApiError ? caught.message : '작업 생성에 실패했습니다.')
    }
  }

  /* JobCard 가 이미 SSE 를 구독하고 있으므로 상태를 올려받는다.
     App 에서 따로 구독하면 작업마다 스트림이 두 개가 된다. */
  const handleJobStatus = useCallback(
    (jobId: string, status: JobStatus, percent: number) => {
      // 이 작업이 어떤 버튼의 **현재** 작업인지 확인한다. 아니면 무시한다.
      const key = Object.keys(activeJob).find((k) => activeJob[k] === jobId)
      if (!key) return
      if (status === 'done') {
        mark(key, { status: 'done', percent: 100 })
        window.setTimeout(() => mark(key, null), 4000)
      } else if (status === 'error' || status === 'canceled') {
        mark(key, { status: 'error', percent: 0 })
      } else {
        mark(key, { status: 'running', percent })
      }
    },
    [activeJob, mark],
  )

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
            <MediaPreview
              /* 새 URL 이면 재마운트 — 이전 게시글의 선택 상태가 남으면
                 "선택한 15개" 가 1개짜리 게시글에서도 그대로 보인다 */
              key={resolved.url}
              info={resolved.info}
              downloads={downloads}
              onDownload={startDownload}
            />
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
                  <JobCard
                    key={job.id}
                    initial={job}
                    autoSave={started.has(job.id)}
                    onStatus={handleJobStatus}
                    saveMode={saveModes[job.id] ?? 'zip'}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
