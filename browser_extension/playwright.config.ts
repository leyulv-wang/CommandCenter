import { defineConfig } from '@playwright/test';
import path from 'node:path';

const projectRoot = path.resolve(import.meta.dirname, '..');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 480_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      name: 'command-center',
      command:
        'conda run -n langgraph python -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: projectRoot,
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      name: 'purchase-system',
      command:
        'conda run -n langgraph python -m uvicorn external_systems.connected_system.main:app --host 127.0.0.1 --port 8101',
      cwd: projectRoot,
      url: 'http://127.0.0.1:8101/api/system-profile',
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
