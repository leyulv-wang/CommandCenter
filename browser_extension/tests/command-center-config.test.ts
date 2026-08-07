import { describe, expect, it } from 'vitest';
import {
  DEFAULT_COMMAND_CENTER_PROFILE,
  profileForUrl,
  type CommandCenterProfile,
} from '@/command-center/config';

describe('CommandCenter profiles', () => {
  it('selects the configured MES profile by exact origin', () => {
    expect(
      profileForUrl('http://yifeng.dtsum.com/purchase/apply', [
        DEFAULT_COMMAND_CENTER_PROFILE,
      ])?.systemCode,
    ).toBe('yifeng_mes');
  });

  it('does not match suffix or credential-confusion origins', () => {
    expect(
      profileForUrl('http://yifeng.dtsum.com.attacker.test/', [
        DEFAULT_COMMAND_CENTER_PROFILE,
      ]),
    ).toBeNull();
    expect(
      profileForUrl('http://yifeng.dtsum.com@attacker.test/', [
        DEFAULT_COMMAND_CENTER_PROFILE,
      ]),
    ).toBeNull();
  });

  it('supports another system without changing the recorder', () => {
    const profile: CommandCenterProfile = {
      id: 'test',
      displayName: '测试系统',
      origins: ['https://test.example'],
      systemCode: 'test_system',
      commandCenterUrl: 'http://127.0.0.1:8000',
      captureNetworkBodies: true,
    };

    expect(profileForUrl('https://test.example/form', [profile])).toEqual(
      profile,
    );
  });

  it('returns null for invalid URLs', () => {
    expect(profileForUrl('not a URL', [DEFAULT_COMMAND_CENTER_PROFILE])).toBeNull();
  });
});
