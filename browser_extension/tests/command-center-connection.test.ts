import { describe, expect, it, vi } from 'vitest';
import { SystemConnectionCoordinator } from '@/command-center/connection';
import { DEFAULT_COMMAND_CENTER_PROFILE } from '@/command-center/config';

function setup(enabled = false) {
  let consent = enabled;
  const consentStore = {
    get: vi.fn(async () => consent),
    set: vi.fn(async (_systemCode: string, value: boolean) => {
      consent = value;
    }),
  };
  const client = {
    beginSystemConnection: vi.fn(async () => ({ connectionToken: 'connection-token' })),
    putSystemCredential: vi.fn(async () => ({ status: 'connected' })),
    getSystemConnection: vi.fn(async () => ({ status: 'disconnected' })),
    disconnectSystem: vi.fn(async () => ({ status: 'disconnected' })),
    verifyLatestSystemSkill: vi.fn(async () => ({ status: 'verified_candidate' })),
  };
  return {
    consentStore,
    client,
    coordinator: new SystemConnectionCoordinator({ consentStore, client }),
  };
}

describe('SystemConnectionCoordinator', () => {
  it('syncs only the configured header after explicit consent', async () => {
    const { coordinator, client, consentStore } = setup();
    await coordinator.enable(DEFAULT_COMMAND_CENTER_PROFILE);
    await coordinator.observeRequest(DEFAULT_COMMAND_CENTER_PROFILE, {
      url: 'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list',
      requestHeaders: [
        { name: 'Accept', value: 'application/json' },
        { name: 'x-access-token', value: 'private-mes-token' },
      ],
    });

    expect(consentStore.set).toHaveBeenCalledWith('yifeng_mes', true);
    expect(client.putSystemCredential).toHaveBeenCalledWith(
      'yifeng_mes',
      'connection-token',
      'X-Access-Token',
      'private-mes-token',
    );
    expect(client.verifyLatestSystemSkill).toHaveBeenCalledWith('yifeng_mes');
    expect(JSON.stringify(consentStore)).not.toContain('private-mes-token');
  });

  it('ignores disabled, wrong-origin, and unrelated headers', async () => {
    const { coordinator, client } = setup(false);
    const requestHeaders = [{ name: 'X-Access-Token', value: 'private-mes-token' }];

    await coordinator.observeRequest(DEFAULT_COMMAND_CENTER_PROFILE, {
      url: 'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list',
      requestHeaders,
    });
    await coordinator.enable(DEFAULT_COMMAND_CENTER_PROFILE);
    await coordinator.observeRequest(DEFAULT_COMMAND_CENTER_PROFILE, {
      url: 'http://attacker.test/',
      requestHeaders,
    });
    await coordinator.observeRequest(DEFAULT_COMMAND_CENTER_PROFILE, {
      url: 'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list',
      requestHeaders: [{ name: 'Authorization', value: 'private-mes-token' }],
    });

    expect(client.putSystemCredential).not.toHaveBeenCalled();
  });

  it('disconnects remotely and clears consent', async () => {
    const { coordinator, client, consentStore } = setup(true);

    await coordinator.disable(DEFAULT_COMMAND_CENTER_PROFILE);

    expect(consentStore.set).toHaveBeenCalledWith('yifeng_mes', false);
    expect(client.disconnectSystem).toHaveBeenCalledWith('yifeng_mes');
  });
});
