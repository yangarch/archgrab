import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { makeInfo, makeItem } from '../test/factories'

const resolve = vi.fn()

vi.mock('../api/client', () => ({
  // 파라미터 프로퍼티는 erasableSyntaxOnly 에서 금지된다 (tsc -b 가 빌드에서 잡는다)
  ApiError: class ApiError extends Error {
    code: string
    status: number
    constructor(code: string, message: string, status: number) {
      super(message)
      this.code = code
      this.status = status
    }
  },
  api: {
    me: () => Promise.resolve({ authenticated: true, configured: true }),
    listJobs: () => Promise.resolve([]),
    engines: () => Promise.resolve({}),
    logout: () => Promise.resolve({ authenticated: false }),
    resolve: (url: string) => resolve(url),
    createJob: () => Promise.resolve({ job_id: 'j1' }),
    getJob: () => Promise.resolve(null),
  },
}))

const FIFTEEN = Array.from({ length: 15 }, (_, i) => makeItem(String(i)))
const ONE = [makeItem('0', 'video')]

async function paste(user: ReturnType<typeof userEvent.setup>, url: string) {
  const input = screen.getByPlaceholderText(/붙여넣으세요/)
  await user.clear(input)
  await user.type(input, url)
  await user.click(screen.getByRole('button', { name: '가져오기' }))
}

beforeEach(() => {
  resolve.mockReset()
})

describe('새 URL 을 해석했을 때 이전 게시글의 선택이 남지 않는다', () => {
  it('15개 → 1개 로 바뀌면 선택 개수도 1개가 된다', async () => {
    const user = userEvent.setup()
    resolve
      .mockResolvedValueOnce({ info: makeInfo(FIFTEEN, { key: 'AAA' }), cached: false })
      .mockResolvedValueOnce({ info: makeInfo(ONE, { key: 'BBB' }), cached: false })

    render(<App />)
    await waitFor(() => expect(screen.getByPlaceholderText(/붙여넣으세요/)).toBeInTheDocument())

    await paste(user, 'https://www.instagram.com/p/AAA/')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /낱개로 15개/ })).toBeInTheDocument(),
    )

    await paste(user, 'https://www.instagram.com/p/BBB/')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /낱개로 1개/ })).toBeInTheDocument(),
    )
    // 이전 게시글의 15개가 남아 있으면 안 된다 (실제로 보고된 버그)
    expect(screen.queryByRole('button', { name: /낱개로 15개/ })).not.toBeInTheDocument()
    // 항목 하나뿐이므로 zip 버튼도 없어야 한다
    expect(screen.queryByRole('button', { name: /zip으로/ })).not.toBeInTheDocument()
  })

  it('1개 → 15개 로 바뀌는 반대 방향도 맞다', async () => {
    const user = userEvent.setup()
    resolve
      .mockResolvedValueOnce({ info: makeInfo(ONE, { key: 'BBB' }), cached: false })
      .mockResolvedValueOnce({ info: makeInfo(FIFTEEN, { key: 'AAA' }), cached: false })

    render(<App />)
    await waitFor(() => expect(screen.getByPlaceholderText(/붙여넣으세요/)).toBeInTheDocument())

    await paste(user, 'https://www.instagram.com/p/BBB/')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /낱개로 1개/ })).toBeInTheDocument(),
    )

    await paste(user, 'https://www.instagram.com/p/AAA/')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /낱개로 15개/ })).toBeInTheDocument(),
    )
  })
})
