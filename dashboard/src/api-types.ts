// ⚠️ 자동 생성 파일 — 직접 수정 금지
// 생성: node scripts/gen-types.mjs  (입력: src/openapi.json)
// 소스: server/scripts/gen_openapi.py → FastAPI /openapi.json


export interface Body_chat_api_chat_post {
  message?: string
  to?: string
  files?: string[]
}

export interface Body_create_task_api_tasks_post {
  instruction: string
  files?: string[]
}

export interface Body_submit_job_api_jobs_post {
  spec_id: string
  title?: string
  input?: string
  source_job_id?: string
  depends_on?: string
  files?: string[]
}

export interface GateDecisionRequest {
  decision: string
  feedback?: string
}

export interface PlaybookRunRequest {
  input?: Record<string, string>
}

export interface TopicRequest {
  topic: string
}

// PATCH /api/jobs/tools/{tool_id}
export type ToggleJobsToolsToolIdPatchBody = Record<string, unknown>