import { MESSAGE_TYPES } from './shared/protocol.mjs';

const PROFILE_ORIGIN = 'http://yifeng.dtsum.com';
const hostText = document.querySelector('#tab-host');
const statusText = document.querySelector('#capture-status');
const startButton = document.querySelector('#start');
const stopButton = document.querySelector('#stop');
let selectedTabMatchesProfile = false;

function render(status) {
  const capturing = Boolean(status?.capturing);
  statusText.textContent = status?.paused
    ? '录制已暂停：所选标签页已离开允许的站点'
    : capturing
      ? `正在录制（${status.eventCount} 个待上传事件）`
      : status?.learningStatus === 'verified_candidate'
        ? '只读 Skill 已验证，状态：verified_candidate'
        : status?.learningStatus
          ? `演示处理结果：${status.learningStatus}`
          : '未录制';
  startButton.disabled = !selectedTabMatchesProfile || capturing;
  stopButton.disabled = !capturing;
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
  render(await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_STATUS }));
}

startButton.addEventListener('click', async () => render(await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.START_CAPTURE })));
stopButton.addEventListener('click', async () => render(await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.STOP_CAPTURE })));
refresh();
