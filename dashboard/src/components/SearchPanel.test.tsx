import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SearchPanel } from './SearchPanel'

afterEach(() => {
  vi.restoreAllMocks()
})

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn(async (_u: string) => ({
    json: async () => payload,
  })) as unknown as typeof fetch
  global.fetch = fetchMock
  return fetchMock as unknown as ReturnType<typeof vi.fn>
}

describe('<SearchPanel>', () => {
  it('초기에는 안내 메시지 표시', () => {
    render(<SearchPanel onClose={() => {}} />)
    expect(screen.getByText('2글자 이상 입력하세요')).toBeInTheDocument()
  })

  it('1글자 입력은 검색 안 함', async () => {
    const fetchMock = stubFetch({ q: '', type: 'all', logs: [] })
    render(<SearchPanel onClose={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText(/검색어/), { target: { value: 'a' } })
    await new Promise((r) => setTimeout(r, 500))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('2글자 이상 입력 시 디바운스 후 fetch', async () => {
    const fetchMock = stubFetch({
      q: 'api', type: 'all',
      logs: [{
        id: 'log-1', agent_id: 'developer', event_type: 'response',
        message: 'API 구현 완료', timestamp: '2026-04-15T01:00:00Z',
      }],
    })
    render(<SearchPanel onClose={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText(/검색어/), { target: { value: 'api' } })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1), { timeout: 1500 })
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('q=api')
    expect(url).toContain('type=all')
    expect(url).not.toContain('preset=')
    expect(await screen.findByText('API 구현 완료')).toBeInTheDocument()
  })

  it('errors preset 토글 시 q가 비어도 검색 + preset=errors 전송', async () => {
    const fetchMock = stubFetch({ q: '', type: 'logs', preset: 'errors', logs: [] })
    render(<SearchPanel onClose={() => {}} />)
    fireEvent.click(screen.getByText('에러만'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1), { timeout: 1500 })
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('preset=errors')
  })

  it('결과 없으면 "결과 없음" 표시', async () => {
    stubFetch({ q: 'zzz', type: 'all', logs: [], suggestions: [], dynamics: [] })
    render(<SearchPanel onClose={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText(/검색어/), { target: { value: 'zzz' } })
    expect(await screen.findByText('결과 없음', {}, { timeout: 1500 })).toBeInTheDocument()
  })

  // 접근성 검증 — 건의 #259fa9aa (designer 다짐) 반영
  describe('접근성', () => {
    it('닫기 버튼에 aria-label="닫기"가 부여되어 있다', () => {
      render(<SearchPanel onClose={() => {}} />)
      const close = screen.getByRole('button', { name: '닫기' })
      expect(close).toHaveAttribute('aria-label', '닫기')
    })

    it('검색 입력은 autofocus로 포커스를 받는다', () => {
      render(<SearchPanel onClose={() => {}} />)
      const input = screen.getByPlaceholderText(/검색어/)
      expect(document.activeElement).toBe(input)
    })

    it('Tab 키로 검색 입력 → 닫기 버튼 순서로 포커스가 이동한다', async () => {
      const user = userEvent.setup()
      render(<SearchPanel onClose={() => {}} />)
      const input = screen.getByPlaceholderText(/검색어/)
      const close = screen.getByRole('button', { name: '닫기' })
      expect(document.activeElement).toBe(input)
      await user.tab()
      expect(document.activeElement).toBe(close)
    })

    it('배경 클릭으로 onClose 호출된다 (모달 해제 경로)', () => {
      const onClose = vi.fn()
      // SearchPanel은 createPortal로 document.body에 붙음
      render(<SearchPanel onClose={onClose} />)
      const backdrop = document.body.querySelector('div.bg-black\\/60') as HTMLElement
      expect(backdrop).not.toBeNull()
      fireEvent.click(backdrop)
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })
})
