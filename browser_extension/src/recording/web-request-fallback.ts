import { originAllowed } from '@/command-center/config';
import { createId } from '@/shared/id';
import type {
  CapturedEvent,
  NetworkRequestEvent,
  NetworkResponseEvent,
} from '@/shared/types';

export type WebRequestRecordingContext = {
  traceId: string;
  tabIds: ReadonlySet<number>;
  allowedOrigins: readonly string[];
};

export type WebRequestBeforeDetails = {
  requestId: string;
  tabId: number;
  method: string;
  url: string;
  initiator?: string;
  timeStamp: number;
  type?: string;
};

export type WebRequestCompletedDetails = {
  requestId: string;
  tabId: number;
  url: string;
  statusCode?: number;
  timeStamp: number;
};

export type WebRequestFailedDetails = Omit<
  WebRequestCompletedDetails,
  'statusCode'
> & { error?: string };

type PendingRequest = {
  traceId: string;
  tabId: number;
  pageUrl: string;
  startedAt: number;
};

export function createWebRequestFallbackRecorder(options: {
  getContext: () => WebRequestRecordingContext | null;
  sendEvent: (event: CapturedEvent) => void | Promise<void>;
}) {
  const pending = new Map<string, PendingRequest>();

  async function beforeRequest(details: WebRequestBeforeDetails): Promise<void> {
    const context = options.getContext();
    if (!context || !context.tabIds.has(details.tabId)) return;
    if (!isAllowedHttpUrl(details.url, context.allowedOrigins)) return;
    const pageUrl = safePageUrl(details.initiator, details.url);
    const request: NetworkRequestEvent = {
      event_id: createId('ev_'),
      trace_id: context.traceId,
      tab_id: details.tabId,
      timestamp: details.timeStamp,
      url: pageUrl,
      kind: 'network_request',
      capture_channel: 'browser_web_request',
      request_id: details.requestId,
      method: details.method.toUpperCase(),
      full_url: details.url,
      initiator: pageUrl,
      fetch_kind: fetchKind(details.type),
      req_headers: {},
    };
    pending.set(details.requestId, {
      traceId: context.traceId,
      tabId: details.tabId,
      pageUrl,
      startedAt: details.timeStamp,
    });
    await options.sendEvent(request);
  }

  async function finish(
    details: WebRequestCompletedDetails,
    status?: number,
  ): Promise<void> {
    const request = pending.get(details.requestId);
    if (!request || request.tabId !== details.tabId) return;
    pending.delete(details.requestId);
    const response: NetworkResponseEvent = {
      event_id: createId('ev_'),
      trace_id: request.traceId,
      tab_id: request.tabId,
      timestamp: details.timeStamp,
      url: request.pageUrl,
      kind: 'network_response',
      capture_channel: 'browser_web_request',
      request_id: details.requestId,
      ...(status !== undefined ? { status } : {}),
      duration_ms: Math.max(0, details.timeStamp - request.startedAt),
    };
    await options.sendEvent(response);
  }

  return {
    beforeRequest,
    completed(details: WebRequestCompletedDetails) {
      return finish(details, details.statusCode);
    },
    failed(details: WebRequestFailedDetails) {
      return finish(details);
    },
    clear(traceId?: string) {
      if (!traceId) {
        pending.clear();
        return;
      }
      for (const [requestId, request] of pending) {
        if (request.traceId === traceId) pending.delete(requestId);
      }
    },
  };
}

function isAllowedHttpUrl(
  value: string,
  allowedOrigins: readonly string[],
): boolean {
  try {
    const url = new URL(value);
    return (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      originAllowed(value, allowedOrigins)
    );
  } catch {
    return false;
  }
}

function safePageUrl(initiator: string | undefined, requestUrl: string): string {
  if (initiator && /^https?:\/\//i.test(initiator)) return initiator;
  return requestUrl;
}

function fetchKind(type: string | undefined): NetworkRequestEvent['fetch_kind'] {
  if (type === 'xmlhttprequest') return 'xhr';
  if (type === 'main_frame' || type === 'sub_frame') return 'navigation';
  return 'other';
}
