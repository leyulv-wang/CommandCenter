import {
  chromium,
  type BrowserContext,
  type Page,
  type Worker,
} from '@playwright/test';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

export type ExtensionHarness = {
  context: BrowserContext;
  worker: Worker;
  extensionId: string;
  cleanup(): Promise<void>;
};

export async function launchExtensionContext(): Promise<ExtensionHarness> {
  const extensionPath = path.resolve(import.meta.dirname, '../dist/chrome-mv3');
  const userDataDir = await mkdtemp(
    path.join(os.tmpdir(), 'command-center-extension-e2e-'),
  );
  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
    ],
  });
  const worker =
    context.serviceWorkers()[0] ??
    (await context.waitForEvent('serviceworker', { timeout: 15_000 }));
  const extensionId = new URL(worker.url()).host;

  return {
    context,
    worker,
    extensionId,
    async cleanup() {
      await context.close();
      await rm(userDataDir, { recursive: true, force: true });
    },
  };
}

export async function sendExtensionMessage<T>(
  page: Page,
  message: Record<string, unknown>,
): Promise<T> {
  return await page.evaluate(async (payload) => {
    const runtime = (
      globalThis as typeof globalThis & {
        chrome: { runtime: { sendMessage(value: unknown): Promise<unknown> } };
      }
    ).chrome.runtime;
    return await runtime.sendMessage(payload);
  }, message) as T;
}

export async function readRecordingEvidenceSummary(worker: Worker): Promise<{
  traceId: string;
  kinds: string[];
  remoteRecordingId: string;
}> {
  return await worker.evaluate(async () => {
    const open = indexedDB.open('journey-forge-local');
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error);
    });
    try {
      const rows = await new Promise<Array<Record<string, unknown>>>((resolve, reject) => {
        const request = database
          .transaction('recordings', 'readonly')
          .objectStore('recordings')
          .getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const latest = rows
        .filter((row) => Boolean(row.command_center))
        .sort(
          (left, right) =>
            Number(right.updated_at ?? 0) - Number(left.updated_at ?? 0),
        )[0];
      if (!latest) throw new Error('No CommandCenter recording in extension storage.');
      const traceId = String(latest.trace_id);
      const events = await new Promise<Array<Record<string, unknown>>>((resolve, reject) => {
        const request = database
          .transaction('events', 'readonly')
          .objectStore('events')
          .index('trace_id')
          .getAll(traceId);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const connection = latest.command_center as Record<string, unknown>;
      return {
        traceId,
        kinds: events.map((event) => String(event.kind)),
        remoteRecordingId: String(connection.recording_id),
      };
    } finally {
      database.close();
    }
  });
}
