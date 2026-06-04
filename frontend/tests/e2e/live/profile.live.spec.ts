/**
 * Live integration spec — profiling stage.
 *
 * Runs against a real backend serving qa/workspaces/${QA_WORKSPACE}/state.json.
 * No API routes are mocked. Asserts actual rendered values from the fixture,
 * not just DOM presence.
 *
 * Run with:
 *   QA_WORKSPACE=profiling           pnpm playwright test --config playwright.live.config.ts
 *   QA_WORKSPACE=profiling_deviation pnpm playwright test --config playwright.live.config.ts
 *
 * The deviation variant (total_rows/total_columns) specifically tests the
 * frontend's ?? fallback — this test would have caught the post-Night-2
 * regression before it reached the human reviewer.
 */

import { test, expect } from "@playwright/test";

test.describe("profile view — live backend", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("profile-view")).toBeVisible({ timeout: 8_000 });
  });

  test("shape strip renders row count from fixture", async ({ page }) => {
    const strip = page.getByTestId("shape-strip");
    await expect(strip).toBeVisible();
    // Fixture has 100 rows (either via rows or total_rows — both render as "100")
    await expect(strip).toContainText("100");
  });

  test("shape strip renders column count from fixture", async ({ page }) => {
    const strip = page.getByTestId("shape-strip");
    await expect(strip).toBeVisible();
    // Fixture has 9 columns (either via columns or total_columns)
    await expect(strip).toContainText("9");
  });

  test("shape strip renders inferred target from fixture", async ({ page }) => {
    const strip = page.getByTestId("shape-strip");
    await expect(strip).toContainText("churned");
  });

  test("column rows render real column names from fixture", async ({ page }) => {
    const rows = page.getByTestId("column-row");
    await expect(rows.first()).toBeVisible();
    // Fixture columns include customer_id, plan_tier, monthly_spend, churned
    const allText = await page.getByTestId("profile-view").textContent();
    expect(allText).toContain("customer_id");
    expect(allText).toContain("plan_tier");
  });

  test("reprof-input and reprof-submit are present and wired", async ({ page }) => {
    await expect(page.getByTestId("reprof-input")).toBeVisible();
    await expect(page.getByTestId("reprof-submit")).toBeVisible();
    // Submit disabled when input is empty
    await expect(page.getByTestId("reprof-submit")).toBeDisabled();
  });

  test("accept profile button is present and enabled", async ({ page }) => {
    const btn = page.getByTestId("profile-accept-btn");
    await expect(btn).toBeVisible();
    await expect(btn).toBeEnabled();
  });
});
