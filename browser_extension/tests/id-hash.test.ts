import { afterEach, describe, expect, it, vi } from 'vitest';
import { createId } from '@/shared/id';
import { sha256Hex } from '@/shared/hash';

describe('shared utilities', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('creates prefixed IDs', () => {
    expect(createId('tr_')).toMatch(/^tr_[a-z0-9]+_[a-f0-9]{24}$/);
  });

  it('hashes strings as sha256 hex', async () => {
    await expect(sha256Hex('hello')).resolves.toBe(
      '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    );
  });

  it('hashes with the same result when Web Crypto is unavailable', async () => {
    vi.stubGlobal('crypto', {});

    await expect(sha256Hex('abc')).resolves.toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    );
  });
});
