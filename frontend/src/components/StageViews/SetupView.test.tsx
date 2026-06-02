// SetupView tests — N1-S15
// TDD: tests written before implementation.
// Acceptance criteria from docs/planning/02_STORY_BACKLOG.md and story brief.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import SetupView from "./SetupView";

// ---------------------------------------------------------------------------
// Mock useApi so we do not touch network in unit tests
// ---------------------------------------------------------------------------

vi.mock("../../hooks/useApi", () => ({
  api: {
    postSetup: vi.fn(),
  },
}));

// Mock useSSE — SetupView may use it to listen for stage.changed
vi.mock("../../hooks/useSSE", () => ({
  useSSE: vi.fn(),
}));

import { api } from "../../hooks/useApi";
import { useSSE } from "../../hooks/useSSE";

const mockPostSetup = api.postSetup as ReturnType<typeof vi.fn>;
const mockUseSSE = useSSE as ReturnType<typeof vi.fn>;

function makeFile(name = "data.csv"): File {
  return new File(["col1,col2\n1,2"], name, { type: "text/csv" });
}

describe("SetupView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: useSSE is a no-op
    mockUseSSE.mockImplementation(() => ({ connected: true }));
  });

  // ── test_renders_controls ────────────────────────────────────────────────

  it("test_renders_controls — renders file input, aim input, submit button", () => {
    render(<SetupView />);

    expect(screen.getByTestId("csv-input")).toBeInTheDocument();
    expect(screen.getByTestId("aim-input")).toBeInTheDocument();
    expect(screen.getByTestId("submit-btn")).toBeInTheDocument();
  });

  // ── test_submit_disabled_without_file ────────────────────────────────────

  it("test_submit_disabled_without_file — no file selected → button disabled", async () => {
    const user = userEvent.setup();
    render(<SetupView />);

    const aimInput = screen.getByTestId("aim-input");
    await user.type(aimInput, "Understand churn drivers");

    expect(screen.getByTestId("submit-btn")).toBeDisabled();
  });

  // ── test_submit_disabled_with_empty_aim ──────────────────────────────────

  it("test_submit_disabled_with_empty_aim — file selected, aim empty → button disabled", async () => {
    const user = userEvent.setup();
    render(<SetupView />);

    const csvInput = screen.getByTestId("csv-input");
    const file = makeFile();
    await user.upload(csvInput, file);

    // aim is empty by default
    expect(screen.getByTestId("submit-btn")).toBeDisabled();
  });

  // ── test_submit_enabled ──────────────────────────────────────────────────

  it("test_submit_enabled — file + non-empty aim → button enabled", async () => {
    const user = userEvent.setup();
    render(<SetupView />);

    const csvInput = screen.getByTestId("csv-input");
    const aimInput = screen.getByTestId("aim-input");

    await user.upload(csvInput, makeFile());
    await user.type(aimInput, "Understand churn drivers");

    expect(screen.getByTestId("submit-btn")).not.toBeDisabled();
  });

  // ── test_posts_on_submit ─────────────────────────────────────────────────

  it("test_posts_on_submit — fill form + click submit → api.postSetup called with correct args", async () => {
    const user = userEvent.setup();
    mockPostSetup.mockResolvedValue({ ok: true, session_id: "ses_abc" });

    render(<SetupView />);

    const csvInput = screen.getByTestId("csv-input");
    const aimInput = screen.getByTestId("aim-input");
    const file = makeFile("customers.csv");

    await user.upload(csvInput, file);
    await user.type(aimInput, "Understand churn drivers");
    await user.click(screen.getByTestId("submit-btn"));

    expect(mockPostSetup).toHaveBeenCalledOnce();
    const [calledFile, calledAim] = mockPostSetup.mock.calls[0] as [File, string];
    expect(calledFile.name).toBe("customers.csv");
    expect(calledAim).toBe("Understand churn drivers");
  });

  // ── test_shows_error ─────────────────────────────────────────────────────

  it("test_shows_error — api.postSetup throws ApiError → setup-error div appears", async () => {
    const user = userEvent.setup();
    mockPostSetup.mockRejectedValue({
      error: "invalid_stage",
      message: "Not in setup stage.",
    });

    render(<SetupView />);

    const csvInput = screen.getByTestId("csv-input");
    const aimInput = screen.getByTestId("aim-input");

    await user.upload(csvInput, makeFile());
    await user.type(aimInput, "Understand churn drivers");
    await user.click(screen.getByTestId("submit-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("setup-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("setup-error")).toHaveTextContent("Not in setup stage.");
  });

  // ── Drag-and-drop tests ──────────────────────────────────────────────────

  // ── test_dropzone_renders ────────────────────────────────────────────────

  it("test_dropzone_renders — data-testid='drop-zone' is in the document", () => {
    render(<SetupView />);
    expect(screen.getByTestId("drop-zone")).toBeInTheDocument();
  });

  // ── test_drag_over_sets_active_state ─────────────────────────────────────

  it("test_drag_over_sets_active_state — dragover on drop-zone sets data-dragging=true", () => {
    render(<SetupView />);
    const dropZone = screen.getByTestId("drop-zone");

    fireEvent.dragOver(dropZone);

    expect(dropZone).toHaveAttribute("data-dragging", "true");
  });

  // ── test_drag_leave_clears_active_state ──────────────────────────────────

  it("test_drag_leave_clears_active_state — dragleave removes the dragging state", () => {
    render(<SetupView />);
    const dropZone = screen.getByTestId("drop-zone");

    fireEvent.dragOver(dropZone);
    expect(dropZone).toHaveAttribute("data-dragging", "true");

    fireEvent.dragLeave(dropZone);
    expect(dropZone).not.toHaveAttribute("data-dragging", "true");
  });

  // ── test_drop_sets_file ──────────────────────────────────────────────────

  it("test_drop_sets_file — drop event with CSV file sets the file and shows filename", () => {
    render(<SetupView />);
    const dropZone = screen.getByTestId("drop-zone");
    const file = makeFile("dropped.csv");

    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file] },
    });

    expect(screen.getByText(/dropped\.csv/)).toBeInTheDocument();
  });
});
