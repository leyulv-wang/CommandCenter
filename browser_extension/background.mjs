import { MESSAGE_TYPES } from './shared/protocol.mjs';
import {
  hmacFingerprint,
  sanitizeUrl,
  summarizeBody,
} from './shared/redaction.mjs';

const PROFILE_ORIGIN = 'http://yifeng.dtsum.com';
const MAX_BODY_BYTES = 64 * 1024;
const MAX_BUFFERED_EVENTS = 500;
const STATIC_RESOURCE_TYPES = new Set(['Font', 'Image', 'Manifest', 'Media', 'Script', 'Stylesheet']);
let capture = null;

function exactOrigin(value) {
  try {
    const url = new URL(value);
    return url.origin === value ? value : null;
  } catch {
    return null;
  }
}

function headerValue(headers, wantedName) {
  const wanted = wantedName.toLowerCase();
  const entry = Object.entries(headers ?? {}).find(([name]) => name.toLowerCase() === wanted);
  return entry ? String(entry[1]) : null;
}

function responseBodyEligible(state, params, maxBodyBytes) {
  if (!state?.response || STATIC_RESOURCE_TYPES.has(params.type ?? state.resourceType)) return false;
  const { response } = state;
  if (response.origin !== state.origin || response.mimeType !== 'application/json') return false;
  if (/\battachment\b/i.test(response.contentDisposition ?? '')) return false;
  if (Number.isFinite(response.contentLength) && response.contentLength > maxBodyBytes) return false;
  if (Number.isFinite(params.encodedDataLength) && params.encodedDataLength > maxBodyBytes) return false;
  return true;
}

export function createNetworkObserver(adapter, options = {}) {
  const allowedOrigin = exactOrigin(options.allowedOrigin ?? PROFILE_ORIGIN);
  if (!allowedOrigin) throw new TypeError('allowedOrigin must be an exact origin.');
  const maxBodyBytes = options.maxBodyBytes ?? MAX_BODY_BYTES;
  const maxBufferedEvents = options.maxBufferedEvents ?? MAX_BUFFERED_EVENTS;
  const fingerprintKey = options.fingerprintKey ?? crypto.randomUUID();
  const requests = new Map();
  const credentials = new Map();
  const eventBuffer = [];
  let selected = null;
  let paused = false;
  let flushPromise = null;

  function currentStatus() {
    return {
      attached: Boolean(selected),
      tabId: selected?.tabId ?? null,
      origin: selected?.origin ?? null,
      paused,
      bufferedEventCount: eventBuffer.length,
    };
  }

  async function attachToTab(tabId, origin) {
    if (!Number.isInteger(tabId) || tabId < 0 || exactOrigin(origin) !== allowedOrigin) {
      throw new Error('The selected tab must use the allowed origin.');
    }
    if (selected) await detachFromTab(selected.tabId);
    await adapter.attach(tabId);
    try {
      await adapter.enableNetwork(tabId);
    } catch (error) {
      await adapter.detach(tabId).catch(() => {});
      throw error;
    }
    selected = { tabId, origin };
    paused = false;
    return currentStatus();
  }

  async function detachFromTab(tabId) {
    if (!selected || tabId !== selected.tabId) return currentStatus();
    const detachedTabId = selected.tabId;
    selected = null;
    requests.clear();
    credentials.clear();
    try {
      await adapter.detach(detachedTabId);
    } finally {
      return currentStatus();
    }
  }

  async function flushBatch() {
    if (flushPromise) return flushPromise;
    if (eventBuffer.length === 0) return [];
    const batch = eventBuffer.slice();
    flushPromise = (async () => {
      await adapter.sendEvidence(batch);
      eventBuffer.splice(0, batch.length);
      return batch;
    })();
    try {
      return await flushPromise;
    } finally {
      flushPromise = null;
    }
  }

  async function handoffCredential(name, value) {
    if (!selected || String(name).toLowerCase() !== 'x-access-token' || typeof value !== 'string' || !value) return false;
    credentials.set('X-Access-Token', value);
    await adapter.sendCredential('X-Access-Token', value);
    return true;
  }

  function buffer(event) {
    eventBuffer.push(event);
    if (eventBuffer.length > maxBufferedEvents) eventBuffer.shift();
  }

  async function requestWillBeSent(params) {
    let url;
    try {
      url = sanitizeUrl(params.request?.url);
    } catch {
      return;
    }
    if (url.origin !== selected.origin) {
      if (params.type === 'Document') await pause();
      return;
    }
    const method = String(params.request?.method ?? '').toUpperCase();
    if (!/^[A-Z]{3,10}$/.test(method)) return;
    const rawBody = typeof params.request?.postData === 'string' ? params.request.postData : '';
    const bodySummary = summarizeBody(rawBody, maxBodyBytes);
    const requestFingerprint = rawBody && !bodySummary.truncated
      ? await hmacFingerprint(rawBody, fingerprintKey)
      : null;
    requests.set(params.requestId, {
      method,
      origin: url.origin,
      path: url.path,
      queryParameterNames: url.queryParameterNames,
      startedAt: Number.isFinite(params.timestamp) ? params.timestamp : null,
      resourceType: params.type ?? null,
      requestFingerprint,
      requestWasJson: bodySummary.json,
      endpointFingerprint: await hmacFingerprint(
        `${method}\n${url.origin}${url.path}\n${url.queryParameterNames.join('\n')}`,
        fingerprintKey,
      ),
      response: null,
    });
  }

  async function requestWillBeSentExtraInfo(params) {
    if (!requests.has(params.requestId)) return;
    const token = headerValue(params.headers, 'X-Access-Token');
    if (token) await handoffCredential('X-Access-Token', token);
  }

  function responseReceived(params) {
    const state = requests.get(params.requestId);
    if (!state) return;
    let url;
    try {
      url = sanitizeUrl(params.response?.url);
    } catch {
      requests.delete(params.requestId);
      return;
    }
    if (url.origin !== selected.origin || url.origin !== state.origin) {
      requests.delete(params.requestId);
      return;
    }
    const contentLength = Number(headerValue(params.response?.headers, 'content-length'));
    state.resourceType = params.type ?? state.resourceType;
    state.response = {
      origin: url.origin,
      status: Number.isInteger(params.response?.status) ? params.response.status : null,
      receivedAt: Number.isFinite(params.timestamp) ? params.timestamp : null,
      mimeType: String(params.response?.mimeType ?? '').split(';', 1)[0].trim().toLowerCase(),
      contentDisposition: headerValue(params.response?.headers, 'content-disposition'),
      contentLength: Number.isFinite(contentLength) && contentLength >= 0 ? contentLength : null,
    };
  }

  async function loadingFinished(params) {
    const state = requests.get(params.requestId);
    if (!state?.response) return;
    let responseFingerprint = null;
    let responseWasJson = false;
    if (responseBodyEligible(state, params, maxBodyBytes)) {
      const rawBody = await adapter.responseBody(selected.tabId, params.requestId);
      const summary = summarizeBody(rawBody, maxBodyBytes);
      if (!summary.truncated) {
        responseWasJson = summary.json;
        responseFingerprint = await hmacFingerprint(rawBody, fingerprintKey);
      }
    }
    const completedAt = Number.isFinite(params.timestamp) ? params.timestamp : state.response.receivedAt;
    buffer({
      type: 'network',
      method: state.method,
      origin: state.origin,
      path: state.path,
      queryParameterNames: state.queryParameterNames,
      startedAt: state.startedAt,
      completedAt,
      durationMs: Number.isFinite(state.startedAt) && Number.isFinite(completedAt)
        ? Math.max(0, Math.round((completedAt - state.startedAt) * 1000))
        : null,
      status: state.response.status,
      resourceType: state.resourceType,
      requestWasJson: state.requestWasJson,
      responseWasJson,
      requestFingerprint: state.requestFingerprint,
      responseFingerprint,
      endpointFingerprint: state.endpointFingerprint,
    });
    requests.delete(params.requestId);
  }

  async function handleDebuggerEvent(tabId, method, params = {}) {
    if (!selected || tabId !== selected.tabId) return;
    if (method === 'Network.requestWillBeSent') await requestWillBeSent(params);
    if (method === 'Network.requestWillBeSentExtraInfo') await requestWillBeSentExtraInfo(params);
    if (method === 'Network.responseReceived') responseReceived(params);
    if (method === 'Network.loadingFinished') await loadingFinished(params);
  }

  async function pause() {
    if (!selected) return currentStatus();
    const tabId = selected.tabId;
    paused = true;
    try {
      await flushBatch();
    } finally {
      await detachFromTab(tabId);
      paused = true;
      options.onPaused?.();
    }
    return currentStatus();
  }

  async function handleTabUpdated(tabId, url) {
    if (!selected || tabId !== selected.tabId) return currentStatus();
    let origin = null;
    try { origin = new URL(url).origin; } catch { /* An unreadable navigation is not trusted. */ }
    return origin === selected.origin ? currentStatus() : pause();
  }

  async function handleDebuggerDetach(tabId) {
    if (!selected || tabId !== selected.tabId) return currentStatus();
    selected = null;
    paused = true;
    requests.clear();
    credentials.clear();
    options.onPaused?.();
    return currentStatus();
  }

  return {
    attachToTab,
    detachFromTab,
    flushBatch,
    handoffCredential,
    handleDebuggerDetach,
    handleDebuggerEvent,
    handleTabUpdated,
    status: currentStatus,
  };
}

function chromeAdapter(chromeApi) {
  const target = (tabId) => ({ tabId });
  return {
    attach: (tabId) => chromeApi.debugger.attach(target(tabId), '1.3'),
    detach: (tabId) => chromeApi.debugger.detach(target(tabId)),
    enableNetwork: (tabId) => chromeApi.debugger.sendCommand(target(tabId), 'Network.enable', {
      maxPostDataSize: MAX_BODY_BYTES,
    }),
    async responseBody(tabId, requestId) {
      const result = await chromeApi.debugger.sendCommand(target(tabId), 'Network.getResponseBody', { requestId });
      return result?.body ?? '';
    },
    async sendEvidence(batch) {
      if (!capture) return;
      capture.events.push(...batch);
      if (capture.events.length > MAX_BUFFERED_EVENTS) {
        capture.events.splice(0, capture.events.length - MAX_BUFFERED_EVENTS);
      }
    },
    async sendCredential() {
      // Task 7 supplies the authenticated dedicated credential transport.
      // Until then, the observer retains the credential only in its private memory.
    },
  };
}

const chrome = globalThis.chrome;
const chromeApi = chrome;
const networkObserver = chromeApi ? createNetworkObserver(chromeAdapter(chromeApi), {
  allowedOrigin: PROFILE_ORIGIN,
  onPaused: () => {
    if (capture) capture.paused = true;
  },
}) : null;

export async function attachToTab(tabId, origin = capture?.origin) {
  if (!networkObserver) throw new Error('Chrome debugger is unavailable.');
  return networkObserver.attachToTab(tabId, origin);
}

export async function detachFromTab(tabId) {
  return networkObserver?.detachFromTab(tabId);
}

export async function flushBatch() {
  return networkObserver?.flushBatch() ?? [];
}

export async function handoffCredential(name, value) {
  return networkObserver?.handoffCredential(name, value) ?? false;
}

function status() {
  return capture
    ? {
        capturing: !capture.paused,
        paused: capture.paused,
        tabId: capture.tabId,
        origin: capture.origin,
        eventCount: capture.events.length,
      }
    : { capturing: false, paused: false, tabId: null, origin: null, eventCount: 0 };
}

function isTrustedPopupSender(sender) {
  return sender.id === chromeApi.runtime.id && sender.url === chromeApi.runtime.getURL('popup.html') && !sender.tab;
}

function isPopupControlMessage(message) {
  return [MESSAGE_TYPES.GET_STATUS, MESSAGE_TYPES.START_CAPTURE, MESSAGE_TYPES.STOP_CAPTURE].includes(message?.type);
}

function tabOrigin(tab) {
  try { return tab?.url ? new URL(tab.url).origin : null; } catch { return null; }
}

function sessionFor(tab, origin) {
  return { tabId: tab.id, origin, id: crypto.randomUUID() };
}

async function startSelectedTabCapture() {
  if (capture) await stopCapture(capture);
  const [tab] = await chromeApi.tabs.query({ active: true, currentWindow: true });
  const origin = tabOrigin(tab);
  if (!Number.isInteger(tab?.id) || origin !== PROFILE_ORIGIN) {
    throw new Error('Select a permitted profile tab before starting capture.');
  }

  const session = sessionFor(tab, origin);
  capture = { ...session, events: [], paused: false };
  try {
    await attachToTab(tab.id, origin);
    await chromeApi.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.START_CAPTURE, session });
  } catch (error) {
    await detachFromTab(tab.id).catch(() => {});
    capture = null;
    throw error;
  }
  return status();
}

async function stopCapture(expectedCapture = capture) {
  if (!expectedCapture || capture !== expectedCapture) return status();
  try {
    await flushBatch();
  } finally {
    await detachFromTab(expectedCapture.tabId).catch(() => {});
    await chromeApi.tabs.sendMessage(expectedCapture.tabId, {
      type: MESSAGE_TYPES.STOP_CAPTURE,
      sessionId: expectedCapture.id,
    }).catch(() => {});
    if (capture === expectedCapture) capture = null;
  }
  return status();
}

if (chromeApi) {
  chromeApi.debugger.onEvent.addListener((source, method, params) => {
    if (Number.isInteger(source.tabId)) void networkObserver.handleDebuggerEvent(source.tabId, method, params);
  });

  chromeApi.debugger.onDetach.addListener((source) => {
    if (Number.isInteger(source.tabId)) void networkObserver.handleDebuggerDetach(source.tabId);
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (!capture || tabId !== capture.tabId || (!changeInfo.url && changeInfo.status !== 'loading')) return;
    const url = changeInfo.url ?? tab?.url;
    void networkObserver.handleTabUpdated(tabId, url).then(() => {
      if (capture?.tabId === tabId && networkObserver.status().paused) {
        chromeApi.tabs.sendMessage(tabId, {
          type: MESSAGE_TYPES.STOP_CAPTURE,
          sessionId: capture.id,
        }).catch(() => {});
      }
    });
  });

  chrome.tabs.onRemoved.addListener((tabId) => {
    if (capture?.tabId === tabId) void stopCapture(capture);
  });

  chromeApi.runtime.onMessage.addListener((message, sender, sendResponse) => {
    (async () => {
      if (isPopupControlMessage(message)) {
        if (!isTrustedPopupSender(sender)) throw new Error('Only this extension popup may control capture.');
        if (message.type === MESSAGE_TYPES.GET_STATUS) return status();
        if (message.type === MESSAGE_TYPES.START_CAPTURE) return startSelectedTabCapture();
        return stopCapture();
      }

      if (message?.type === MESSAGE_TYPES.UI_EVENT && capture && !capture.paused
          && sender.id === chromeApi.runtime.id && sender.tab?.id === capture.tabId) {
        const senderOrigin = sender.origin || tabOrigin(sender.tab);
        if (senderOrigin === capture.origin && message.sessionId === capture.id) {
          capture.events.push(message.event);
          if (capture.events.length > MAX_BUFFERED_EVENTS) capture.events.shift();
        }
      }
      return status();
    })().then(sendResponse, (error) => sendResponse({ error: error.message, ...status() }));
    return true;
  });
}
