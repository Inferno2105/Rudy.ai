import { resolve } from 'node:path'

import { defineConfig, devices } from '@playwright/test'

/**
 * One end-to-end path through the real stack: the built UI served by the real
 * FastAPI app, with the model pipeline replaced by a stub
 * (`backend/tests/e2e_server.py`) and all data in a temporary directory.
 *
 * Run `npm run build` first; the server serves `dist/`.
 */
const port = Number(process.env.E2E_PORT ?? 8765)

// Absolute paths: on Windows the command runs through cmd.exe, which cannot
// execute a relative "../" path.
const python = resolve(
  process.env.E2E_PYTHON ??
    (process.platform === 'win32' ? '../venv312/Scripts/python.exe' : '../venv312/bin/python'),
)
const server = resolve('../backend/tests/e2e_server.py')

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: `"${python}" "${server}" --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
