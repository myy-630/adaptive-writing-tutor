import type { Mode, Stage } from './types'

export type ComponentKey =
  | 'essayEditor' | 'promptCard' | 'teachingDialog' | 'grammarErrorCard'
  | 'grammarGraph' | 'microLessonCard' | 'practiceQuestion'
  | 'paragraphStructure' | 'contentExpansion' | 'revisionChecklist'
  | 'learningStatePanel'

export interface LayoutConfig {
  main: ComponentKey[]
  side: ComponentKey[]
  bottom: ComponentKey[]
}

const STAGE_LAYOUTS: Record<Stage, LayoutConfig> = {
  prompt_analysis: {
    main: ['promptCard'], side: ['learningStatePanel'], bottom: ['teachingDialog'],
  },
  first_draft: {
    main: ['essayEditor'], side: ['promptCard', 'learningStatePanel'], bottom: ['teachingDialog'],
  },
  grammar_revision: {
    main: ['essayEditor'],
    side: ['grammarErrorCard', 'grammarGraph', 'microLessonCard', 'practiceQuestion', 'learningStatePanel'],
    bottom: ['teachingDialog'],
  },
  structure_revision: {
    main: ['essayEditor'], side: ['paragraphStructure', 'learningStatePanel'], bottom: ['teachingDialog'],
  },
  content_expansion: {
    main: ['essayEditor'], side: ['contentExpansion', 'learningStatePanel'], bottom: ['teachingDialog'],
  },
  language_refinement: {
    main: ['essayEditor'], side: ['practiceQuestion', 'learningStatePanel'], bottom: ['teachingDialog'],
  },
  second_draft: {
    main: ['essayEditor'], side: ['revisionChecklist', 'learningStatePanel'], bottom: [],
  },
  final_evaluation: {
    main: ['essayEditor'], side: ['revisionChecklist', 'learningStatePanel'], bottom: ['teachingDialog'],
  },
}

export function layoutFor(stage: Stage, mode: Mode): LayoutConfig {
  if (mode === 'independent') {
    return { main: ['essayEditor'], side: [], bottom: [] }
  }
  return STAGE_LAYOUTS[stage]
}
