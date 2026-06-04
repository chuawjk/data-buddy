/**
 * Live integration spec — building stage.
 *
 * Run with:
 *   QA_WORKSPACE=building pnpm playwright test --config playwright.live.config.ts
 *
 * Fixture workspace: qa/workspaces/building/
 *   sec_01 — accepted, has md_path + py_path (interpretation + code visible)
 *   sec_02 — proposed, has md_path + py_path (revision + accept/drop controls)
 *   sec_03 — queued, no artefacts (no pane rendered)
 */

import { test, expect } from "@playwright/test";

test.describe("build view — live backend", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("build-view")).toBeVisible({ timeout: 8_000 });
  });

  test("section list shows all fixture sections", async ({ page }) => {
    const list = page.getByTestId("section-list");
    await expect(list).toBeVisible();
    await expect(list.locator('[data-testid^="section-row-"]')).toHaveCount(3);
  });

  test("section status badges reflect fixture state", async ({ page }) => {
    await expect(page.getByTestId("section-status-sec_01")).toHaveText(/accepted/i);
    await expect(page.getByTestId("section-status-sec_02")).toHaveText(/proposed/i);
    await expect(page.getByTestId("section-status-sec_03")).toHaveText(/queued/i);
  });

  test("accepted section pane renders interpretation from fixture md file", async ({ page }) => {
    // sec_01 is accepted — first pane; artefacts load via GET /file
    const pane = page.locator('[data-testid="section-pane"]').first();
    const interp = pane.getByTestId("section-interpretation");
    await expect(interp).toBeVisible({ timeout: 5_000 });
    await expect(interp).toContainText("23.4%");
  });

  test("accepted section pane has code toggle", async ({ page }) => {
    // sec_01 has py_path — code toggle should be present
    const pane = page.locator('[data-testid="section-pane"]').first();
    await expect(pane.getByTestId("section-code-toggle")).toBeVisible({ timeout: 5_000 });
  });

  test("proposed section pane renders interpretation and revision controls", async ({
    page,
  }) => {
    // sec_02 is proposed — second pane
    const pane = page.locator('[data-testid="section-pane"]').nth(1);
    await expect(pane.getByTestId("section-interpretation")).toBeVisible({ timeout: 5_000 });
    await expect(pane.getByTestId("section-revise-input")).toBeVisible();
    await expect(pane.getByTestId("section-revise-btn")).toBeVisible();
    await expect(pane.getByTestId("section-accept-btn")).toBeVisible();
    await expect(pane.getByTestId("section-drop-btn")).toBeVisible();
  });

  test("queued section has no pane rendered", async ({ page }) => {
    // sec_03 is queued — getSectionPanes() excludes it
    const panes = page.locator('[data-testid="section-pane"]');
    await expect(panes).toHaveCount(2);
  });

  test("export button is enabled because one section is accepted", async ({ page }) => {
    await expect(page.getByTestId("export-btn")).toBeVisible();
    await expect(page.getByTestId("export-btn")).toBeEnabled();
  });
});
