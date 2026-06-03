/**
 * Live integration spec — planning stage.
 *
 * Run with:
 *   QA_WORKSPACE=planning pnpm playwright test --config playwright.live.config.ts
 */

import { test, expect } from "@playwright/test";

test.describe("plan view — live backend", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("plan-view")).toBeVisible({ timeout: 8_000 });
  });

  test("plan section list renders all fixture sections", async ({ page }) => {
    const list = page.getByTestId("plan-section-list");
    await expect(list).toBeVisible();
    // Fixture has 3 sections
    const rows = list.getByTestId(/^plan-section-/);
    await expect(rows).toHaveCount(3);
  });

  test("section titles from fixture are rendered", async ({ page }) => {
    const viewText = await page.getByTestId("plan-view").textContent();
    expect(viewText).toContain("Churn Baseline");
    expect(viewText).toContain("Plan and Spend");
    expect(viewText).toContain("Engagement and Tenure");
  });

  test("aim from fixture is present in the page", async ({ page }) => {
    // The aim is shown in the header
    const body = await page.locator("body").textContent();
    expect(body).toContain("understand drivers of customer churn");
  });

  test("plan-turn-input accepts text and enables submit", async ({ page }) => {
    const input = page.getByTestId("plan-turn-input");
    const submit = page.getByTestId("plan-turn-submit");
    await expect(submit).toBeDisabled();
    await input.fill("add a section on regional cohorts");
    await expect(submit).toBeEnabled();
  });

  test("plan-accept-btn is present and enabled", async ({ page }) => {
    const btn = page.getByTestId("plan-accept-btn");
    await expect(btn).toBeVisible();
    await expect(btn).toBeEnabled();
  });
});
