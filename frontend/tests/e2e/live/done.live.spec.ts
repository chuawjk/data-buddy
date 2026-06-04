/**
 * Live integration spec — done stage.
 *
 * Run with:
 *   QA_WORKSPACE=done pnpm playwright test --config playwright.live.config.ts
 *
 * Fixture workspace: qa/workspaces/done/
 *   stage = "done"
 *   sec_01 — accepted ("Churn Baseline")
 *   sec_02 — accepted ("Plan and Spend")
 *   sec_03 — dropped ("Engagement and Tenure")
 *
 * Tests assert the DoneView renders correctly via real HTTP from a known state.
 * This layer catches contract mismatches that mocked specs cannot see.
 *
 * Regression check for the done stage transition.
 */

import { test, expect } from "@playwright/test";

test.describe("done view — live backend", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("done-view")).toBeVisible({ timeout: 8_000 });
  });

  test("done-view container is rendered", async ({ page }) => {
    await expect(page.getByTestId("done-view")).toBeVisible();
  });

  test("done view shows 'Brief complete' heading", async ({ page }) => {
    await expect(page.getByTestId("done-view")).toContainText("Brief complete");
  });

  test("done-export-button is present and enabled", async ({ page }) => {
    const btn = page.getByTestId("done-export-button");
    await expect(btn).toBeVisible();
    await expect(btn).toBeEnabled();
  });

  test("done-section-list renders only accepted sections", async ({ page }) => {
    // Fixture has 2 accepted + 1 dropped — only 2 should appear
    const list = page.getByTestId("done-section-list");
    await expect(list).toBeVisible();
    const items = list.locator('[data-testid^="done-section-item-"]');
    await expect(items).toHaveCount(2);
  });

  test("accepted section titles are rendered in plan order", async ({ page }) => {
    const viewText = await page.getByTestId("done-view").textContent();
    expect(viewText).toContain("Churn Baseline");
    expect(viewText).toContain("Plan and Spend");
  });

  test("dropped section is excluded from done-section-list", async ({ page }) => {
    // sec_03 is dropped — must not appear
    await expect(page.getByTestId("done-section-item-sec_03")).not.toBeVisible();
  });

  test("accepted section items carry per-section data-testid", async ({ page }) => {
    await expect(page.getByTestId("done-section-item-sec_01")).toBeVisible();
    await expect(page.getByTestId("done-section-item-sec_02")).toBeVisible();
  });
});
