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
          { id: 7, url: 'http://127.0.0.1:8101/' },
        ]),
      },
    });
  });

  it('shows the selected system and requires an objective before recording', async () => {
    render(<PopupApp />);

    expect(await screen.findByText('采购业务系统')).toBeVisible();
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
    await screen.findByText('采购业务系统');

    await userEvent.type(screen.getByLabelText('演示目标'), '查询采购申请');
    await userEvent.click(screen.getByRole('button', { name: '开始录制' }));

    await waitFor(() =>
      expect(sendRuntimeMessage).toHaveBeenCalledWith({
        type: 'start-recording',
        label: '查询采购申请',
      }),
    );
  });

  it('restores a failed local upload instead of returning to the idle form', async () => {
    vi.mocked(sendRuntimeMessage).mockImplementation(async (message: unknown) => {
      if ((message as { type?: string }).type === 'get-command-center-status') {
        return {
          recording_id: 'remote-failed',
          status: 'failed',
        } as never;
      }
      return {
        active: false,
        traceId: null,
        row: {
          trace_id: 'tr_failed',
          status: 'failed',
          envelope: {
            label: '查询采购申请',
            started_at: new Date().toISOString(),
            summary: { event_counts: {} },
          },
          command_center: {
            recording_id: 'remote-failed',
            remote_status: 'failed',
          },
        },
      } as never;
    });

    render(<PopupApp />);

    expect(
      await screen.findByText('处理失败，证据仍保存在本地。'),
    ).toBeVisible();
    expect(screen.queryByLabelText('演示目标')).not.toBeInTheDocument();
  });

  it('restores an uploaded recording that is still learning', async () => {
    vi.mocked(sendRuntimeMessage).mockImplementation(async (message: unknown) => {
      if ((message as { type?: string }).type === 'get-command-center-status') {
        return {
          recording_id: 'remote-learning',
          status: 'learning',
        } as never;
      }
      return {
        active: false,
        traceId: null,
        row: {
          trace_id: 'tr_learning',
          status: 'uploaded',
          envelope: {
            label: '查询采购申请',
            started_at: new Date().toISOString(),
            summary: { event_counts: {} },
          },
          command_center: {
            recording_id: 'remote-learning',
            remote_status: 'learning',
          },
        },
      } as never;
    });

    render(<PopupApp />);

    expect(
      await screen.findByText('智能体正在对齐页面操作和 API。'),
    ).toBeVisible();
  });
});
