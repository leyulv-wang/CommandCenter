import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import * as backgroundModule from '../background.mjs';
import * as protocolModule from '../shared/protocol.mjs';

const { createRecordingApi, sessionStateSnapshot } = backgroundModule;


test('backend lifecycle separates evidence, credential, and final analysis', async () => {
  const calls = [];
  const fetchMock = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith('/recordings')) {
      return new Response(JSON.stringify({ recording_id: 'recording-1' }), { status: 201 });
    }
    if (url.endsWith('/extension/start')) {
      return new Response(JSON.stringify({ recording_token: 'one-time-token' }), { status: 200 });
    }
    if (url.endsWith('/extension/events')) {
      return new Response(JSON.stringify({ accepted: true }), { status: 202 });
    }
    if (url.endsWith('/extension/credential')) {
      return new Response(null, { status: 202 });
    }
    return new Response(JSON.stringify({
      recording_id: 'recording-1',
      status: 'verified_candidate',
      learning_result: { candidate_skill: { name: '查询采购申请' } },
    }), { status: 200 });
  };
  const api = createRecordingApi(fetchMock, 'http://command-center.test');
  const session = await api.start();
  await api.events(session, {
    batch_id: 'batch-1', recording_id: 'recording-1', events: [{ event_type: 'click' }],
  });
  await api.credential(session, 'X-Access-Token', 'private-secret');
  const stopped = await api.stop(session);

  assert.equal(session.recordingToken, 'one-time-token');
  assert.equal(stopped.status, 'verified_candidate');
  assert.deepEqual(
    calls.map((call) => new URL(call.url).pathname),
    [
      '/recordings',
      '/recordings/recording-1/extension/start',
      '/recordings/recording-1/extension/events',
      '/recordings/recording-1/extension/credential',
      '/recordings/recording-1/extension/stop',
    ],
  );
  assert.equal(calls[2].options.body.includes('private-secret'), false);
  assert.equal(calls[3].options.body.includes('private-secret'), true);
  assert.equal(calls[4].options.body, undefined);
});


test('capture stops page observation and uploads evidence before queueing analysis', async () => {
  const background = await readFile(new URL('../background.mjs', import.meta.url), 'utf8');
  const stopContent = background.indexOf('type: MESSAGE_TYPES.STOP_CAPTURE', background.indexOf('async function stopCapture'));
  const analyze = background.indexOf('recordingApi.stop(expectedCapture)', background.indexOf('async function stopCapture'));

  assert.ok(stopContent >= 0 && analyze > stopContent);
  assert.match(background, /await uploadPendingEvidence\(\);[\s\S]*recordingApi\.stop/);
  assert.match(background, /if \(stopPromise\) return stopPromise/);
  assert.match(background, /expectedCapture\.stopping = true;[\s\S]*persistSessionState\(\)/);
  assert.match(background, /if \(restored\.stopping\)[\s\S]*return;/);
  assert.match(background, /if \(expectedCapture\.networkCapture\) await forceDetachFromTab/);
});

test('popup explicitly identifies readonly mode before capture', async () => {
  const popupHtml = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  const popupScript = await readFile(new URL('../popup.mjs', import.meta.url), 'utf8');

  assert.match(popupHtml, /只读模式：未录制/);
  assert.match(popupHtml, /id="capture-error"/);
  assert.match(popupHtml, /id="extension-version"/);
  assert.match(popupScript, /status\?\.error/);
  assert.match(popupScript, /if \(controlBusy\) return/);
  assert.match(popupScript, /扩展后台未连接/);
  assert.match(popupScript, /try \{[\s\S]*GET_STATUS[\s\S]*\} catch/);
  assert.equal(protocolModule.captureStatusText({}), '只读模式：未录制');
});

test('failed upload retains a terminal result and explicit popup feedback', () => {
  assert.deepEqual(
    backgroundModule.failedLearningResult('recording-1'),
    { recording_id: 'recording-1', status: 'upload_failed' },
  );
  assert.equal(
    protocolModule.captureStatusText({ learningStatus: 'upload_failed' }),
    '录制上传失败，请查看中控',
  );
});

test('active capture survives service worker suspension in session-only storage', async () => {
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url), 'utf8'));
  const snapshot = sessionStateSnapshot({
    tabId: 7,
    origin: 'http://yifeng.dtsum.com',
    id: 'browser-session',
    recordingId: 'recording-1',
    recordingToken: 'one-time-recording-token',
    events: [{ event_type: 'click' }],
    paused: false,
    fingerprintKey: 'fingerprint-key',
    clientSequence: 3,
    droppedEvents: 1,
  }, null);

  assert.ok(manifest.permissions.includes('storage'));
  assert.equal(snapshot.version, 4);
  assert.equal(snapshot.capture.recordingId, 'recording-1');
  assert.equal(snapshot.capture.clientSequence, 3);
  assert.deepEqual(snapshot.capture.events, [{ event_type: 'click' }]);
  assert.equal(JSON.stringify(snapshot).includes('X-Access-Token'), false);
});
