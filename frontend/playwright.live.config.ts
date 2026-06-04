/**
 * Playwright live integration config.
 *
 * Unlike the mocked e2e specs (playwright.config.ts), these tests run against
 * a real backend serving a pre-loaded fixture workspace. No API routes are
 * intercepted — the full frontend → HTTP → backend → state stack is exercised.
 *
 * Usage:
 *   QA_WORKSPACE=profiling            pnpm playwright test --config playwright.live.config.ts
 *   QA_WORKSPACE=profiling_deviation  pnpm playwright test --config playwright.live.config.ts
 *   QA_WORKSPACE=planning             pnpm playwright test --config playwright.live.config.ts
 *
 * QA_WORKSPACE defaults to "profiling" if unset.
 */

import { defineConfig } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const REPO_ROOT = path.resolve(fileURLToPath(import.meta.url), "../..");
const workspace = process.env.QA_WORKSPACE ?? "profiling";

// Each workspace only exercises the spec files relevant to its stage —
// profiling and profiling_deviation run profile specs; planning runs plan specs.
const TEST_MATCH: Record<string, string> = {
  profiling: "**/*profile*.live.spec.ts",
  profiling_deviation: "**/*profile*.live.spec.ts",
  planning: "**/*plan*.live.spec.ts",
  building: "**/*build*.live.spec.ts",
};
const testMatch = TEST_MATCH[workspace] ?? "**/*.live.spec.ts";

export default defineConfig({
  testDir: "./tests/e2e/live",
  testMatch,
  use: {
    baseURL: "http://localhost:5173",
    // Give real HTTP calls more time than mocked tests need
    actionTimeout: 10_000,
  },
  // Each live run gets a fresh server — never reuse a server whose workspace
  // may have been mutated by a previous test run.
  webServer: [
    {
      command: `SKIP_OPENCODE=1 WORKSPACE_ROOT=qa/workspaces/${workspace} uv run --project backend uvicorn backend.main:app --port 8000`,
      url: "http://localhost:8000/health",
      reuseExistingServer: false,
      cwd: REPO_ROOT,
      timeout: 20_000,
    },
    {
      command: "pnpm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: false,
      timeout: 20_000,
    },
  ],
});
