import type { ComponentType } from 'react'
import { BookOpen, CheckCircle2, CircleHelp, GitBranch, Lightbulb, MessageCircle, PenLine, Sparkles, Target } from 'lucide-react'
import type { FormState, SessionView } from './types'

export interface WorkspaceProps {
  session: SessionView
  draft: string
  setDraft: (value: string) => void
  form: FormState
  setForm: (value: FormState) => void
  busy: boolean
}

function Field({ label, value, onChange, multiline = false, placeholder = '' }: {
  label: string; value: string; onChange: (value: string) => void; multiline?: boolean; placeholder?: string
}) {
  return <label className="field"><span>{label}</span>{multiline
    ? <textarea value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} rows={3} />
    : <input value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />}</label>
}

function update(props: WorkspaceProps, key: keyof FormState, value: string | boolean) {
  props.setForm({ ...props.form, [key]: value })
}

export function EssayEditor({ session, draft, setDraft, busy }: WorkspaceProps) {
  const isFinal = session.stage === 'final_evaluation'
  return <section className="panel editor-panel" aria-label="作文编辑器">
    <div className="panel-heading"><span className="icon-box"><PenLine size={18} /></span><div><h2>{session.stage === 'prompt_analysis' ? '写下你的审题想法' : '我的作文'}</h2><p>{session.mode === 'independent' ? session.task.prompt : '直接修改你的文字，保留自己的表达。'}</p></div></div>
    <textarea className="essay-input" aria-label="作文内容" value={draft} onChange={event => setDraft(event.target.value)} disabled={busy || isFinal} placeholder={session.stage === 'prompt_analysis' ? '写下你对题目、写作对象和需要覆盖的要点的理解…' : '从这里开始写作…'} />
    <div className="editor-footer"><span>{draft.trim() ? draft.trim().split(/\s+/).length : 0} 词</span><span>内容会随每次提交保存</span></div>
  </section>
}

export function PromptCard(props: WorkspaceProps) {
  const { session, form } = props
  const analysis = session.stage === 'prompt_analysis'
  return <section className="panel" aria-label="审题卡">
    <div className="panel-heading"><span className="icon-box teal"><CircleHelp size={18} /></span><div><h2>写作任务</h2><p>先弄清要求，再动笔。</p></div></div>
    <p className="task-prompt">{session.task.prompt}</p>
    <div className="task-meta"><span>{session.task.genre}</span><span>{session.task.grade} 年级</span></div>
    {session.task.required_points.length > 0 && <div className="required-points"><strong>需要覆盖</strong>{session.task.required_points.map(point => <span key={point}>✓ {point}</span>)}</div>}
    {analysis && <div className="form-grid">
      <Field label="写给谁看" value={form.audience} onChange={value => update(props, 'audience', value)} />
      <Field label="写作目的" value={form.purpose} onChange={value => update(props, 'purpose', value)} />
      <Field label="文体" value={form.genre} onChange={value => update(props, 'genre', value)} />
      <Field label="必须写到的要点（逗号分隔）" value={form.requiredPoints} onChange={value => update(props, 'requiredPoints', value)} />
      <Field label="时态" value={form.tense} onChange={value => update(props, 'tense', value)} />
      <Field label="人称" value={form.person} onChange={value => update(props, 'person', value)} />
      <Field label="其他限制" value={form.constraints} onChange={value => update(props, 'constraints', value)} multiline />
    </div>}
  </section>
}

export function TeachingDialog({ session, form, ...props }: WorkspaceProps) {
  const result = session.last_result
  return <section className="panel teaching-panel" aria-label="教学对话区">
    <div className="panel-heading"><span className="icon-box violet"><MessageCircle size={18} /></span><div><h2>{session.completed ? '学习反馈' : '学习引导'}</h2><p>{session.completed ? 'Draft 1 与 Draft 2 的比较结果' : '根据本轮诊断给出的提示'}</p></div></div>
    <div className="teaching-bubble">{(result?.teaching_text || result?.feedback || '提交后，这里会出现与你当前写作阶段相关的引导。').replace(/\*\*/g, '')}</div>
    {result?.blocked && <p className="inline-warning">本轮教学未通过质量检查，请先根据反馈调整。</p>}
    {!session.completed && <Field label="给导师的问题或说明（选填）" value={form.message} onChange={value => props.setForm({ ...form, message: value })} placeholder="我想重点练习…" />}
  </section>
}

export function GrammarErrorCard({ session }: WorkspaceProps) {
  return <section className="panel" aria-label="语法错误卡">
    <div className="panel-heading"><span className="icon-box coral"><Target size={18} /></span><div><h2>语法定位</h2><p>先自己观察，再尝试修改。</p></div></div>
    {session.grammar_hints.length === 0 ? <p className="muted">本轮没有需要展示的语法定位。</p> : <div className="stack">{session.grammar_hints.map((hint, index) => <div className="error-item" key={`${hint.start_offset}-${index}`}><div className="error-top"><span>发现 {index + 1}</span><span>{hint.category}</span></div><strong>“{hint.original_expression}”</strong><small>位置 {hint.start_offset + 1}–{hint.end_offset} · {hint.knowledge_node_id}</small></div>)}</div>}
  </section>
}

export function GrammarKnowledgeGraph({ session }: WorkspaceProps) {
  return <section className="panel" aria-label="语法知识图谱">
    <div className="panel-heading"><span className="icon-box teal"><GitBranch size={18} /></span><div><h2>知识路径</h2><p>理解当前知识点与前置基础</p></div></div>
    {session.knowledge_paths.length === 0 ? <p className="muted">暂无关联的知识路径。</p> : session.knowledge_paths.map(path => <div className="knowledge-path" key={path.target.node.id}>
      <div className="knowledge-node target"><strong>{path.target.node.label}</strong><span>{path.target.mastery === null ? '尚无掌握记录' : `掌握度 ${Math.round(path.target.mastery * 100)}%`}</span></div>
      {path.learning_path ? <ol className="learning-path-steps" aria-label="学习步骤">{path.learning_path.steps.map(step => <li key={step.node.id} className={`learning-step ${step.status}`}><strong>{step.node.label}</strong><span>{step.purpose === 'review' ? '长期复习 · ' : ''}{step.status === 'mastered' ? '已掌握' : step.status === 'blocked' ? '等待前置知识' : step.mastery_state === 'verify' ? '待验证' : '待学习'}{path.learning_path?.next_node_id === step.node.id ? ' · 当前步骤' : ''}</span></li>)}</ol>
        : path.prerequisites.length > 0 && <div className="knowledge-pre"><span className="path-line">↑ 前置知识</span>{path.prerequisites.map(node => <div className="knowledge-node" key={node.node.id}><strong>{node.node.label}</strong><span>{node.mastery === null ? '尚无记录' : `${Math.round(node.mastery * 100)}%`}</span></div>)}</div>}
    </div>)}
  </section>
}

export function MicroLessonCard({ session }: WorkspaceProps) {
  const target = session.knowledge_paths[0]?.target
  return <section className="panel" aria-label="微课卡">
    <div className="panel-heading"><span className="icon-box amber"><BookOpen size={18} /></span><div><h2>知识小讲堂</h2><p>看完后回到自己的句子里尝试</p></div></div>
    {target ? <><strong className="lesson-title">{target.node.label}</strong><p>{target.node.description}</p></> : <p className="muted">当前没有需要补充的语法微课。</p>}
  </section>
}

export function PracticeQuestion(props: WorkspaceProps) {
  const prompt = props.session.last_result?.transfer_prompt
  const languageStage = props.session.stage === 'language_refinement'
  return <section className="panel" aria-label="练习题">
    <div className="panel-heading"><span className="icon-box amber"><Lightbulb size={18} /></span><div><h2>迁移练习</h2><p>把刚学到的方法用于新句子</p></div></div>
    {languageStage ? <><p className="practice-prompt">选一个句子，说明它和前后句的关系，再修改自己的表达。</p><Field label="句子关系说明" value={props.form.relationExplanation} onChange={value => update(props, 'relationExplanation', value)} multiline /></>
      : prompt ? <><p className="practice-prompt">{prompt}</p><Field label="我的回答" value={props.form.transferResponse} onChange={value => update(props, 'transferResponse', value)} multiline /></>
      : <p className="muted">完成本轮修改后会出现练习。</p>}
  </section>
}

export function ParagraphStructure(props: WorkspaceProps) {
  return <section className="panel" aria-label="段落结构图">
    <div className="panel-heading"><span className="icon-box teal"><GitBranch size={18} /></span><div><h2>段落结构</h2><p>检查开头、主体与结尾的衔接</p></div></div>
    <div className="structure-flow"><span>开头</span><i /> <span>主体</span><i /> <span>结尾</span></div>
    <div className="stack"><Field label="开头承担什么作用" value={props.form.opening} onChange={value => update(props, 'opening', value)} multiline /><Field label="主体如何展开" value={props.form.body} onChange={value => update(props, 'body', value)} multiline /><Field label="结尾如何收束" value={props.form.conclusion} onChange={value => update(props, 'conclusion', value)} multiline /></div>
  </section>
}

export function ContentExpansion(props: WorkspaceProps) {
  const fields: { key: keyof FormState; label: string }[] = [
    { key: 'viewpoint', label: '观点' }, { key: 'reason', label: '原因' },
    { key: 'example', label: '例子' }, { key: 'detail', label: '细节' },
    { key: 'resultOrFeeling', label: '结果或感受' },
  ]
  return <section className="panel" aria-label="内容展开卡">
    <div className="panel-heading"><span className="icon-box violet"><Sparkles size={18} /></span><div><h2>展开一个想法</h2><p>让段落更具体、更有说服力</p></div></div>
    <div className="stack">{fields.map(({ key, label }, index) => <div className="expansion-row" key={key}><span className="step-number">{index + 1}</span><Field label={label} value={String(props.form[key])} onChange={value => update(props, key, value)} multiline /></div>)}</div>
  </section>
}

export function RevisionChecklist({ session, form, ...props }: WorkspaceProps) {
  const items = ['我覆盖了题目要求的所有要点', '每段都有清楚的作用', '我检查了语法与用词', '我加入了自己的例子和细节']
  return <section className="panel" aria-label="Revision Checklist">
    <div className="panel-heading"><span className="icon-box teal"><CheckCircle2 size={18} /></span><div><h2>修改清单</h2><p>用自己的判断完成最后一轮</p></div></div>
    <ul className="checklist">{items.map(item => <li key={item}><span>□</span>{item}</li>)}</ul>
    {session.stage === 'second_draft' && <label className="checkbox-field"><input type="checkbox" checked={form.independentRevision} onChange={event => props.setForm({ ...form, independentRevision: event.target.checked })} />这次修改由我独立完成</label>}
    {session.last_result?.final_comparison && <div className="comparison"><strong>修改结果</strong><p>仍需关注的语法问题：{session.last_result.final_comparison.remaining_count}</p></div>}
  </section>
}

export function LearningStatePanel({ session }: WorkspaceProps) {
  const state = session.student_state
  const labels: Record<string, string> = { content: '内容', grammar: '语法', prompt_analysis: '审题', sentence_expression: '句子表达', structure: '结构' }
  const evidenceCount = state.abilities.reduce((sum, item) => sum + item.evidence_count, 0)
  return <section className="panel" aria-label="学习状态面板">
    <div className="panel-heading"><span className="icon-box violet"><Target size={18} /></span><div><h2>学习状态</h2><p>Student State 当前估计</p></div></div>
    <p className="goal">目标：{state.student.learning_goal}</p>
    <div className="stack">{state.abilities.map(ability => <div className="mastery-row" key={ability.dimension}><div><span>{labels[ability.dimension] ?? ability.dimension}</span><strong>{Math.round(ability.rubric_score * 100)}%</strong></div><div className="meter"><span style={{ width: `${Math.round(ability.rubric_score * 100)}%` }} /></div></div>)}</div>
    <small className="state-footnote">{evidenceCount ? `依据 ${evidenceCount} 条过程性量表证据更新，仅反映已检查的写作特征` : '尚无量表证据，当前为初始估计'}</small>
  </section>
}

export const COMPONENT_REGISTRY = {
  essayEditor: EssayEditor,
  promptCard: PromptCard,
  teachingDialog: TeachingDialog,
  grammarErrorCard: GrammarErrorCard,
  grammarGraph: GrammarKnowledgeGraph,
  microLessonCard: MicroLessonCard,
  practiceQuestion: PracticeQuestion,
  paragraphStructure: ParagraphStructure,
  contentExpansion: ContentExpansion,
  revisionChecklist: RevisionChecklist,
  learningStatePanel: LearningStatePanel,
} satisfies Record<string, ComponentType<WorkspaceProps>>
