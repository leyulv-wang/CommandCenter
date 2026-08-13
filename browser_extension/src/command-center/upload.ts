import {
  createCommandCenterClient,
  type CommandCenterRecordingClient,
} from '@/command-center/client';
import { createEvidenceConverter } from '@/command-center/evidence';
import { db, type JourneyForgeDB } from '@/storage/db';
import type { CapturedEvent, RecordingRow } from '@/shared/types';

class NoUploadableEvidenceError extends Error {}

const RESUMABLE_STATUSES: RecordingRow['status'][] = [
  'ready',
  'failed',
  'uploading',
];

export type CommandCenterUploadRunner = {
  uploadRecording(traceId: string): Promise<RecordingRow>;
  uploadNextRecording(): Promise<RecordingRow | null>;
};

export function createCommandCenterUploadRunner(options: {
  clientFactory?: (baseUrl: string) => CommandCenterRecordingClient;
  database?: JourneyForgeDB;
} = {}): CommandCenterUploadRunner {
  const database = options.database ?? db;
  const clientFactory =
    options.clientFactory ??
    ((baseUrl: string) => createCommandCenterClient({ baseUrl }));

  async function update(
    row: RecordingRow,
    patch: Partial<RecordingRow>,
  ): Promise<RecordingRow> {
    const next: RecordingRow = {
      ...row,
      ...patch,
      trace_id: row.trace_id,
      envelope: row.envelope,
      updated_at: Date.now(),
    };
    await database.recordings.put(next);
    return next;
  }

  async function uploadRecording(traceId: string): Promise<RecordingRow> {
    const row = await database.recordings.get(traceId);
    if (!row) throw new Error(`recording not found: ${traceId}`);
    if (!RESUMABLE_STATUSES.includes(row.status)) {
      throw new Error(`recording cannot be uploaded from status: ${row.status}`);
    }
    const connection = row.command_center;
    if (!connection) {
      throw new Error(`recording has no CommandCenter session: ${traceId}`);
    }

    let current = await update(row, { status: 'uploading', last_error: undefined });
    try {
      const converter = createEvidenceConverter({
        allowedOrigins: connection.allowed_origins,
        ...(connection.origin_system_codes
          ? { originSystemCodes: connection.origin_system_codes }
          : {}),
        fingerprintKey: connection.fingerprint_key,
        maxBufferedEvents: 10_000,
      });
      const captured = await database.events
        .where('trace_id')
        .equals(traceId)
        .sortBy('timestamp');
      for (const event of selectCommandCenterNetworkChannel(captured)) {
        converter.append(event);
      }
      const batch = await converter.flush(connection.recording_id);
      if (!batch || batch.events.length === 0) {
        throw new NoUploadableEvidenceError(
          'recording contains no uploadable CommandCenter evidence',
        );
      }

      const client = clientFactory(connection.base_url);
      await client.uploadEvents(
        connection.recording_id,
        connection.recording_token,
        batch,
      );
      const stopped = await client.stop(
        connection.recording_id,
        connection.recording_token,
      );
      current = await update(current, {
        status: 'uploaded',
        command_center: {
          ...connection,
          remote_status: stopped.status,
        },
      });
      return current;
    } catch (error) {
      const abortReason =
        error instanceof NoUploadableEvidenceError
          ? 'no_uploadable_evidence'
          : 'upload_failed';
      try {
        await clientFactory(connection.base_url).abort(
          connection.recording_id,
          connection.recording_token,
          abortReason,
        );
      } catch {
        // Remote cleanup is best-effort. Local evidence and the original error
        // remain authoritative for retry and diagnosis.
      }
      await update(current, {
        status: 'failed',
        last_error: safeErrorMessage(error),
      });
      throw error;
    }
  }

  return {
    uploadRecording,
    async uploadNextRecording() {
      const candidates = await database.recordings
        .where('status')
        .anyOf(RESUMABLE_STATUSES)
        .toArray();
      const next = candidates
        .filter((candidate) => candidate.command_center)
        .sort(
          (left, right) =>
            left.updated_at - right.updated_at || left.created_at - right.created_at,
        )[0];
      return next ? await uploadRecording(next.trace_id) : null;
    },
  };
}

export function selectCommandCenterNetworkChannel(
  events: CapturedEvent[],
): CapturedEvent[] {
  const hasPageHttpRequest = events.some(
    (event) =>
      event.kind === 'network_request' &&
      event.capture_channel !== 'browser_web_request',
  );
  if (!hasPageHttpRequest) return events;
  return events.filter(
    (event) =>
      !(
        (event.kind === 'network_request' ||
          event.kind === 'network_response') &&
        event.capture_channel === 'browser_web_request'
      ),
  );
}

function safeErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return 'CommandCenter upload failed.';
  return error.message.slice(0, 512);
}

export const commandCenterUploadRunner = createCommandCenterUploadRunner();
