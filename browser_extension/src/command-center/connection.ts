import type {
  CommandCenterClient,
  SystemConnectionStatus,
} from '@/command-center/client';
import {
  originAllowed,
  type CommandCenterProfile,
} from '@/command-center/config';

export type RequestHeader = {
  name: string;
  value?: string;
};

export type ConnectionConsentStore = {
  get(systemCode: string): Promise<boolean>;
  set(systemCode: string, enabled: boolean): Promise<void>;
};

type ConnectionClient = Pick<
  CommandCenterClient,
  | 'beginSystemConnection'
  | 'putSystemCredential'
  | 'getSystemConnection'
  | 'disconnectSystem'
  | 'verifyLatestSystemSkill'
>;

export type SystemConnectionView = SystemConnectionStatus & {
  consent: boolean;
};

export class SystemConnectionCoordinator {
  readonly #consentStore: ConnectionConsentStore;
  readonly #client: ConnectionClient;

  constructor(options: {
    consentStore: ConnectionConsentStore;
    client: ConnectionClient;
  }) {
    this.#consentStore = options.consentStore;
    this.#client = options.client;
  }

  async enable(profile: CommandCenterProfile): Promise<SystemConnectionView> {
    requireCredentialHeader(profile);
    await this.#consentStore.set(profile.systemCode, true);
    return {
      system_code: profile.systemCode,
      display_name: profile.displayName,
      status: 'waiting_for_mes_request',
      consent: true,
    };
  }

  async disable(profile: CommandCenterProfile): Promise<SystemConnectionView> {
    await this.#consentStore.set(profile.systemCode, false);
    const status = await this.#client.disconnectSystem(profile.systemCode);
    return { ...status, consent: false };
  }

  async status(profile: CommandCenterProfile): Promise<SystemConnectionView> {
    const consent = await this.#consentStore.get(profile.systemCode);
    if (!consent) {
      return {
        system_code: profile.systemCode,
        display_name: profile.displayName,
        status: 'disconnected',
        consent: false,
      };
    }
    const status = await this.#client.getSystemConnection(profile.systemCode);
    return {
      ...status,
      status: status.status === 'disconnected'
        ? 'waiting_for_mes_request'
        : status.status,
      consent: true,
    };
  }

  async observeRequest(
    profile: CommandCenterProfile,
    request: { url: string; requestHeaders: readonly RequestHeader[] },
  ): Promise<void> {
    const configuredHeader = profile.credentialHeader;
    if (
      !configuredHeader ||
      !(await this.#consentStore.get(profile.systemCode)) ||
      !originAllowed(request.url, profile.origins)
    ) return;

    const header = request.requestHeaders.find(
      (candidate) => candidate.name.toLowerCase() === configuredHeader.toLowerCase(),
    );
    const secret = header?.value?.trim();
    if (!secret || secret.includes('\r') || secret.includes('\n')) return;

    const { connectionToken } = await this.#client.beginSystemConnection(
      profile.systemCode,
    );
    await this.#client.putSystemCredential(
      profile.systemCode,
      connectionToken,
      configuredHeader,
      secret,
    );
    try {
      await this.#client.verifyLatestSystemSkill(profile.systemCode);
    } catch {
      // Credential synchronization remains useful before a candidate Skill exists.
    }
  }
}

export function createBrowserConnectionConsentStore(): ConnectionConsentStore {
  const key = (systemCode: string) => `command-center-connection-consent:${systemCode}`;
  return {
    async get(systemCode) {
      const result = await chrome.storage.local.get(key(systemCode));
      return result[key(systemCode)] === true;
    },
    async set(systemCode, enabled) {
      await chrome.storage.local.set({ [key(systemCode)]: enabled });
    },
  };
}

function requireCredentialHeader(profile: CommandCenterProfile): string {
  if (!profile.credentialHeader) {
    throw new Error('当前业务系统未配置可同步的认证请求头。');
  }
  return profile.credentialHeader;
}
