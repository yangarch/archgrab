import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { makeInfo, makeItem } from '../test/factories'

const resolve = vi.fn()
const createJob = vi.fn()
const getJob = vi.fn()

// EventSource 는 jsdom 에 없다. 여기서 보려는 건 스트림이 아니라 "완료 표시가
// 언제 남고 언제 지워지는가" 라서 훅을 통째로 대체한다.
vi.mock('../hooks/useJobStream', () => ({ useJobStream: (initial: unknown) => initial }))

vi.mock('../api/client', () => ({
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
    createJob: (body: unknown) => createJob(body),
    getJob: (id: string) => getJob(id),
  },
}))

function doneJob(id = 'j1') {
  return {
    id,
    status: 'done' as const,
    url: 'https://www.instagram.com/p/AAA/',
    progress: { done_bytes: 1, total_bytes: 1, percent: 100, current: null, index: 1, count: 1 },
    files: [{ name: 'a_1.jpg', size: 10, token: 'tok', content_type: 'image/jpeg' }],
    created_at: '2026-10-01T00:00:00',
  }
}

async function paste(user: ReturnType<typeof userEvent.setup>, url: string) {
  const input = screen.getByPlaceholderText(/붙여넣으세요/)
  await user.clear(input)
  await user.type(input, url)
  await user.click(screen.getByRole('button', { name: '가져오기' }))
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  resolve.mockReset()
  createJob.mockReset().mockResolvedValue({ job_id: 'j1' })
  getJob.mockReset().mockResolvedValue(doneJob())
  // 자동 저장이 실제 다운로드를 걸지 않도록
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  vi.useRealTimers()
})

describe('완료 표시가 남는 범위', () => {
  it('항목 버튼의 저장됨은 사라지지 않는다 — 무엇을 받았는지 알 수 있어야 한다', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    resolve.mockResolvedValue({ info: makeInfo([makeItem('0'), makeItem('1')]), cached: false })

    render(<App />)
    await waitFor(() => expect(screen.getByPlaceholderText(/붙여넣으세요/)).toBeInTheDocument())
    await paste(user, 'https://www.instagram.com/p/AAA/')
    await waitFor(() => expect(screen.getAllByRole('button', { name: /내려받기/ })).toHaveLength(2))

    await user.click(screen.getAllByRole('button', { name: 'jpg 내려받기' })[0])
    await waitFor(() => expect(screen.getByRole('button', { name: '저장됨 ✓' })).toBeInTheDocument())

    // 일괄 버튼이었다면 4초 뒤 사라진다. 항목 버튼은 남아야 한다.
    // act 로 감싸야 타이머가 건 setState 가 DOM 까지 반영된다 — 감싸지 않으면
    // 자동 삭제가 살아 있어도 화면이 그대로라 테스트가 통과해버린다.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(screen.getByRole('button', { name: '저장됨 ✓' })).toBeInTheDocument()
    // 받지 않은 항목 하나만 기본 상태로 남는다 (되돌아왔다면 2개가 된다)
    expect(screen.getAllByRole('button', { name: 'jpg 내려받기' })).toHaveLength(1)
  })

  it('다른 게시글을 열면 이전 표시가 남지 않는다', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    resolve
      .mockResolvedValueOnce({ info: makeInfo([makeItem('0')], { key: 'AAA' }), cached: false })
      .mockResolvedValueOnce({ info: makeInfo([makeItem('0')], { key: 'BBB' }), cached: false })

    render(<App />)
    await waitFor(() => expect(screen.getByPlaceholderText(/붙여넣으세요/)).toBeInTheDocument())
    await paste(user, 'https://www.instagram.com/p/AAA/')
    await waitFor(() => expect(screen.getByRole('button', { name: 'jpg 내려받기' })).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'jpg 내려받기' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '저장됨 ✓' })).toBeInTheDocument())

    // 항목 id 는 게시글마다 0,1,2… 로 겹친다. 남겨두면 엉뚱한 타일에 붙는다.
    await paste(user, 'https://www.instagram.com/p/BBB/')
    await waitFor(() => expect(screen.getByRole('button', { name: 'jpg 내려받기' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '저장됨 ✓' })).not.toBeInTheDocument()
  })
})
