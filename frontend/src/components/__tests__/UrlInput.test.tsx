import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import UrlInput from '../UrlInput'

function setup() {
  render(<UrlInput onResolved={vi.fn()} onNeedsCookies={vi.fn()} />)
  return { user: userEvent.setup(), input: screen.getByPlaceholderText(/붙여넣으세요/) }
}

describe('입력 지우기', () => {
  it('비어 있으면 버튼이 없다', () => {
    setup()
    expect(screen.queryByRole('button', { name: '입력 지우기' })).not.toBeInTheDocument()
  })

  it('입력하면 버튼이 뜨고, 누르면 지워진다', async () => {
    const { user, input } = setup()
    await user.type(input, 'https://www.instagram.com/p/AAA/')
    await user.click(screen.getByRole('button', { name: '입력 지우기' }))

    expect(input).toHaveValue('')
    expect(screen.queryByRole('button', { name: '입력 지우기' })).not.toBeInTheDocument()
  })

  it('지운 뒤 입력창에 포커스가 남는다 — 바로 다음 링크를 붙여넣을 수 있게', async () => {
    const { user, input } = setup()
    await user.type(input, 'https://x.com/a/status/1')
    await user.click(screen.getByRole('button', { name: '입력 지우기' }))
    expect(input).toHaveFocus()
  })

  it('플랫폼 배지도 함께 사라진다', async () => {
    const { user, input } = setup()
    await user.type(input, 'https://www.instagram.com/p/AAA/')
    expect(screen.getByText('인스타그램')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '입력 지우기' }))
    expect(screen.queryByText('인스타그램')).not.toBeInTheDocument()
  })
})
