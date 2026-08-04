export const MESSAGE_TYPES = Object.freeze({
  START_CAPTURE: 'CC_START_CAPTURE',
  STOP_CAPTURE: 'CC_STOP_CAPTURE',
  UI_EVENT: 'CC_UI_EVENT',
  GET_STATUS: 'CC_GET_STATUS',
  STATUS: 'CC_STATUS',
});

export function captureStatusText(status = {}) {
  if (status.paused) return '录制已暂停：所选标签页已离开允许的站点';
  if (status.capturing) return `正在录制（${status.eventCount} 个待上传事件）`;
  if (status.learningStatus === 'verified_candidate') {
    return '只读 Skill 已验证，状态：verified_candidate';
  }
  if (status.learningStatus === 'upload_failed') {
    return '录制上传失败，请查看中控';
  }
  if (status.learningStatus) return `演示处理结果：${status.learningStatus}`;
  return '只读模式：未录制';
}

function cleanText(value) {
  return typeof value === 'string' ? value.trim().slice(0, 500) : null;
}

function sanitizeControl(control = {}) {
  return {
    tag: cleanText(control.tag),
    type: cleanText(control.type),
    role: cleanText(control.role),
    name: cleanText(control.name),
    label: cleanText(control.label),
    placeholder: cleanText(control.placeholder),
    column: cleanText(control.column),
    row: cleanText(control.row),
    dialog: cleanText(control.dialog),
    section: cleanText(control.section),
  };
}

export function buildUIEvent(input = {}) {
  const control = sanitizeControl(input.control);
  const isSensitive = control.type === 'password' || control.type === 'file';

  return {
    type: MESSAGE_TYPES.UI_EVENT,
    actionType: cleanText(input.actionType),
    control,
    valueBefore: isSensitive ? null : cleanText(input.valueBefore),
    valueAfter: isSensitive ? null : cleanText(input.valueAfter),
    timestamp: Number.isFinite(input.timestamp) ? input.timestamp : Date.now(),
  };
}
