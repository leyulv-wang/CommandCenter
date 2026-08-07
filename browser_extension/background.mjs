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
const SESSION_STATE_KEY = 'commandCenterSessionState';
const SESSION_STATE_VERSION = 4;
const STATIC_RESOURCE_TYPES = new Set(['Font', 'Image', 'Manifest', 'Media', 'Script', 'Stylesheet']);
let capture = null;
let lastLearningResult = null;
let storageWrite = Promise.resolve();
let stopPromise = null;

export function sessionStateSnapshot(activeCapture, learningResult) {
  return {
    version: SESSION_STATE_VERSION,
    capture: activeCapture ? {
      tabId: activeCapture.tabId,
      origin: activeCapture.origin,
      id: activeCapture.id,
      recordingId: activeCapture.recordingId,
      recordingToken: activeCapture.recordingToken,
      events: Array.isArray(activeCapture.events)
        ? activeCapture.events.slice(-MAX_BUFFERED_EVENTS)
        : [],
      paused: Boolean(activeCapture.paused),
      stopping: Boolean(activeCapture.stopping),
      networkCapture: Boolean(activeCapture.networkCapture),
      fingerprintKey: activeCapture.fingerprintKey,
      clientSequence: Number.isInteger(activeCapture.clientSequence)
        ? activeCapture.clientSequence
        : 0,
      droppedEvents: Number.isInteger(activeCapture.droppedEvents)
        ? activeCapture.droppedEvents
        : 0,
    } : null,
    lastLearningResult: learningResult ? {
      recording_id: learningResult.recording_id,
      status: learningResult.status,
    } : null,
  };
}

function validStoredCapture(value) {
  if (!value || !Number.isInteger(value.tabId) || value.tabId < 0) return null;
  if (exactOrigin(value.origin) !== PROFILE_ORIGIN) return null;
  for (const key of ['id', 'recordingId', 'recordingToken', 'fingerprintKey']) {
    if (typeof value[key] !== 'string' || !value[key]) return null;
  }
  return sessionStateSnapshot(value, null).capture;
}

function persistSessionState() {
  if (!chromeApi?.storage?.session) return Promise.resolve();
  if (typeof chromeApi.storage.session.set !== 'function') {
    return Promise.reject(new Error('当前浏览器不支持扩展会话存储。'));
  }
  const snapshot = sessionStateSnapshot(capture, lastLearningResult);
  storageWrite = storageWrite
    .catch(() => {})
    .then(() => chromeApi.storage.session.set({ [SESSION_STATE_KEY]: snapshot }));
  return storageWrite;
}

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
    async status(session) {
      return requireJson(await request(`/recordings/${session.recordingId}`));
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
  const parsedCompleted = new Date(raw.completedAt ?? Date.now());
  const completed = Number.isNaN(parsedCompleted.getTime()) ? new Date() : parsedCompleted;
  const parsedStarted = new Date(raw.startedAt ?? completed.getTime() - Math.max(0, Number(raw.durationMs) || 0));
  const started = Number.isNaN(parsedStarted.getTime()) ? completed : parsedStarted;
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
  await persistSessionState();
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

  async function restoreTab(tabId, origin) {
    if (!Number.isInteger(tabId) || tabId < 0 || exactOrigin(origin) !== allowedOrigin) {
      throw new Error('The stored tab must use the allowed origin.');
    }
    clearSessionState();
    const alreadyAttached = await adapter.isAttached?.(tabId) ?? false;
    if (!alreadyAttached) await adapter.attach(tabId);
    try {
      await adapter.enableNetwork(tabId);
    } catch (error) {
      if (!alreadyAttached) await adapter.detach(tabId).catch(() => {});
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
      startedAt: new Date().toISOString(),
      monotonicStartedAt: Number.isFinite(params.timestamp) ? params.timestamp : null,
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
      receivedAt: new Date().toISOString(),
      monotonicReceivedAt: Number.isFinite(params.timestamp) ? params.timestamp : null,
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
    const monotonicCompletedAt = Number.isFinite(params.timestamp)
      ? params.timestamp
      : state.response.monotonicReceivedAt;
    const completedAt = new Date().toISOString();
    buffer({
      type: 'network',
      method: state.method,
      origin: state.origin,
      path: state.path,
      queryParameterNames: state.queryParameterNames,
      startedAt: state.startedAt,
      completedAt,
      durationMs: Number.isFinite(state.monotonicStartedAt) && Number.isFinite(monotonicCompletedAt)
        ? Math.max(0, Math.round((monotonicCompletedAt - state.monotonicStartedAt) * 1000))
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
    restoreTab,
    status: currentStatus,
  };
}

function chromeAdapter(chromeApi) {
  const target = (tabId) => ({ tabId });
  return {
    attach: (tabId) => chromeApi.debugger.attach(target(tabId), '1.3'),
    detach: (tabId) => chromeApi.debugger.detach(target(tabId)),
    async isAttached(tabId) {
      const targets = await chromeApi.debugger.getTargets();
      return targets.some((item) => item.tabId === tabId && item.attached);
    },
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
    if (capture) {
      capture.paused = true;
      void persistSessionState();
    }
  },
}) : null;

async function restoreSessionState() {
  if (!chromeApi?.storage?.session || !networkObserver) return;
  const stored = await chromeApi.storage.session.get(SESSION_STATE_KEY);
  const state = stored?.[SESSION_STATE_KEY];
  lastLearningResult = state?.lastLearningResult ?? null;
  const restored = state?.version === SESSION_STATE_VERSION
    ? validStoredCapture(state?.capture)
    : null;
  if (!restored) {
    capture = null;
    await persistSessionState();
    return;
  }
  try {
    const tab = await chromeApi.tabs.get(restored.tabId);
    if (tabOrigin(tab) !== restored.origin) throw new Error('The recorded tab is no longer available.');
    capture = restored;
    if (restored.stopping) {
      capture.paused = true;
      return;
    }
    capture.paused = false;
    if (restored.networkCapture) {
      const permitted = await chromeApi.permissions.contains({ permissions: ['debugger'] });
      if (!permitted) throw new Error('Stored API observation permission is no longer available.');
      await networkObserver.restoreTab(restored.tabId, restored.origin);
    }
    await chromeApi.tabs.sendMessage(restored.tabId, {
      type: MESSAGE_TYPES.START_CAPTURE,
      session: { tabId: restored.tabId, origin: restored.origin, id: restored.id },
    }).catch(() => {});
    await persistSessionState();
  } catch {
    capture = { ...restored, paused: true };
    await persistSessionState();
  }
}

const captureReady = chromeApi
  ? restoreSessionState().catch(() => { capture = null; })
  : Promise.resolve();

export async function attachToTab(tabId, origin = capture?.origin) {
  if (!networkObserver) throw new Error('Chrome debugger is unavailable.');
  return networkObserver.attachToTab(tabId, origin);
}

export async function detachFromTab(tabId) {
  return networkObserver?.detachFromTab(tabId);
}

async function forceDetachFromTab(tabId) {
  await detachFromTab(tabId).catch(() => {});
  if (!Number.isInteger(tabId) || !chromeApi?.debugger?.getTargets) return;
  const targets = await chromeApi.debugger.getTargets();
  const stillAttached = targets.some((item) => item.tabId === tabId && item.attached);
  if (stillAttached) await chromeApi.debugger.detach({ tabId }).catch(() => {});
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
        capturing: !capture.paused && !capture.stopping,
        paused: capture.paused && !capture.stopping,
        stopping: Boolean(capture.stopping),
        tabId: capture.tabId,
        origin: capture.origin,
        eventCount: capture.events.length,
        recordingId: capture.recordingId,
        learningStatus: null,
        captureMode: capture.networkCapture ? 'semantic_and_api' : 'semantic',
      }
    : {
        capturing: false,
        paused: false,
        stopping: false,
        tabId: null,
        origin: null,
        eventCount: 0,
        recordingId: lastLearningResult?.recording_id ?? null,
        learningStatus: lastLearningResult?.status ?? null,
        captureMode: null,
      };
}

async function refreshLearningResult() {
  if (capture || !lastLearningResult?.recording_id) return;
  if (!['recorded', 'analyzing'].includes(lastLearningResult.status)) return;
  try {
    const current = await recordingApi.status({
      recordingId: lastLearningResult.recording_id,
    });
    lastLearningResult = current;
    await persistSessionState();
  } catch {
    // Status polling is best effort; the saved recording remains available.
  }
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

async function startSelectedTabCapture(captureNetwork = false) {
  await captureReady;
  if (capture) await stopCapture(capture);
  const [tab] = await chromeApi.tabs.query({ active: true, currentWindow: true });
  const origin = tabOrigin(tab);
  if (!Number.isInteger(tab?.id) || origin !== PROFILE_ORIGIN) {
    throw new Error('Select a permitted profile tab before starting capture.');
  }

  const session = sessionFor(tab, origin);
  try {
    if (captureNetwork) await attachToTab(tab.id, origin);
    const backendSession = await recordingApi.start();
    capture = {
      ...session,
      ...backendSession,
      events: [],
      paused: false,
      stopping: false,
      networkCapture: Boolean(captureNetwork),
      fingerprintKey: crypto.randomUUID(),
      clientSequence: 0,
      droppedEvents: 0,
    };
    lastLearningResult = null;
    await persistSessionState();
    await chromeApi.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.START_CAPTURE, session });
  } catch (error) {
    if (captureNetwork) await detachFromTab(tab.id).catch(() => {});
    capture = null;
    await persistSessionState();
    throw error;
  }
  return status();
}

async function stopCaptureOnce(expectedCapture = capture) {
  await captureReady;
  if (!expectedCapture || capture !== expectedCapture) return status();
  let result = null;
  try {
    expectedCapture.stopping = true;
    expectedCapture.paused = true;
    await persistSessionState();
    await chromeApi.tabs.sendMessage(expectedCapture.tabId, {
      type: MESSAGE_TYPES.STOP_CAPTURE,
      sessionId: expectedCapture.id,
    }).catch(() => {});
    if (expectedCapture.networkCapture) await flushBatch();
    await uploadPendingEvidence();
    if (expectedCapture.networkCapture) await forceDetachFromTab(expectedCapture.tabId);
    result = await recordingApi.stop(expectedCapture);
    lastLearningResult = result;
  } catch (error) {
    lastLearningResult = failedLearningResult(expectedCapture.recordingId);
    throw error;
  } finally {
    if (expectedCapture.networkCapture) await forceDetachFromTab(expectedCapture.tabId);
    expectedCapture.recordingToken = null;
    if (capture === expectedCapture) capture = null;
    await persistSessionState();
  }
  return { ...status(), learningResult: result?.learning_result ?? null };
}

async function stopCapture(expectedCapture = capture) {
  if (stopPromise) return stopPromise;
  const operation = stopCaptureOnce(expectedCapture);
  stopPromise = operation;
  try {
    return await operation;
  } finally {
    if (stopPromise === operation) stopPromise = null;
  }
}

if (chromeApi) {
  chromeApi.debugger.onEvent.addListener((source, method, params) => {
    if (Number.isInteger(source.tabId)) {
      void captureReady.then(() => networkObserver.handleDebuggerEvent(source.tabId, method, params));
    }
  });

  chromeApi.debugger.onDetach.addListener((source) => {
    if (Number.isInteger(source.tabId)) {
      void captureReady
        .then(() => networkObserver.handleDebuggerDetach(source.tabId))
        .then(() => persistSessionState());
    }
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    void captureReady.then(async () => {
      // A status-only loading event has no trustworthy navigation target.
      // Chrome emits changeInfo.url separately when the top-level URL changes.
      if (!capture || tabId !== capture.tabId || !changeInfo.url) return;
      let nextOrigin = null;
      try { nextOrigin = new URL(changeInfo.url).origin; } catch { /* Pause on unreadable navigation. */ }
      if (nextOrigin === capture.origin) return;
      if (capture.networkCapture) await networkObserver.handleTabUpdated(tabId, changeInfo.url);
      capture.paused = true;
      await chromeApi.tabs.sendMessage(tabId, {
        type: MESSAGE_TYPES.STOP_CAPTURE,
        sessionId: capture.id,
      }).catch(() => {});
      await persistSessionState();
    });
  });

  chrome.tabs.onRemoved.addListener((tabId) => {
    void captureReady.then(() => {
      if (capture?.tabId === tabId) return stopCapture(capture);
      return undefined;
    });
  });

  chromeApi.runtime.onMessage.addListener((message, sender, sendResponse) => {
    (async () => {
      await captureReady;
      if (isPopupControlMessage(message)) {
        if (!isTrustedPopupSender(sender)) throw new Error('Only this extension popup may control capture.');
        if (message.type === MESSAGE_TYPES.GET_STATUS) {
          await refreshLearningResult();
          return status();
        }
        if (message.type === MESSAGE_TYPES.START_CAPTURE) {
          return startSelectedTabCapture(message.captureNetwork === true);
        }
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
          await persistSessionState();
        }
      }
      return status();
    })().then(sendResponse, (error) => {
      const message = error instanceof Error ? error.message : 'Unknown extension error.';
      console.error('CommandCenter extension request failed:', message);
      sendResponse({ error: message, ...status() });
    });
    return true;
  });
}
