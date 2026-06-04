// Playwright structural spec — N2-S17 · Export control
// Tagged @N2-S17 so it can be run in isolation: pnpm playwright test --grep @N2-S17
//
// Structural checks only — asserts that required data-testid elements are present
// in the rendered DOM at the building stage. Does not test API wiring or live backend.

import { test, expect } from "@playwright/test";

// MSW / stub fixtures: the structural tests run against a Vite dev server that
// intercepts /api/state via the browser's service worker or a request interceptor.
// For the lane self-gate, we verify the element structure only (data-testid presence
// and basic disabled state). Full export behaviour is QA's responsibility.

test.describe("@N2-S17 Export control — structural", () => {
  test("export-btn is present in the header at building stage with no accepted sections", async ({
    page,
  }) => {
    // Intercept /api/state to return building stage with no accepted sections
    await page.route("/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          version: "1",
          stage: "building",
          aim: "Understand churn",
          dataset_path: "data/customers.csv",
          last_saved: "2026-06-03T00:00:00Z",
          profile: null,
          plan: [],
        }),
      });
    });

    // Stub the SSE endpoint to avoid connection errors
    await page.route("/api/events", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: ": keepalive\n\n",
      });
    });

    await page.goto("/");

    // export-btn must be present and disabled (0 accepted sections)
    const exportBtn = page.getByTestId("export-btn");
    await expect(exportBtn).toBeVisible();
    await expect(exportBtn).toBeDisabled();
  });

  test("export-btn is enabled when plan contains an accepted section at building stage", async ({
    page,
  }) => {
    await page.route("/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          version: "1",
          stage: "building",
          aim: "Understand churn",
          dataset_path: "data/customers.csv",
          last_saved: "2026-06-03T00:00:00Z",
          profile: null,
          plan: [
            {
              id: "sec_01",
              title: "Overview",
              hypothesis: "Revenue correlates with age",
              status: "accepted",
              py_path: "sections/sec_01.py",
              png_path: "sections/sec_01.png",
              md_path: "sections/sec_01.md",
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

    const exportBtn = page.getByTestId("export-btn");
    await expect(exportBtn).toBeVisible();
    await expect(exportBtn).toBeEnabled();
  });

  test("export-btn is absent at setup stage", async ({ page }) => {
    await page.route("/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          version: "1",
          stage: "setup",
          aim: "",
          dataset_path: "",
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

    // At setup stage, export-btn should not be rendered
    await expect(page.getByTestId("setup-view")).toBeVisible();
    await expect(page.getByTestId("export-btn")).not.toBeVisible();
  });
});
