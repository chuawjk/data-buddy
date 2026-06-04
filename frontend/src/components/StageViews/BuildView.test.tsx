// BuildView tests
// TDD: tests written alongside implementation.
// Acceptance criteria from docs/plans/2026-06-03-n2-s16.md

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import BuildView from "./BuildView";
import type { Section, StateResponse } from "../../types/api";

// ---------------------------------------------------------------------------
// Mock useApi
// ---------------------------------------------------------------------------

const mockGetState = vi.fn();
const mockPostSectionAccept = vi.fn();
const mockPostSectionDrop = vi.fn();
const mockPostTurn = vi.fn();
const mockGetFile = vi.fn();

vi.mock("../../hooks/useApi", () => ({
  api: {
    getState: (...args: unknown[]) => mockGetState(...args),
    postSectionAccept: (...args: unknown[]) => mockPostSectionAccept(...args),
    postSectionDrop: (...args: unknown[]) => mockPostSectionDrop(...args),
    postTurn: (...args: unknown[]) => mockPostTurn(...args),
    getFile: (...args: unknown[]) => mockGetFile(...args),
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

const QUEUED_SECTION: Section = {
  id: "sec-01",
  title: "Cohort overview",
  hypothesis: "Check churn baseline",
  status: "queued",
  py_path: null,
  png_path: null,
  md_path: null,
};

const BUILDING_SECTION: Section = {
  id: "sec-02",
  title: "Churn by plan tier",
  hypothesis: "Higher tiers have lower churn",
  status: "building",
  py_path: null,
  png_path: null,
  md_path: null,
};

const PROPOSED_SECTION: Section = {
  id: "sec-02",
  title: "Churn by plan tier",
  hypothesis: "Higher tiers have lower churn",
  status: "proposed",
  py_path: "analyses/02_churn.py",
  png_path: "charts/02_churn.png",
  md_path: "sections/02_churn.md",
};

function makeStateResponse(sections: Section[]): StateResponse {
  return {
    version: "1",
    stage: "building",
    aim: "Understand churn",
    dataset_path: "data/customers.csv",
    last_saved: "2026-06-03T00:00:00Z",
    profile: null,
    plan: sections,
  };
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe("BuildView", () => {
  beforeEach(() => {
    capturedOnEvent = null;
    vi.clearAllMocks();
    // Default: getState returns empty plan
    mockGetState.mockResolvedValue(makeStateResponse([]));
    // Default: api calls resolve
    mockPostSectionAccept.mockResolvedValue(undefined);
    mockPostSectionDrop.mockResolvedValue(undefined);
    mockPostTurn.mockResolvedValue(undefined);
    // Default: getFile returns empty content (SectionPane needs this)
    mockGetFile.mockResolvedValue("# code");
  });

  // ── test_renders_build_view ──────────────────────────────────────────────

  it("test_renders_build_view — build-view testid is present", async () => {
    render(<BuildView />);
    expect(screen.getByTestId("build-view")).toBeInTheDocument();
  });

  // ── test_renders_sections_from_props ────────────────────────────────────

  it("test_renders_sections_from_props — section rows rendered from props on mount", async () => {
    const sections = [QUEUED_SECTION, BUILDING_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId(`section-row-${QUEUED_SECTION.id}`)).toBeInTheDocument();
    });

    expect(screen.getByTestId(`section-row-${BUILDING_SECTION.id}`)).toBeInTheDocument();
  });

  // ── test_renders_section_status ─────────────────────────────────────────

  it("test_renders_section_status — section-status-{id} shows correct status text", async () => {
    const sections = [QUEUED_SECTION, BUILDING_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${QUEUED_SECTION.id}`)).toHaveTextContent("queued");
    });

    expect(screen.getByTestId(`section-status-${BUILDING_SECTION.id}`)).toHaveTextContent(
      "building"
    );
  });

  // ── test_shows_spinner_for_building_section ──────────────────────────────

  it("test_shows_spinner_for_building_section — section-building-spinner shown when active section is building", async () => {
    const sections = [QUEUED_SECTION, BUILDING_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-building-spinner")).toBeInTheDocument();
    });
  });

  // ── test_shows_pane_for_active_section ───────────────────────────────────

  it("test_shows_pane_for_active_section — section-pane shown for building section", async () => {
    const sections = [QUEUED_SECTION, BUILDING_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getAllByTestId("section-pane").length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── test_shows_pane_for_each_non_queued_section ──────────────────────────

  it("test_shows_pane_for_each_non_queued_section — one pane per non-queued section", async () => {
    const sections = [
      QUEUED_SECTION,
      BUILDING_SECTION,
      PROPOSED_SECTION,
    ];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    // QUEUED_SECTION should have no pane; BUILDING + PROPOSED should each have one.
    await waitFor(() => {
      expect(screen.getAllByTestId("section-pane")).toHaveLength(2);
    });
  });

  // ── test_section_building_event_marks_section ────────────────────────────

  it("test_section_building_event_marks_section — section.building SSE updates status badge", async () => {
    const sections = [QUEUED_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${QUEUED_SECTION.id}`)).toHaveTextContent("queued");
    });

    // Emit section.building event
    dispatchSSEEvent({
      type: "section.building",
      section_id: "sec-01",
      title: "Cohort overview",
      ts: Date.now(),
    });

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${QUEUED_SECTION.id}`)).toHaveTextContent(
        "building"
      );
    });
  });

  // ── test_section_proposed_event_updates_sections ─────────────────────────

  it("test_section_proposed_event_updates_sections — section.proposed SSE refreshes from state", async () => {
    const sections = [BUILDING_SECTION];
    mockGetState
      .mockResolvedValueOnce(makeStateResponse(sections))
      .mockResolvedValueOnce(makeStateResponse([PROPOSED_SECTION]));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-building-spinner")).toBeInTheDocument();
    });

    // Emit section.proposed
    dispatchSSEEvent({
      type: "section.proposed",
      section_id: "sec-02",
      py_path: "analyses/02_churn.py",
      png_path: "charts/02_churn.png",
      md_path: "sections/02_churn.md",
      ts: Date.now(),
    });

    await waitFor(() => {
      expect(mockGetState).toHaveBeenCalledTimes(2);
    });
  });

  // ── test_accept_button_calls_api ─────────────────────────────────────────

  it("test_accept_button_calls_api — clicking accept calls api.postSectionAccept with section id", async () => {
    const user = userEvent.setup();
    const sections = [PROPOSED_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));
    mockGetFile.mockResolvedValue("import pandas as pd");

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-accept-btn")).not.toBeDisabled();
    });

    await user.click(screen.getByTestId("section-accept-btn"));

    expect(mockPostSectionAccept).toHaveBeenCalledOnce();
    expect(mockPostSectionAccept).toHaveBeenCalledWith(PROPOSED_SECTION.id);
  });

  // ── test_accept_optimistic_update ────────────────────────────────────────

  it("test_accept_optimistic_update — status badge updates to accepted after click", async () => {
    const user = userEvent.setup();
    const sections = [PROPOSED_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));
    mockGetFile.mockResolvedValue("import pandas as pd");

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-accept-btn")).not.toBeDisabled();
    });

    await user.click(screen.getByTestId("section-accept-btn"));

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${PROPOSED_SECTION.id}`)).toHaveTextContent(
        "accepted"
      );
    });
  });

  // ── test_drop_button_calls_api ────────────────────────────────────────────

  it("test_drop_button_calls_api — clicking drop calls api.postSectionDrop with section id", async () => {
    const user = userEvent.setup();
    const sections = [PROPOSED_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));
    mockGetFile.mockResolvedValue("import pandas as pd");

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-drop-btn")).not.toBeDisabled();
    });

    await user.click(screen.getByTestId("section-drop-btn"));

    expect(mockPostSectionDrop).toHaveBeenCalledOnce();
    expect(mockPostSectionDrop).toHaveBeenCalledWith(PROPOSED_SECTION.id);
  });

  // ── test_build_bottom_bar_removed ────────────────────────────────────────

  it("test_build_bottom_bar_removed — building stage has no global bottom bar", () => {
    render(<BuildView />);

    expect(screen.queryByTestId("build-bottom-bar")).toBeNull();
    expect(screen.queryByTestId("bottom-bar-input")).toBeNull();
    expect(screen.queryByTestId("bottom-bar-send")).toBeNull();
  });

  // ── test_section_revise_calls_postTurn_with_section_id ──────────────────

  it("test_section_revise_calls_postTurn_with_section_id — proposed section revise targets section", async () => {
    const user = userEvent.setup();
    const sections = [PROPOSED_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));
    mockGetFile.mockResolvedValue("section text");

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-revise-input")).not.toBeDisabled();
    });

    await user.type(screen.getByTestId("section-revise-input"), "use a grouped bar chart");
    await user.click(screen.getByTestId("section-revise-btn"));

    expect(mockPostTurn).toHaveBeenCalledOnce();
    expect(mockPostTurn).toHaveBeenCalledWith("use a grouped bar chart", PROPOSED_SECTION.id);
  });

  // ── test_section_revise_marks_section_building ──────────────────────────

  it("test_section_revise_marks_section_building — section status updates after targeted revise", async () => {
    const user = userEvent.setup();
    const sections = [PROPOSED_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));
    mockGetFile.mockResolvedValue("section text");

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-revise-input")).not.toBeDisabled();
    });

    await user.type(screen.getByTestId("section-revise-input"), "revise the chart");
    await user.click(screen.getByTestId("section-revise-btn"));

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${PROPOSED_SECTION.id}`)).toHaveTextContent(
        "building"
      );
    });
  });

  // ── test_section_failed_event_updates_status ─────────────────────────────

  it("test_section_failed_event_updates_status — section.failed SSE marks section as failed", async () => {
    const sections = [BUILDING_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${BUILDING_SECTION.id}`)).toHaveTextContent(
        "building"
      );
    });

    dispatchSSEEvent({
      type: "section.failed",
      section_id: "sec-02",
      reason: "timeout",
      ts: Date.now(),
    });

    await waitFor(() => {
      expect(screen.getByTestId(`section-status-${BUILDING_SECTION.id}`)).toHaveTextContent(
        "failed"
      );
    });
  });

  // ── test_empty_sections_shows_no_list ────────────────────────────────────

  it("test_empty_sections_shows_no_list — section-list absent when no sections", async () => {
    mockGetState.mockResolvedValue(makeStateResponse([]));

    render(<BuildView sections={[]} />);

    await waitFor(() => {
      expect(mockGetState).toHaveBeenCalled();
    });

    expect(screen.queryByTestId("section-list")).toBeNull();
  });

  // ── test_hydrates_on_mount_from_state ────────────────────────────────────

  it("test_hydrates_on_mount_from_state — sections hydrated from api.getState on mount", async () => {
    const sections = [QUEUED_SECTION, BUILDING_SECTION];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={[]} />);

    await waitFor(() => {
      expect(screen.getByTestId(`section-row-${QUEUED_SECTION.id}`)).toBeInTheDocument();
    });
  });

  // ── test_section_order_preserved ─────────────────────────────────────────

  it("test_section_order_preserved — sections rendered in plan order", async () => {
    const sections = [
      { ...QUEUED_SECTION, id: "sec-01", title: "Section A" },
      { ...QUEUED_SECTION, id: "sec-02", title: "Section B" },
      { ...QUEUED_SECTION, id: "sec-03", title: "Section C" },
    ];
    mockGetState.mockResolvedValue(makeStateResponse(sections));

    render(<BuildView sections={sections} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-list")).toBeInTheDocument();
    });

    const rows = screen.getAllByTestId(/^section-row-/);
    expect(rows[0]).toHaveTextContent("Section A");
    expect(rows[1]).toHaveTextContent("Section B");
    expect(rows[2]).toHaveTextContent("Section C");
  });
});
