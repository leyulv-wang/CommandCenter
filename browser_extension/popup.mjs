import { captureStatusText, MESSAGE_TYPES } from './shared/protocol.mjs';

const PROFILE_ORIGIN = 'http://yifeng.dtsum.com';
const hostText = document.querySelector('#tab-host');
const versionText = document.querySelector('#extension-version');
const statusText = document.querySelector('#capture-status');
const errorText = document.querySelector('#capture-error');
const startButton = document.querySelector('#start');
const stopButton = document.querySelector('#stop');
const networkCheckbox = document.querySelector('#capture-network');
let selectedTabMatchesProfile = false;
let controlBusy = false;
versionText.textContent = `扩展版本 ${chrome.runtime.getManifest().version}`;

function withTimeout(promise, timeoutMs, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(message)), timeoutMs)),
  ]);
}

function render(status) {
  const capturing = Boolean(status?.capturing);
  statusText.textContent = captureStatusText(status);
  errorText.textContent = typeof status?.error === 'string' ? status.error : '';
  errorText.hidden = !errorText.textContent;
  startButton.disabled = controlBusy || !selectedTabMatchesProfile || capturing;
  stopButton.disabled = controlBusy || !capturing;
  networkCheckbox.disabled = controlBusy || capturing;
}

async function activeTabMatchesProfile() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const url = new URL(tab?.url);
    selectedTabMatchesProfile = url.origin === PROFILE_ORIGIN;
    hostText.textContent = selectedTabMatchesProfile ? `已选择：${url.host}` : '当前标签页不在测试配置的主机上';
  } catch {
    selectedTabMatchesProfile = false;
    hostText.textContent = '无法读取当前标签页主机';
  }
}

async function refresh() {
  await activeTabMatchesProfile();
  // The start control must not depend on a potentially suspended service worker.
  render({});
  try {
    render(await withTimeout(
      chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_STATUS }),
      1500,
      '扩展后台状态读取超时。',
    ));
  } catch {
    render({ error: '扩展后台未连接或响应超时；可以点击开始重试。' });
  }
}

async function controlCapture(type) {
  if (controlBusy) return;
  controlBusy = true;
  let controlError = null;
  try {
    render({});
    let captureNetwork = false;
    if (type === MESSAGE_TYPES.START_CAPTURE && networkCheckbox.checked) {
      captureNetwork = await chrome.permissions.request({ permissions: ['debugger'] });
      if (!captureNetwork) throw new Error('未授予 API 观察权限，未开始录制。');
    }
    render(await withTimeout(
      chrome.runtime.sendMessage({ type, captureNetwork }),
      20000,
      type === MESSAGE_TYPES.START_CAPTURE
        ? '启动录制超时，请检查中控服务。'
        : '停止录制超时；证据可能仍在后台保存。',
    ));
  } catch (error) {
    controlError = error instanceof Error ? error.message : '扩展操作失败。';
  } finally {
    controlBusy = false;
    if (controlError) {
      try {
        const current = await withTimeout(
          chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_STATUS }),
          1500,
          '扩展后台状态读取超时。',
        );
        render({ ...current, error: controlError });
      } catch {
        render({ error: controlError });
      }
    } else {
      await refresh();
    }
  }
}

startButton.addEventListener('click', () => controlCapture(MESSAGE_TYPES.START_CAPTURE));
stopButton.addEventListener('click', () => controlCapture(MESSAGE_TYPES.STOP_CAPTURE));
refresh();
