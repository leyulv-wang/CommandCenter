import { describe, expect, it, vi } from 'vitest';
import {
  createWebRequestFallbackRecorder,
  createWebRequestRecordingScope,
  type WebRequestRecordingContext,
} from '@/recording/web-request-fallback';
import type { CapturedEvent } from '@/shared/types';

const context: WebRequestRecordingContext = {
  traceId: 'tr_mes',
  tabIds: new Set([7]),
  allowedOrigins: ['http://yifeng.dtsum.com'],
};

describe('browser webRequest fallback recorder', () => {
  it('tracks only tabs connected to the active recording lifecycle', () => {
    const scope = createWebRequestRecordingScope();

    expect(scope.context()).toBeNull();
    scope.activate('tr_mes', ['http://yifeng.dtsum.com']);
    scope.connectTab(7);
    expect(scope.context()).toEqual({
      traceId: 'tr_mes',
      tabIds: new Set([7]),
      allowedOrigins: ['http://yifeng.dtsum.com'],
    });
    scope.disconnectTab(7);
    expect(scope.context()?.tabIds).toEqual(new Set());
    expect(scope.deactivate()).toBe('tr_mes');
    expect(scope.context()).toBeNull();
  });

  it('records a minimal paired request and response for the active MES tab', async () => {
    const events: CapturedEvent[] = [];
    const recorder = createWebRequestFallbackRecorder({
      getContext: () => context,
      sendEvent: async (event) => {
        events.push(event);
      },
    });

    await recorder.beforeRequest({
      requestId: 'request-1',
      tabId: 7,
      method: 'GET',
      url: 'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list?pageNo=1',
      initiator: 'http://yifeng.dtsum.com',
      timeStamp: 1_000,
      type: 'xmlhttprequest',
    });
    await recorder.completed({
      requestId: 'request-1',
      tabId: 7,
      url: 'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list?pageNo=1',
      statusCode: 200,
      timeStamp: 1_025,
    });

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({
      kind: 'network_request',
      capture_channel: 'browser_web_request',
      trace_id: 'tr_mes',
      tab_id: 7,
      request_id: 'request-1',
      method: 'GET',
      fetch_kind: 'xhr',
      req_headers: {},
    });
    expect(events[0]).not.toHaveProperty('req_body');
    expect(events[1]).toMatchObject({
      kind: 'network_response',
      capture_channel: 'browser_web_request',
      request_id: 'request-1',
      status: 200,
      duration_ms: 25,
    });
    expect(events[1]).not.toHaveProperty('res_body');
  });

  it.each([
    ['another tab', { tabId: 8, url: 'http://yifeng.dtsum.com/api/list' }],
    ['another origin', { tabId: 7, url: 'http://example.test/api/list' }],
    ['non-http URL', { tabId: 7, url: 'data:text/plain,hello' }],
  ])('ignores %s', async (_label, override) => {
    const sendEvent = vi.fn();
    const recorder = createWebRequestFallbackRecorder({
      getContext: () => context,
      sendEvent,
    });

    await recorder.beforeRequest({
      requestId: 'ignored',
      tabId: override.tabId,
      method: 'GET',
      url: override.url,
      timeStamp: 1,
      type: 'xmlhttprequest',
    });

    expect(sendEvent).not.toHaveBeenCalled();
  });

  it('cleans failed and explicitly cleared requests without crossing traces', async () => {
    const events: CapturedEvent[] = [];
    const recorder = createWebRequestFallbackRecorder({
      getContext: () => context,
      sendEvent: async (event) => {
        events.push(event);
      },
    });
    const request = {
      requestId: 'request-failed',
      tabId: 7,
      method: 'GET',
      url: 'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list',
      timeStamp: 10,
      type: 'xmlhttprequest',
    };

    await recorder.beforeRequest(request);
    await recorder.failed({
      requestId: request.requestId,
      tabId: request.tabId,
      url: request.url,
      timeStamp: 20,
      error: 'net::ERR_ABORTED',
    });
    await recorder.completed({
      requestId: request.requestId,
      tabId: request.tabId,
      url: request.url,
      statusCode: 200,
      timeStamp: 30,
    });

    expect(events).toHaveLength(2);
    expect(events[1]).toMatchObject({
      kind: 'network_response',
      request_id: request.requestId,
      duration_ms: 10,
    });

    await recorder.beforeRequest({ ...request, requestId: 'request-cleared' });
    recorder.clear('tr_mes');
    await recorder.completed({
      requestId: 'request-cleared',
      tabId: 7,
      url: request.url,
      statusCode: 200,
      timeStamp: 40,
    });
    expect(events).toHaveLength(3);
  });
});
