import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { createRecordingApi } from '../background.mjs';


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


test('capture stops page observation before requesting learning analysis', async () => {
  const background = await readFile(new URL('../background.mjs', import.meta.url), 'utf8');
  const stopContent = background.indexOf('type: MESSAGE_TYPES.STOP_CAPTURE', background.indexOf('async function stopCapture'));
  const analyze = background.indexOf('recordingApi.stop(expectedCapture)', background.indexOf('async function stopCapture'));

  assert.ok(stopContent >= 0 && analyze > stopContent);
  assert.match(background, /await uploadPendingEvidence\(\);[\s\S]*await detachFromTab[\s\S]*recordingApi\.stop/);
});

test('popup explicitly identifies readonly mode before capture', async () => {
  const popupHtml = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  const popupModule = await readFile(new URL('../popup.mjs', import.meta.url), 'utf8');

  assert.match(popupHtml, /只读模式：未录制/);
  assert.match(popupModule, /只读模式：未录制/);
});
