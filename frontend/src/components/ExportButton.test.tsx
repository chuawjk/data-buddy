// ExportButton tests — N2-S17
// TDD: tests written before implementation.
// Acceptance criteria from docs/planning/02_STORY_BACKLOG.md and story brief.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import ExportButton from "./ExportButton";

// ---------------------------------------------------------------------------
// Mock useApi so we do not touch network in unit tests
// ---------------------------------------------------------------------------

vi.mock("../hooks/useApi", () => ({
  api: {
    getExport: vi.fn(),
  },
}));

import { api } from "../hooks/useApi";

const mockGetExport = api.getExport as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Patch URL static methods (not available in jsdom without them).
// Patch HTMLAnchorElement.prototype.click to intercept downloads.
// ---------------------------------------------------------------------------

const mockCreateObjectURL = vi.fn().mockReturnValue("blob:mock-url");
const mockRevokeObjectURL = vi.fn();

// Track anchor click invocations globally
let anchorClickCalls = 0;
const originalAnchorClick = HTMLAnchorElement.prototype.click;

beforeEach(() => {
  vi.clearAllMocks();
  anchorClickCalls = 0;
  URL.createObjectURL = mockCreateObjectURL;
  URL.revokeObjectURL = mockRevokeObjectURL;
  HTMLAnchorElement.prototype.click = function () {
    anchorClickCalls++;
  };
});

afterEach(() => {
  HTMLAnchorElement.prototype.click = originalAnchorClick;
  vi.restoreAllMocks();
  // Ensure fake timers are always cleaned up even if a test fails/times out
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ExportButton", () => {
  // ── Happy path ────────────────────────────────────────────────────────────

  it("renders with export-btn testid and is not disabled when disabled=false", () => {
    render(<ExportButton disabled={false} />);
    const btn = screen.getByTestId("export-btn");
    expect(btn).toBeInTheDocument();
    expect(btn).not.toBeDisabled();
  });

  it("triggers download when clicked and api.getExport resolves", async () => {
    const user = userEvent.setup();
    mockGetExport.mockResolvedValue("# My Brief\n\nContent here.");

    render(<ExportButton disabled={false} />);

    await user.click(screen.getByTestId("export-btn"));

    await waitFor(() => {
      expect(mockGetExport).toHaveBeenCalledOnce();
    });

    await waitFor(() => {
      expect(anchorClickCalls).toBe(1);
    });

    expect(mockCreateObjectURL).toHaveBeenCalledOnce();
    const blobArg = mockCreateObjectURL.mock.calls[0][0] as Blob;
    expect(blobArg).toBeInstanceOf(Blob);
  });

  it("anchor download attribute is set to brief.md on export", async () => {
    const user = userEvent.setup();
    mockGetExport.mockResolvedValue("# Brief");

    const originalCreateElement = document.createElement.bind(document);
    let capturedAnchor: HTMLAnchorElement | null = null;
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreateElement(tag);
      if (tag === "a") capturedAnchor = el as HTMLAnchorElement;
      return el;
    });

    render(<ExportButton disabled={false} />);
    await user.click(screen.getByTestId("export-btn"));

    await waitFor(() => {
      expect(capturedAnchor?.download).toBe("brief.md");
    });
  });

  it("handles a very long markdown string without truncation", async () => {
    const user = userEvent.setup();
    const longMarkdown = "# Section\n\n" + "word ".repeat(10000);
    mockGetExport.mockResolvedValue(longMarkdown);

    render(<ExportButton disabled={false} />);
    await user.click(screen.getByTestId("export-btn"));

    await waitFor(() => {
      expect(mockCreateObjectURL).toHaveBeenCalledOnce();
    });

    const blobArg = mockCreateObjectURL.mock.calls[0][0] as Blob;
    expect(blobArg.size).toBeGreaterThan(10000);
  });

  // ── Error paths ───────────────────────────────────────────────────────────

  it("shows export-error when api.getExport rejects", async () => {
    const user = userEvent.setup();
    mockGetExport.mockRejectedValue({ error: "export_failed", message: "Export failed." });

    render(<ExportButton disabled={false} />);

    await user.click(screen.getByTestId("export-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("export-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("export-error")).toHaveTextContent("Export failed.");
  });

  it("export-error auto-dismisses after 4 seconds", async () => {
    // Must set up fake timers before rendering so that setTimeout in useEffect is captured
    vi.useFakeTimers();
    mockGetExport.mockRejectedValue({ error: "export_failed", message: "Export failed." });

    render(<ExportButton disabled={false} />);

    // Use fireEvent to avoid userEvent's own internal timer dependencies
    act(() => {
      fireEvent.click(screen.getByTestId("export-btn"));
    });

    // Flush async microtasks (the rejected promise handler) by advancing timers by 0ms
    // then wrapping in act to process state updates
    await act(async () => {
      // Yield to the microtask queue (rejected promise callbacks) without using setTimeout
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("export-error")).toBeInTheDocument();

    // Advance the fake clock past the 4-second auto-dismiss timeout
    act(() => {
      vi.advanceTimersByTime(4100);
    });

    expect(screen.queryByTestId("export-error")).not.toBeInTheDocument();
  });

  // ── Edge cases / null inputs ───────────────────────────────────────────────

  it("is disabled when disabled=true", () => {
    render(<ExportButton disabled={true} />);
    expect(screen.getByTestId("export-btn")).toBeDisabled();
  });

  it("does NOT call api.getExport when disabled and clicked", async () => {
    render(<ExportButton disabled={true} />);

    // Manually fire a click event to test the internal guard
    await act(async () => {
      const btn = screen.getByTestId("export-btn");
      btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(mockGetExport).not.toHaveBeenCalled();
  });

  it("does not show export-error on initial render", () => {
    render(<ExportButton disabled={false} />);
    expect(screen.queryByTestId("export-error")).not.toBeInTheDocument();
  });

  it("clears export-error on second successful export", async () => {
    const user = userEvent.setup();

    // First call fails, second succeeds
    mockGetExport
      .mockRejectedValueOnce({ error: "export_failed", message: "First failure." })
      .mockResolvedValueOnce("# Brief");

    render(<ExportButton disabled={false} />);

    // First click triggers error
    await user.click(screen.getByTestId("export-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("export-error")).toBeInTheDocument();
    });

    // After error, isExporting=false so the button should be enabled
    // Second click — api.getExport resolves, so error is cleared at the start of handleClick
    await user.click(screen.getByTestId("export-btn"));

    await waitFor(() => {
      // After successful export, error was cleared by setError(null) in handleClick
      expect(screen.queryByTestId("export-error")).not.toBeInTheDocument();
    });
  });
});
