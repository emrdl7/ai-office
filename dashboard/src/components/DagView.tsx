// DAG 시각화 컴포넌트 (WKFL-05)
// React Flow(@xyflow/react)로 태스크 의존성과 진행 상태를 시각화한다.
import { useCallback } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type NodeTypes,
  type Node,
  type Edge,
} from '@xyflow/react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { DagNode, DagEdge } from '../types'

interface DagResponse {
  nodes: DagNode[]
  edges: DagEdge[]
}

async function fetchDag(): Promise<DagResponse> {
  const res = await fetch('/api/dag')
  if (!res.ok) throw new Error('DAG 로드 실패')
  return res.json() as Promise<DagResponse>
}

// 태스크 상태별 노드 색상
function statusColor(status: string): { bg: string; border: string; text: string } {
  switch (status) {
    case 'processing':
      return { bg: '#1d4ed8', border: '#3b82f6', text: '#fff' }
    case 'done':
      return { bg: '#15803d', border: '#22c55e', text: '#fff' }
    case 'failed':
      return { bg: '#b91c1c', border: '#ef4444', text: '#fff' }
    case 'blocked':
      return { bg: '#c2410c', border: '#f97316', text: '#fff' }
    default: // pending
      return { bg: '#374151', border: '#6b7280', text: '#e5e7eb' }
  }
}

// 커스텀 노드 컴포넌트
function TaskNode({ data }: { data: { label: string; status: string; assigned_to: string } }) {
  const colors = statusColor(data.status)
  return (
    <div
      style={{
        background: colors.bg,
        border: `2px solid ${colors.border}`,
        color: colors.text,
        borderRadius: 8,
        padding: '8px 12px',
        minWidth: 140,
        maxWidth: 200,
        fontSize: 12,
        lineHeight: 1.4,
      }}
      role="group"
      aria-label={`태스크: ${data.label}, 상태: ${data.status}, 담당: ${data.assigned_to}`}
    >
      <div style={{ fontWeight: 600, marginBottom: 2, wordBreak: 'break-word' }}>
        {data.label}
      </div>
      <div style={{ opacity: 0.8, fontSize: 10 }}>
        {data.assigned_to} — {data.status}
      </div>
    </div>
  )
}

const nodeTypes: NodeTypes = {
  taskNode: TaskNode,
}

export function DagView() {
  const { theme, setDag } = useStore()

  const { data } = useQuery({
    queryKey: ['dag'],
    queryFn: fetchDag,
    refetchInterval: 3000,
    select: (d) => {
      setDag(d.nodes, d.edges)
      return d
    },
  })

  const nodes: Node[] = (data?.nodes ?? []).map((n) => ({
    id: n.id,
    type: 'taskNode',
    position: n.position,
    data: {
      label: n.data.label,
      status: n.data.status,
      assigned_to: n.data.assigned_to,
    },
  }))

  const edges: Edge[] = (data?.edges ?? []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    animated: false,
    style: { stroke: '#6b7280' },
  }))

  const onInit = useCallback(() => {
    // ReactFlow 초기화 완료
  }, [])

  const bgColor = theme === 'dark' ? '#030712' : '#f9fafb'

  if (nodes.length === 0) {
    return (
      <div
        className="h-full flex flex-col items-center justify-center text-gray-400 text-sm"
        role="status"
      >
        <p className="text-lg mb-2" aria-hidden="true">--</p>
        <p>아직 태스크가 없습니다</p>
        <p className="text-xs mt-1 opacity-60">작업을 지시하면 DAG가 표시됩니다</p>
      </div>
    )
  }

  return (
    <div
      className="h-full rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700"
      role="region"
      aria-label="태스크 DAG 시각화"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={onInit}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        style={{ background: bgColor }}
        aria-label="태스크 의존성 그래프"
      >
        <Background />
        <Controls aria-label="뷰 컨트롤" />
        <MiniMap
          style={{ background: theme === 'dark' ? '#1f2937' : '#f3f4f6' }}
          aria-label="미니맵"
        />
      </ReactFlow>

      {/* 범례 */}
      <div
        className="absolute bottom-12 left-3 flex gap-2 text-xs flex-wrap"
        role="list"
        aria-label="상태 범례"
      >
        {[
          { status: 'pending', label: '대기' },
          { status: 'processing', label: '진행 중' },
          { status: 'done', label: '완료' },
          { status: 'failed', label: '실패' },
          { status: 'blocked', label: '차단됨' },
        ].map(({ status, label }) => {
          const c = statusColor(status)
          return (
            <span
              key={status}
              role="listitem"
              className="flex items-center gap-1 px-1.5 py-0.5 rounded"
              style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}` }}
            >
              {label}
            </span>
          )
        })}
      </div>
    </div>
  )
}
