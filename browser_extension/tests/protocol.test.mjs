import assert from 'node:assert/strict';
import test from 'node:test';

import { buildUIEvent, captureStatusText } from '../shared/protocol.mjs';

test('stopped capture reports API analysis without claiming browser recording', () => {
  assert.equal(
    captureStatusText({ stopping: true }),
    '录制已停止，智能体正在通过只读 API 分析和验证',
  );
});

test('password controls never carry values', () => {
  const event = buildUIEvent({
    actionType: 'input',
    control: { type: 'password', label: '密码' },
    valueBefore: '',
    valueAfter: 'secret',
  });

  assert.equal(event.valueBefore, null);
  assert.equal(event.valueAfter, null);
});

test('file controls never carry values', () => {
  const event = buildUIEvent({
    actionType: 'input',
    control: { type: 'file', label: '附件' },
    valueBefore: '',
    valueAfter: 'C:\\fakepath\\quote.pdf',
  });

  assert.equal(event.valueBefore, null);
  assert.equal(event.valueAfter, null);
});

test('semantic control context is retained', () => {
  const event = buildUIEvent({
    actionType: 'input',
    control: { type: 'number', label: '数量', section: '采购申请明细' },
    valueBefore: '',
    valueAfter: '10',
  });

  assert.equal(event.control.label, '数量');
});
