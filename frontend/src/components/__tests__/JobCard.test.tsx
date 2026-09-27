import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import JobCard from '../JobCard'
import type { Job, JobFile } from '../../api/types'

// useJobStream 은 EventSource 를 연다. jsdom 에는 없고, 여기서 검증하려는 건
// 스트림이 아니라 "완료되면 무엇을 저장하는가" 라서 훅을 통째로 대체한다.
vi.mock('../../hooks/useJobStream', () => ({
  useJobStream: (initial: Job) => initial,
}))

function file(name: string): JobFile {
  return { name, size: 1000, token: `tok-${name}`, content_type: 'application/octet-stream' }
}

function job(files: JobFile[], status: Job['status'] = 'done'): Job {
  return {
    id: 'job-1',
    status,
    url: 'https://www.instagram.com/p/AAA/',
    progress: { done_bytes: 0, total_bytes: null, percent: 100, current: null, index: 0, count: 0 },
    files,
    created_at: '2026-09-27T00:00:00',
  }
}

const THREE = [file('a_1.jpg'), file('a_2.jpg'), file('a.zip')]

let clicks: string[]

beforeEach(() => {
  clicks = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    if (this.hasAttribute('download')) clicks.push(this.getAttribute('download') ?? '')
  })
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('완료 시 브라우저 저장', () => {
  it("zip 모드는 zip 하나만 저장한다", async () => {
    render(<JobCard initial={job(THREE)} autoSave saveMode="zip" />)
    await vi.advanceTimersByTimeAsync(2000)
    expect(clicks).toEqual(['a.zip'])
  })

  it('낱개 모드는 zip 을 빼고 파일마다 저장한다', async () => {
    render(<JobCard initial={job(THREE)} autoSave saveMode="each" />)
    await vi.advanceTimersByTimeAsync(2000)
    expect(clicks).toEqual(['a_1.jpg', 'a_2.jpg'])
  })

  it('낱개 저장은 간격을 두고 순차 발동한다 — 한꺼번에 쏘면 브라우저가 흘린다', async () => {
    render(<JobCard initial={job(THREE)} autoSave saveMode="each" />)
    expect(clicks).toEqual(['a_1.jpg'])          // 첫 개는 즉시
    await vi.advanceTimersByTimeAsync(400)
    expect(clicks).toEqual(['a_1.jpg', 'a_2.jpg'])
  })

  it('zip 이 없으면 단일 파일을 저장한다', async () => {
    render(<JobCard initial={job([file('only.mp4')])} autoSave saveMode="zip" />)
    await vi.advanceTimersByTimeAsync(2000)
    expect(clicks).toEqual(['only.mp4'])
  })

  it('과거 작업(autoSave 꺼짐)은 저장하지 않는다 — 새로고침마다 파일이 쏟아지면 안 된다', async () => {
    render(<JobCard initial={job(THREE)} saveMode="each" />)
    await vi.advanceTimersByTimeAsync(2000)
    expect(clicks).toEqual([])
  })

  it('완료 전에는 저장하지 않는다', async () => {
    render(<JobCard initial={job(THREE, 'downloading')} autoSave saveMode="zip" />)
    await vi.advanceTimersByTimeAsync(2000)
    expect(clicks).toEqual([])
  })

  it('저장한 개수를 알린다', async () => {
    render(<JobCard initial={job(THREE)} autoSave saveMode="each" />)
    await vi.advanceTimersByTimeAsync(2000)
    expect(screen.getByText(/2개를 브라우저 다운로드 폴더에 저장했습니다/)).toBeInTheDocument()
  })
})

describe('상태 보고', () => {
  it('부모에게 상태와 진행률을 올려보낸다 — 누른 버튼이 그걸로 표시한다', () => {
    const onStatus = vi.fn()
    render(<JobCard initial={job(THREE)} onStatus={onStatus} />)
    expect(onStatus).toHaveBeenCalledWith('job-1', 'done', 100)
  })
})
