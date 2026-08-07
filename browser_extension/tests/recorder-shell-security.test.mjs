import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const extensionRoot = new URL('..', import.meta.url);
const content = await readFile(new URL('content.js', extensionRoot), 'utf8');
const background = await readFile(new URL('background.mjs', extensionRoot), 'utf8');

test('file controls are rejected before content reads their values', () => {
  assert.match(content, /function sensitive\(element\)[\s\S]*type === 'file'/);
  const guard = content.indexOf('if (!element || sensitive(element)) return;');
  const firstValueRead = content.indexOf('element.value');
  assert.ok(guard >= 0 && guard < firstValueRead);
});

test('content only accepts control messages from this extension', () => {
  assert.match(content, /function isTrustedExtensionMessage\(sender\)/);
  assert.match(content, /if \(!isTrustedExtensionMessage\(sender\)\) return;/);
});

test('background pauses capture when the locked tab navigates away and stops when it closes', () => {
  assert.match(background, /chrome\.tabs\.onUpdated\.addListener/);
  assert.match(background, /chrome\.tabs\.onRemoved\.addListener/);
  assert.match(background, /!changeInfo\.url\) return/);
  assert.match(background, /nextOrigin === capture\.origin/);
  assert.match(background, /capture\.paused = true/);
  assert.match(background, /stopCapture\(capture\)/);
});

test('semantic recording is the default and debugger capture requires optional permission', async () => {
  const manifest = JSON.parse(await readFile(new URL('manifest.json', extensionRoot), 'utf8'));
  const popup = await readFile(new URL('popup.mjs', extensionRoot), 'utf8');
  assert.equal(manifest.permissions.includes('debugger'), false);
  assert.equal(manifest.optional_permissions.includes('debugger'), true);
  assert.match(background, /async function startSelectedTabCapture\(captureNetwork = false\)/);
  assert.match(background, /if \(captureNetwork\) await attachToTab/);
  assert.match(popup, /permissions\.request/);
});

test('background gates popup control messages and bounds semantic event flow', () => {
  assert.match(background, /function isTrustedPopupSender\(sender\)/);
  assert.match(background, /if \(!isTrustedPopupSender\(sender\)\) throw/);
  assert.match(content, /const MAX_MUTATION_RECORDS = \d+;/);
  assert.match(content, /const MAX_EVENTS_PER_WINDOW = \d+;/);
});
