import { expect, test } from '@playwright/test';
import {
  launchExtensionContext,
  readRecordingEvidenceSummary,
  sendExtensionMessage,
} from './extension-harness';

type RecordingActionResponse = {
  active: boolean;
  traceId: string | null;
  row?: {
    status: string;
    last_error?: string;
    command_center?: { recording_id?: string };
  };
};

const SUCCESS_STATUSES = new Set(['verified_candidate', 'published']);
const TERMINAL_STATUSES = new Set([
  ...SUCCESS_STATUSES,
  'browser_candidate',
  'rejected',
  'needs_reteach',
  'upload_failed',
]);

test('real extension records and learns a read-only purchase query', async ({
  request,
}) => {
  const beforeResponse = await request.get(
    'http://127.0.0.1:8101/api/submissions',
  );
  expect(beforeResponse.ok()).toBe(true);
  const submissionsBefore = await beforeResponse.text();
  const harness = await launchExtensionContext();

  try {
    const purchasePage = await harness.context.newPage();
    await purchasePage.goto('http://127.0.0.1:8101/', {
      waitUntil: 'networkidle',
    });
    await purchasePage.bringToFront();
    const extensionPage = await harness.context.newPage();
    await extensionPage.goto(
      `chrome-extension://${harness.extensionId}/popup.html`,
    );

    const started = await sendExtensionMessage<RecordingActionResponse>(
      extensionPage,
      {
        type: 'start-recording',
        label: '查询采购申请',
        profileId: 'local-purchase',
      },
    );
    expect(started.active).toBe(true);
    expect(started.row?.status).toBe('recording');

    await purchasePage.getByRole('button', { name: '申请记录' }).click();
    const submissionsRequest = purchasePage.waitForResponse(
      (response) =>
        response.url() === 'http://127.0.0.1:8101/api/submissions' &&
        response.request().method() === 'GET',
    );
    await purchasePage
      .getByRole('button', { name: '刷新申请记录' })
      .click();
    await submissionsRequest;

    const stopped = await sendExtensionMessage<RecordingActionResponse>(
      extensionPage,
      { type: 'stop-recording', traceId: started.traceId },
    );
    expect(stopped.active).toBe(false);
    const evidence = await readRecordingEvidenceSummary(harness.worker);
    expect(
      stopped.row?.status,
      `extension upload failed: ${stopped.row?.last_error ?? 'no safe error'}; kinds=${evidence.kinds.join(',')}`,
    ).toBe('uploaded');
    expect(evidence.kinds).toContain('action');
    expect(evidence.kinds).toContain('network_request');
    expect(evidence.kinds).toContain('network_response');

    let finalRecording: {
      status?: string;
      failure_reasons?: string[];
      api_learning_result?: { failure_reasons?: string[] };
    } = {};
    await expect
      .poll(
        async () => {
          const response = await request.get(
            `http://127.0.0.1:8000/recordings/${evidence.remoteRecordingId}`,
          );
          expect(response.ok()).toBe(true);
          finalRecording = await response.json();
          return TERMINAL_STATUSES.has(finalRecording.status ?? '');
        },
        { timeout: 420_000, intervals: [500, 1_000, 2_000] },
      )
      .toBe(true);
    const finalStatus = finalRecording.status ?? '';
    expect(
      SUCCESS_STATUSES.has(finalStatus),
      `learning ended as ${finalStatus}: ${[
        ...(finalRecording.failure_reasons ?? []),
        ...(finalRecording.api_learning_result?.failure_reasons ?? []),
      ].join(' | ')}`,
    ).toBe(true);

    const popup = extensionPage;
    await popup.reload();
    await expect(
      popup.getByText(
        finalStatus === 'published'
          ? 'Skill 已通过测试并发布。'
          : 'API Skill 已验证。',
      ),
    ).toBeVisible({ timeout: 15_000 });
    await popup.reload();
    await expect(
      popup.getByText(
        finalStatus === 'published'
          ? 'Skill 已通过测试并发布。'
          : 'API Skill 已验证。',
      ),
    ).toBeVisible({ timeout: 15_000 });

    const afterResponse = await request.get(
      'http://127.0.0.1:8101/api/submissions',
    );
    expect(afterResponse.ok()).toBe(true);
    expect(await afterResponse.text()).toBe(submissionsBefore);
  } finally {
    await harness.cleanup();
  }
});
