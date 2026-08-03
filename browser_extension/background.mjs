import { MESSAGE_TYPES } from './shared/protocol.mjs';

const PROFILE_HOST = 'yifeng.dtsum.com';
let capture = null;

function status() {
  return capture
    ? { capturing: true, tabId: capture.tabId, origin: capture.origin, eventCount: capture.events.length }
    : { capturing: false, tabId: null, origin: null, eventCount: 0 };
}

async function startSelectedTabCapture() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab?.url ? new URL(tab.url) : null;
  if (!tab?.id || !url || url.host !== PROFILE_HOST || !/^https?:$/.test(url.protocol)) {
    throw new Error('Select a permitted profile tab before starting capture.');
  }

  capture = { tabId: tab.id, origin: url.origin, events: [] };
  await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.START_CAPTURE });
  return status();
}

async function stopCapture() {
  const activeCapture = capture;
  capture = null;
  if (activeCapture) {
    await chrome.tabs.sendMessage(activeCapture.tabId, { type: MESSAGE_TYPES.STOP_CAPTURE }).catch(() => {});
  }
  return status();
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message?.type === MESSAGE_TYPES.GET_STATUS) return status();
    if (message?.type === MESSAGE_TYPES.START_CAPTURE) return startSelectedTabCapture();
    if (message?.type === MESSAGE_TYPES.STOP_CAPTURE) return stopCapture();

    if (message?.type === MESSAGE_TYPES.UI_EVENT && capture && sender.tab?.id === capture.tabId) {
      const senderOrigin = sender.origin || new URL(sender.tab.url).origin;
      if (senderOrigin === capture.origin) {
        capture.events.push(message.event);
        if (capture.events.length > 500) capture.events.shift();
      }
    }
    return status();
  })().then(sendResponse, (error) => sendResponse({ error: error.message, ...status() }));
  return true;
});
