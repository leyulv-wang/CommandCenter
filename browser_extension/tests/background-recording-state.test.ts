import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { latestCommandCenterRecording } from '@/recording/latest-command-center';
import { db } from '@/storage/db';
import type { RecordingRow } from '@/shared/types';

function row(
  traceId: string,
  updatedAt: number,
  withCommandCenter = true,
): RecordingRow {
  return {
    trace_id: traceId,
    status: 'failed',
    envelope: {
      schema_version: 'journey_trace_v1',
      trace_id: traceId,
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
    ...(withCommandCenter
      ? {
          command_center: {
            base_url: 'http://127.0.0.1:8000',
            system_code: 'connected_system',
            recording_id: `remote-${traceId}`,
            recording_token: 'single-use-token',
            allowed_origins: ['http://127.0.0.1:8101'],
            fingerprint_key: 'fingerprint-key',
          },
        }
      : {}),
    created_at: 1,
    updated_at: updatedAt,
  };
}

describe('latest CommandCenter recording', () => {
  beforeEach(async () => {
    await db.delete();
    await db.open();
  });

  afterEach(async () => {
    await db.delete();
  });

  it('returns the most recently updated CommandCenter row only', async () => {
    await db.recordings.bulkPut([
      row('older', 10),
      row('unrelated-newer', 30, false),
      row('latest-connected', 20),
    ]);

    await expect(latestCommandCenterRecording(db)).resolves.toMatchObject({
      trace_id: 'latest-connected',
      updated_at: 20,
    });
  });
});
