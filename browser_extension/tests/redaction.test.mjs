import assert from 'node:assert/strict';
import test from 'node:test';

import {
  hmacFingerprint,
  sanitizeHeaders,
  sanitizeUrl,
  summarizeBody,
} from '../shared/redaction.mjs';
import { createNetworkObserver } from '../background.mjs';

test('credential headers are removed from evidence', () => {
  assert.deepEqual(
    sanitizeHeaders({
      'X-Access-Token': 'secret',
      Authorization: 'Bearer private',
      Cookie: 'session=private',
      'X-API-Key': 'private',
      'Content-Type': 'application/json',
    }),
    { 'Content-Type': 'application/json' },
  );
});

test('URLs retain only origin, path, and query parameter names', () => {
  assert.deepEqual(
    sanitizeUrl('http://yifeng.dtsum.com/api/list?token=secret&pageNo=2&pageNo=3#private'),
    {
      origin: 'http://yifeng.dtsum.com',
      path: '/api/list',
      queryParameterNames: ['token', 'pageNo'],
    },
  );
});

test('URLs drop query parameter names that the evidence protocol cannot represent', () => {
  assert.deepEqual(
    sanitizeUrl('http://yifeng.dtsum.com/api/list?_t=123&pageNo=2&bad%5Bname%5D=x'),
    {
      origin: 'http://yifeng.dtsum.com',
      path: '/api/list',
      queryParameterNames: ['pageNo'],
    },
  );
});

test('response summaries obey the byte limit without retaining raw bodies', () => {
  const result = summarizeBody('x'.repeat(100), 16);

  assert.equal(result.truncated, true);
  assert.equal(result.body.length <= 16, true);
  assert.equal(result.body.includes('xxxxxxxx'), false);
});

test('body fingerprints are keyed and stable without exposing the value', async () => {
  const first = await hmacFingerprint('private business value', 'recording-key');
  const second = await hmacFingerprint('private business value', 'recording-key');
  const differentKey = await hmacFingerprint('private business value', 'other-key');

  assert.equal(first, second);
  assert.notEqual(first, differentKey);
  assert.equal(first.includes('private'), false);
});

function fakeAdapter(options = {}) {
  const calls = [];
  let evidenceFailures = options.evidenceFailures ?? 0;
  return {
    calls,
    async attach(tabId) { calls.push(['attach', tabId]); },
    async detach(tabId) { calls.push(['detach', tabId]); },
    async enableNetwork(tabId) { calls.push(['enable', tabId]); },
    async responseBody(tabId, requestId) {
      calls.push(['body', tabId, requestId]);
      return options.body ?? '{"employee":"private"}';
    },
    async sendEvidence(batch) {
      calls.push(['evidence', batch]);
      if (evidenceFailures > 0) {
        evidenceFailures--;
        throw new Error('upload failed');
      }
    },
    async sendCredential(name, value) { calls.push(['credential', name, value]); },
  };
}

test('observer rejects a tab whose exact origin is not selected and allowed', async () => {
  const adapter = fakeAdapter();
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
  });

  await assert.rejects(
    observer.attachToTab(7, 'https://yifeng.dtsum.com'),
    /allowed origin/,
  );
  assert.deepEqual(adapter.calls, []);
});

test('observer sanitizes before buffering and hands credentials off separately', async () => {
  const adapter = fakeAdapter();
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  await observer.handleDebuggerEvent(7, 'Network.requestWillBeSent', {
    requestId: 'request-1',
    timestamp: 10,
    type: 'XHR',
    request: {
      method: 'GET',
      url: 'http://yifeng.dtsum.com/api/list?token=secret&pageNo=2',
      headers: { Authorization: 'private', 'Content-Type': 'application/json' },
      postData: '{"password":"private"}',
    },
  });
  await observer.handleDebuggerEvent(7, 'Network.requestWillBeSentExtraInfo', {
    requestId: 'request-1',
    headers: { 'X-Access-Token': 'credential', Cookie: 'session=private' },
  });
  await observer.handleDebuggerEvent(7, 'Network.responseReceived', {
    requestId: 'request-1',
    timestamp: 11,
    type: 'XHR',
    response: {
      url: 'http://yifeng.dtsum.com/api/list?token=secret&pageNo=2',
      status: 200,
      mimeType: 'application/json',
      headers: { 'content-length': '22', 'set-cookie': 'session=private' },
    },
  });
  await observer.handleDebuggerEvent(7, 'Network.loadingFinished', {
    requestId: 'request-1',
    timestamp: 12,
    encodedDataLength: 22,
  });
  await observer.flushBatch();

  const credentialCall = adapter.calls.find(([name]) => name === 'credential');
  const evidenceCall = adapter.calls.find(([name]) => name === 'evidence');
  assert.deepEqual(credentialCall, ['credential', 'X-Access-Token', 'credential']);
  assert.ok(evidenceCall);
  const serialized = JSON.stringify(evidenceCall[1]);
  for (const forbidden of ['secret', 'private', 'credential', 'Authorization', 'Cookie', 'password']) {
    assert.equal(serialized.includes(forbidden), false, forbidden);
  }
  assert.equal(evidenceCall[1][0].method, 'GET');
  assert.deepEqual(evidenceCall[1][0].queryParameterNames, ['token', 'pageNo']);
});

test('observer ignores other tabs and detaches after navigation leaves the exact origin', async () => {
  const adapter = fakeAdapter();
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  await observer.handleDebuggerEvent(8, 'Network.requestWillBeSent', {
    requestId: 'other-tab',
    request: { method: 'GET', url: 'http://yifeng.dtsum.com/api/list' },
  });
  await observer.handleTabUpdated(7, 'http://yifeng.dtsum.com.evil.test/path');

  assert.deepEqual(adapter.calls.filter(([name]) => name === 'evidence'), []);
  assert.deepEqual(adapter.calls.at(-1), ['detach', 7]);
  assert.equal(observer.status().paused, true);
});

test('observer does not hand off credentials for an uncorrelated foreign request', async () => {
  const adapter = fakeAdapter();
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  await observer.handleDebuggerEvent(7, 'Network.requestWillBeSent', {
    requestId: 'foreign-request',
    type: 'XHR',
    request: { method: 'GET', url: 'http://evil.test/api/list' },
  });
  await observer.handleDebuggerEvent(7, 'Network.requestWillBeSentExtraInfo', {
    requestId: 'foreign-request',
    headers: { 'X-Access-Token': 'foreign-credential' },
  });

  assert.deepEqual(adapter.calls.filter(([name]) => name === 'credential'), []);
});

test('observer never reads bodies for static, download, oversized, or foreign responses', async () => {
  const adapter = fakeAdapter();
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
    maxBodyBytes: 32,
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  const responses = [
    ['static', { url: 'http://yifeng.dtsum.com/app.js', status: 200, mimeType: 'application/javascript', headers: { 'content-length': '12' } }, 'Script'],
    ['download', { url: 'http://yifeng.dtsum.com/export', status: 200, mimeType: 'application/json', headers: { 'content-disposition': 'attachment' } }, 'XHR'],
    ['large', { url: 'http://yifeng.dtsum.com/api/list', status: 200, mimeType: 'application/json', headers: { 'content-length': '33' } }, 'XHR'],
    ['foreign', { url: 'http://evil.test/api/list', status: 200, mimeType: 'application/json', headers: { 'content-length': '12' } }, 'XHR'],
  ];
  for (const [requestId, response, type] of responses) {
    await observer.handleDebuggerEvent(7, 'Network.responseReceived', { requestId, response, type, timestamp: 20 });
    await observer.handleDebuggerEvent(7, 'Network.loadingFinished', { requestId, timestamp: 21, encodedDataLength: 12 });
  }

  assert.deepEqual(adapter.calls.filter(([name]) => name === 'body'), []);
});

async function completeJsonExchange(observer, requestId, headers, encodedDataLength = 12) {
  await observer.handleDebuggerEvent(7, 'Network.requestWillBeSent', {
    requestId,
    timestamp: 10,
    type: 'XHR',
    request: { method: 'GET', url: `http://yifeng.dtsum.com/api/${requestId}` },
  });
  await observer.handleDebuggerEvent(7, 'Network.responseReceived', {
    requestId,
    timestamp: 11,
    type: 'XHR',
    response: {
      url: `http://yifeng.dtsum.com/api/${requestId}`,
      status: 200,
      mimeType: 'application/json',
      headers,
    },
  });
  await observer.handleDebuggerEvent(7, 'Network.loadingFinished', {
    requestId,
    timestamp: 12,
    encodedDataLength,
  });
}

test('observer requires one strict identity Content-Length before reading a JSON body', async () => {
  const adapter = fakeAdapter({ body: '{"ok":true}' });
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
    maxBodyBytes: 32,
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  await completeJsonExchange(observer, 'missing', {});
  await completeJsonExchange(observer, 'invalid', { 'content-length': '12x' });
  await completeJsonExchange(observer, 'conflict', { 'Content-Length': '12', 'content-length': '13' });
  await completeJsonExchange(observer, 'compressed', { 'content-length': '12', 'content-encoding': 'gzip' });
  await completeJsonExchange(observer, 'chunked', { 'content-length': '12', 'transfer-encoding': 'chunked' });
  await completeJsonExchange(observer, 'large', { 'content-length': '33' });
  await completeJsonExchange(observer, 'eligible', { 'content-length': '11', 'content-encoding': 'identity' });
  await observer.flushBatch();

  assert.deepEqual(adapter.calls.filter(([name]) => name === 'body'), [['body', 7, 'eligible']]);
  const evidence = adapter.calls.find(([name]) => name === 'evidence')[1];
  assert.deepEqual(
    evidence.map((event) => event.responseBodySkippedReason),
    [
      'missing_content_length',
      'invalid_content_length',
      'conflicting_content_length',
      'encoded_response',
      'transfer_encoded_response',
      'content_length_exceeds_limit',
      null,
    ],
  );
});

test('encodedDataLength is not used as the decoded response-body limit', async () => {
  const adapter = fakeAdapter({ body: '{"ok":true}' });
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
    maxBodyBytes: 32,
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  await completeJsonExchange(observer, 'headers-overhead', { 'content-length': '11' }, 10_000);

  assert.deepEqual(adapter.calls.filter(([name]) => name === 'body'), [['body', 7, 'headers-overhead']]);
});

test('observer drops a body fingerprint when the actual bytes exceed the declared safe size', async () => {
  const adapter = fakeAdapter({ body: 'x'.repeat(100) });
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
    maxBodyBytes: 32,
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');

  await completeJsonExchange(observer, 'lied-about-size', { 'content-length': '4' });
  await observer.flushBatch();

  const event = adapter.calls.find(([name]) => name === 'evidence')[1][0];
  assert.equal(event.responseFingerprint, null);
  assert.equal(event.responseBodySkippedReason, 'actual_body_exceeds_limit');
});

test('failed upload clears the session so a new session cannot flush stale evidence', async () => {
  const adapter = fakeAdapter({ body: '{"ok":true}', evidenceFailures: 1 });
  const observer = createNetworkObserver(adapter, {
    allowedOrigin: 'http://yifeng.dtsum.com',
    fingerprintKey: 'recording-key',
    maxBodyBytes: 32,
  });
  await observer.attachToTab(7, 'http://yifeng.dtsum.com');
  await completeJsonExchange(observer, 'old-session', { 'content-length': '11' });

  await assert.rejects(
    observer.handleTabUpdated(7, 'http://evil.test/away'),
    /upload failed/,
  );
  assert.equal(observer.status().bufferedEventCount, 0);
  assert.equal(observer.status().attached, false);

  await observer.attachToTab(7, 'http://yifeng.dtsum.com');
  assert.deepEqual(await observer.flushBatch(), []);
  assert.equal(adapter.calls.filter(([name]) => name === 'evidence').length, 1);
});
