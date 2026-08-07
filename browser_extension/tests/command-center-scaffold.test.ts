import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('CommandCenter extension scaffold', () => {
  it('uses the Browser-BC WXT foundation without debugger permission', () => {
    const config = readFileSync(resolve('wxt.config.ts'), 'utf8');
    expect(config).toContain("modules: ['@wxt-dev/module-react']");
    expect(config).not.toContain("'debugger'");
  });

  it('records the exact upstream source', () => {
    const upstream = readFileSync(resolve('UPSTREAM.md'), 'utf8');
    expect(upstream).toContain('https://github.com/Einsia/Browser-BC');
    expect(upstream).toContain('5afc6d4');
  });
});
