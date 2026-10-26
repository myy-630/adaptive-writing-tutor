export const STAGES = [
  'prompt_analysis',
  'first_draft',
  'grammar_revision',
  'structure_revision',
  'content_expansion',
  'language_refinement',
  'second_draft',
  'final_evaluation',
] as const

export type Stage = (typeof STAGES)[number]
export type Mode = 'guided' | 'semi_guided' | 'independent'

export const STAGE_LABELS: Record<Stage, string> = {
  prompt_analysis: '审题',
  first_draft: '初稿',
  grammar_revision: '语法修改',
  structure_revision: '结构修改',
  content_expansion: '内容补充',
  language_refinement: '语言优化',
  second_draft: '二次重写',
  final_evaluation: '最终评估',
}

export const MODE_LABELS: Record<Mode, string> = {
  guided: '强引导',
  semi_guided: '半引导',
  independent: '独立写作',
}

export interface Task {
  id: string
  prompt: string
  genre: string
  grade: number
  required_points: string[]
}

export interface AbilityState {
  dimension: string
  rubric_score: number
  confidence: number
  evidence_count: number
}

export interface KnowledgeState {
  node_id: string
  mastery: number
  confidence: number
  evidence_count: number
}

export interface StudentState {
  student: { id: string; grade: number; learning_goal: string }
  abilities: AbilityState[]
  knowledge: KnowledgeState[]
  prompt_dependency: {
    evidence_count: number
    average_hint_level: number
    independent_revision_count: number
    transfer_success_count: number
  }
}

export interface GrammarHint {
  start_offset: number
  end_offset: number
  original_expression: string
  category: string
  knowledge_node_id: string
}

export interface NodeOverlay {
  node: { id: string; label: string; description: string }
  mastery: number | null
  confidence: number | null
  evidence_count: number
}

export interface KnowledgePath {
  target: NodeOverlay
  prerequisites: NodeOverlay[]
  learning_path?: {
    goal_node_id: string
    review_node_ids: string[]
    next_node_id: string | null
    completed: boolean
    steps: {
      node: { id: string; label: string }
      status: 'mastered' | 'ready' | 'blocked'
      mastery_state: 'learn' | 'verify' | 'mastered'
      purpose: 'current' | 'review'
      blocked_by_node_ids: string[]
    }[]
  } | null
}

export interface DraftComparison {
  resolved: Record<string, number>
  repeated: Record<string, number>
  new: Record<string, number>
  remaining_count: number
}

export interface WorkflowResult {
  request_id: string
  session_id: string
  stage: Stage
  mode: Mode
  stage_passed: boolean
  completed: boolean
  feedback: string
  teaching_text: string | null
  evaluation_verdict: 'pass' | 'directive' | 'block' | null
  transfer_prompt: string | null
  final_comparison: DraftComparison | null
  action: string | null
  target_knowledge_node_id: string | null
  retries: number
  blocked: boolean
}

export interface SessionView {
  id: string
  student_id: string
  task: Task
  stage: Stage
  mode: Mode
  current_draft: string | null
  completed: boolean
  student_state: StudentState
  last_result: WorkflowResult | null
  grammar_hints: GrammarHint[]
  knowledge_paths: KnowledgePath[]
}

export interface FormState {
  audience: string
  purpose: string
  genre: string
  requiredPoints: string
  tense: string
  person: string
  constraints: string
  opening: string
  body: string
  conclusion: string
  viewpoint: string
  reason: string
  example: string
  detail: string
  resultOrFeeling: string
  relationExplanation: string
  transferResponse: string
  independentRevision: boolean
  message: string
}

export const EMPTY_FORM: FormState = {
  audience: '', purpose: '', genre: '', requiredPoints: '', tense: '', person: '', constraints: '',
  opening: '', body: '', conclusion: '', viewpoint: '', reason: '', example: '', detail: '',
  resultOrFeeling: '', relationExplanation: '', transferResponse: '', independentRevision: false,
  message: '',
}
