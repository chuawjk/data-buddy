// Playwright structural spec — Plan screen
//
// Structural checks only — asserts that required data-testid elements are present
// in the rendered DOM at the planning stage. Does not test API wiring or live backend.

import { test, expect } from "@playwright/test";

test.describe("Plan screen — structural", () => {
  test("plan-view mounts with plan-section-list and items at planning stage", async ({ page }) => {
    // Intercept /api/state to return planning stage with two sections
    await page.route("/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          version: "1",
          stage: "planning",
          aim: "Understand churn",
          dataset_path: "data/customers.csv",
          last_saved: "2026-06-03T00:00:00Z",
          profile: null,
          plan: [
            {
              id: "sec_01",
              title: "Overview",
              hypothesis: "Revenue correlates with age",
              status: "queued",
              py_path: null,
              png_path: null,
              md_path: null,
            },
            {
              id: "sec_02",
              title: "Churn Analysis",
              hypothesis: "High-risk customers churn within 90 days",
              status: "queued",
              py_path: null,
              png_path: null,
              md_path: null,
            },
          ],
        }),
      });
    });

    // Stub SSE endpoint to avoid connection errors
    await page.route("/api/events", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: ": keepalive\n\n",
      });
    });

    await page.goto("/");

    // plan-view must mount
    await expect(page.getByTestId("plan-view")).toBeVisible();

    // plan-section-list must be present
    await expect(page.getByTestId("plan-section-list")).toBeVisible();

    // Both sections must be present
    await expect(page.getByTestId("plan-section-sec_01")).toBeVisible();
    await expect(page.getByTestId("plan-section-sec_02")).toBeVisible();

    // plan-accept-btn must be present
    await expect(page.getByTestId("plan-accept-btn")).toBeVisible();
  });

  test("plan-turn-input and plan-turn-submit are present at planning stage", async ({ page }) => {
    await page.route("/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          version: "1",
          stage: "planning",
          aim: "Understand churn",
          dataset_path: "data/customers.csv",
          last_saved: "2026-06-03T00:00:00Z",
          profile: null,
          plan: [
            {
              id: "sec_01",
              title: "Overview",
              hypothesis: "Hypothesis",
              status: "queued",
              py_path: null,
              png_path: null,
              md_path: null,
            },
          ],
        }),
      });
    });

    await page.route("/api/events", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: ": keepalive\n\n",
      });
    });

    await page.goto("/");

    await expect(page.getByTestId("plan-turn-input")).toBeVisible();
    await expect(page.getByTestId("plan-turn-submit")).toBeVisible();
    // Submit is disabled when input is empty
    await expect(page.getByTestId("plan-turn-submit")).toBeDisabled();
  });

  test("plan-view renders with empty sections array — no crash", async ({ page }) => {
    await page.route("/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          version: "1",
          stage: "planning",
          aim: "Understand churn",
          dataset_path: "data/customers.csv",
          last_saved: "2026-06-03T00:00:00Z",
          profile: null,
          plan: [],
        }),
      });
    });

    await page.route("/api/events", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: ": keepalive\n\n",
      });
    });

    await page.goto("/");

    await expect(page.getByTestId("plan-view")).toBeVisible();
    await expect(page.getByTestId("plan-section-list")).toBeVisible();
    await expect(page.getByTestId("plan-accept-btn")).toBeVisible();
  });
});
