import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PopupApp } from '@/entrypoints/popup/App';
import { sendRuntimeMessage } from '@/shared/runtime';

vi.mock('@/shared/runtime', () => ({ sendRuntimeMessage: vi.fn() }));
vi.mock('@/storage/db', async () => {
  const config = await import('@/command-center/config');
  return {
    getConfig: vi.fn(async () => ({
      commandCenterProfiles: config.DEFAULT_COMMAND_CENTER_PROFILES,
      selectedCommandCenterProfileId: config.DEFAULT_COMMAND_CENTER_PROFILE.id,
    })),
  };
});

describe('CommandCenter popup', () => {
  beforeEach(() => {
    vi.mocked(sendRuntimeMessage).mockReset();
    vi.mocked(sendRuntimeMessage).mockResolvedValue({
      active: false,
      traceId: null,
      row: null,
    });
    vi.stubGlobal('chrome', {
      tabs: {
        query: vi.fn(async () => [
          { id: 7, url: 'http://yifeng.dtsum.com/purchase/apply' },
        ]),
      },
    });
  });

  it('shows the selected system and requires an objective before recording', async () => {
    render(<PopupApp />);

    expect(await screen.findByText('益丰 MES')).toBeVisible();
    expect(screen.getByLabelText('演示目标')).toBeVisible();
    expect(screen.getByRole('button', { name: '开始录制' })).toBeDisabled();
    expect(screen.queryByText(/同时观察 API/)).not.toBeInTheDocument();
    expect(screen.queryByText(/debugger/i)).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('演示目标'), '查询采购申请');
    expect(screen.getByRole('button', { name: '开始录制' })).toBeEnabled();
  });

  it('starts recording with the user objective', async () => {
    vi.mocked(sendRuntimeMessage)
      .mockResolvedValueOnce({ active: false, traceId: null, row: null })
      .mockResolvedValueOnce({
        active: true,
        traceId: 'tr_test',
        row: {
          trace_id: 'tr_test',
          status: 'recording',
          envelope: {
            started_at: new Date().toISOString(),
            summary: { event_counts: {} },
          },
        },
      });
    render(<PopupApp />);
    await screen.findByText('益丰 MES');

    await userEvent.type(screen.getByLabelText('演示目标'), '查询采购申请');
    await userEvent.click(screen.getByRole('button', { name: '开始录制' }));

    await waitFor(() =>
      expect(sendRuntimeMessage).toHaveBeenCalledWith({
        type: 'start-recording',
        label: '查询采购申请',
      }),
    );
  });
});
