import type { SessionView, Stage } from './types'

export function sessionFor(stage: Stage, mode: SessionView['mode'] = 'guided'): SessionView {
  return {
    id: 'session-1', student_id: 'student-1',
    task: { id: 'task-1', prompt: 'Write about a memorable day.', genre: 'narrative', grade: 8, required_points: ['event', 'feeling'] },
    stage, mode, current_draft: 'I has a memorable day.', completed: false,
    student_state: {
      student: { id: 'student-1', grade: 8, learning_goal: 'Write clearly' },
      abilities: [{ dimension: 'grammar', rubric_score: 0.65, confidence: 0.8, evidence_count: 2 }],
      knowledge: [],
      prompt_dependency: { evidence_count: 0, average_hint_level: 0, independent_revision_count: 0, transfer_success_count: 0 },
    },
    last_result: null,
    grammar_hints: [{ start_offset: 2, end_offset: 5, original_expression: 'has', category: 'subject_verb_agreement', knowledge_node_id: 'grammar.sva' }],
    knowledge_paths: [{ target: { node: { id: 'grammar.sva', label: '主谓一致', description: 'Match the verb to the subject.' }, mastery: 0.45, confidence: 0.7, evidence_count: 2 }, prerequisites: [] }],
  }
}
