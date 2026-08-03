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

test('background stops capture when the locked tab navigates away or closes', () => {
  assert.match(background, /chrome\.tabs\.onUpdated\.addListener/);
  assert.match(background, /chrome\.tabs\.onRemoved\.addListener/);
  assert.match(background, /stopCapture\(capture\)/);
});

test('background gates popup control messages and bounds semantic event flow', () => {
  assert.match(background, /function isTrustedPopupSender\(sender\)/);
  assert.match(background, /if \(!isTrustedPopupSender\(sender\)\) throw/);
  assert.match(content, /const MAX_MUTATION_RECORDS = \d+;/);
  assert.match(content, /const MAX_EVENTS_PER_WINDOW = \d+;/);
});
