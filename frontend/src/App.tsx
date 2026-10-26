import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Feather, LoaderCircle, RotateCcw, Sparkles } from 'lucide-react'
import { buildSubmission, createWorkspace, getSession, submitTurn } from './api'
import { COMPONENT_REGISTRY } from './components'
import type { WorkspaceProps } from './components'
import { layoutFor } from './layout'
import { EMPTY_FORM, MODE_LABELS, STAGES, STAGE_LABELS } from './types'
import type { ComponentKey } from './layout'
import type { FormState, SessionView, Stage } from './types'
import './styles.css'

const STORAGE_KEY = 'awt.activeSession'
type SavedSession = { sessionId: string; studentId: string }

function readSaved(): SavedSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as SavedSession
    return value.sessionId && value.studentId ? value : null
  } catch {
    return null
  }
}

function WorkspaceSection({ keys, props }: { keys: ComponentKey[]; props: WorkspaceProps }) {
  return <>{keys.map(key => {
    const Component = COMPONENT_REGISTRY[key]
    return <Component key={key} {...props} />
  })}</>
}

function Welcome({ onCreate, busy, error }: {
  onCreate: (value: { grade: number; learningGoal: string; prompt: string; genre: string; requiredPoints: string[] }) => Promise<void>
  busy: boolean
  error: string | null
}) {
  const [grade, setGrade] = useState(8)
  const [learningGoal, setLearningGoal] = useState('提升英语写作表达')
  const [prompt, setPrompt] = useState('')
  const [genre, setGenre] = useState('narrative')
  const [points, setPoints] = useState('')
  return <div className="welcome-wrap"><div className="welcome-card">
    <div className="welcome-mark"><Feather size={28} /></div>
    <span className="eyebrow">ADAPTIVE WRITING TUTOR</span>
    <h1>让每一篇作文，<br /><em>成为一次成长。</em></h1>
    <p className="welcome-description">从读懂题目到独立重写，按你的学习状态一步步推进。</p>
    <form onSubmit={event => { event.preventDefault(); void onCreate({ grade, learningGoal, prompt, genre, requiredPoints: points.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }) }}>
      <div className="welcome-grid"><label className="field"><span>年级</span><input type="number" min="7" max="12" value={grade} onChange={event => setGrade(Number(event.target.value))} required /></label>
      <label className="field"><span>文体</span><select value={genre} onChange={event => setGenre(event.target.value)}><option value="narrative">记叙文</option><option value="argumentative">议论文</option><option value="expository">说明文</option><option value="letter">书信</option></select></label></div>
      <label className="field"><span>学习目标</span><input value={learningGoal} onChange={event => setLearningGoal(event.target.value)} required /></label>
      <label className="field"><span>作文题目</span><textarea value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="输入老师布置的英文作文题目…" rows={4} required /></label>
      <label className="field"><span>必写要点（逗号分隔）</span><input value={points} onChange={event => setPoints(event.target.value)} placeholder="例如：经历，原因，感受" /></label>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <button className="primary-button welcome-submit" type="submit" disabled={busy || !prompt.trim()}>{busy ? <><LoaderCircle className="spin" size={18} /> 正在创建…</> : <>开始写作 <ArrowRight size={18} /></>}</button>
    </form>
  </div><div className="welcome-aside"><span className="aside-orb"><Sparkles size={30} /></span><h2>你的写作旅程</h2><div className="journey-list"><p><span>01</span> 理解题目与目标</p><p><span>02</span> 写出属于自己的初稿</p><p><span>03</span> 逐步修改语法、结构与内容</p><p><span>04</span> 独立完成二次重写</p></div></div></div>
}

export default function App() {
  const [saved, setSaved] = useState<SavedSession | null>(() => readSaved())
  const [session, setSession] = useState<SessionView | null>(null)
  const [loading, setLoading] = useState(Boolean(saved))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const pendingTurn = useRef<{ fingerprint: string; requestId: string } | null>(null)

  useEffect(() => {
    if (!saved) return
    let active = true
    getSession(saved.sessionId, saved.studentId).then(value => {
      if (!active) return
      setSession(value)
      setDraft(value.current_draft ?? '')
      setForm(previous => ({ ...previous, genre: value.task.genre, requiredPoints: value.task.required_points.join(', ') }))
      setError(null)
    }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '工作区加载失败。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [saved])

  async function create(input: Parameters<typeof createWorkspace>[0]) {
    setBusy(true)
    setError(null)
    try {
      const value = await createWorkspace(input)
      const ids = { sessionId: value.sessionId, studentId: value.studentId }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
      setLoading(true)
      setSaved(ids)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建工作区失败。')
    } finally {
      setBusy(false)
    }
  }

  async function send() {
    if (!session || !saved) return
    setBusy(true)
    setError(null)
    try {
      const submission = buildSubmission(session.stage, session.mode, draft, form)
      const fingerprint = JSON.stringify({ stage: session.stage, mode: session.mode, submission })
      if (pendingTurn.current?.fingerprint !== fingerprint) {
        pendingTurn.current = { fingerprint, requestId: crypto.randomUUID() }
      }
      await submitTurn(saved.sessionId, saved.studentId, submission, pendingTurn.current.requestId)
      const value = await getSession(saved.sessionId, saved.studentId)
      setSession(value)
      setDraft(value.current_draft ?? '')
      if (value.stage !== session.stage) setForm(previous => ({ ...EMPTY_FORM, genre: value.task.genre, requiredPoints: value.task.required_points.join(', '), message: previous.message }))
      pendingTurn.current = null
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提交失败，请重试。')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <main className="loading-screen" role="status"><LoaderCircle className="spin" size={30} /><span>正在恢复你的写作工作区…</span></main>
  if (!session) {
    if (saved) return <main className="load-error"><Feather size={30} /><h1>暂时无法恢复工作区</h1><p role="alert">{error}</p><button className="primary-button" onClick={() => { setLoading(true); setSaved({ ...saved }) }}><RotateCcw size={16} /> 重试连接</button></main>
    return <Welcome onCreate={create} busy={busy} error={error} />
  }

  const layout = layoutFor(session.stage, session.mode)
  const componentProps: WorkspaceProps = { session, draft, setDraft, form, setForm, busy }
  const stageIndex = STAGES.indexOf(session.stage)
  const stageAction: Record<Stage, string> = {
    prompt_analysis: '提交审题', first_draft: '提交初稿', grammar_revision: '提交语法修改',
    structure_revision: '提交结构修改', content_expansion: '提交内容补充',
    language_refinement: '提交语言优化', second_draft: '完成二次重写', final_evaluation: '完成评估',
  }
  return <div className={`app-shell mode-${session.mode}`}>
    <header className="topbar"><div className="brand"><span className="brand-icon"><Feather size={20} /></span><span>Writing <strong>Tutor</strong></span></div><div className="header-right"><span className="mode-pill">{MODE_LABELS[session.mode]}</span><span className="student-pill">{session.student_state.student.grade} 年级</span></div></header>
    <div className="workspace-wrap"><aside className="stage-sidebar"><div className="sidebar-label">写作旅程</div><nav aria-label="写作阶段">{STAGES.map((stage, index) => <div className={`stage-item ${index === stageIndex ? 'active' : ''} ${index < stageIndex ? 'done' : ''}`} key={stage}><span className="stage-dot">{index < stageIndex ? '✓' : String(index + 1).padStart(2, '0')}</span><span>{STAGE_LABELS[stage]}</span></div>)}</nav><div className="sidebar-footer">一步一步，写出自己的表达。</div></aside>
      <main className="workspace-main"><div className="workspace-heading"><div><span className="eyebrow">STAGE {String(stageIndex + 1).padStart(2, '0')} / 08</span><h1>{STAGE_LABELS[session.stage]}</h1><p>{session.completed ? '本次写作已完成，请查看两稿比较与学习反馈。' : session.mode === 'independent' ? '独立完成这一阶段，按自己的节奏思考与修改。' : '查看本阶段任务，完成后提交进入下一步。'}</p></div><span className="progress-label">{Math.round(((stageIndex + (session.completed ? 1 : 0)) / STAGES.length) * 100)}% 完成</span></div>
        <div className="workspace-grid"><div className="main-column"><WorkspaceSection keys={layout.main} props={componentProps} /><WorkspaceSection keys={layout.bottom} props={componentProps} /></div>{layout.side.length > 0 && <div className="side-column"><WorkspaceSection keys={layout.side} props={componentProps} /></div>}</div>
        {error && <p className="error-banner workspace-error" role="alert">{error}</p>}
        {session.last_result?.feedback && <p className="feedback-strip" role="status">{session.last_result.feedback}</p>}
        <div className="action-bar"><span>{session.completed ? '本次写作已完成' : '你的文字由你决定，提交后会保存当前版本。'}</span><button className="primary-button" onClick={() => void send()} disabled={busy || session.completed}>{busy ? <><LoaderCircle className="spin" size={17} /> 提交中…</> : <>{stageAction[session.stage]} <ArrowRight size={17} /></>}</button></div>
      </main></div>
  </div>
}
