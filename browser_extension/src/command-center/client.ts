import type { CommandCenterEvidenceBatch } from '@/command-center/evidence';

export type CommandCenterRecordingStatus = {
  recording_id: string;
  status: string;
  final_status?: string;
  failure_stage?: string;
  public_message?: string;
};

export type SystemConnectionStatus = {
  system_code?: string;
  display_name?: string;
  status: string;
  credential_source?: string;
};

export type ExtensionAbortReason =
  | 'no_uploadable_evidence'
  | 'upload_failed';

export type CommandCenterRecordingClient = {
  createRecording(input: {
    objective: string;
    sourceSystem: string;
  }): Promise<{ recordingId: string }>;
  start(recordingId: string): Promise<{ recordingToken: string }>;
  uploadEvents(
    recordingId: string,
    token: string,
    batch: CommandCenterEvidenceBatch,
  ): Promise<void>;
  stop(recordingId: string, token: string): Promise<{ status: string }>;
  abort(
    recordingId: string,
    token: string,
    reason: ExtensionAbortReason,
  ): Promise<{ status: string }>;
  getStatus(recordingId: string): Promise<CommandCenterRecordingStatus>;
};

export type CommandCenterConnectionClient = {
  beginSystemConnection(systemCode: string): Promise<{ connectionToken: string }>;
  putSystemCredential(
    systemCode: string,
    connectionToken: string,
    name: string,
    secret: string,
  ): Promise<SystemConnectionStatus>;
  getSystemConnection(systemCode: string): Promise<SystemConnectionStatus>;
  disconnectSystem(systemCode: string): Promise<SystemConnectionStatus>;
  verifyLatestSystemSkill(systemCode: string): Promise<{ status: string }>;
};

export type CommandCenterClient = CommandCenterRecordingClient &
  CommandCenterConnectionClient;

export function createCommandCenterClient(options: {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}): CommandCenterClient {
  const baseUrl = options.baseUrl.replace(/\/+$/, '');
  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? 15_000;

  async function request(path: string, init: RequestInit = {}): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(`${baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`CommandCenter request failed (${response.status}).`);
      }
      return await response.json();
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error('CommandCenter request timed out.');
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function authorizedHeaders(token: string): HeadersInit {
    return {
      'Content-Type': 'application/json',
      'X-CommandCenter-Recording-Token': token,
    };
  }

  return {
    async createRecording(input) {
      const response = await request('/recordings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          objective: input.objective,
          source_system: input.sourceSystem,
          source_task_id: 'browser-extension-demonstration',
          capture_source: 'browser_extension',
        }),
      });
      return { recordingId: requiredString(response, 'recording_id') };
    },

    async start(recordingId) {
      const response = await request(
        `/recordings/${encodeURIComponent(recordingId)}/extension/start`,
        { method: 'POST' },
      );
      return { recordingToken: requiredString(response, 'recording_token') };
    },

    async uploadEvents(recordingId, token, batch) {
      await request(`/recordings/${encodeURIComponent(recordingId)}/extension/events`, {
        method: 'POST',
        headers: authorizedHeaders(token),
        body: JSON.stringify(batch),
      });
    },

    async stop(recordingId, token) {
      const response = await request(
        `/recordings/${encodeURIComponent(recordingId)}/extension/stop`,
        { method: 'POST', headers: authorizedHeaders(token) },
      );
      return { status: optionalString(response, 'status') ?? 'queued' };
    },

    async abort(recordingId, token, reason) {
      const response = await request(
        `/recordings/${encodeURIComponent(recordingId)}/extension/abort`,
        {
          method: 'POST',
          headers: authorizedHeaders(token),
          body: JSON.stringify({ reason }),
        },
      );
      return { status: optionalString(response, 'status') ?? 'upload_failed' };
    },

    async getStatus(recordingId) {
      return (await request(
        `/recordings/${encodeURIComponent(recordingId)}`,
      )) as CommandCenterRecordingStatus;
    },

    async beginSystemConnection(systemCode) {
      const response = await request(
        `/system-connections/${encodeURIComponent(systemCode)}/begin`,
        { method: 'POST' },
      );
      return { connectionToken: requiredString(response, 'connection_token') };
    },

    async putSystemCredential(systemCode, connectionToken, name, secret) {
      return (await request(
        `/system-connections/${encodeURIComponent(systemCode)}/credential`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'X-CommandCenter-Connection-Token': connectionToken,
          },
          body: JSON.stringify({ name, secret }),
        },
      )) as SystemConnectionStatus;
    },

    async getSystemConnection(systemCode) {
      return (await request(
        `/system-connections/${encodeURIComponent(systemCode)}`,
      )) as SystemConnectionStatus;
    },

    async disconnectSystem(systemCode) {
      return (await request(
        `/system-connections/${encodeURIComponent(systemCode)}`,
        { method: 'DELETE' },
      )) as SystemConnectionStatus;
    },

    async verifyLatestSystemSkill(systemCode) {
      return (await request(
        `/system-connections/${encodeURIComponent(systemCode)}/verify-latest-skill`,
        { method: 'POST' },
      )) as { status: string };
    },
  };
}

function requiredString(value: unknown, key: string): string {
  const result = optionalString(value, key);
  if (!result) throw new Error(`CommandCenter response missing ${key}.`);
  return result;
}

function optionalString(value: unknown, key: string): string | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = (value as Record<string, unknown>)[key];
  return typeof candidate === 'string' && candidate ? candidate : null;
}
