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

export default function JobCard({ initial }: { initial: Job }) {
  const job = useJobStream(initial)
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
