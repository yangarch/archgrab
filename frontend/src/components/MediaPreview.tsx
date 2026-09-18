import { useMemo, useState } from 'react'

import type { MediaInfo, MediaItem } from '../api/types'

interface Props {
  info: MediaInfo
  busy: boolean
  /** 선택한 항목들을 한 작업으로 받는다 */
  onDownload: (itemIds: string[]) => void
}

function duration(seconds?: number | null) {
  if (!seconds) return null
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** 항목이 실제로 무엇인지 — 타입 + 확장자. 받기 전에 알 수 있어야 한다. */
function itemKind(item: MediaItem) {
  const ext = item.formats[0]?.ext ?? (item.type === 'video' ? 'mp4' : 'jpg')
  return {
    ext,
    label: item.type === 'video' ? `▶ ${duration(item.duration) ?? '동영상'}` : '이미지',
  }
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

  // key 로 재마운트되지만, 그래도 없는 id 가 집계나 요청에 섞이지 않게 막는다.
  const chosen = useMemo(() => allIds.filter((id) => selected.has(id)), [allIds, selected])
  const allSelected = chosen.length === allIds.length && allIds.length > 0
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

      {info.notice && (
        <div className="notice small" style={{ marginTop: 12 }}>
          {info.notice}
        </div>
      )}

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
          disabled={busy || chosen.length === 0}
          onClick={() => onDownload(chosen)}
        >
          {busy ? '요청 중…' : `선택한 ${chosen.length}개 한번에`}
        </button>
      </div>

      <div className="grid">
        {info.items.map((item) => {
          const active = selected.has(item.id)
          const { ext, label } = itemKind(item)
          const format = item.formats[0]
          return (
            <div key={item.id} className={`tile${active ? ' tile-on' : ''}`}>
              {/* 썸네일 전체가 선택 토글 */}
              <button
                className="thumb-btn"
                aria-pressed={active}
                aria-label={`${item.index + 1}번 항목 선택`}
                onClick={() => toggle(item.id)}
              >
                <div className="thumb">
                  {item.thumbnail ? (
                    <img
                      src={item.thumbnail}
                      alt=""
                      /* loading="lazy" 를 쓰지 않는다 — Chrome 의 교차 판정이
                         .thumb 의 overflow/aspect-ratio 와 얽히면 요청을 아예
                         시작하지 않는 경우가 있었다. 썸네일은 작고 개수도 적다. */
                      decoding="async"
                    />
                  ) : (
                    <span className="muted small">미리보기 없음</span>
                  )}
                  <span className="tile-type">{label}</span>
                  {active && <span className="tile-check">✓</span>}
                </div>
              </button>

              <div className="tile-foot">
                <div className="small muted clamp" title={format?.label}>
                  {format?.label ?? '원본'}
                </div>
                {/* 요청사항: 항목마다 타입이 보이는 개별 다운로드 버튼 */}
                <button
                  className="small dl"
                  disabled={busy}
                  onClick={() => onDownload([item.id])}
                >
                  {ext} 내려받기
                </button>
              </div>
            </div>
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
