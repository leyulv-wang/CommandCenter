import { MESSAGE_TYPES } from './shared/protocol.mjs';
import {
  hmacFingerprint,
  sanitizeUrl,
  summarizeBody,
} from './shared/redaction.mjs';

const PROFILE_ORIGIN = 'http://yifeng.dtsum.com';
const COMMAND_CENTER_ORIGIN = 'http://127.0.0.1:8000';
const MAX_BODY_BYTES = 64 * 1024;
const MAX_BUFFERED_EVENTS = 500;
const STATIC_RESOURCE_TYPES = new Set(['Font', 'Image', 'Manifest', 'Media', 'Script', 'Stylesheet']);
let capture = null;
let lastLearningResult = null;

function recordingHeaders(session) {
  return {
    'Content-Type': 'application/json',
    'X-CommandCenter-Recording-Token': session.recordingToken,
  };
}

async function requireJson(response) {
  if (!response.ok) throw new Error(`CommandCenter request failed (${response.status}).`);
  return response.json();
}

export function createRecordingApi(fetchImpl = fetch, baseUrl = COMMAND_CENTER_ORIGIN) {
  const request = (path, options = {}) => fetchImpl(`${baseUrl}${path}`, options);
  return {
    async start() {
      const created = await requireJson(await request('/recordings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          objective: '查询采购申请',
          source_system: 'yifeng_mes',
          source_task_id: 'browser-extension-demonstration',
          capture_source: 'browser_extension',
        }),
      }));
      const started = await requireJson(await request(
        `/recordings/${created.recording_id}/extension/start`,
        { method: 'POST' },
      ));
      return {
        recordingId: created.recording_id,
        recordingToken: started.recording_token,
      };
    },
    async events(session, batch) {
      return requireJson(await request(`/recordings/${session.recordingId}/extension/events`, {
        method: 'POST', headers: recordingHeaders(session), body: JSON.stringify(batch),
      }));
    },
    async credential(session, name, secret) {
      const response = await request(`/recordings/${session.recordingId}/extension/credential`, {
        method: 'PUT',
        headers: recordingHeaders(session),
        body: JSON.stringify({ name, secret }),
      });
      if (!response.ok) throw new Error(`CommandCenter request failed (${response.status}).`);
    },
    async stop(session) {
      return requireJson(await request(`/recordings/${session.recordingId}/extension/stop`, {
        method: 'POST', headers: recordingHeaders(session),
      }));
    },
  };
}

const recordingApi = createRecordingApi();

export function failedLearningResult(recordingId) {
  return { recording_id: recordingId, status: 'upload_failed' };
}

function exactOrigin(value) {
  try {
    const url = new URL(value);
    return url.origin === value ? value : null;
  } catch {
    return null;
  }
}

function safeSemanticText(value) {
  if (typeof value !== 'string') return null;
  const text = value.trim().slice(0, 256);
  if (!text || /authorization|cookie|credential|token|api\s*key|password|captcha|local.?storage|file.?content/i.test(text)) return null;
  return text;
}

function safeIdentifier(value) {
  if (typeof value !== 'string') return null;
  const candidate = value.trim().slice(0, 128);
  return /^[A-Za-z][A-Za-z0-9_.-]*$/.test(candidate) ? candidate : null;
}

function nextClientSequence() {
  if (!capture) throw new Error('No active recording.');
  capture.clientSequence += 1;
  return capture.clientSequence;
}

async function recordedUiEvent(raw, sender) {
  const action = raw?.actionType === 'change' ? 'select' : raw?.actionType;
  if (!['click', 'input', 'select', 'submit', 'navigation'].includes(action)) return null;
  const senderUrl = new URL(sender.tab.url);
  const control = raw.control ?? {};
  const controlFingerprint = await hmacFingerprint(JSON.stringify(control), capture.fingerprintKey);
  const value = typeof raw.valueAfter === 'string' ? raw.valueAfter : null;
  const descriptor = {
    selector_fingerprint: controlFingerprint,
  };
  const role = safeIdentifier(control.role || control.tag);
  const inputType = safeIdentifier(control.type);
  const label = safeSemanticText(control.label);
  const accessibleName = safeSemanticText(control.name || control.placeholder);
  if (role) descriptor.role = role;
  if (inputType) descriptor.input_type = inputType;
  if (label) descriptor.label = label;
  if (accessibleName) descriptor.accessible_name = accessibleName;
  return {
    event_id: crypto.randomUUID(),
    client_sequence: nextClientSequence(),
    occurred_at: new Date(Number.isFinite(raw.timestamp) ? raw.timestamp : Date.now()).toISOString(),
    event_type: action,
    page: {
      origin: senderUrl.origin,
      path: senderUrl.pathname || '/',
      fingerprint: await hmacFingerprint(`${senderUrl.origin}${senderUrl.pathname}`, capture.fingerprintKey),
    },
    control: descriptor,
    value_fingerprint: value ? await hmacFingerprint(value, capture.fingerprintKey) : null,
  };
}

function recordedNetworkEvent(raw) {
  const completed = new Date();
  const started = new Date(completed.getTime() - Math.max(0, Number(raw.durationMs) || 0));
  return {
    exchange_id: crypto.randomUUID(),
    client_sequence: nextClientSequence(),
    started_at: started.toISOString(),
    completed_at: completed.toISOString(),
    method: raw.method,
    path_template: raw.path,
    query_parameter_names: raw.queryParameterNames ?? [],
    request_fingerprint: raw.requestFingerprint,
    response_status: raw.status ?? 0,
    response_fingerprint: raw.responseFingerprint,
    endpoint_fingerprint: raw.endpointFingerprint,
  };
}

async function uploadPendingEvidence() {
  if (!capture || capture.events.length === 0) return;
  const events = capture.events.slice();
  await recordingApi.events(capture, {
    batch_id: crypto.randomUUID(),
    recording_id: capture.recordingId,
    events,
    redaction_summary: {
      redacted_field_count: 0,
      fingerprinted_value_count: events.length,
      dropped_evidence_count: capture.droppedEvents,
    },
  });
  capture.events.splice(0, events.length);
  capture.droppedEvents = 0;
}

function headerValue(headers, wantedName) {
  const wanted = wantedName.toLowerCase();
  const entry = Object.entries(headers ?? {}).find(([name]) => name.toLowerCase() === wanted);
  return entry ? String(entry[1]) : null;
}

function responseBodySkipReason(state, maxBodyBytes) {
  if (!state?.response) return 'missing_response_metadata';
  if (STATIC_RESOURCE_TYPES.has(state.resourceType)) return 'static_resource';
  const { response } = state;
  if (response.origin !== state.origin) return 'foreign_origin';
  if (response.mimeType !== 'application/json') return 'non_json_response';
  if (/\battachment\b/i.test(response.contentDisposition ?? '')) return 'download_response';
  if (response.transferEncodings.some((value) => value.toLowerCase() !== 'identity')) {
    return 'transfer_encoded_response';
  }
  if (response.contentEncodings.some((value) => value.toLowerCase() !== 'identity')) {
    return 'encoded_response';
  }
  if (response.contentLengths.length === 0) return 'missing_content_length';
  if (response.contentLengths.some((value) => !/^(0|[1-9]\d*)$/.test(value))) {
    return 'invalid_content_length';
  }
  const lengths = response.contentLengths.map(Number);
  if (lengths.some((value) => !Number.isSafeInteger(value))) return 'invalid_content_length';
  if (new Set(lengths).size !== 1) return 'conflicting_content_length';
  if (lengths[0] > maxBodyBytes) return 'content_length_exceeds_limit';
  return null;
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

  function clearSessionState() {
    requests.clear();
    credentials.clear();
    eventBuffer.splice(0);
  }

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
    clearSessionState();
    await adapter.attach(tabId);
    try {
      await adapter.enableNetwork(tabId);
    } catch (error) {
      await adapter.detach(tabId).catch(() => {});
      clearSessionState();
      selected = null;
      paused = true;
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
    try {
      await adapter.detach(detachedTabId);
    } finally {
      clearSessionState();
    }
    return currentStatus();
  }

  async function flushBatch() {
    if (flushPromise) return flushPromise;
    if (eventBuffer.length === 0) return [];
    const batch = eventBuffer.slice();
    flushPromise = (async () => {
      try {
        await adapter.sendEvidence(batch);
        eventBuffer.splice(0, batch.length);
        return batch;
      } catch (error) {
        const attachedTabId = selected?.tabId;
        selected = null;
        paused = true;
        clearSessionState();
        if (Number.isInteger(attachedTabId)) await adapter.detach(attachedTabId).catch(() => {});
        options.onPaused?.();
        throw error;
      }
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
    const headerEntries = Object.entries(params.response?.headers ?? {});
    const valuesFor = (name) => headerEntries
      .filter(([headerName]) => headerName.toLowerCase() === name)
      .map(([, value]) => String(value));
    state.resourceType = params.type ?? state.resourceType;
    state.response = {
      origin: url.origin,
      status: Number.isInteger(params.response?.status) ? params.response.status : null,
      receivedAt: Number.isFinite(params.timestamp) ? params.timestamp : null,
      mimeType: String(params.response?.mimeType ?? '').split(';', 1)[0].trim().toLowerCase(),
      contentDisposition: headerValue(params.response?.headers, 'content-disposition'),
      contentLengths: valuesFor('content-length'),
      contentEncodings: valuesFor('content-encoding'),
      transferEncodings: valuesFor('transfer-encoding'),
    };
  }

  async function loadingFinished(params) {
    const state = requests.get(params.requestId);
    if (!state?.response) return;
    let responseFingerprint = null;
    let responseWasJson = false;
    let responseBodySkippedReason = responseBodySkipReason(state, maxBodyBytes);
    if (!responseBodySkippedReason) {
      const rawBody = await adapter.responseBody(selected.tabId, params.requestId);
      const summary = summarizeBody(rawBody, maxBodyBytes);
      if (summary.truncated) {
        responseBodySkippedReason = 'actual_body_exceeds_limit';
      } else {
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
      responseBodySkippedReason,
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
      const stillSelected = selected?.tabId === tabId;
      if (stillSelected) await detachFromTab(tabId);
      paused = true;
      if (stillSelected) options.onPaused?.();
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
    clearSessionState();
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
      capture.events.push(...batch.map(recordedNetworkEvent));
      if (capture.events.length > MAX_BUFFERED_EVENTS) {
        capture.droppedEvents += capture.events.length - MAX_BUFFERED_EVENTS;
        capture.events.splice(0, capture.events.length - MAX_BUFFERED_EVENTS);
      }
      await uploadPendingEvidence();
    },
    async sendCredential(name, value) {
      if (!capture) return;
      await recordingApi.credential(capture, name, value);
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
        recordingId: capture.recordingId,
        learningStatus: null,
      }
    : {
        capturing: false,
        paused: false,
        tabId: null,
        origin: null,
        eventCount: 0,
        recordingId: lastLearningResult?.recording_id ?? null,
        learningStatus: lastLearningResult?.status ?? null,
      };
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
  try {
    await attachToTab(tab.id, origin);
    const backendSession = await recordingApi.start();
    capture = {
      ...session,
      ...backendSession,
      events: [],
      paused: false,
      fingerprintKey: crypto.randomUUID(),
      clientSequence: 0,
      droppedEvents: 0,
    };
    lastLearningResult = null;
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
  let result = null;
  try {
    await chromeApi.tabs.sendMessage(expectedCapture.tabId, {
      type: MESSAGE_TYPES.STOP_CAPTURE,
      sessionId: expectedCapture.id,
    }).catch(() => {});
    await flushBatch();
    await uploadPendingEvidence();
    await detachFromTab(expectedCapture.tabId).catch(() => {});
    result = await recordingApi.stop(expectedCapture);
    lastLearningResult = result;
  } catch (error) {
    lastLearningResult = failedLearningResult(expectedCapture.recordingId);
    throw error;
  } finally {
    await detachFromTab(expectedCapture.tabId).catch(() => {});
    expectedCapture.recordingToken = null;
    if (capture === expectedCapture) capture = null;
  }
  return { ...status(), learningResult: result?.learning_result ?? null };
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
          const event = await recordedUiEvent(message.event, sender);
          if (event) {
            capture.events.push(event);
            if (capture.events.length > MAX_BUFFERED_EVENTS) {
              capture.events.shift();
              capture.droppedEvents++;
            }
          } else {
            capture.droppedEvents++;
          }
        }
      }
      return status();
    })().then(sendResponse, (error) => sendResponse({ error: error.message, ...status() }));
    return true;
  });
}
