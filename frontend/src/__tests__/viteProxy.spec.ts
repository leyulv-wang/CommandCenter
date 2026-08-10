import { describe, expect, it } from 'vitest'
import config from '../../vite.config.ts?raw'

describe('Vite development proxy', () => {
  it('routes every CommandCenter API prefix used by the test console', () => {
    expect(config).toContain("'/recordings':")
    expect(config).toContain("'/task-runs':")
    expect(config).toContain("'/system-connections':")
  })
})
