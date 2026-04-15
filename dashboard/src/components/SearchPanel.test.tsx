import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SearchPanel } from './SearchPanel'

afterEach(() => {
  vi.restoreAllMocks()
})

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn(async (_url: string) => ({
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
    fireEvent.click(screen.getByText('⚠ 에러만'))
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
})
