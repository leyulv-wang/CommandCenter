import { useEffect, useState } from 'react';
import {
  profileForUrl,
  type CommandCenterProfile,
} from '@/command-center/config';
import type { CommandCenterRecordingStatus } from '@/command-center/client';
import { errorMessage } from '@/shared/errors';
import { sendRuntimeMessage } from '@/shared/runtime';
import type { RecordingRow } from '@/shared/types';
import { getConfig } from '@/storage/db';
import { Alert, Badge, Button, Card, CardContent, Input } from '@/ui/primitives';

type ActiveRecordingResponse = {
  active: boolean;
  traceId: string | null;
  row?: RecordingRow | null;
};

type RecordingActionResponse = ActiveRecordingResponse & {
  row?: RecordingRow;
};

type View = 'loading' | 'idle' | 'recording' | 'processing';

export function PopupApp() {
  const [view, setView] = useState<View>('loading');
  const [profile, setProfile] = useState<CommandCenterProfile | null>(null);
  const [tabHost, setTabHost] = useState('未选择可录制页面');
  const [objective, setObjective] = useState('');
  const [activeRow, setActiveRow] = useState<RecordingRow | null>(null);
  const [remoteStatus, setRemoteStatus] = useState<CommandCenterRecordingStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [config, active, tabs] = await Promise.all([
          getConfig(),
          sendRuntimeMessage<ActiveRecordingResponse>({ type: 'get-active-recording' }),
          chrome.tabs.query({ active: true, currentWindow: true }),
        ]);
        if (cancelled) return;
        const tabUrl = tabs[0]?.url ?? '';
        const selected = profileForUrl(tabUrl, config.commandCenterProfiles);
        setProfile(selected);
        setTabHost(hostFor(tabUrl));
        if (active.active && active.row) {
          setActiveRow(active.row);
          setObjective(active.row.envelope.label ?? '');
          setView('recording');
        } else {
          setView('idle');
        }
      } catch (caught) {
        if (!cancelled) {
          setError(errorMessage(caught));
          setView('idle');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (view !== 'processing' || !activeRow) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await sendRuntimeMessage<CommandCenterRecordingStatus>({
          type: 'get-command-center-status',
          traceId: activeRow.trace_id,
        });
        if (!cancelled) setRemoteStatus(status);
      } catch {
        // The local upload result remains visible; polling is best-effort.
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 1_500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [view, activeRow]);

  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function start(): void {
    if (!profile || !objective.trim()) return;
    void run(async () => {
      const response = await sendRuntimeMessage<RecordingActionResponse>({
        type: 'start-recording',
        label: objective.trim(),
      });
      if (!response.row) throw new Error('扩展未返回录制会话。');
      setActiveRow(response.row);
      setRemoteStatus(null);
      setView('recording');
    });
  }

  function stop(): void {
    if (!activeRow) return;
    void run(async () => {
      const response = await sendRuntimeMessage<RecordingActionResponse>({
        type: 'stop-recording',
        traceId: activeRow.trace_id,
      });
      if (!response.row) throw new Error('扩展未返回上传结果。');
      setActiveRow(response.row);
      setRemoteStatus({
        recording_id: response.row.command_center?.recording_id ?? '',
        status:
          response.row.status === 'failed'
            ? 'failed'
            : response.row.command_center?.remote_status ?? 'queued',
      });
      setView('processing');
    });
  }

  function reset(): void {
    setActiveRow(null);
    setRemoteStatus(null);
    setObjective('');
    setView('idle');
  }

  const canStart =
    view === 'idle' && Boolean(profile) && Boolean(objective.trim()) && !busy;

  return (
    <main className="jf-popup">
      <header className="jf-header">
        <div>
          <p className="jf-eyebrow">COMMANDCENTER</p>
          <h1 className="jf-title">演示观察器</h1>
        </div>
        <span
          className={view === 'recording' ? 'jf-dot recording' : 'jf-dot'}
          aria-hidden
        />
      </header>

      {error ? <Alert tone="danger">{error}</Alert> : null}

      <Card>
        <CardContent>
          <div className="jf-rec-top">
            <span className="jf-muted">当前业务系统</span>
            <Badge tone={profile ? 'success' : 'warning'}>
              {profile ? '已匹配' : '不可录制'}
            </Badge>
          </div>
          <strong>{profile?.displayName ?? '没有匹配的系统配置'}</strong>
          <p className="jf-domains">{tabHost}</p>
        </CardContent>
      </Card>

      {view === 'loading' ? <p className="jf-muted">正在读取录制状态…</p> : null}

      {view === 'idle' ? (
        <>
          <label className="jf-field">
            <span>演示目标</span>
            <Input
              aria-label="演示目标"
              value={objective}
              placeholder="例如：查询采购申请"
              onChange={(event) => setObjective(event.target.value)}
              disabled={busy}
            />
          </label>
          <p className="jf-muted">页面操作和对应 API 会记录在同一条时间轨迹中。</p>
          <Button
            variant="primary"
            className="jf-wide"
            onClick={start}
            disabled={!canStart}
          >
            开始录制
          </Button>
        </>
      ) : null}

      {view === 'recording' ? (
        <>
          <Alert tone="warning">正在录制：{objective}</Alert>
          <Button
            variant="danger"
            className="jf-wide"
            onClick={stop}
            disabled={busy}
          >
            停止录制并学习
          </Button>
        </>
      ) : null}

      {view === 'processing' ? (
        <>
          <Alert tone={statusTone(remoteStatus?.status)}>
            {statusText(remoteStatus?.status)}
          </Alert>
          {activeRow?.command_center?.recording_id ? (
            <p className="jf-domains">
              录制编号：{activeRow.command_center.recording_id}
            </p>
          ) : null}
          <Button className="jf-wide" onClick={reset} disabled={busy}>
            录制下一个任务
          </Button>
        </>
      ) : null}
    </main>
  );
}

function hostFor(value: string): string {
  try {
    return new URL(value).host;
  } catch {
    return '无法读取当前页面地址';
  }
}

function statusText(status: string | undefined): string {
  const labels: Record<string, string> = {
    queued: '证据已上传，等待智能体学习。',
    learning: '智能体正在对齐页面操作和 API。',
    testing: '候选 Skill 正在进行无害测试。',
    published: 'Skill 已通过测试并发布。',
    verified_candidate: 'API Skill 已验证。',
    browser_candidate: '没有可靠 API，已保存为浏览器候选。',
    needs_reteach: '本次演示未能生成 Skill，请查看中控提示。',
    failed: '处理失败，证据仍保存在本地。',
  };
  return labels[status ?? ''] ?? '证据已提交，中控正在处理。';
}

function statusTone(status: string | undefined): 'success' | 'warning' | 'danger' {
  if (status === 'published' || status === 'verified_candidate') return 'success';
  if (status === 'failed' || status === 'needs_reteach') return 'danger';
  return 'warning';
}
