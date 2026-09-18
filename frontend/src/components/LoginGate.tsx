import { useState } from 'react'

import { ApiError, api } from '../api/client'

interface Props {
  configured: boolean
  onAuthenticated: () => void
}

export default function LoginGate({ configured, onAuthenticated }: Props) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.login(password)
      onAuthenticated()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : '로그인에 실패했습니다.')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  if (!configured) {
    return (
      <div className="gate">
        <div className="card">
          <h2 style={{ marginTop: 0 }}>초기 설정이 필요합니다</h2>
          <p className="muted">
            아직 비밀번호가 등록되지 않았습니다. 터미널에서 <code>make hashpw</code> 를 실행해
            출력된 두 줄을 <code>.env</code> 에 넣고 서버를 다시 시작해주세요.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="gate">
      <form className="card" onSubmit={submit}>
        <h2 style={{ margin: 0, fontSize: 16 }}>archgrab</h2>
        <p className="muted small" style={{ margin: 0 }}>
          개인용 서비스입니다. 비밀번호를 입력해주세요.
        </p>
        <input
          type="password"
          value={password}
          autoFocus
          autoComplete="current-password"
          placeholder="비밀번호"
          onChange={(event) => setPassword(event.target.value)}
        />
        {error && <div className="error small">{error}</div>}
        <button className="primary" type="submit" disabled={busy || !password}>
          {busy ? '확인 중…' : '로그인'}
        </button>
      </form>
    </div>
  )
}
