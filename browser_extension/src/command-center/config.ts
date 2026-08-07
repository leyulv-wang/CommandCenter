export type CommandCenterProfile = {
  id: string;
  displayName: string;
  origins: string[];
  systemCode: string;
  commandCenterUrl: string;
  captureNetworkBodies: boolean;
};

export const DEFAULT_COMMAND_CENTER_PROFILE: CommandCenterProfile = {
  id: 'yifeng-mes',
  displayName: '益丰 MES',
  origins: ['http://yifeng.dtsum.com'],
  systemCode: 'yifeng_mes',
  commandCenterUrl: 'http://127.0.0.1:8000',
  captureNetworkBodies: true,
};

export const DEFAULT_COMMAND_CENTER_PROFILES: CommandCenterProfile[] = [
  DEFAULT_COMMAND_CENTER_PROFILE,
];

export function profileForUrl(
  url: string,
  profiles: readonly CommandCenterProfile[],
): CommandCenterProfile | null {
  let origin: string;
  try {
    origin = new URL(url).origin;
  } catch {
    return null;
  }

  return (
    profiles.find((profile) =>
      profile.origins.some((candidate) => exactOrigin(candidate) === origin),
    ) ?? null
  );
}

export function originAllowed(
  url: string,
  allowedOrigins: readonly string[],
): boolean {
  let origin: string;
  try {
    origin = new URL(url).origin;
  } catch {
    return false;
  }
  return allowedOrigins.some((candidate) => exactOrigin(candidate) === origin);
}

function exactOrigin(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.origin === value ? parsed.origin : null;
  } catch {
    return null;
  }
}
