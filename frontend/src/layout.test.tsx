import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { COMPONENT_REGISTRY } from './components'
import { layoutFor } from './layout'
import { EMPTY_FORM, STAGES } from './types'
import { sessionFor } from './testFixtures'

describe('deterministic workspace layout', () => {
  it('uses a distinct component combination for each stage', () => {
    const signatures = STAGES.map(stage => JSON.stringify(layoutFor(stage, 'guided')))
    expect(new Set(signatures).size).toBe(STAGES.length)
  })

  it('shows KG in grammar, structure in structure, and expansion in content', () => {
    expect(layoutFor('grammar_revision', 'guided').side).toEqual(expect.arrayContaining(['grammarErrorCard', 'grammarGraph', 'microLessonCard', 'practiceQuestion']))
    expect(layoutFor('structure_revision', 'guided').side).toContain('paragraphStructure')
    expect(layoutFor('content_expansion', 'guided').side).toContain('contentExpansion')
  })

  it.each(STAGES)('independent mode only shows the editor in %s', stage => {
    expect(layoutFor(stage, 'independent')).toEqual({ main: ['essayEditor'], side: [], bottom: [] })
  })

  it('hides teaching and full AI draft during rewrite', () => {
    const layout = layoutFor('second_draft', 'guided')
    expect(layout.bottom).toEqual([])
    expect([...layout.main, ...layout.side]).not.toContain('teachingDialog')
    expect([...layout.main, ...layout.side]).toContain('revisionChecklist')
  })

  it('registers every referenced component and renders backend KG state', () => {
    for (const stage of STAGES) {
      const layout = layoutFor(stage, 'guided')
      for (const key of [...layout.main, ...layout.side, ...layout.bottom]) expect(COMPONENT_REGISTRY[key]).toBeTypeOf('function')
    }
    const Graph = COMPONENT_REGISTRY.grammarGraph
    render(<Graph session={sessionFor('grammar_revision')} draft="" setDraft={vi.fn()} form={EMPTY_FORM} setForm={vi.fn()} busy={false} />)
    expect(screen.getByText('主谓一致')).toBeInTheDocument()
    expect(screen.getByText('掌握度 45%')).toBeInTheDocument()
  })

  it('does not expose corrected expressions in the grammar card', () => {
    const Card = COMPONENT_REGISTRY.grammarErrorCard
    render(<Card session={sessionFor('grammar_revision')} draft="" setDraft={vi.fn()} form={EMPTY_FORM} setForm={vi.fn()} busy={false} />)
    expect(screen.getByText('“has”')).toBeInTheDocument()
    expect(screen.queryByText('have')).not.toBeInTheDocument()
  })
})
