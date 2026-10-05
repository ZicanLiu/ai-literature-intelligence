import { defineConfig } from '@playwright/test'
import path from 'node:path'
const root = path.resolve(import.meta.dirname, '../..')
const python = process.env.COMPARISON_TEST_PYTHON || 'python'
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: { baseURL:'http://127.0.0.1:8876', viewport:{width:1440,height:900}, trace:'retain-on-failure', screenshot:'only-on-failure' },
  webServer: [{
    command: '"' + python + '" -m app.comparison_workspace_main --data-dir temp/workspace-browser-tests --port 8876',
    cwd:root,
    url:'http://127.0.0.1:8876/api/capabilities',
    reuseExistingServer:false,
    timeout:60000,
    env:{ DISABLE_LIVE_API:'true' },
  }, {
    command: '"' + python + '" -m tests.fixtures.comparison_workspace.mock_live_server --data-dir temp/workspace-live-browser-tests --port 8877',
    cwd:root,
    url:'http://127.0.0.1:8877/api/capabilities',
    reuseExistingServer:false,
    timeout:60000,
    env:{ DISABLE_LIVE_API:'false' },
  }],
})
