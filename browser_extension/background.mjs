import { MESSAGE_TYPES } from './shared/protocol.mjs';

const PROFILE_HOST = 'yifeng.dtsum.com';
let capture = null;

function status() {
  return capture
    ? { capturing: true, tabId: capture.tabId, origin: capture.origin, eventCount: capture.events.length }
    : { capturing: false, tabId: null, origin: null, eventCount: 0 };
}

function isTrustedPopupSender(sender) {
  return sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL('popup.html') && !sender.tab;
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
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const origin = tabOrigin(tab);
  const url = origin ? new URL(origin) : null;
  if (!tab?.id || !url || url.host !== PROFILE_HOST || url.protocol !== 'http:') {
    throw new Error('Select a permitted profile tab before starting capture.');
  }

  const session = sessionFor(tab, origin);
  capture = { ...session, events: [] };
  await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.START_CAPTURE, session });
  return status();
}

async function stopCapture(expectedCapture = capture) {
  if (!expectedCapture || capture !== expectedCapture) return status();
  capture = null;
  await chrome.tabs.sendMessage(expectedCapture.tabId, { type: MESSAGE_TYPES.STOP_CAPTURE, sessionId: expectedCapture.id }).catch(() => {});
  return status();
}

function lockedTabLeftOrigin(tabId, tab, changeInfo = {}) {
  if (!capture || tabId !== capture.tabId) return false;
  if (!changeInfo.url && changeInfo.status !== 'loading') return false;
  return tabOrigin(tab) !== capture.origin;
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (lockedTabLeftOrigin(tabId, tab, changeInfo)) void stopCapture(capture);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (capture?.tabId === tabId) void stopCapture(capture);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (isPopupControlMessage(message)) {
      if (!isTrustedPopupSender(sender)) throw new Error('Only this extension popup may control capture.');
      if (message.type === MESSAGE_TYPES.GET_STATUS) return status();
      if (message.type === MESSAGE_TYPES.START_CAPTURE) return startSelectedTabCapture();
      return stopCapture();
    }

    if (message?.type === MESSAGE_TYPES.UI_EVENT && capture && sender.id === chrome.runtime.id && sender.tab?.id === capture.tabId) {
      const senderOrigin = sender.origin || tabOrigin(sender.tab);
      if (senderOrigin === capture.origin && message.sessionId === capture.id) {
        capture.events.push(message.event);
        if (capture.events.length > 500) capture.events.shift();
      }
    }
    return status();
  })().then(sendResponse, (error) => sendResponse({ error: error.message, ...status() }));
  return true;
});
