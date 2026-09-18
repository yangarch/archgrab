import { useState } from 'react'

import { ApiError, api } from '../api/client'
import type { MediaInfo } from '../api/types'

const PLATFORM_LABEL: Record<string, string> = {
  instagram: '인스타그램',
  x: 'X',
  youtube: '유튜브',
}

/** 서버 판별과 별개로, 입력하는 동안 어느 플랫폼인지 눈으로 보여주기만 한다. */
function detectPlatform(url: string): string | null {
  const text = url.toLowerCase()
  if (text.includes('instagram.com') || text.includes('instagr.am')) return 'instagram'
  if (text.includes('x.com') || text.includes('twitter.com')) return 'x'
  if (text.includes('youtube.com') || text.includes('youtu.be')) return 'youtube'
  return null
}

interface Props {
  onResolved: (info: MediaInfo, url: string) => void
  onNeedsCookies: () => void
}

export default function UrlInput({ onResolved, onNeedsCookies }: Props) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const platform = detectPlatform(url)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { info } = await api.resolve(url.trim())
      onResolved(info, url.trim())
    } catch (caught) {
      if (caught instanceof ApiError) setError(caught)
      else setError(new ApiError('INTERNAL', '해석에 실패했습니다.', 500))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="row">
        <input
          type="url"
          value={url}
          placeholder="게시글 · 릴스 · 스토리 링크를 붙여넣으세요"
          autoFocus
          onChange={(event) => setUrl(event.target.value)}
        />
        <button className="primary" type="submit" disabled={busy || url.trim().length < 8}>
          {busy ? '해석 중…' : '가져오기'}
        </button>
      </div>

      {platform && (
        <div className="small muted" style={{ marginTop: 8 }}>
          감지: <span className="badge">{PLATFORM_LABEL[platform]}</span>
        </div>
      )}

      {error && (
        <div className="error small" style={{ marginTop: 12 }}>
          <div>{error.message}</div>
          {error.code === 'LOGIN_REQUIRED' && (
            <button className="small" style={{ marginTop: 8 }} onClick={onNeedsCookies}>
              쿠키 등록하러 가기
            </button>
          )}
          {error.detail && (
            <details style={{ marginTop: 8 }}>
              <summary className="muted">자세히</summary>
              <pre className="detail">{error.detail}</pre>
            </details>
          )}
        </div>
      )}
    </form>
  )
}
