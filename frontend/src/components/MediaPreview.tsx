import { useMemo, useState } from 'react'

import type { DownloadState, JobFile, MediaInfo, MediaItem, SaveMode } from '../api/types'
import { SHARE_SIZE_LIMIT, canShareFiles, shareFile } from '../lib/share'

/** 일괄 버튼의 진행 상태 키 (항목 id 와 섞이지 않는 이름) */
export const BULK_ZIP_KEY = '__bulk_zip__'
/** 갤러리 요청키 접두어 — 항목 id 를 붙여 쓴다 (`gallery:2`) */
export const GALLERY_PREFIX = 'gallery:'
export const BULK_EACH_KEY = '__bulk_each__'

interface Props {
  info: MediaInfo
  /** 요청키 → 진행 상태 */
  downloads: Record<string, DownloadState>
  onDownload: (
    itemIds: string[],
    key: string,
    mode: SaveMode,
    formatIds: Record<string, string>,
    forShare?: boolean,
  ) => void
  /** 갤러리로 보낼 준비가 끝난 파일 (항목 id → 파일) */
  galleryReady?: Record<string, JobFile>
  onGallerySent?: (itemId: string, key: string) => void
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

export default function MediaPreview({
  info,
  downloads,
  onDownload,
  galleryReady = {},
  onGallerySent,
}: Props) {
  // 지원 기기에서만 갤러리 버튼을 띄운다. 데스크톱 크롬은 share 가 있어도
  // 파일은 못 보내므로 눌러도 아무 일 없는 버튼이 된다.
  const shareable = canShareFiles()
  const allIds = useMemo(() => info.items.map((item) => item.id), [info])
  const [selected, setSelected] = useState<Set<string>>(() => new Set(allIds))
  /* 항목별로 고른 포맷. 유튜브는 한 영상에 화질이 9개까지 오므로 고를 수 있어야
     한다. 인스타·X 는 대개 하나뿐이라 선택기가 뜨지 않는다. */
  const [formatIds, setFormatIds] = useState<Record<string, string>>(() =>
    Object.fromEntries(info.items.map((item) => [item.id, item.formats[0]?.id ?? ''])),
  )

  const formatOf = (item: MediaItem) =>
    item.formats.find((f) => f.id === formatIds[item.id]) ?? item.formats[0]

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
          onClick={() => onDownload(chosen, BULK_EACH_KEY, 'each', formatIds)}
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
            onClick={() => onDownload(chosen, BULK_ZIP_KEY, 'zip', formatIds)}
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
          const { label } = itemKind(item)
          const format = formatOf(item)
          const ext = format?.ext ?? (item.type === 'video' ? 'mp4' : 'jpg')
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
                {item.formats.length > 1 ? (
                  <select
                    className="small quality"
                    aria-label={`${item.index + 1}번 항목 화질`}
                    value={format?.id ?? ''}
                    onChange={(event) =>
                      setFormatIds((current) => ({ ...current, [item.id]: event.target.value }))
                    }
                  >
                    {item.formats.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="small muted clamp" title={format?.label}>
                    {format?.label ?? '원본'}
                  </div>
                )}
                {/* 항목마다 타입이 보이는 개별 다운로드 버튼 */}
                <button
                  className={`small dl${view.tone}`}
                  disabled={view.busy}
                  aria-busy={view.busy}
                  onClick={() => onDownload([item.id], item.id, 'each', formatIds)}
                >
                  {view.busy && <span className="spinner" aria-hidden="true" />}
                  {view.text}
                </button>

                {/* 갤러리로 바로 보내기. 파일이 준비되면 버튼이 "보내기" 로
                    바뀐다 — iOS 는 탭 직후에만 공유 시트를 열어주므로 준비와
                    공유를 한 번의 탭으로 묶을 수 없다. */}
                {shareable && (format?.filesize ?? 0) <= SHARE_SIZE_LIMIT && (
                  <GalleryButton
                    item={item}
                    state={downloads[GALLERY_PREFIX + item.id]}
                    ready={galleryReady[item.id]}
                    onStart={() =>
                      onDownload([item.id], GALLERY_PREFIX + item.id, 'each', formatIds, true)
                    }
                    onSent={() => onGallerySent?.(item.id, GALLERY_PREFIX + item.id)}
                  />
                )}
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


interface GalleryButtonProps {
  item: MediaItem
  state: DownloadState | undefined
  ready: JobFile | undefined
  onStart: () => void
  onSent: () => void
}

/** `갤러리` → (준비) → `갤러리로 보내기` → `저장됨 ✓` */
function GalleryButton({ item, state, ready, onStart, onSent }: GalleryButtonProps) {
  const [sending, setSending] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function send() {
    if (!ready) return
    setSending(true)
    setProblem(null)
    const outcome = await shareFile(ready)
    setSending(false)
    if (outcome === 'shared') onSent()
    else if (outcome === 'retry') setProblem('한 번 더 눌러주세요')
    else if (outcome !== 'cancelled') setProblem('갤러리 저장에 실패했습니다')
  }

  const busy = sending || state?.status === 'starting' || state?.status === 'running'
  let text = '갤러리'
  let tone = ''
  if (sending) text = '보내는 중…'
  else if (state?.status === 'ready' || ready) {
    text = '갤러리로 보내기'
    // 지금 눌러야 할 때라는 걸 색으로도 알린다. 문구만 바뀌면 놓치기 쉽다.
    tone = ' is-ready'
  }
  else if (state?.status === 'running')
    text = state.percent > 0 ? `준비 중 ${Math.round(state.percent)}%` : '준비 중…'
  else if (state?.status === 'starting') text = '요청 중…'
  else if (state?.status === 'done') {
    text = '저장됨 ✓'
    tone = ' is-done'
  } else if (state?.status === 'error') {
    text = '실패 · 다시'
    tone = ' is-error'
  }

  return (
    <>
      <button
        className={`small dl${tone}`}
        disabled={busy}
        aria-busy={busy}
        /* 고정 문구를 쓰면 접근성 이름이 상태를 가린다 — 화면에는
           "준비 중 40%" 가 보이는데 스크린리더는 계속 "갤러리에 저장" 을
           읽는다. 항목 번호만 앞에 붙이고 나머지는 실제 문구를 쓴다. */
        aria-label={`${item.index + 1}번 항목 ${text}`}
        onClick={() => (ready ? void send() : onStart())}
      >
        {busy && <span className="spinner" aria-hidden="true" />}
        {text}
      </button>
      {problem && <div className="muted small" style={{ flexBasis: '100%' }}>{problem}</div>}
    </>
  )
}
