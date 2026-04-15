import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TaskInput } from './TaskInput'

afterEach(() => {
  vi.restoreAllMocks()
})

function renderInput() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TaskInput />
    </QueryClientProvider>,
  )
}

function stubFetch(handler: (url: string, init?: RequestInit) => unknown) {
  const mock = vi.fn(async (url: string, init?: RequestInit) => ({
    ok: true,
    json: async () => handler(url, init),
  })) as unknown as typeof fetch
  global.fetch = mock
  return mock as unknown as ReturnType<typeof vi.fn>
}

describe('<TaskInput>', () => {
  it('빈 입력일 때 지시 버튼 비활성화', async () => {
    stubFetch(() => [])
    renderInput()
    const submit = screen.getByLabelText('작업 지시하기') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
  })

  it('입력 후 빈 목록 안내', async () => {
    stubFetch(() => [])
    renderInput()
    fireEvent.change(screen.getByLabelText('작업 지시 입력'), {
      target: { value: '리포트 작성해줘' },
    })
    expect((screen.getByLabelText('작업 지시하기') as HTMLButtonElement).disabled).toBe(false)
    expect(await screen.findByText('아직 작업 지시가 없습니다')).toBeInTheDocument()
  })

  it('태스크 목록 렌더링 및 상태 점', async () => {
    stubFetch(() => [
      { task_id: 't-1', state: 'completed', instruction: '첫 번째 작업', created_at: '' },
      { task_id: 't-2', state: 'running', instruction: '두 번째 작업', created_at: '' },
    ])
    renderInput()
    expect(await screen.findByText(/첫 번째 작업/)).toBeInTheDocument()
    expect(screen.getByText(/두 번째 작업/)).toBeInTheDocument()
  })

  it('지시하기 클릭 시 POST /api/tasks 호출', async () => {
    let postBody: FormData | null = null
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        postBody = init.body as FormData
        return { ok: true, json: async () => ({ task_id: 'new-1' }) }
      }
      return { ok: true, json: async () => [] }
    }) as unknown as typeof fetch
    global.fetch = fetchMock
    renderInput()
    fireEvent.change(screen.getByLabelText('작업 지시 입력'), {
      target: { value: '새 작업' },
    })
    fireEvent.click(screen.getByLabelText('작업 지시하기'))
    await waitFor(() => {
      const calls = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls
      expect(calls.some((c) => c[0] === '/api/tasks' && (c[1] as RequestInit | undefined)?.method === 'POST')).toBe(true)
    })
    expect(postBody).not.toBeNull()
    expect(postBody!.get('instruction')).toBe('새 작업')
  })
})
