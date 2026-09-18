import { useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../api/client'
import type { CookieStatus } from '../api/types'

const PLATFORMS: { id: string; label: string; hint: string }[] = [
  { id: 'instagram', label: '인스타그램', hint: '스토리·비공개 게시글에 필요합니다' },
  { id: 'x', label: 'X', hint: 'M2 에서 사용합니다' },
  { id: 'youtube', label: '유튜브', hint: 'M3 에서 사용합니다' },
]

export default function CookieSettings() {
  const [rows, setRows] = useState<CookieStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const inputs = useRef<Record<string, HTMLInputElement | null>>({})

  const refresh = () => api.cookies().then(setRows, () => setRows([]))

  useEffect(() => {
    void refresh()
  }, [])

  async function upload(platform: string, file: File) {
    setError(null)
    try {
      await api.uploadCookies(platform, file)
      await refresh()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : '업로드에 실패했습니다.')
    }
  }

  async function remove(platform: string) {
    await api.deleteCookies(platform).catch(() => undefined)
    await refresh()
  }

  return (
    <div className="card">
      <h2 style={{ margin: '0 0 4px', fontSize: 16 }}>쿠키</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        브라우저에서 Netscape 형식 <code>cookies.txt</code>를 내보내 올려주세요. 암호화되어
        저장되고 응답·로그에 노출되지 않습니다.
      </p>

      {error && <div className="error small">{error}</div>}

      <div className="rows">
        {PLATFORMS.map((platform) => {
          const status = rows.find((row) => row.platform === platform.id)
          return (
            <div className="row cookie-row" key={platform.id}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div>
                  {platform.label}{' '}
                  {status?.present ? (
                    <span className={`badge small ${status.expired ? 'status-error' : 'status-done'}`}>
                      {status.expired ? '만료됨' : `등록됨 · ${status.entries}개`}
                    </span>
                  ) : (
                    <span className="badge small muted">없음</span>
                  )}
                </div>
                <div className="muted small">{platform.hint}</div>
              </div>

              <input
                ref={(element) => {
                  inputs.current[platform.id] = element
                }}
                type="file"
                accept=".txt,text/plain"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void upload(platform.id, file)
                  event.target.value = ''
                }}
              />
              <button className="small" onClick={() => inputs.current[platform.id]?.click()}>
                {status?.present ? '교체' : '등록'}
              </button>
              {status?.present && (
                <button className="small" onClick={() => void remove(platform.id)}>
                  삭제
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
