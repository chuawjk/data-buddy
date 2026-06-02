// Tests for ActivityRail — TDD: tests written first against acceptance criteria.
// Mocks useSSE so we control which events arrive without a real EventSource.
//
// Acceptance criteria (N1-S17):
//   - tool.bash_running  → activity-tool-running item
//   - tool.bash_done     → activity-tool-done item with elapsed_ms
//   - tool.file_written  → activity-file-written item with file path
//   - message.part       → appended to activity-message text area in order
//   - session.idle       → resets (clears) the rail
//   - out-of-order events → no crash, rail stays consistent

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import ActivityRail from "./ActivityRail";

// ---------------------------------------------------------------------------
// Mock useSSE
// ---------------------------------------------------------------------------

// We capture the onEvent callback so tests can dispatch arbitrary events.
let capturedOnEvent: ((event: unknown) => void) | null = null;

vi.mock("../hooks/useSSE", () => ({
  useSSE: (onEvent: (event: unknown) => void) => {
    capturedOnEvent = onEvent;
    return { connected: true };
  },
}));

// Helper — dispatch an event into the component via the captured callback.
function dispatchEvent(event: unknown) {
  act(() => {
    if (capturedOnEvent) capturedOnEvent(event);
  });
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe("ActivityRail", () => {
  beforeEach(() => {
    capturedOnEvent = null;
  });

  it("test_renders_empty — renders with no events; rail exists, no items", () => {
    render(<ActivityRail />);

    const rail = screen.getByTestId("activity-rail");
    expect(rail).toBeInTheDocument();

    expect(screen.queryByTestId("activity-tool-running")).toBeNull();
    expect(screen.queryByTestId("activity-tool-done")).toBeNull();
    expect(screen.queryByTestId("activity-file-written")).toBeNull();
    // message area should be absent or empty
    const msgArea = screen.queryByTestId("activity-message");
    if (msgArea) {
      expect(msgArea.textContent).toBe("");
    }
  });

  it("test_tool_running — dispatch tool.bash_running, assert item with tool name appears", () => {
    render(<ActivityRail />);

    dispatchEvent({
      type: "tool.bash_running",
      command: "python profile.py",
      description: "Run profiling",
      started_at: 1000,
      ts: 1000,
    });

    const items = screen.getAllByTestId("activity-tool-running");
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain("python profile.py");
  });

  it("test_tool_done — dispatch tool.bash_done, assert elapsed shown", () => {
    render(<ActivityRail />);

    dispatchEvent({
      type: "tool.bash_done",
      command: "python profile.py",
      exit_code: 0,
      elapsed_ms: 312,
      ts: 2000,
    });

    const items = screen.getAllByTestId("activity-tool-done");
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain("python profile.py");
    expect(items[0].textContent).toContain("312");
  });

  it("test_file_written — dispatch tool.file_written, assert path shown", () => {
    render(<ActivityRail />);

    dispatchEvent({
      type: "tool.file_written",
      file: "analyses/sec_02_churn.py",
      op: "add",
      additions: 40,
      deletions: 0,
      elapsed_ms: 5,
      ts: 3000,
    });

    const items = screen.getAllByTestId("activity-file-written");
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain("analyses/sec_02_churn.py");
  });

  it("test_message_part_appends — two message.part events append in order", () => {
    render(<ActivityRail />);

    dispatchEvent({
      type: "message.part",
      part_id: "prt_1",
      content: "Hello, ",
      ts: 4000,
    });

    dispatchEvent({
      type: "message.part",
      part_id: "prt_2",
      content: "world!",
      ts: 4001,
    });

    const msgArea = screen.getByTestId("activity-message");
    expect(msgArea.textContent).toContain("Hello, ");
    expect(msgArea.textContent).toContain("world!");
    // Verify order: "Hello, " comes before "world!" in the text
    const text = msgArea.textContent ?? "";
    expect(text.indexOf("Hello, ")).toBeLessThan(text.indexOf("world!"));
  });

  it("test_reset_on_idle — events then session.idle clears the rail", () => {
    render(<ActivityRail />);

    dispatchEvent({
      type: "tool.bash_running",
      command: "ls",
      description: null,
      started_at: 5000,
      ts: 5000,
    });
    dispatchEvent({
      type: "tool.file_written",
      file: "out.txt",
      op: "add",
      additions: 1,
      deletions: 0,
      elapsed_ms: 2,
      ts: 5001,
    });
    dispatchEvent({
      type: "message.part",
      part_id: "prt_x",
      content: "some text",
      ts: 5002,
    });

    // Verify items present before reset
    expect(screen.getAllByTestId("activity-tool-running")).toHaveLength(1);
    expect(screen.getAllByTestId("activity-file-written")).toHaveLength(1);
    expect(screen.getByTestId("activity-message").textContent).toBe("some text");

    // Fire session.idle
    dispatchEvent({ type: "session.idle", ts: 6000 });

    // All items should be gone
    expect(screen.queryByTestId("activity-tool-running")).toBeNull();
    expect(screen.queryByTestId("activity-tool-done")).toBeNull();
    expect(screen.queryByTestId("activity-file-written")).toBeNull();
    const msgArea = screen.queryByTestId("activity-message");
    if (msgArea) {
      expect(msgArea.textContent).toBe("");
    }
  });

  it("test_out_of_order_consistent — mixed event order, no crash, rail is consistent", () => {
    // This test dispatches events in a unusual order and asserts no crash and
    // that counts are consistent (no duplicates, no negatives).
    render(<ActivityRail />);

    // Dispatch done before running (out of order)
    dispatchEvent({
      type: "tool.bash_done",
      command: "cat file.txt",
      exit_code: 0,
      elapsed_ms: 10,
      ts: 100,
    });
    dispatchEvent({
      type: "tool.file_written",
      file: "charts/01.png",
      op: "add",
      additions: 1,
      deletions: 0,
      elapsed_ms: 3,
      ts: 90,
    });
    dispatchEvent({
      type: "tool.bash_running",
      command: "python run.py",
      description: null,
      started_at: 80,
      ts: 80,
    });
    dispatchEvent({
      type: "message.part",
      part_id: "prt_a",
      content: "chunk",
      ts: 110,
    });

    // Should render without crashing; counts must be exact
    expect(screen.getAllByTestId("activity-tool-done")).toHaveLength(1);
    expect(screen.getAllByTestId("activity-file-written")).toHaveLength(1);
    expect(screen.getAllByTestId("activity-tool-running")).toHaveLength(1);
    expect(screen.getByTestId("activity-message")).toBeInTheDocument();
  });
});
