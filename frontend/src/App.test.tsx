import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { sessionFor } from './testFixtures'

const saved = { sessionId: 'session-1', studentId: 'student-1' }

function okJson(value: unknown) {
  return { ok: true, json: async () => value } as Response
}

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})
afterEach(() => vi.unstubAllGlobals())

describe('adaptive workspace', () => {
  it('shows a useful empty state', () => {
    render(<App />)
    expect(screen.getByText(/让每一篇作文/)).toBeInTheDocument()
    expect(screen.getByLabelText('作文题目')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /开始写作/ })).toBeDisabled()
  })

  it('restores a session on refresh and selects components from backend state', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const fetchMock = vi.fn().mockResolvedValue(okJson(sessionFor('grammar_revision')))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    expect(screen.getByText('正在恢复你的写作工作区…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '语法修改', level: 1 })).toBeInTheDocument()
    expect(screen.getByLabelText('语法知识图谱')).toBeInTheDocument()
    expect(screen.getAllByText('主谓一致')).toHaveLength(2)
    expect(screen.getByDisplayValue('I has a memorable day.')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/sessions/session-1?student_id=student-1', expect.any(Object))
  })

  it('renders independent mode with the writing area only', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okJson(sessionFor('grammar_revision', 'independent'))))
    render(<App />)
    expect(await screen.findByRole('heading', { name: '语法修改', level: 1 })).toBeInTheDocument()
    expect(screen.getByLabelText('作文编辑器')).toBeInTheDocument()
    expect(screen.queryByLabelText('语法错误卡')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('语法知识图谱')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('教学对话区')).not.toBeInTheDocument()
  })

  it('shows a loading state until the API responds', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise<Response>(resolve => { finish = resolve })))
    render(<App />)
    expect(screen.getByRole('status')).toHaveTextContent('正在恢复')
    finish(okJson(sessionFor('structure_revision')))
    expect(await screen.findByLabelText('段落结构图')).toBeInTheDocument()
  })

  it('shows an API failure and retries the same saved session', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(okJson(sessionFor('content_expansion')))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('无法连接教学服务')
    fireEvent.click(screen.getByRole('button', { name: /重试连接/ }))
    expect(await screen.findByLabelText('内容展开卡')).toBeInTheDocument()
    expect(localStorage.getItem('awt.activeSession')).toBe(JSON.stringify(saved))
  })

  it('keeps a draft when submission fails', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const fetchMock = vi.fn().mockResolvedValueOnce(okJson(sessionFor('first_draft'))).mockRejectedValueOnce(new Error('offline'))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    const editor = await screen.findByLabelText('作文内容')
    fireEvent.change(editor, { target: { value: 'My work in progress' } })
    fireEvent.click(screen.getByRole('button', { name: /提交初稿/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('无法连接教学服务'))
    expect(screen.getByDisplayValue('My work in progress')).toBeInTheDocument()
  })

  it('does not render an AI draft during the second draft stage', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const session = sessionFor('second_draft')
    session.last_result = {
      request_id: 'request-1', session_id: session.id, stage: 'second_draft', mode: 'guided',
      stage_passed: true, completed: false, feedback: 'Revise your draft independently.',
      teaching_text: 'FULL AI REWRITTEN DRAFT', evaluation_verdict: 'pass', transfer_prompt: null,
      final_comparison: null, action: null, target_knowledge_node_id: null, retries: 0, blocked: false,
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okJson(session)))
    render(<App />)
    expect(await screen.findByRole('heading', { name: '二次重写', level: 1 })).toBeInTheDocument()
    expect(screen.queryByText('FULL AI REWRITTEN DRAFT')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Revision Checklist')).toBeInTheDocument()
  })

  it('offers the required sentence relation input in language refinement', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okJson(sessionFor('language_refinement'))))
    render(<App />)
    expect(await screen.findByLabelText('句子关系说明')).toBeInTheDocument()
  })

  it('shows a completed session as feedback without an unusable reply field', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const session = sessionFor('final_evaluation')
    session.completed = true
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okJson(session)))
    render(<App />)
    expect(await screen.findByRole('heading', { name: '最终评估', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('本次写作已完成，请查看两稿比较与学习反馈。')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '学习反馈' })).toBeInTheDocument()
    expect(screen.queryByLabelText('给导师的问题或说明（选填）')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /完成评估/ })).toBeDisabled()
  })

  it('reuses the same request ID when retrying an unchanged failed turn', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson(sessionFor('first_draft')))
      .mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValueOnce(okJson({}))
      .mockResolvedValueOnce(okJson(sessionFor('first_draft')))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByLabelText('作文内容')
    fireEvent.click(screen.getByRole('button', { name: /提交初稿/ }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: /提交初稿/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
    const first = JSON.parse(fetchMock.mock.calls[1][1].body as string)
    const retry = JSON.parse(fetchMock.mock.calls[2][1].body as string)
    expect(first.submission.request_id).toBe(retry.submission.request_id)
  })

  it('ignores a corrupt saved session and shows the empty state', () => {
    localStorage.setItem('awt.activeSession', '{invalid')
    render(<App />)
    expect(screen.getByLabelText('作文题目')).toBeInTheDocument()
  })

  it('shows validation errors from the API without losing the workspace', async () => {
    localStorage.setItem('awt.activeSession', JSON.stringify(saved))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson(sessionFor('first_draft')))
      .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail: [] }) } as Response)
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByLabelText('作文内容')
    fireEvent.click(screen.getByRole('button', { name: /提交初稿/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('输入未通过检查')
    expect(screen.getByLabelText('作文编辑器')).toBeInTheDocument()
  })
})
