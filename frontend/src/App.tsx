import { useCallback, useEffect, useState } from 'react'

import { ApiError, api } from './api/client'
import type { DownloadState, Job, JobFile, MediaInfo, SaveMode } from './api/types'
import CookieSettings from './components/CookieSettings'
import JobCard from './components/JobCard'
import LoginGate from './components/LoginGate'
import MediaPreview, {
  BULK_EACH_KEY,
  BULK_ZIP_KEY,
  GALLERY_PREFIX,
} from './components/MediaPreview'
import UrlInput from './components/UrlInput'

type Session = { loading: true } | { loading: false; authenticated: boolean; configured: boolean }

/** 일괄 받기 버튼의 요청키인가 (항목 단위와 구분한다). */
function isBulkKey(key: string): boolean {
  return key === BULK_EACH_KEY || key === BULK_ZIP_KEY
}

/** 갤러리 요청키(`gallery:2`)에서 항목 id 를 뽑는다. 아니면 null. */
function galleryItemId(key: string): string | null {
  return key.startsWith(GALLERY_PREFIX) ? key.slice(GALLERY_PREFIX.length) : null
}
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
  /* 갤러리로 보낼 준비가 끝난 파일 (항목 id → 파일).
     iOS 는 탭 직후에만 공유 시트를 허용하는데 서버가 파일을 받는 데 몇 초
     걸린다. 그래서 받아두고, 사용자가 다시 탭할 때 그 제스처로 공유한다. */
  const [galleryReady, setGalleryReady] = useState<Record<string, JobFile>>({})
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

  async function startDownload(
    itemIds: string[],
    key: string,
    mode: SaveMode = 'zip',
    formatIds: Record<string, string> = {},
    forShare = false,
  ) {
    if (!resolved) return
    setJobError(null)
    mark(key, { status: 'starting', percent: 0 })
    try {
      const { job_id } = await api.createJob({
        url: resolved.url,
        item_ids: itemIds.length === resolved.info.items.length ? null : itemIds,
        // 낱개로 저장할 거면 zip 을 만들 필요가 없다
        bundle: mode === 'zip',
        // 유튜브처럼 화질이 여럿인 경우 고른 것을 그대로 넘긴다
        format_ids: Object.keys(formatIds).length > 0 ? formatIds : null,
      })
      const job = await api.getJob(job_id)
      setActiveJob((current) => ({ ...current, [key]: job_id }))
      setSaveModes((current) => ({ ...current, [job_id]: mode }))
      // 갤러리로 보낼 작업은 파일 앱에 자동 저장하지 않는다 — 두 곳에 중복으로
      // 남는다. started 에 넣지 않으면 JobCard 가 자동 저장을 건너뛴다.
      if (!forShare) setStarted((current) => new Set(current).add(job_id))
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
    (job: Job) => {
      // 이 작업이 어떤 버튼의 **현재** 작업인지 확인한다. 아니면 무시한다.
      const key = Object.keys(activeJob).find((k) => activeJob[k] === job.id)
      if (!key) return
      const { status, progress } = job

      if (status === 'error' || status === 'canceled') {
        mark(key, { status: 'error', percent: 0 })
        return
      }
      if (status !== 'done') {
        mark(key, { status: 'running', percent: progress.percent })
        return
      }

      const itemId = galleryItemId(key)
      if (itemId !== null) {
        // 갤러리 흐름: 여기서 공유하면 제스처 권한이 없어 실패한다.
        // 파일만 챙겨두고 버튼을 "보내기" 로 바꿔 사용자의 다음 탭을 기다린다.
        const file = job.files.find((f) => !f.name.endsWith('.zip')) ?? job.files[0]
        if (file) {
          setGalleryReady((current) => ({ ...current, [itemId]: file }))
          mark(key, { status: 'ready', percent: 100 })
          return
        }
      }
      mark(key, { status: 'done', percent: 100 })
      // 항목 버튼의 완료 표시는 남긴다 — 무엇을 이미 받았는지 알 수 있어야 한다.
      // 일괄 버튼만 되돌린다. 그 문구는 현재 선택 개수를 보여줘야 하므로
      // "저장됨" 이 계속 붙어 있으면 선택을 바꿔도 개수가 안 보인다.
      if (isBulkKey(key)) window.setTimeout(() => mark(key, null), 4000)
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
              // 항목 id 는 게시글마다 0,1,2… 로 겹친다. 이전 게시글의 완료
              // 표시를 남겨두면 엉뚱한 타일에 "저장됨" 이 붙는다.
              setDownloads({})
              setGalleryReady({})
              setActiveJob({})
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
              galleryReady={galleryReady}
              onDownload={startDownload}
              onGallerySent={(itemId, key) => {
                setGalleryReady((current) => {
                  const next = { ...current }
                  delete next[itemId]
                  return next
                })
                mark(key, { status: 'done', percent: 100 })
              }}
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
