import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useActivityState } from "./useActivityState";

// Stable ref so dispatch never dereferences a stale or null callback.
const onEventRef: { current: (e: unknown) => void } = { current: () => {} };

vi.mock("./useSSE", () => ({
  useSSE: (onEvent: (e: unknown) => void) => {
    onEventRef.current = onEvent;
    return { connected: true };
  },
}));

function dispatch(e: unknown) {
  act(() => {
    onEventRef.current(e);
  });
}

describe("useActivityState", () => {
  beforeEach(() => {
    onEventRef.current = () => {};
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("initial state is idle with zero counts", () => {
    const { result } = renderHook(() => useActivityState());
    expect(result.current.isRunning).toBe(false);
    expect(result.current.bashCount).toBe(0);
    expect(result.current.fileCount).toBe(0);
    expect(result.current.dotPhase).toBe(0);
  });

  it("message.part activates isRunning without touching counts", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "message.part", part_id: "p1", content: "hi", ts: 1 });
    expect(result.current.isRunning).toBe(true);
    expect(result.current.bashCount).toBe(0);
    expect(result.current.fileCount).toBe(0);
  });

  it("tool.bash_running activates isRunning without touching counts", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_running", command: "ls", description: null, started_at: 1, ts: 1 });
    expect(result.current.isRunning).toBe(true);
    expect(result.current.bashCount).toBe(0);
  });

  it("tool.bash_done increments bashCount", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "ls", exit_code: 0, elapsed_ms: 50, ts: 2 });
    expect(result.current.bashCount).toBe(1);
    dispatch({ type: "tool.bash_done", command: "cat f", exit_code: 0, elapsed_ms: 10, ts: 3 });
    expect(result.current.bashCount).toBe(2);
  });

  it("tool.file_written increments fileCount", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.file_written", file: "a.py", op: "add", additions: 1, deletions: 0, elapsed_ms: 5, ts: 2 });
    expect(result.current.fileCount).toBe(1);
  });

  it("session.idle sets isRunning to false and preserves counts", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "x", exit_code: 0, elapsed_ms: 1, ts: 1 });
    dispatch({ type: "tool.file_written", file: "f", op: "add", additions: 1, deletions: 0, elapsed_ms: 1, ts: 2 });
    expect(result.current.bashCount).toBe(1);
    expect(result.current.fileCount).toBe(1);

    dispatch({ type: "session.idle", ts: 3 });

    expect(result.current.isRunning).toBe(false);
    expect(result.current.bashCount).toBe(1);
    expect(result.current.fileCount).toBe(1);
  });

  it("first activating event after session.idle resets counts", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "x", exit_code: 0, elapsed_ms: 1, ts: 1 });
    dispatch({ type: "session.idle", ts: 2 });
    expect(result.current.bashCount).toBe(1);

    dispatch({ type: "tool.bash_done", command: "y", exit_code: 0, elapsed_ms: 1, ts: 3 });
    expect(result.current.bashCount).toBe(1);
    expect(result.current.isRunning).toBe(true);
  });

  it("dotPhase cycles 0→1→2→0 every 500ms while running, clears on idle", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useActivityState());

    dispatch({ type: "message.part", part_id: "p1", content: "x", ts: 1 });
    expect(result.current.dotPhase).toBe(0);

    act(() => { vi.advanceTimersByTime(500); });
    expect(result.current.dotPhase).toBe(1);

    act(() => { vi.advanceTimersByTime(500); });
    expect(result.current.dotPhase).toBe(2);

    act(() => { vi.advanceTimersByTime(500); });
    expect(result.current.dotPhase).toBe(0);

    dispatch({ type: "session.idle", ts: 2 });
    act(() => { vi.advanceTimersByTime(1500); });
    expect(result.current.dotPhase).toBe(0);
  });

  it("unknown event types are ignored without error", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "stage.changed", stage: "profiling", ts: 1 });
    expect(result.current.isRunning).toBe(false);
  });

  it("initial log is empty", () => {
    const { result } = renderHook(() => useActivityState());
    expect(result.current.log).toEqual([]);
  });

  it("tool.bash_done appends a $-prefixed command to log", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "ls -la", exit_code: 0, elapsed_ms: 10, ts: 1 });
    expect(result.current.log).toEqual(["$ ls -la"]);
  });

  it("tool.file_written appends a ✎-prefixed file path to log", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.file_written", file: "workspace/sections/s1.md", op: "add", additions: 5, deletions: 0, elapsed_ms: 5, ts: 1 });
    expect(result.current.log).toEqual(["✎ workspace/sections/s1.md"]);
  });

  it("long commands are stored in full (truncation is handled by CSS line-clamp)", () => {
    const { result } = renderHook(() => useActivityState());
    const longCmd = "python analyze_data.py --input data.csv --output results.json";
    dispatch({ type: "tool.bash_done", command: longCmd, exit_code: 0, elapsed_ms: 100, ts: 1 });
    expect(result.current.log[0]).toBe(`$ ${longCmd}`);
  });

  it("log is preserved after session.idle", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "ls", exit_code: 0, elapsed_ms: 1, ts: 1 });
    dispatch({ type: "session.idle", ts: 2 });
    expect(result.current.log).toEqual(["$ ls"]);
  });

  it("log resets on first event after session.idle", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "ls", exit_code: 0, elapsed_ms: 1, ts: 1 });
    dispatch({ type: "session.idle", ts: 2 });
    dispatch({ type: "tool.bash_done", command: "pwd", exit_code: 0, elapsed_ms: 1, ts: 3 });
    expect(result.current.log).toEqual(["$ pwd"]);
  });

  it("log is capped at 20 entries", () => {
    const { result } = renderHook(() => useActivityState());
    for (let i = 0; i < 25; i++) {
      dispatch({ type: "tool.bash_done", command: `cmd${i}`, exit_code: 0, elapsed_ms: 1, ts: i });
    }
    expect(result.current.log).toHaveLength(20);
    expect(result.current.log[0]).toBe("$ cmd5");
    expect(result.current.log[19]).toBe("$ cmd24");
  });

  it("mixed bash and file events produce interleaved log entries", () => {
    const { result } = renderHook(() => useActivityState());
    dispatch({ type: "tool.bash_done", command: "run.sh", exit_code: 0, elapsed_ms: 1, ts: 1 });
    dispatch({ type: "tool.file_written", file: "out.csv", op: "add", additions: 10, deletions: 0, elapsed_ms: 1, ts: 2 });
    expect(result.current.log).toEqual(["$ run.sh", "✎ out.csv"]);
  });
});
