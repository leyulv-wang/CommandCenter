import {
  createCommandCenterClient,
  type CommandCenterClient,
  type CommandCenterRecordingStatus,
} from '@/command-center/client';
import type { CommandCenterProfile } from '@/command-center/config';
import { startRecording, stopRecording } from '@/recording/recorder';
import { db } from '@/storage/db';
import type { RecordingRow } from '@/shared/types';
import { systemClock } from '@/shared/time';
import { commandCenterUploadRunner } from '@/command-center/upload';

type StartLocal = (options: {
  label: string;
  commandCenter: NonNullable<RecordingRow['command_center']>;
}) => Promise<RecordingRow>;

export type CommandCenterSessionCoordinator = {
  start(input: {
    objective: string;
    profile: CommandCenterProfile;
  }): Promise<RecordingRow>;
  stop(traceId: string): Promise<RecordingRow>;
  resumeUpload(traceId: string): Promise<RecordingRow>;
  getStatus(traceId: string): Promise<CommandCenterRecordingStatus>;
};

export function createCommandCenterSessionCoordinator(
  dependencies: {
    clientFactory?: (baseUrl: string) => CommandCenterClient;
    startLocal?: StartLocal;
    stopLocal?: (traceId: string) => Promise<RecordingRow>;
    uploadLocal?: (traceId: string) => Promise<RecordingRow>;
    getLocal?: (traceId: string) => Promise<RecordingRow | undefined>;
  } = {},
): CommandCenterSessionCoordinator {
  const clientFactory =
    dependencies.clientFactory ??
    ((baseUrl: string) => createCommandCenterClient({ baseUrl }));
  const startLocal =
    dependencies.startLocal ??
    ((options) => startRecording(systemClock, options));
  const stopLocal = dependencies.stopLocal ?? stopRecording;
  const uploadLocal =
    dependencies.uploadLocal ?? commandCenterUploadRunner.uploadRecording;
  const getLocal = dependencies.getLocal ?? ((traceId) => db.recordings.get(traceId));

  return {
    async start(input) {
      const objective = input.objective.trim();
      if (!objective) throw new Error('演示目标不能为空。');
      const client = clientFactory(input.profile.commandCenterUrl);
      const created = await client.createRecording({
        objective,
        sourceSystem: input.profile.systemCode,
      });
      const grant = await client.start(created.recordingId);
      return await startLocal({
        label: objective,
        commandCenter: {
          base_url: input.profile.commandCenterUrl,
          system_code: input.profile.systemCode,
          recording_id: created.recordingId,
          recording_token: grant.recordingToken,
          allowed_origins: [...input.profile.origins],
          fingerprint_key: crypto.randomUUID(),
        },
      });
    },

    async stop(traceId) {
      await stopLocal(traceId);
      return await uploadLocal(traceId);
    },

    async resumeUpload(traceId) {
      const row = await getLocal(traceId);
      if (!row) throw new Error(`recording not found: ${traceId}`);
      if (row.status !== 'ready' && row.status !== 'failed' && row.status !== 'uploading') {
        throw new Error(`recording cannot resume from status: ${row.status}`);
      }
      return await uploadLocal(traceId);
    },

    async getStatus(traceId) {
      const row = await getLocal(traceId);
      const connection = row?.command_center;
      if (!connection) throw new Error(`recording has no CommandCenter session: ${traceId}`);
      return await clientFactory(connection.base_url).getStatus(connection.recording_id);
    },
  };
}

export const commandCenterSession = createCommandCenterSessionCoordinator();
