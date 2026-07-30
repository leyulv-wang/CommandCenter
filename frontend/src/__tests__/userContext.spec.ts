import { describe, expect, it } from 'vitest'

import { resolveTestUser } from '../userContext'


describe('resolveTestUser', () => {
  it('defaults to the applicant when the parameter is absent', () => {
    expect(resolveTestUser('').id).toBe('u001')
  })

  it('resolves the purchase approver', () => {
    expect(resolveTestUser('?user=u002')).toEqual({
      id: 'u002',
      name: '采购审批人',
      role: '采购审批',
    })
  })

  it('falls back for an unknown test user', () => {
    expect(resolveTestUser('?user=unknown').id).toBe('u001')
  })
})
