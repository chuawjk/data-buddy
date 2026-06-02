// Tests for ProfileView — TDD: tests written first against acceptance criteria.
// Mocks useApi and useSSE so tests are fast and deterministic.
//
// Acceptance criteria (N1-S16):
//   - shape strip ("Rows: N | Columns: N") — data-testid="shape-strip"
//   - one column-row per column — data-testid="column-row"
//   - column detail: name, type, summary visible per row
//   - bottom-bar submit disabled when input is empty
//   - bottom-bar submit calls api.postTurn with input text, then clears input
//   - on profile.ready SSE event: re-fetches state via api.getState
//   - hydrates correctly from a passed profile prop (simulates page refresh)

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProfileView from "./ProfileView";
import type { Profile } from "../../types/api";

// ---------------------------------------------------------------------------
// Mock useApi
// ---------------------------------------------------------------------------

const mockGetState = vi.fn();
const mockPostTurn = vi.fn();

vi.mock("../../hooks/useApi", () => ({
  api: {
    getState: (...args: unknown[]) => mockGetState(...args),
    postTurn: (...args: unknown[]) => mockPostTurn(...args),
  },
}));

// ---------------------------------------------------------------------------
// Mock useSSE — captures onEvent callback so tests can emit SSE events
// ---------------------------------------------------------------------------

let capturedOnEvent: ((event: unknown) => void) | null = null;

vi.mock("../../hooks/useSSE", () => ({
  useSSE: (onEvent: (event: unknown) => void) => {
    capturedOnEvent = onEvent;
    return { connected: true };
  },
}));

function dispatchSSEEvent(event: unknown) {
  act(() => {
    if (capturedOnEvent) capturedOnEvent(event);
  });
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SAMPLE_PROFILE: Profile = {
  shape: { rows: 12450, columns: 9, nulls_pct: 0.2, target: "churned" },
  columns: [
    {
      name: "customer_id",
      type: "str",
      flags: [],
      summary: "12,450 unique · 0 nulls",
      nulls_pct: 0,
    },
    {
      name: "signup_date",
      type: "date",
      flags: ["nullable"],
      summary: "2019-04 → 2025-09",
      nulls_pct: 0.1,
    },
    {
      name: "churned",
      type: "bool",
      flags: ["low_cardinality"],
      summary: "14.3% true · 1,780 of 12,450",
      nulls_pct: 0,
    },
  ],
  flags: ["has_target"],
};

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe("ProfileView", () => {
  beforeEach(() => {
    capturedOnEvent = null;
    vi.clearAllMocks();
    // Default: postTurn resolves immediately (204)
    mockPostTurn.mockResolvedValue(undefined);
    // Default: getState resolves with state including the sample profile
    mockGetState.mockResolvedValue({
      version: "1",
      stage: "profiling",
      aim: "Understand churn",
      dataset_path: "data/customers.csv",
      last_saved: "2026-06-02T00:00:00Z",
      profile: SAMPLE_PROFILE,
      plan: [],
    });
  });

  // -------------------------------------------------------------------------
  // test_renders_shape_strip
  // -------------------------------------------------------------------------

  it("test_renders_shape_strip — displays rows and columns counts from profile", () => {
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    const strip = screen.getByTestId("shape-strip");
    expect(strip).toBeInTheDocument();
    expect(strip.textContent).toContain("12450");
    expect(strip.textContent).toContain("9");
  });

  // -------------------------------------------------------------------------
  // test_renders_column_rows
  // -------------------------------------------------------------------------

  it("test_renders_column_rows — one column-row per column in profile", () => {
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    const rows = screen.getAllByTestId("column-row");
    expect(rows).toHaveLength(SAMPLE_PROFILE.columns.length);
  });

  // -------------------------------------------------------------------------
  // test_column_details
  // -------------------------------------------------------------------------

  it("test_column_details — name, type, and summary visible in a column row", () => {
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    const rows = screen.getAllByTestId("column-row");
    // Check first column: customer_id
    const firstRow = rows[0];
    expect(firstRow.textContent).toContain("customer_id");
    expect(firstRow.textContent).toContain("str");
    expect(firstRow.textContent).toContain("12,450 unique");
  });

  // -------------------------------------------------------------------------
  // test_bottom_bar_disabled_when_empty
  // -------------------------------------------------------------------------

  it("test_bottom_bar_disabled_when_empty — submit is disabled when input is empty", () => {
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    const submitBtn = screen.getByTestId("reprof-submit");
    expect(submitBtn).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // test_bottom_bar_submit
  // -------------------------------------------------------------------------

  it("test_bottom_bar_submit — typing text and submitting calls api.postTurn with that text", async () => {
    const user = userEvent.setup();
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    const input = screen.getByTestId("reprof-input");
    const submitBtn = screen.getByTestId("reprof-submit");

    // Type some text — submit should become enabled
    await user.type(input, "cap support_tickets at p99");
    expect(submitBtn).not.toBeDisabled();

    // Click submit
    await user.click(submitBtn);

    // postTurn called with the typed text
    expect(mockPostTurn).toHaveBeenCalledOnce();
    expect(mockPostTurn).toHaveBeenCalledWith("cap support_tickets at p99");

    // Input cleared after submission
    await waitFor(() => {
      expect((input as HTMLInputElement).value).toBe("");
    });
  });

  // -------------------------------------------------------------------------
  // test_profile_updates_on_event
  // -------------------------------------------------------------------------

  it("test_profile_updates_on_event — profile.ready SSE event triggers api.getState", async () => {
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    // Emit a profile.ready SSE event
    dispatchSSEEvent({
      type: "profile.ready",
      profile: SAMPLE_PROFILE,
      ts: Date.now(),
    });

    await waitFor(() => {
      expect(mockGetState).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // test_hydrates_from_state
  // -------------------------------------------------------------------------

  it("test_hydrates_from_state — given a profile prop, the data is displayed (page refresh)", () => {
    render(<ProfileView profile={SAMPLE_PROFILE} />);

    // Shape strip
    const strip = screen.getByTestId("shape-strip");
    expect(strip).toBeInTheDocument();

    // Column rows count matches
    const rows = screen.getAllByTestId("column-row");
    expect(rows).toHaveLength(3);

    // Verify last column details are present
    const lastRow = rows[2];
    expect(lastRow.textContent).toContain("churned");
    expect(lastRow.textContent).toContain("bool");
  });

  // -------------------------------------------------------------------------
  // test_renders_null_profile — loading/null state
  // -------------------------------------------------------------------------

  it("test_renders_null_profile — renders gracefully with null profile (loading state)", () => {
    render(<ProfileView profile={null} />);

    // Should not crash; shape-strip and column-row should not appear
    expect(screen.queryByTestId("shape-strip")).toBeNull();
    expect(screen.queryByTestId("column-row")).toBeNull();

    // Bottom bar input and submit should still render
    expect(screen.getByTestId("reprof-input")).toBeInTheDocument();
    expect(screen.getByTestId("reprof-submit")).toBeInTheDocument();
  });
});
