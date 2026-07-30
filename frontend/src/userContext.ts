export interface TestUser {
  id: 'u001' | 'u002'
  name: string
  role: string
}

export const TEST_USERS: Record<TestUser['id'], TestUser> = {
  u001: { id: 'u001', name: '普通员工', role: '采购申请' },
  u002: { id: 'u002', name: '采购审批人', role: '采购审批' },
}

export function resolveTestUser(search = window.location.search): TestUser {
  const candidate = new URLSearchParams(search).get('user')
  return candidate === 'u002' ? TEST_USERS.u002 : TEST_USERS.u001
}
