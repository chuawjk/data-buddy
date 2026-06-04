// section-build.spec.ts — N2-S16 @N2-S16
// Playwright structural gate: verifies QA-seam testids are present on the build screen.
// Tagged @N2-S16.
//
// These tests mock the API so they don't require a running backend.
// They assert structural presence of testids, not interactive behaviour
// (that is covered by Vitest unit tests).

import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Mock state: building stage with one building and one proposed section
// ---------------------------------------------------------------------------

const MOCK_STATE = {
  version: "1",
  stage: "building",
  aim: "Understand churn drivers",
  dataset_path: "data/customers.csv",
  last_saved: "2026-06-03T00:00:00Z",
  profile: {
    shape: { rows: 12450, columns: 9, nulls_pct: 0.2, target: "churned" },
    columns: [],
    flags: [],
  },
  plan: [
    {
      id: "sec-01",
      title: "Cohort overview",
      hypothesis: "Check churn baseline",
      status: "proposed",
      py_path: "analyses/01_cohort.py",
      png_path: "charts/01_cohort.png",
      md_path: "sections/01_cohort.md",
    },
    {
      id: "sec-02",
      title: "Churn by plan tier",
      hypothesis: "Higher tiers have lower churn",
      status: "building",
      py_path: null,
      png_path: null,
      md_path: null,
    },
  ],
};

const MOCK_PY = `import pandas as pd\ndf = pd.read_csv("data.csv")`;
const MOCK_MD = `Churn rate is 14.3% for the cohort.`;

test.describe("@N2-S16 Section build screen — structural gate", () => {
  test.beforeEach(async ({ page }) => {
    // Mock GET /api/state
    await page.route("**/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_STATE),
      });
    });

    // Mock GET /api/file for .py and .md files
    await page.route("**/api/file**", (route) => {
      const url = route.request().url();
      if (url.includes(".py")) {
        void route.fulfill({ status: 200, contentType: "text/plain", body: MOCK_PY });
      } else if (url.includes(".md")) {
        void route.fulfill({ status: 200, contentType: "text/plain", body: MOCK_MD });
      } else if (url.includes(".png")) {
        // Serve a tiny 1x1 PNG for chart images
        void route.fulfill({
          status: 200,
          contentType: "image/png",
          body: Buffer.from(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "base64"
          ),
        });
      } else {
        void route.fulfill({ status: 200, contentType: "text/plain", body: "" });
      }
    });

    // Mock SSE endpoint — return empty stream
    await page.route("**/api/events", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "",
      });
    });

    await page.goto("/");
  });

  // ── build-view mounts ─────────────────────────────────────────────────────

  test("build-view mounts for stage=building", async ({ page }) => {
    await expect(page.getByTestId("build-view")).toBeVisible();
  });

  // ── section-list is present ───────────────────────────────────────────────

  test("section-list present with section rows", async ({ page }) => {
    await expect(page.getByTestId("section-list")).toBeVisible();
    await expect(page.getByTestId("section-row-sec-01")).toBeVisible();
    await expect(page.getByTestId("section-row-sec-02")).toBeVisible();
  });

  // ── section-status testids present ───────────────────────────────────────

  test("section-status testids present for each section", async ({ page }) => {
    await expect(page.getByTestId("section-status-sec-01")).toBeVisible();
    await expect(page.getByTestId("section-status-sec-02")).toBeVisible();
  });

  // ── section-pane present ─────────────────────────────────────────────────

  test("section-pane present with correct testids", async ({ page }) => {
    await expect(page.getByTestId("section-pane")).toBeVisible();
    await expect(page.getByTestId("section-pane-title")).toBeVisible();
  });

  // ── building spinner shown for building section ───────────────────────────

  test("section-building-spinner visible when active section is building", async ({ page }) => {
    await expect(page.getByTestId("section-building-spinner")).toBeVisible();
  });

  // ── per-section revision controls present (global bottom bar was removed post-Night-2) ──

  test("section-revise-input and section-revise-btn present on proposed section", async ({ page }) => {
    const proposedOnlyState = {
      ...MOCK_STATE,
      plan: [
        {
          id: "sec-01",
          title: "Cohort overview",
          hypothesis: "Check churn baseline",
          status: "proposed",
          py_path: "analyses/01_cohort.py",
          png_path: "charts/01_cohort.png",
          md_path: "sections/01_cohort.md",
        },
      ],
    };

    await page.route("**/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(proposedOnlyState),
      });
    });

    await page.goto("/");

    await expect(page.getByTestId("section-revise-input")).toBeVisible();
    await expect(page.getByTestId("section-revise-btn")).toBeVisible();
  });

  // ── section-accept-btn and section-drop-btn visible for proposed section ──

  test("section-accept-btn and section-drop-btn visible for proposed section", async ({
    page,
  }) => {
    // The proposed section (sec-01) is the most recently proposed when sec-02 is building.
    // After sec-02 finishes building, sec-01 shows accept/drop.
    // Since sec-02 is building, it is the active section (building takes priority).
    // To see accept/drop, we need a state where the active section is proposed.
    const proposedOnlyState = {
      ...MOCK_STATE,
      plan: [
        {
          id: "sec-01",
          title: "Cohort overview",
          hypothesis: "Check churn baseline",
          status: "proposed",
          py_path: "analyses/01_cohort.py",
          png_path: "charts/01_cohort.png",
          md_path: "sections/01_cohort.md",
        },
      ],
    };

    await page.route("**/api/state", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(proposedOnlyState),
      });
    });

    await page.goto("/");

    await expect(page.getByTestId("section-accept-btn")).toBeVisible();
    await expect(page.getByTestId("section-drop-btn")).toBeVisible();
  });
});
