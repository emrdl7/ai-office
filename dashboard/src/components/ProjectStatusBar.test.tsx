import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProjectStatusBar, formatElapsed } from './ProjectStatusBar'

describe('formatElapsed', () => {
  it('0 이하면 빈 문자열', () => {
    expect(formatElapsed(0)).toBe('')
    expect(formatElapsed(-5)).toBe('')
  })

  it('60초 미만은 초 단위', () => {
    expect(formatElapsed(45)).toBe('45s')
  })

  it('60초~1시간은 "분 초"', () => {
    expect(formatElapsed(125)).toBe('2m 5s')
    expect(formatElapsed(59 * 60 + 30)).toBe('59m 30s')
  })

  it('1시간 이상은 "시간 분"', () => {
    expect(formatElapsed(3600)).toBe('1h 0m')
    expect(formatElapsed(3600 + 25 * 60)).toBe('1h 25m')
  })
})

function renderWithQuery(payload: unknown) {
  // @ts-expect-error: fetch 스텁
  global.fetch = async () => ({ json: async () => payload })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ProjectStatusBar />
    </QueryClientProvider>,
  )
}

describe('<ProjectStatusBar>', () => {
  it('idle 상태면 렌더하지 않음', async () => {
    const { container } = renderWithQuery({
      state: 'idle', project_id: '', title: '', active_agent: '',
      current_phase: '', work_started_at: '', elapsed_sec: 0,
      revision_count: 0, nodes: null,
    })
    // 첫 페치 완료 대기 후 컨테이너가 비어 있어야 함
    await new Promise((r) => setTimeout(r, 10))
    expect(container.firstChild).toBeNull()
  })

  it('working 상태면 라벨/단계/노드 진행도 표시', async () => {
    renderWithQuery({
      state: 'working', project_id: 'p1', title: 'API 구현',
      active_agent: 'developer', current_phase: '구현',
      work_started_at: '2026-04-15T00:00:00Z', elapsed_sec: 125,
      revision_count: 2,
      nodes: { total: 5, completed: 2, in_progress: 1 },
    })
    expect(await screen.findByText('작업중')).toBeInTheDocument()
    expect(screen.getByText('구현')).toBeInTheDocument()
    expect(screen.getByText(/developer/)).toBeInTheDocument()
    expect(screen.getByText(/2m 5s/)).toBeInTheDocument()
    expect(screen.getByText(/rev 2/)).toBeInTheDocument()
    expect(screen.getByText(/노드 2\/5/)).toBeInTheDocument()
    expect(screen.getByText(/진행 1/)).toBeInTheDocument()
  })
})
