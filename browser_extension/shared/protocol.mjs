export const MESSAGE_TYPES = Object.freeze({
  START_CAPTURE: 'CC_START_CAPTURE',
  STOP_CAPTURE: 'CC_STOP_CAPTURE',
  UI_EVENT: 'CC_UI_EVENT',
  GET_STATUS: 'CC_GET_STATUS',
  STATUS: 'CC_STATUS',
});

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
  const isPassword = control.type === 'password';

  return {
    type: MESSAGE_TYPES.UI_EVENT,
    actionType: cleanText(input.actionType),
    control,
    valueBefore: isPassword ? null : cleanText(input.valueBefore),
    valueAfter: isPassword ? null : cleanText(input.valueAfter),
    timestamp: Number.isFinite(input.timestamp) ? input.timestamp : Date.now(),
  };
}
