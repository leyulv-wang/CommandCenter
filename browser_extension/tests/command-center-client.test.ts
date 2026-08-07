import { describe, expect, it, vi } from 'vitest';
import { createCommandCenterClient } from '@/command-center/client';

const recordingId = '123e4567-e89b-42d3-a456-426614174000';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('CommandCenter client', () => {
  it('calls the existing recording lifecycle endpoints', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ recording_id: recordingId }, 201))
      .mockResolvedValueOnce(jsonResponse({ recording_token: 'single-use-token' }))
      .mockResolvedValueOnce(jsonResponse({ accepted: true }, 202))
      .mockResolvedValueOnce(jsonResponse({ recording_id: recordingId, status: 'queued' }, 202))
      .mockResolvedValueOnce(jsonResponse({ recording_id: recordingId, status: 'learning' }));
    const client = createCommandCenterClient({
      baseUrl: 'http://127.0.0.1:8000/',
      fetchImpl,
    });

    await client.createRecording({ objective: '查询采购申请', sourceSystem: 'yifeng_mes' });
    await client.start(recordingId);
    await client.uploadEvents(recordingId, 'single-use-token', {
      batch_id: '223e4567-e89b-42d3-a456-426614174000',
      recording_id: recordingId,
      events: [],
      page_mutations: [],
      redaction_summary: {
        redacted_field_count: 0,
        fingerprinted_value_count: 0,
        dropped_evidence_count: 0,
      },
    });
    await client.stop(recordingId, 'single-use-token');
    await client.getStatus(recordingId);

    expect(
      fetchImpl.mock.calls.map(([input, init]) => [
        new URL(String(input)).pathname,
        init?.method ?? 'GET',
      ]),
    ).toEqual([
      ['/recordings', 'POST'],
      [`/recordings/${recordingId}/extension/start`, 'POST'],
      [`/recordings/${recordingId}/extension/events`, 'POST'],
      [`/recordings/${recordingId}/extension/stop`, 'POST'],
      [`/recordings/${recordingId}`, 'GET'],
    ]);
  });

  it('sends the recording token only as an authorization header', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ accepted: true }, 202));
    const client = createCommandCenterClient({ baseUrl: 'http://127.0.0.1:8000', fetchImpl });
    const batch = {
      batch_id: '223e4567-e89b-42d3-a456-426614174000',
      recording_id: recordingId,
      events: [],
      page_mutations: [],
      redaction_summary: {
        redacted_field_count: 0,
        fingerprinted_value_count: 0,
        dropped_evidence_count: 0,
      },
    };

    await client.uploadEvents(recordingId, 'single-use-token', batch);

    const [, init] = fetchImpl.mock.calls[0]!;
    expect(new Headers(init?.headers).get('X-CommandCenter-Recording-Token')).toBe(
      'single-use-token',
    );
    expect(String(init?.body)).not.toContain('single-use-token');
  });

  it('reports a safe status error without returning the response body', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ detail: 'private-token' }, 422));
    const client = createCommandCenterClient({ baseUrl: 'http://127.0.0.1:8000', fetchImpl });

    const error = await client.getStatus(recordingId).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain('CommandCenter request failed (422)');
    expect((error as Error).message).not.toContain('private-token');
  });
});
