// PlanView tests — N2-S15
// TDD: tests written before implementation.
// Acceptance criteria from docs/planning/02_STORY_BACKLOG.md and story brief.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import PlanView from "./PlanView";
import type { Section } from "../../types/api";

// ---------------------------------------------------------------------------
// Mock useApi — no real network calls
// ---------------------------------------------------------------------------

const mockPostPlanUpdate = vi.fn();
const mockPostPlanAccept = vi.fn();
const mockPostTurn = vi.fn();

vi.mock("../../hooks/useApi", () => ({
  api: {
    postPlanUpdate: (...args: unknown[]) => mockPostPlanUpdate(...args),
    postPlanAccept: (...args: unknown[]) => mockPostPlanAccept(...args),
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

function makeSection(
  id: string,
  title: string,
  hypothesis: string,
  status: Section["status"] = "queued"
): Section {
  return {
    id,
    title,
    hypothesis,
    status,
    py_path: null,
    png_path: null,
    md_path: null,
  };
}

const SAMPLE_SECTIONS: Section[] = [
  makeSection("sec_01", "Overview", "Revenue correlates with age"),
  makeSection("sec_02", "Churn Analysis", "High-risk customers churn within 90 days"),
  makeSection("sec_03", "Feature Importance", "Top 3 features explain 80% of variance"),
];

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe("PlanView", () => {
  beforeEach(() => {
    capturedOnEvent = null;
    vi.clearAllMocks();
    // Defaults: all API calls resolve successfully
    mockPostPlanUpdate.mockResolvedValue({ ok: true });
    mockPostPlanAccept.mockResolvedValue(undefined);
    mockPostTurn.mockResolvedValue(undefined);
  });

  // ── Rendering ─────────────────────────────────────────────────────────────

  it("renders plan-view container and plan-section-list", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.getByTestId("plan-view")).toBeInTheDocument();
    expect(screen.getByTestId("plan-section-list")).toBeInTheDocument();
  });

  it("renders one section row per section with title and hypothesis", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    for (const section of SAMPLE_SECTIONS) {
      expect(screen.getByTestId(`plan-section-${section.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`plan-section-title-${section.id}`)).toHaveTextContent(
        section.title
      );
      expect(screen.getByTestId(`plan-section-hyp-${section.id}`)).toHaveTextContent(
        section.hypothesis
      );
    }
  });

  it("renders accept, turn-input, and turn-submit controls", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.getByTestId("plan-accept-btn")).toBeInTheDocument();
    expect(screen.getByTestId("plan-turn-input")).toBeInTheDocument();
    expect(screen.getByTestId("plan-turn-submit")).toBeInTheDocument();
  });

  it("renders edit, drop, move-up, move-down buttons for each section", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    for (const section of SAMPLE_SECTIONS) {
      expect(screen.getByTestId(`plan-edit-${section.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`plan-drop-${section.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`plan-move-up-${section.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`plan-move-down-${section.id}`)).toBeInTheDocument();
    }
  });

  it("renders add-section button", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.getByTestId("plan-add-section")).toBeInTheDocument();
  });

  // ── Null / missing inputs ─────────────────────────────────────────────────

  it("renders with empty sections array — no section rows, no crash", () => {
    render(<PlanView initialSections={[]} />);
    expect(screen.getByTestId("plan-view")).toBeInTheDocument();
    expect(screen.getByTestId("plan-section-list")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-section-sec_01")).not.toBeInTheDocument();
  });

  it("renders section with empty title without crashing", () => {
    const sections = [makeSection("sec_01", "", "some hypothesis")];
    render(<PlanView initialSections={sections} />);
    expect(screen.getByTestId("plan-section-sec_01")).toBeInTheDocument();
  });

  // ── Inline edit ───────────────────────────────────────────────────────────

  it("clicking edit button enters edit mode — shows save and cancel buttons", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    await user.click(screen.getByTestId("plan-edit-sec_01"));

    expect(screen.getByTestId("plan-save-edit-sec_01")).toBeInTheDocument();
    expect(screen.getByTestId("plan-cancel-edit-sec_01")).toBeInTheDocument();
  });

  it("saving an edit calls api.postPlanUpdate with updated sections", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    // Enter edit mode
    await user.click(screen.getByTestId("plan-edit-sec_01"));

    // Find the title input in edit mode and update it
    const titleInput = screen.getByTestId("plan-section-title-sec_01");
    await user.clear(titleInput);
    await user.type(titleInput, "Updated Title");

    // Save
    await user.click(screen.getByTestId("plan-save-edit-sec_01"));

    await waitFor(() => {
      expect(mockPostPlanUpdate).toHaveBeenCalledOnce();
    });

    const [calledSections] = mockPostPlanUpdate.mock.calls[0] as [Section[]];
    const updatedSection = calledSections.find((s) => s.id === "sec_01");
    expect(updatedSection?.title).toBe("Updated Title");
  });

  it("cancelling an edit does not call api.postPlanUpdate", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    await user.click(screen.getByTestId("plan-edit-sec_01"));

    const titleInput = screen.getByTestId("plan-section-title-sec_01");
    await user.clear(titleInput);
    await user.type(titleInput, "Discarded Change");

    await user.click(screen.getByTestId("plan-cancel-edit-sec_01"));

    expect(mockPostPlanUpdate).not.toHaveBeenCalled();
    // Original title should be restored
    expect(screen.getByTestId("plan-section-title-sec_01")).toHaveTextContent("Overview");
  });

  // ── Drop section ──────────────────────────────────────────────────────────

  it("dropping a section removes it and calls api.postPlanUpdate", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    await user.click(screen.getByTestId("plan-drop-sec_02"));

    await waitFor(() => {
      expect(mockPostPlanUpdate).toHaveBeenCalledOnce();
    });

    const [calledSections] = mockPostPlanUpdate.mock.calls[0] as [Section[]];
    expect(calledSections.find((s) => s.id === "sec_02")).toBeUndefined();
    expect(calledSections.find((s) => s.id === "sec_01")).toBeDefined();
  });

  it("drop button is disabled when only one section remains", () => {
    const singleSection = [makeSection("sec_01", "Overview", "Hypothesis A")];
    render(<PlanView initialSections={singleSection} />);

    expect(screen.getByTestId("plan-drop-sec_01")).toBeDisabled();
  });

  // ── Reorder ───────────────────────────────────────────────────────────────

  it("move-up swaps section with previous and calls api.postPlanUpdate", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    // sec_02 is at index 1 — move up should swap with sec_01
    await user.click(screen.getByTestId("plan-move-up-sec_02"));

    await waitFor(() => {
      expect(mockPostPlanUpdate).toHaveBeenCalledOnce();
    });

    const [calledSections] = mockPostPlanUpdate.mock.calls[0] as [Section[]];
    expect(calledSections[0].id).toBe("sec_02");
    expect(calledSections[1].id).toBe("sec_01");
  });

  it("move-down swaps section with next and calls api.postPlanUpdate", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    // sec_01 is at index 0 — move down should swap with sec_02
    await user.click(screen.getByTestId("plan-move-down-sec_01"));

    await waitFor(() => {
      expect(mockPostPlanUpdate).toHaveBeenCalledOnce();
    });

    const [calledSections] = mockPostPlanUpdate.mock.calls[0] as [Section[]];
    expect(calledSections[0].id).toBe("sec_02");
    expect(calledSections[1].id).toBe("sec_01");
  });

  it("move-up is disabled for the first section", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.getByTestId("plan-move-up-sec_01")).toBeDisabled();
  });

  it("move-down is disabled for the last section", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.getByTestId("plan-move-down-sec_03")).toBeDisabled();
  });

  // ── Add section ───────────────────────────────────────────────────────────

  it("clicking add-section adds a new row in edit mode", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    const listBefore = screen.getAllByTestId(/^plan-section-sec/);
    await user.click(screen.getByTestId("plan-add-section"));

    // A new section row should be added
    const listAfter = screen.getAllByTestId(/^plan-section-/);
    expect(listAfter.length).toBeGreaterThan(listBefore.length);
  });

  // ── Bottom-bar turn ───────────────────────────────────────────────────────

  it("plan-turn-submit is disabled when input is empty", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.getByTestId("plan-turn-submit")).toBeDisabled();
  });

  it("bottom-bar submit calls api.postTurn with the input text", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    const input = screen.getByTestId("plan-turn-input");
    await user.type(input, "Add a section on geographic trends");
    await user.click(screen.getByTestId("plan-turn-submit"));

    await waitFor(() => {
      expect(mockPostTurn).toHaveBeenCalledOnce();
    });
    expect(mockPostTurn).toHaveBeenCalledWith("Add a section on geographic trends");
  });

  it("bottom-bar input clears after successful turn submission", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    const input = screen.getByTestId("plan-turn-input");
    await user.type(input, "Some revision request");
    await user.click(screen.getByTestId("plan-turn-submit"));

    await waitFor(() => {
      expect((input as HTMLInputElement).value).toBe("");
    });
  });

  // ── Accept flow ───────────────────────────────────────────────────────────

  it("clicking accept calls api.postPlanAccept", async () => {
    const user = userEvent.setup();
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    await user.click(screen.getByTestId("plan-accept-btn"));

    await waitFor(() => {
      expect(mockPostPlanAccept).toHaveBeenCalledOnce();
    });
  });

  // ── SSE: plan.ready ───────────────────────────────────────────────────────

  it("plan.ready SSE event resets sections from event.sections", async () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    const newSections: Section[] = [
      makeSection("sec_new_1", "New Section A", "New hypothesis A"),
      makeSection("sec_new_2", "New Section B", "New hypothesis B"),
    ];

    dispatchSSEEvent({
      type: "plan.ready",
      sections: newSections,
      ts: Date.now(),
    });

    await waitFor(() => {
      expect(screen.getByTestId("plan-section-sec_new_1")).toBeInTheDocument();
      expect(screen.getByTestId("plan-section-sec_new_2")).toBeInTheDocument();
    });

    // Old sections should be gone
    expect(screen.queryByTestId("plan-section-sec_01")).not.toBeInTheDocument();
  });

  it("plan.ready SSE clears isTurnInFlight (re-enables turn input after revision)", async () => {
    const user = userEvent.setup();
    // postTurn never resolves on its own — will be unblocked by plan.ready SSE
    mockPostTurn.mockReturnValue(new Promise(() => {}));

    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    const input = screen.getByTestId("plan-turn-input");
    await user.type(input, "Revision request");
    await user.click(screen.getByTestId("plan-turn-submit"));

    // Input should be disabled while turn is in flight
    await waitFor(() => {
      expect(screen.getByTestId("plan-turn-input")).toBeDisabled();
    });

    // plan.ready SSE arrives with updated sections
    const updatedSections: Section[] = [makeSection("sec_01", "Updated Overview", "New hyp")];
    dispatchSSEEvent({ type: "plan.ready", sections: updatedSections, ts: Date.now() });

    // Input should be re-enabled
    await waitFor(() => {
      expect(screen.getByTestId("plan-turn-input")).not.toBeDisabled();
    });
  });

  // ── Error paths ───────────────────────────────────────────────────────────

  it("api.postPlanUpdate failure shows plan-error banner", async () => {
    const user = userEvent.setup();
    mockPostPlanUpdate.mockRejectedValue({ error: "update_failed", message: "Update failed." });

    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    // Trigger a drop which calls postPlanUpdate
    await user.click(screen.getByTestId("plan-drop-sec_02"));

    await waitFor(() => {
      expect(screen.getByTestId("plan-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("plan-error")).toHaveTextContent("Update failed.");
  });

  it("api.postTurn failure shows plan-error and preserves input text", async () => {
    const user = userEvent.setup();
    mockPostTurn.mockRejectedValue({ error: "turn_failed", message: "Turn failed." });

    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    const input = screen.getByTestId("plan-turn-input");
    await user.type(input, "A revision request");
    await user.click(screen.getByTestId("plan-turn-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("plan-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("plan-error")).toHaveTextContent("Turn failed.");
    // Input should be preserved for retry
    expect(input).toHaveValue("A revision request");
  });

  it("api.postPlanAccept failure shows plan-error banner", async () => {
    const user = userEvent.setup();
    mockPostPlanAccept.mockRejectedValue({
      error: "accept_failed",
      message: "Accept failed.",
    });

    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    await user.click(screen.getByTestId("plan-accept-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("plan-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("plan-error")).toHaveTextContent("Accept failed.");
  });

  it("turn.error SSE event shows error in plan-error banner", async () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);

    dispatchSSEEvent({
      type: "turn.error",
      stage: "planning",
      reason: "timeout",
      ts: Date.now(),
    });

    await waitFor(() => {
      expect(screen.getByTestId("plan-error")).toBeInTheDocument();
    });
  });

  // ── plan-saving-indicator ─────────────────────────────────────────────────

  it("plan-saving-indicator is absent when no save is in progress", () => {
    render(<PlanView initialSections={SAMPLE_SECTIONS} />);
    expect(screen.queryByTestId("plan-saving-indicator")).not.toBeInTheDocument();
  });
});
