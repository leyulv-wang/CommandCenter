import { describe, expect, it, vi } from 'vitest';
import { connectRecordingTab } from '@/recording/tab-connection';

const activeMessage = {
  type: 'recording-state' as const,
  active: true,
  traceId: 'tr_local',
  allowedOrigins: ['http://127.0.0.1:8101'],
};

describe('recording tab connection', () => {
  it('uses the existing content-script receiver without reinjection', async () => {
    const sendMessage = vi.fn(async () => ({ ok: true }));
    const inject = vi.fn(async () => undefined);

    await expect(
      connectRecordingTab({
        tabId: 7,
        url: 'http://127.0.0.1:8101/',
        message: activeMessage,
        allowedOrigins: activeMessage.allowedOrigins,
        sendMessage,
        inject,
      }),
    ).resolves.toBe('messaged');
    expect(inject).not.toHaveBeenCalled();
  });

  it('injects the packaged observer when an allowed page has no receiver', async () => {
    const sendMessage = vi.fn(async () => {
      throw new Error('Receiving end does not exist');
    });
    const inject = vi.fn(async () => undefined);

    await expect(
      connectRecordingTab({
        tabId: 8,
        url: 'http://127.0.0.1:8101/tasks',
        message: activeMessage,
        allowedOrigins: activeMessage.allowedOrigins,
        sendMessage,
        inject,
      }),
    ).resolves.toBe('injected');
    expect(inject).toHaveBeenCalledWith(8);
  });

  it('never injects into a page outside the recording origin allowlist', async () => {
    const inject = vi.fn(async () => undefined);

    await expect(
      connectRecordingTab({
        tabId: 9,
        url: 'https://example.com/',
        message: activeMessage,
        allowedOrigins: activeMessage.allowedOrigins,
        sendMessage: vi.fn(async () => {
          throw new Error('Receiving end does not exist');
        }),
        inject,
      }),
    ).resolves.toBe('skipped');
    expect(inject).not.toHaveBeenCalled();
  });

  it('never injects while broadcasting a stopped state', async () => {
    const inject = vi.fn(async () => undefined);

    await expect(
      connectRecordingTab({
        tabId: 10,
        url: 'http://127.0.0.1:8101/',
        message: { ...activeMessage, active: false, traceId: null },
        allowedOrigins: activeMessage.allowedOrigins,
        sendMessage: vi.fn(async () => {
          throw new Error('Receiving end does not exist');
        }),
        inject,
      }),
    ).resolves.toBe('skipped');
    expect(inject).not.toHaveBeenCalled();
  });
});
