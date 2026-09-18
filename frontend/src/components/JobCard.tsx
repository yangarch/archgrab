import { useEffect, useRef, useState } from 'react'

import { useJobStream } from '../hooks/useJobStream'
import type { Job } from '../api/types'

const STATUS_LABEL: Record<string, string> = {
  queued: '대기 중',
  downloading: '내려받는 중',
  packaging: '정리 중',
  done: '완료',
  error: '실패',
  canceled: '취소',
}

function humanSize(bytes: number) {
  if (bytes < 1024) return `${bytes}B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)}${units[unit]}`
}

interface Props {
  initial: Job
  /** 이번 세션에서 버튼으로 시작한 작업만 자동 저장한다.
   *  과거 작업 목록까지 자동 저장하면 새로고침마다 파일이 쏟아진다. */
  autoSave?: boolean
}

export default function JobCard({ initial, autoSave = false }: Props) {
  const job = useJobStream(initial)
  // ref 는 중복 발동 방지용(StrictMode 는 effect 를 두 번 돌린다),
  // state 는 화면 갱신용. ref 만 쓰면 안내 문구가 리렌더될 때까지 안 뜬다.
  const fired = useRef(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!autoSave || fired.current || job.status !== 'done') return
    // 여러 항목을 묶은 작업은 zip 하나만, 단일 항목은 그 파일을 저장한다
    const zip = job.files.find((f) => f.name.endsWith('.zip'))
    const target = zip ?? job.files[0]
    if (!target) return
    fired.current = true
    const link = document.createElement('a')
    link.href = `/api/files/${target.token}`
    link.download = target.name
    document.body.appendChild(link)
    link.click()
    link.remove()
    setSaved(true)
  }, [autoSave, job.status, job.files])
  const active = job.status === 'downloading' || job.status === 'packaging'
  const percent = job.status === 'done' ? 100 : job.progress.percent

  return (
    <div className="job">
      <div className="row" style={{ alignItems: 'baseline' }}>
        <span className={`badge small status-${job.status}`}>{STATUS_LABEL[job.status]}</span>
        <span className="small muted clamp" style={{ flex: 1, minWidth: 0 }}>
          {job.progress.current ?? job.title ?? job.url}
        </span>
        {job.progress.count > 1 && (
          <span className="small muted">
            {job.progress.index}/{job.progress.count}
          </span>
        )}
      </div>

      {active && (
        <div className="bar" style={{ marginTop: 10 }}>
          <div className="bar-fill" style={{ width: `${Math.max(2, percent)}%` }} />
        </div>
      )}

      {job.status === 'error' && (
        <div className="error small" style={{ marginTop: 10 }}>
          {job.error_message}
          {job.error_code && <span className="muted"> ({job.error_code})</span>}
        </div>
      )}

      {job.status === 'done' && job.files.length > 0 && (
        <div className="files" style={{ marginTop: 10 }}>
          {saved && (
            <div className="muted small">
              브라우저 다운로드 폴더에 저장했습니다. 다시 받으려면 아래를 누르세요.
            </div>
          )}
          {job.files.map((file) => (
            <a key={file.token} className="file" href={`/api/files/${file.token}`} download>
              <span className="clamp">{file.name}</span>
              <span className="muted small">{humanSize(file.size)}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
