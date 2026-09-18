import { useMemo, useState } from 'react'

import type { DownloadState, MediaInfo, MediaItem, SaveMode } from '../api/types'

/** 일괄 버튼의 진행 상태 키 (항목 id 와 섞이지 않는 이름) */
export const BULK_ZIP_KEY = '__bulk_zip__'
export const BULK_EACH_KEY = '__bulk_each__'

interface Props {
  info: MediaInfo
  /** 요청키 → 진행 상태 */
  downloads: Record<string, DownloadState>
  onDownload: (itemIds: string[], key: string, mode: SaveMode) => void
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

/** 버튼 문구·상태. 서버 작업이 몇 초 걸리므로 누른 버튼이 직접 알려줘야 한다. */
function buttonView(state: DownloadState | undefined, idle: string) {
  switch (state?.status) {
    case 'starting':
      return { text: '요청 중…', busy: true, tone: '' }
    case 'running':
      return {
        text: state.percent > 0 ? `받는 중 ${Math.round(state.percent)}%` : '받는 중…',
        busy: true,
        tone: '',
      }
    case 'done':
      return { text: '저장됨 ✓', busy: false, tone: ' is-done' }
    case 'error':
      return { text: '실패 · 다시', busy: false, tone: ' is-error' }
    default:
      return { text: idle, busy: false, tone: '' }
  }
}

export default function MediaPreview({ info, downloads, onDownload }: Props) {
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

  const asEach = buttonView(downloads[BULK_EACH_KEY], `낱개로 ${chosen.length}개`)
  const asZip = buttonView(downloads[BULK_ZIP_KEY], `zip으로 ${chosen.length}개`)
  const anyBulkBusy = asEach.busy || asZip.busy

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
        {/* 낱개: 파일 그대로 여러 개. 4장쯤이면 압축을 풀 이유가 없다. */}
        <button
          className={`small${asEach.tone}`}
          disabled={anyBulkBusy || chosen.length === 0}
          aria-busy={asEach.busy}
          onClick={() => onDownload(chosen, BULK_EACH_KEY, 'each')}
        >
          {asEach.busy && <span className="spinner" aria-hidden="true" />}
          {asEach.text}
        </button>
        {/* zip 은 2개 이상일 때만 의미가 있다 */}
        {chosen.length > 1 && (
          <button
            className={`primary${asZip.tone}`}
            disabled={anyBulkBusy}
            aria-busy={asZip.busy}
            onClick={() => onDownload(chosen, BULK_ZIP_KEY, 'zip')}
          >
            {asZip.busy && <span className="spinner" aria-hidden="true" />}
            {asZip.text}
          </button>
        )}
      </div>
      {chosen.length > 3 && (
        <div className="muted small" style={{ margin: '-4px 0 10px' }}>
          낱개로 여러 개를 받으면 브라우저가 “여러 파일 다운로드” 허용을 물을 수 있습니다.
        </div>
      )}

      <div className="grid">
        {info.items.map((item) => {
          const active = selected.has(item.id)
          const { ext, label } = itemKind(item)
          const format = item.formats[0]
          const view = buttonView(downloads[item.id], `${ext} 내려받기`)
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
                {/* 항목마다 타입이 보이는 개별 다운로드 버튼 */}
                <button
                  className={`small dl${view.tone}`}
                  disabled={view.busy}
                  aria-busy={view.busy}
                  onClick={() => onDownload([item.id], item.id, 'each')}
                >
                  {view.busy && <span className="spinner" aria-hidden="true" />}
                  {view.text}
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
