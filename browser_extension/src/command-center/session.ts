import {
  createCommandCenterClient,
  type CommandCenterRecordingClient,
  type CommandCenterRecordingStatus,
} from '@/command-center/client';
import type { CommandCenterProfile } from '@/command-center/config';
import { startRecording, stopRecording } from '@/recording/recorder';
import { db } from '@/storage/db';
import type { RecordingRow } from '@/shared/types';
import type { CaptureSettings } from '@/shared/types';
import { systemClock } from '@/shared/time';
import { commandCenterUploadRunner } from '@/command-center/upload';

type StartLocal = (options: {
  label: string;
  captureOverrides?: Partial<CaptureSettings>;
  commandCenter: NonNullable<RecordingRow['command_center']>;
}) => Promise<RecordingRow>;

export type CommandCenterSessionCoordinator = {
  start(input: {
    objective: string;
    profile?: CommandCenterProfile;
    profiles?: CommandCenterProfile[];
  }): Promise<RecordingRow>;
  stop(traceId: string): Promise<RecordingRow>;
  resumeUpload(traceId: string): Promise<RecordingRow>;
  getStatus(traceId: string): Promise<CommandCenterRecordingStatus>;
};

export function createCommandCenterSessionCoordinator(
  dependencies: {
    clientFactory?: (baseUrl: string) => CommandCenterRecordingClient;
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
      const profiles = input.profiles ?? (input.profile ? [input.profile] : []);
      if (profiles.length === 0) throw new Error('至少选择一个业务系统。');
      const primaryProfile = profiles[0];
      if (!primaryProfile) throw new Error('至少选择一个业务系统。');
      const commandCenterUrl = primaryProfile.commandCenterUrl;
      if (profiles.some((profile) => profile.commandCenterUrl !== commandCenterUrl)) {
        throw new Error('联合录制的业务系统必须连接同一个中控。');
      }
      const client = clientFactory(commandCenterUrl);
      const created = await client.createRecording({
        objective,
        sourceSystem: primaryProfile.systemCode,
        sourceSystems: profiles.map((profile) => profile.systemCode),
        recordingMode: profiles.length > 1 ? 'multi_system' : 'single_system',
      });
      const grant = await client.start(created.recordingId);
      const allowedOrigins = profiles.flatMap((profile) => profile.origins);
      const originSystemCodes = Object.fromEntries(
        profiles.flatMap((profile) =>
          profile.origins.map((origin) => [new URL(origin).origin, profile.systemCode]),
        ),
      );
      return await startLocal({
        label: objective,
        captureOverrides: {
          networkBodies: profiles.some((profile) => profile.captureNetworkBodies),
        },
        commandCenter: {
          base_url: commandCenterUrl,
          system_code: primaryProfile.systemCode,
          recording_kind: profiles.length > 1 ? 'multi_system' : 'single_system',
          system_codes: profiles.map((profile) => profile.systemCode),
          recording_id: created.recordingId,
          recording_token: grant.recordingToken,
          allowed_origins: allowedOrigins,
          origin_system_codes: originSystemCodes,
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
