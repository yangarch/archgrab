import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MediaPreview, { BULK_EACH_KEY, BULK_ZIP_KEY } from '../MediaPreview'
import { makeInfo, makeItem, makeMultiFormatItem } from '../../test/factories'

const three = [makeItem('0'), makeItem('1', 'video'), makeItem('2')]

function setup(items = three, downloads = {}) {
  const onDownload = vi.fn()
  render(<MediaPreview info={makeInfo(items)} downloads={downloads} onDownload={onDownload} />)
  return { onDownload, user: userEvent.setup() }
}

describe('항목별 타입 표시', () => {
  it('버튼에 확장자가 드러난다 — 받기 전에 무엇인지 알 수 있어야 한다', () => {
    setup()
    expect(screen.getAllByRole('button', { name: 'jpg 내려받기' })).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'mp4 내려받기' })).toBeInTheDocument()
  })

  it('이미지·동영상 개수를 요약한다', () => {
    setup()
    expect(screen.getByText(/동영상 1 · 이미지 2/)).toBeInTheDocument()
  })
})

describe('일괄 받기 버튼', () => {
  it('2개 이상 선택되면 낱개와 zip 둘 다 제공한다', () => {
    setup()
    expect(screen.getByRole('button', { name: /낱개로 3개/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /zip으로 3개/ })).toBeInTheDocument()
  })

  it('1개만 선택되면 zip 버튼이 사라진다 — 파일 하나에 zip 은 의미가 없다', async () => {
    const { user } = setup()
    // 전체 선택 상태에서 두 개를 해제해 1개만 남긴다
    await user.click(screen.getByLabelText('2번 항목 선택'))
    await user.click(screen.getByLabelText('3번 항목 선택'))

    expect(screen.getByRole('button', { name: /낱개로 1개/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /zip으로/ })).not.toBeInTheDocument()
  })

  it('선택 개수가 실제 선택과 일치한다', async () => {
    const { user } = setup()
    await user.click(screen.getByLabelText('1번 항목 선택'))
    expect(screen.getByRole('button', { name: /낱개로 2개/ })).toBeInTheDocument()
  })

  it('낱개와 zip 이 서로 다른 요청키를 쓴다 — 한쪽 진행률이 다른 쪽에 뜨면 안 된다', async () => {
    const { onDownload, user } = setup()
    await user.click(screen.getByRole('button', { name: /낱개로 3개/ }))
    await user.click(screen.getByRole('button', { name: /zip으로 3개/ }))

    expect(onDownload.mock.calls[0][1]).toBe(BULK_EACH_KEY)
    expect(onDownload.mock.calls[0][2]).toBe('each')
    expect(onDownload.mock.calls[1][1]).toBe(BULK_ZIP_KEY)
    expect(onDownload.mock.calls[1][2]).toBe('zip')
  })
})

describe('진행 상태 표시', () => {
  it('누른 버튼이 요청 중 → 받는 중 N% → 저장됨 으로 바뀐다', () => {
    const cases: Array<[Record<string, unknown>, string]> = [
      [{ status: 'starting', percent: 0 }, '요청 중…'],
      [{ status: 'running', percent: 0 }, '받는 중…'],
      [{ status: 'running', percent: 42 }, '받는 중 42%'],
      [{ status: 'done', percent: 100 }, '저장됨 ✓'],
      [{ status: 'error', percent: 0 }, '실패 · 다시'],
    ]
    for (const [state, text] of cases) {
      const { unmount } = render(
        <MediaPreview info={makeInfo(three)} downloads={{ '0': state as never }} onDownload={vi.fn()} />,
      )
      expect(screen.getByRole('button', { name: text })).toBeInTheDocument()
      unmount()
    }
  })

  it('한 항목을 받는 동안 다른 항목 버튼은 계속 눌린다', () => {
    setup(three, { '0': { status: 'running', percent: 10 } })
    expect(screen.getByRole('button', { name: '받는 중 10%' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'mp4 내려받기' })).toBeEnabled()
  })

  it('일괄 진행 중에는 두 일괄 버튼이 함께 잠긴다', () => {
    setup(three, { [BULK_EACH_KEY]: { status: 'running', percent: 5 } })
    expect(screen.getByRole('button', { name: '받는 중 5%' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /zip으로 3개/ })).toBeDisabled()
  })
})

describe('누락 안내', () => {
  it('엔진이 못 가져온 항목이 있으면 알린다 — 조용히 버리지 않는다', () => {
    const info = makeInfo([makeItem('0')], {
      missing_items: 12,
      notice: '12개 항목을 가져오지 못했습니다 (이미지 항목).',
    })
    render(<MediaPreview info={info} downloads={{}} onDownload={vi.fn()} />)
    expect(screen.getByText(/12개 항목을 가져오지 못했습니다/)).toBeInTheDocument()
  })
})

describe('화질 선택 (유튜브처럼 포맷이 여럿인 경우)', () => {
  it('포맷이 하나뿐이면 선택기 대신 라벨만 보인다', () => {
    setup([makeItem('0')])
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByTitle('1080×1350 · jpg · 원본')).toBeInTheDocument()
  })

  it('포맷이 여러 개면 선택기가 뜨고 기본은 첫 번째다', () => {
    setup([makeMultiFormatItem()])
    const picker = screen.getByRole('combobox', { name: /1번 항목 화질/ })
    expect(picker).toHaveValue('401')
    expect(screen.getAllByRole('option')).toHaveLength(4)
  })

  it('고른 화질에 따라 버튼의 확장자가 바뀐다', async () => {
    const { user } = setup([makeMultiFormatItem()])
    expect(screen.getByRole('button', { name: 'mp4 내려받기' })).toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: /화질/ }), '140')
    expect(screen.getByRole('button', { name: 'm4a 내려받기' })).toBeInTheDocument()
  })

  it('고른 화질이 다운로드 요청에 실린다', async () => {
    const { onDownload, user } = setup([makeMultiFormatItem()])
    await user.selectOptions(screen.getByRole('combobox', { name: /화질/ }), '134')
    await user.click(screen.getByRole('button', { name: 'mp4 내려받기' }))

    expect(onDownload).toHaveBeenCalledWith(['0'], '0', 'each', { '0': '134' })
  })

  it('일괄 받기에도 고른 화질이 실린다', async () => {
    const { onDownload, user } = setup([makeMultiFormatItem('0'), makeItem('1')])
    await user.selectOptions(screen.getByRole('combobox', { name: /1번 항목 화질/ }), '137')
    await user.click(screen.getByRole('button', { name: /낱개로 2개/ }))

    expect(onDownload.mock.calls[0][3]).toEqual({ '0': '137', '1': 'original' })
  })
})

describe('갤러리로 바로 보내기', () => {
  const shareMock = vi.fn()

  function galleryEnv(supported = true) {
    Object.assign(navigator, {
      share: shareMock.mockResolvedValue(undefined),
      canShare: () => supported,
    })
  }

  afterEach(() => {
    Reflect.deleteProperty(navigator, 'share')
    Reflect.deleteProperty(navigator, 'canShare')
    shareMock.mockReset()
  })

  function renderWith(props: Partial<Parameters<typeof MediaPreview>[0]> = {}) {
    const onDownload = vi.fn()
    const onGallerySent = vi.fn()
    render(
      <MediaPreview
        info={makeInfo([makeItem('0')])}
        downloads={{}}
        onDownload={onDownload}
        onGallerySent={onGallerySent}
        {...props}
      />,
    )
    return { onDownload, onGallerySent, user: userEvent.setup() }
  }

  it('지원하지 않는 기기에는 버튼을 띄우지 않는다', () => {
    galleryEnv(false)
    renderWith()
    expect(screen.queryByRole('button', { name: /갤러리/ })).not.toBeInTheDocument()
  })

  it('지원 기기에는 갤러리 버튼이 뜬다', () => {
    galleryEnv()
    renderWith()
    expect(screen.getByRole('button', { name: /1번 항목 갤러리/ })).toBeInTheDocument()
  })

  it('큰 파일에는 띄우지 않는다 — 메모리를 통째로 거친다', () => {
    galleryEnv()
    const big = makeItem('0')
    big.formats[0].filesize = 200 * 1024 * 1024
    renderWith({ info: makeInfo([big]) })
    expect(screen.queryByRole('button', { name: /갤러리/ })).not.toBeInTheDocument()
  })

  it('첫 탭은 공유가 아니라 작업 시작이다 — 파일이 아직 없다', async () => {
    galleryEnv()
    const { onDownload, user } = renderWith()
    await user.click(screen.getByRole('button', { name: /1번 항목 갤러리$/ }))

    expect(onDownload).toHaveBeenCalledWith(['0'], 'gallery:0', 'each', { '0': 'original' }, true)
    expect(shareMock).not.toHaveBeenCalled()
  })

  it('준비되면 문구가 보내기로 바뀐다', () => {
    galleryEnv()
    renderWith({
      galleryReady: { '0': { name: 'a.jpg', size: 10, token: 't', content_type: 'image/jpeg' } },
      downloads: { 'gallery:0': { status: 'ready', percent: 100 } },
    })
    expect(screen.getByRole('button', { name: /갤러리로 보내기/ })).toBeInTheDocument()
  })

  it('준비 상태에서 탭하면 공유 시트를 연다', async () => {
    galleryEnv()
    const file = { name: 'a.jpg', size: 10, token: 't', content_type: 'image/jpeg' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob([new Uint8Array(4)], { type: 'image/jpeg' }),
    }))
    const { onGallerySent, user } = renderWith({ galleryReady: { '0': file } })

    await user.click(screen.getByRole('button', { name: /갤러리로 보내기/ }))
    expect(shareMock).toHaveBeenCalledOnce()
    expect(onGallerySent).toHaveBeenCalledWith('0', 'gallery:0')
    vi.unstubAllGlobals()
  })

  it('진행률을 버튼에 보여준다', () => {
    galleryEnv()
    renderWith({ downloads: { 'gallery:0': { status: 'running', percent: 40 } } })
    expect(screen.getByRole('button', { name: /준비 중 40%/ })).toBeInTheDocument()
  })
})

describe('갤러리 준비 완료 표시', () => {
  function env() {
    Object.assign(navigator, { share: vi.fn(), canShare: () => true })
  }

  afterEach(() => {
    Reflect.deleteProperty(navigator, 'share')
    Reflect.deleteProperty(navigator, 'canShare')
  })

  it('기본 상태에는 강조가 없다', () => {
    env()
    render(
      <MediaPreview info={makeInfo([makeItem('0')])} downloads={{}} onDownload={vi.fn()} />,
    )
    expect(screen.getByRole('button', { name: /1번 항목 갤러리$/ })).not.toHaveClass('is-ready')
  })

  it('준비가 끝나면 색이 바뀐다 — 문구만으로는 놓치기 쉽다', () => {
    env()
    render(
      <MediaPreview
        info={makeInfo([makeItem('0')])}
        downloads={{ 'gallery:0': { status: 'ready', percent: 100 } }}
        galleryReady={{ '0': { name: 'a.jpg', size: 10, token: 't', content_type: 'image/jpeg' } }}
        onDownload={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /갤러리로 보내기/ })).toHaveClass('is-ready')
  })

  it('준비 중에는 아직 강조하지 않는다', () => {
    env()
    render(
      <MediaPreview
        info={makeInfo([makeItem('0')])}
        downloads={{ 'gallery:0': { status: 'running', percent: 30 } }}
        onDownload={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /준비 중 30%/ })).not.toHaveClass('is-ready')
  })
})
