import { useMemo, useState } from 'react'

import type { MediaInfo } from '../api/types'

interface Props {
  info: MediaInfo
  busy: boolean
  onDownload: (itemIds: string[]) => void
}

function duration(seconds?: number | null) {
  if (!seconds) return null
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export default function MediaPreview({ info, busy, onDownload }: Props) {
  const allIds = useMemo(() => info.items.map((item) => item.id), [info])
  const [selected, setSelected] = useState<Set<string>>(() => new Set(allIds))

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const allSelected = selected.size === allIds.length
  const videoCount = info.items.filter((item) => item.type === 'video').length

  return (
    <div className="card">
      <div className="row" style={{ alignItems: 'baseline' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong>{info.uploader ? `@${info.uploader}` : info.platform}</strong>
          {info.title && <div className="muted small clamp">{info.title}</div>}
        </div>
        <span className="badge small">
          {info.items.length}개 · 동영상 {videoCount} · 이미지 {info.items.length - videoCount}
        </span>
      </div>

      <div className="row" style={{ margin: '14px 0 10px' }}>
        <button
          className="small"
          onClick={() => setSelected(allSelected ? new Set() : new Set(allIds))}
        >
          {allSelected ? '전체 해제' : '전체 선택'}
        </button>
        <span className="spacer" />
        <button
          className="primary"
          disabled={busy || selected.size === 0}
          onClick={() => onDownload([...selected])}
        >
          {busy ? '요청 중…' : `${selected.size}개 내려받기`}
        </button>
      </div>

      <div className="grid">
        {info.items.map((item) => {
          const active = selected.has(item.id)
          const format = item.formats[0]
          return (
            <button
              key={item.id}
              className={`tile${active ? ' tile-on' : ''}`}
              aria-pressed={active}
              onClick={() => toggle(item.id)}
            >
              <div className="thumb">
                {item.thumbnail ? (
                  <img src={item.thumbnail} alt="" loading="lazy" />
                ) : (
                  <span className="muted small">미리보기 없음</span>
                )}
                <span className="tile-type">
                  {item.type === 'video' ? `▶ ${duration(item.duration) ?? '동영상'}` : '이미지'}
                </span>
                {active && <span className="tile-check">✓</span>}
              </div>
              <div className="small muted clamp" style={{ padding: '6px 8px' }}>
                {format?.label ?? '원본'}
              </div>
            </button>
          )
        })}
      </div>

      <div className="small muted" style={{ marginTop: 12 }}>
        엔진 {info.engine}
        {info.used_cookies ? ' · 쿠키 사용' : ' · 쿠키 없음'} · 원본 화질 그대로 받습니다
      </div>
    </div>
  )
}
