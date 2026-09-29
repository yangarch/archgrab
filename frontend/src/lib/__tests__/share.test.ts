import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SHARE_SIZE_LIMIT, canShareFiles, isShareable, shareFile } from '../share'
import type { JobFile } from '../../api/types'

function jobFile(overrides: Partial<JobFile> = {}): JobFile {
  return {
    name: 'photo.jpg',
    size: 1_000_000,
    token: 'tok',
    content_type: 'image/jpeg',
    ...overrides,
  }
}

/** iOS 처럼 파일 공유를 지원하는 환경 */
function supported(share = vi.fn().mockResolvedValue(undefined)) {
  Object.assign(navigator, { share, canShare: () => true })
  return share
}

/** 데스크톱 크롬처럼 share 는 있지만 파일은 못 보내는 환경 */
function shareWithoutFiles() {
  Object.assign(navigator, { share: vi.fn(), canShare: () => false })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    blob: async () => new Blob([new Uint8Array(10)], { type: 'image/jpeg' }),
  }))
})

afterEach(() => {
  Reflect.deleteProperty(navigator, 'share')
  Reflect.deleteProperty(navigator, 'canShare')
  vi.unstubAllGlobals()
})

describe('지원 환경 판별', () => {
  it('share 나 canShare 가 없으면 지원하지 않는다', () => {
    expect(canShareFiles()).toBe(false)
  })

  it('파일 공유를 못 하는 브라우저는 걸러낸다 — 눌러도 안 되는 버튼을 띄우면 안 된다', () => {
    shareWithoutFiles()
    expect(canShareFiles()).toBe(false)
  })

  it('둘 다 있으면 지원한다', () => {
    supported()
    expect(canShareFiles()).toBe(true)
  })
})

describe('공유 가능 여부', () => {
  it('지원 기기의 보통 파일은 가능하다', () => {
    supported()
    expect(isShareable(jobFile())).toBe(true)
  })

  it('zip 은 제외한다 — 사진 앱이 받지 않는다', () => {
    supported()
    expect(isShareable(jobFile({ name: 'bundle.zip' }))).toBe(false)
  })

  it('큰 파일은 제외한다 — 메모리를 통째로 거치므로 탭이 죽을 수 있다', () => {
    supported()
    expect(isShareable(jobFile({ size: SHARE_SIZE_LIMIT + 1 }))).toBe(false)
    expect(isShareable(jobFile({ size: SHARE_SIZE_LIMIT }))).toBe(true)
  })

  it('지원하지 않는 환경에서는 언제나 불가', () => {
    expect(isShareable(jobFile())).toBe(false)
  })
})

describe('공유 결과', () => {
  it('성공하면 shared', async () => {
    const share = supported()
    await expect(shareFile(jobFile())).resolves.toBe('shared')
    expect(share).toHaveBeenCalledOnce()
    const passed = share.mock.calls[0][0].files[0]
    expect(passed.name).toBe('photo.jpg')
    expect(passed.type).toBe('image/jpeg')
  })

  it('사용자가 닫으면 cancelled — 실패로 취급하지 않는다', async () => {
    supported(vi.fn().mockRejectedValue(Object.assign(new Error('x'), { name: 'AbortError' })))
    await expect(shareFile(jobFile())).resolves.toBe('cancelled')
  })

  it('제스처 권한이 풀리면 retry — 다시 누르면 캐시 덕에 대개 된다', async () => {
    supported(vi.fn().mockRejectedValue(Object.assign(new Error('x'), { name: 'NotAllowedError' })))
    await expect(shareFile(jobFile())).resolves.toBe('retry')
  })

  it('큰 파일은 받아오기 전에 막는다', async () => {
    supported()
    await expect(shareFile(jobFile({ size: SHARE_SIZE_LIMIT + 1 }))).resolves.toBe('too-large')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('지원하지 않으면 unsupported', async () => {
    await expect(shareFile(jobFile())).resolves.toBe('unsupported')
  })

  it('파일을 못 받으면 failed', async () => {
    supported()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    await expect(shareFile(jobFile())).resolves.toBe('failed')
  })
})
