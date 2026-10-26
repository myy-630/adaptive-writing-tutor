import type { FormState, SessionView, Stage, Task, WorkflowResult } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options?.headers },
    })
  } catch {
    throw new ApiError('无法连接教学服务，请检查后端是否运行。', 0)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const message = body?.error?.message
      ?? (response.status === 422 ? '输入未通过检查，请补齐本阶段必填项。' : `请求失败（${response.status}）`)
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export async function createWorkspace(input: {
  grade: number
  learningGoal: string
  prompt: string
  genre: string
  requiredPoints: string[]
}): Promise<{ sessionId: string; studentId: string; firstResult: WorkflowResult }> {
  const studentId = crypto.randomUUID()
  const taskId = crypto.randomUUID()
  const sessionId = crypto.randomUUID()
  await request('/students', {
    method: 'POST',
    body: JSON.stringify({ id: studentId, grade: input.grade, learning_goal: input.learningGoal }),
  })
  await request<Task>('/tasks', {
    method: 'POST',
    body: JSON.stringify({
      id: taskId,
      prompt: input.prompt,
      genre: input.genre,
      grade: input.grade,
      required_points: input.requiredPoints,
    }),
  })
  await request('/sessions', {
    method: 'POST',
    body: JSON.stringify({ id: sessionId, student_id: studentId, task_id: taskId }),
  })
  const firstResult = await submitTurn(sessionId, studentId, { kind: 'start' })
  return { sessionId, studentId, firstResult }
}

export function getSession(sessionId: string, studentId: string): Promise<SessionView> {
  return request(`/sessions/${encodeURIComponent(sessionId)}?student_id=${encodeURIComponent(studentId)}`)
}

export interface Submission {
  kind: 'start' | 'response' | 'finalize'
  text?: string
  message?: string
  prompt_analysis?: {
    audience: string; purpose: string; genre: string; required_points: string[]
    tense: string; person: string; constraints: string
  }
  structure_plan?: { opening: string; body: string; conclusion: string }
  content_plan?: {
    viewpoint: string; reason: string; example: string; detail: string; result_or_feeling: string
  }
  relation_explanation?: string
  transfer_response?: string
  independent_revision?: boolean
}

export function buildSubmission(stage: Stage, mode: SessionView['mode'], draft: string, form: FormState): Submission {
  if (stage === 'final_evaluation') return { kind: 'finalize' }
  const base: Submission = { kind: 'response', message: form.message || undefined }
  if (stage === 'prompt_analysis') {
    if (mode === 'independent') return { ...base, text: draft }
    return {
      ...base,
      prompt_analysis: {
        audience: form.audience,
        purpose: form.purpose,
        genre: form.genre,
        required_points: form.requiredPoints.split(/[,，\n]/).map(value => value.trim()).filter(Boolean),
        tense: form.tense,
        person: form.person,
        constraints: form.constraints,
      },
    }
  }
  base.text = draft
  if (stage === 'grammar_revision') base.transfer_response = form.transferResponse || undefined
  if (stage === 'structure_revision' && mode !== 'independent') {
    base.structure_plan = { opening: form.opening, body: form.body, conclusion: form.conclusion }
  }
  if (stage === 'content_expansion' && mode !== 'independent') {
    base.content_plan = {
      viewpoint: form.viewpoint, reason: form.reason, example: form.example,
      detail: form.detail, result_or_feeling: form.resultOrFeeling,
    }
  }
  if (stage === 'language_refinement' && mode !== 'independent') {
    base.relation_explanation = form.relationExplanation
  }
  if (stage === 'second_draft') base.independent_revision = mode === 'independent' || form.independentRevision
  return base
}

export function submitTurn(sessionId: string, studentId: string, submission: Submission, requestId: string = crypto.randomUUID()): Promise<WorkflowResult> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/turn`, {
    method: 'POST',
    body: JSON.stringify({
      student_id: studentId,
      submission: { ...submission, request_id: requestId },
    }),
  })
}
