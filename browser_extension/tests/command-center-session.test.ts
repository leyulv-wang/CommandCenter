import { describe, expect, it, vi } from 'vitest';
import { createCommandCenterSessionCoordinator } from '@/command-center/session';
import { DEFAULT_COMMAND_CENTER_PROFILE } from '@/command-center/config';
import { LOCAL_PURCHASE_COMMAND_CENTER_PROFILE } from '@/command-center/config';
import type { RecordingRow } from '@/shared/types';

vi.mock('wxt/browser', () => ({
  browser: {
    alarms: { create: vi.fn() },
    runtime: { getURL: vi.fn() },
    tabs: { create: vi.fn() },
  },
}));

const recordingId = '123e4567-e89b-42d3-a456-426614174000';

function row(status: RecordingRow['status']): RecordingRow {
  return {
    trace_id: 'tr_local',
    status,
    envelope: {
      schema_version: 'journey_trace_v1',
      trace_id: 'tr_local',
      recording_mode: 'research_free_form',
      started_at: '2026-08-07T01:00:00.000Z',
      tags: [],
      browser: { extension_version: '1', user_agent: 'test', timezone: 'UTC' },
      summary: {
        domains: [],
        duration_ms: 0,
        event_counts: {},
        screenshot_count: 0,
        video_chunk_count: 0,
      },
    },
    command_center: {
      base_url: 'http://127.0.0.1:8000',
      system_code: 'yifeng_mes',
      recording_id: recordingId,
      recording_token: 'single-use-token',
      allowed_origins: ['http://yifeng.dtsum.com'],
      fingerprint_key: 'local-fingerprint-key',
    },
    created_at: 1,
    updated_at: 1,
  };
}

describe('CommandCenter session coordinator', () => {
  it('creates the remote session before starting local capture', async () => {
    const calls: string[] = [];
    const client = {
      createRecording: vi.fn(async () => {
        calls.push('remote:create');
        return { recordingId };
      }),
      start: vi.fn(async () => {
        calls.push('remote:start');
        return { recordingToken: 'single-use-token' };
      }),
      uploadEvents: vi.fn(),
      stop: vi.fn(),
      abort: vi.fn(),
      getStatus: vi.fn(),
    };
    const startLocal = vi.fn(async () => {
      calls.push('local:start');
      return row('recording');
    });
    const coordinator = createCommandCenterSessionCoordinator({
      clientFactory: () => client,
      startLocal,
      stopLocal: vi.fn(),
      uploadLocal: vi.fn(),
      getLocal: vi.fn(),
    });

    const started = await coordinator.start({
      objective: '查询采购申请',
      profile: DEFAULT_COMMAND_CENTER_PROFILE,
    });

    expect(calls).toEqual(['remote:create', 'remote:start', 'local:start']);
    expect(startLocal).toHaveBeenCalledWith({
      label: '查询采购申请',
      captureOverrides: { networkBodies: true },
      commandCenter: {
        base_url: 'http://127.0.0.1:8000',
        system_code: 'yifeng_mes',
        recording_kind: 'single_system',
        system_codes: ['yifeng_mes'],
        recording_id: recordingId,
        recording_token: 'single-use-token',
        allowed_origins: ['http://yifeng.dtsum.com'],
        origin_system_codes: { 'http://yifeng.dtsum.com': 'yifeng_mes' },
        fingerprint_key: expect.any(String),
      },
    });
    expect(started.status).toBe('recording');
  });

  it('creates one joint session from two ordered system profiles', async () => {
    const client = {
      createRecording: vi.fn(async () => ({ recordingId })),
      start: vi.fn(async () => ({ recordingToken: 'joint-token' })),
      uploadEvents: vi.fn(), stop: vi.fn(), abort: vi.fn(), getStatus: vi.fn(),
    };
    const startLocal = vi.fn(async () => row('recording'));
    const coordinator = createCommandCenterSessionCoordinator({
      clientFactory: () => client,
      startLocal,
      stopLocal: vi.fn(), uploadLocal: vi.fn(), getLocal: vi.fn(),
    });

    await coordinator.start({
      objective: '跨系统采购跟进',
      profiles: [DEFAULT_COMMAND_CENTER_PROFILE, LOCAL_PURCHASE_COMMAND_CENTER_PROFILE],
    });

    expect(client.createRecording).toHaveBeenCalledWith({
      objective: '跨系统采购跟进',
      sourceSystem: 'yifeng_mes',
      sourceSystems: ['yifeng_mes', 'connected_system'],
      recordingMode: 'multi_system',
    });
    expect(startLocal).toHaveBeenCalledWith(expect.objectContaining({
      captureOverrides: { networkBodies: true },
      commandCenter: expect.objectContaining({
        recording_kind: 'multi_system',
        system_codes: ['yifeng_mes', 'connected_system'],
        allowed_origins: ['http://yifeng.dtsum.com', 'http://127.0.0.1:8101'],
        origin_system_codes: {
          'http://yifeng.dtsum.com': 'yifeng_mes',
          'http://127.0.0.1:8101': 'connected_system',
        },
      }),
    }));
  });

  it('stops local capture before uploading and submitting remote analysis', async () => {
    const calls: string[] = [];
    const coordinator = createCommandCenterSessionCoordinator({
      clientFactory: vi.fn(),
      startLocal: vi.fn(),
      stopLocal: vi.fn(async () => {
        calls.push('local:stop');
        return row('ready');
      }),
      uploadLocal: vi.fn(async () => {
        calls.push('remote:upload-stop');
        return row('uploaded');
      }),
      getLocal: vi.fn(),
    });

    const stopped = await coordinator.stop('tr_local');

    expect(calls).toEqual(['local:stop', 'remote:upload-stop']);
    expect(stopped.status).toBe('uploaded');
  });

  it('resumes failed uploads from the persisted local row', async () => {
    const uploadLocal = vi.fn(async () => row('uploaded'));
    const coordinator = createCommandCenterSessionCoordinator({
      clientFactory: vi.fn(),
      startLocal: vi.fn(),
      stopLocal: vi.fn(),
      uploadLocal,
      getLocal: vi.fn(async () => row('failed')),
    });

    await coordinator.resumeUpload('tr_local');

    expect(uploadLocal).toHaveBeenCalledWith('tr_local');
  });
});
