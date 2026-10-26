import { describe, expect, it } from 'vitest'
import { buildSubmission } from './api'
import { EMPTY_FORM } from './types'

describe('stage submissions', () => {
  it('omits guided scaffolds in independent mode', () => {
    const payload = buildSubmission('structure_revision', 'independent', 'My revised draft', EMPTY_FORM)
    expect(payload).toMatchObject({ kind: 'response', text: 'My revised draft' })
    expect(payload.structure_plan).toBeUndefined()
  })

  it('records an independent rewrite without a hidden checkbox', () => {
    expect(buildSubmission('second_draft', 'independent', 'My second draft', EMPTY_FORM).independent_revision).toBe(true)
  })

  it('uses typed prompt analysis for guided mode and free text for independent mode', () => {
    const form = { ...EMPTY_FORM, genre: 'narrative', requiredPoints: 'event, feeling' }
    expect(buildSubmission('prompt_analysis', 'guided', '', form).prompt_analysis?.required_points).toEqual(['event', 'feeling'])
    expect(buildSubmission('prompt_analysis', 'independent', 'narrative event feeling', form).prompt_analysis).toBeUndefined()
  })

  it('uses the finalization endpoint only at final evaluation', () => {
    expect(buildSubmission('final_evaluation', 'guided', '', EMPTY_FORM)).toEqual({ kind: 'finalize' })
  })
})
