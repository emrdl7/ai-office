import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MetricsPanel, formatDuration } from './MetricsPanel'

describe('formatDuration', () => {
  it('<= 0 이거나 빈 값이면 "-"', () => {
    expect(formatDuration(0)).toBe('-')
    expect(formatDuration(-10)).toBe('-')
  })

  it('60분 미만은 분 단위', () => {
    expect(formatDuration(120)).toBe('2분')
    expect(formatDuration(59 * 60)).toBe('59분')
  })

  it('60분 이상은 "시간 분"', () => {
    expect(formatDuration(3600)).toBe('1시간 0분')
    expect(formatDuration(3600 + 25 * 60)).toBe('1시간 25분')
  })
})

describe('<MetricsPanel>', () => {
  it('데이터 없을 때 빈 상태 메시지 노출', async () => {
    // @ts-expect-error: fetch 스텁
    global.fetch = async () => ({ json: async () => [] })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MetricsPanel onClose={() => {}} />
      </QueryClientProvider>,
    )
    expect(
      await screen.findByText(/아직 수집된 프로젝트 메트릭이 없습니다/),
    ).toBeInTheDocument()
  })
})
