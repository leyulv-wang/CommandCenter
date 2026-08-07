import { originAllowed } from '@/command-center/config';
import type { CaptureSettings } from '@/shared/types';

export type RecordingStateMessage = {
  type: 'recording-state';
  active: boolean;
  traceId: string | null;
  captureSettings?: CaptureSettings | null;
  allowedOrigins?: string[];
};

export type ConnectRecordingTabInput = {
  tabId: number;
  url: string;
  message: RecordingStateMessage;
  allowedOrigins: readonly string[];
  sendMessage: (
    tabId: number,
    message: RecordingStateMessage,
  ) => Promise<unknown>;
  inject: (tabId: number) => Promise<unknown>;
};

export async function connectRecordingTab(
  input: ConnectRecordingTabInput,
): Promise<'messaged' | 'injected' | 'skipped'> {
  try {
    await input.sendMessage(input.tabId, input.message);
    return 'messaged';
  } catch {
    if (
      !input.message.active ||
      !originAllowed(input.url, input.allowedOrigins)
    ) {
      return 'skipped';
    }
    await input.inject(input.tabId);
    return 'injected';
  }
}
