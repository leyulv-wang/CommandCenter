import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createCommandCenterUploadRunner,
  selectCommandCenterNetworkChannel,
} from '@/command-center/upload';
import { db } from '@/storage/db';
import type { CapturedEvent, RecordingRow } from '@/shared/types';
import type { CommandCenterEvidenceBatch } from '@/command-center/evidence';

const recordingId = '123e4567-e89b-42d3-a456-426614174000';

function recording(status: RecordingRow['status'] = 'ready'): RecordingRow {
  return {
    trace_id: 'tr_upload',
    status,
    envelope: {
      schema_version: 'journey_trace_v1',
      trace_id: 'tr_upload',
      recording_mode: 'research_free_form',
      started_at: '2026-08-07T01:00:00.000Z',
      tags: [],
      browser: { extension_version: '1', user_agent: 'test', timezone: 'UTC' },
      summary: {
        domains: ['yifeng.dtsum.com'],
        duration_ms: 30,
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

function capturedEvents(): CapturedEvent[] {
  const page = 'http://yifeng.dtsum.com/purchase/apply';
  const base = { trace_id: 'tr_upload', tab_id: 1, url: page };
  return [
    {
      ...base,
      event_id: 'ev_action',
      timestamp: 1_000,
      kind: 'action',
      action_type: 'click',
      target: {
        tag: 'button',
        selector: '#query',
        xpath: '//*[@id="query"]',
      },
    },
    {
      ...base,
      event_id: 'ev_request',
      timestamp: 1_010,
      kind: 'network_request',
      request_id: 'request-1',
      method: 'GET',
      full_url:
        'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list?pageNo=1',
      fetch_kind: 'fetch',
      req_headers: {},
    },
    {
      ...base,
      event_id: 'ev_response',
      timestamp: 1_030,
      kind: 'network_response',
      request_id: 'request-1',
      status: 200,
    },
  ];
}

function fallbackEvents(): CapturedEvent[] {
  return capturedEvents()
    .filter(
      (event) =>
        event.kind === 'network_request' || event.kind === 'network_response',
    )
    .map((event) => ({
      ...event,
      event_id: `${event.event_id}_fallback`,
      request_id: `${event.request_id}_fallback`,
      capture_channel: 'browser_web_request' as const,
    }));
}

describe('CommandCenter upload runner', () => {
  beforeEach(async () => {
    await db.delete();
    await db.open();
  });

  afterEach(async () => {
    await db.delete();
  });

  it('prefers page HTTP evidence and removes browser fallback duplicates', () => {
    const primary = capturedEvents();
    const selected = selectCommandCenterNetworkChannel([
      ...primary,
      ...fallbackEvents(),
    ]);

    expect(selected).toEqual(primary);
  });

  it('promotes browser fallback HTTP evidence when the page channel has none', () => {
    const action = capturedEvents()[0]!;
    const fallback = fallbackEvents();

    expect(selectCommandCenterNetworkChannel([action, ...fallback])).toEqual([
      action,
      ...fallback,
    ]);
  });

  it('uploads converted evidence then submits asynchronous learning', async () => {
    await db.recordings.put(recording());
    await db.events.bulkPut(capturedEvents());
    const uploadedBatches: CommandCenterEvidenceBatch[] = [];
    const client = {
      createRecording: vi.fn(),
      start: vi.fn(),
      uploadEvents: vi.fn(
        async (
          _remoteRecordingId: string,
          _token: string,
          batch: CommandCenterEvidenceBatch,
        ) => {
          uploadedBatches.push(batch);
        },
      ),
      stop: vi.fn(async () => ({ status: 'queued' })),
      abort: vi.fn(),
      getStatus: vi.fn(),
    };
    const runner = createCommandCenterUploadRunner({ clientFactory: () => client });

    const result = await runner.uploadRecording('tr_upload');

    expect(client.uploadEvents).toHaveBeenCalledTimes(1);
    expect(uploadedBatches[0]?.events).toHaveLength(2);
    expect(client.stop).toHaveBeenCalledWith(recordingId, 'single-use-token');
    expect(result.status).toBe('uploaded');
    expect(result.command_center?.remote_status).toBe('queued');
  });

  it('keeps evidence and marks the row failed when upload is interrupted', async () => {
    await db.recordings.put(recording());
    await db.events.bulkPut(capturedEvents());
    const client = {
      createRecording: vi.fn(),
      start: vi.fn(),
      uploadEvents: vi.fn(async () => {
        throw new Error('offline');
      }),
      stop: vi.fn(),
      abort: vi.fn(async () => ({ status: 'upload_failed' })),
      getStatus: vi.fn(),
    };
    const runner = createCommandCenterUploadRunner({ clientFactory: () => client });

    await expect(runner.uploadRecording('tr_upload')).rejects.toThrow('offline');

    expect((await db.events.where('trace_id').equals('tr_upload').count())).toBe(3);
    expect((await db.recordings.get('tr_upload'))?.status).toBe('failed');
    expect(client.abort).toHaveBeenCalledWith(
      recordingId,
      'single-use-token',
      'upload_failed',
    );
  });

  it('aborts the remote session when no uploadable evidence was captured', async () => {
    await db.recordings.put(recording());
    const client = {
      createRecording: vi.fn(),
      start: vi.fn(),
      uploadEvents: vi.fn(),
      stop: vi.fn(),
      abort: vi.fn(async () => ({ status: 'upload_failed' })),
      getStatus: vi.fn(),
    };
    const runner = createCommandCenterUploadRunner({ clientFactory: () => client });

    await expect(runner.uploadRecording('tr_upload')).rejects.toThrow(
      'recording contains no uploadable CommandCenter evidence',
    );

    expect(client.uploadEvents).not.toHaveBeenCalled();
    expect(client.abort).toHaveBeenCalledWith(
      recordingId,
      'single-use-token',
      'no_uploadable_evidence',
    );
    expect((await db.recordings.get('tr_upload'))?.status).toBe('failed');
  });

  it('preserves the original upload error when remote abort also fails', async () => {
    await db.recordings.put(recording());
    await db.events.bulkPut(capturedEvents());
    const client = {
      createRecording: vi.fn(),
      start: vi.fn(),
      uploadEvents: vi.fn(async () => {
        throw new Error('offline');
      }),
      stop: vi.fn(),
      abort: vi.fn(async () => {
        throw new Error('abort unavailable');
      }),
      getStatus: vi.fn(),
    };
    const runner = createCommandCenterUploadRunner({ clientFactory: () => client });

    await expect(runner.uploadRecording('tr_upload')).rejects.toThrow('offline');

    expect((await db.events.where('trace_id').equals('tr_upload').count())).toBe(3);
    expect((await db.recordings.get('tr_upload'))?.last_error).toBe('offline');
  });
});
