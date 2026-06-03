import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSSE } from "./useSSE";

// ---------------------------------------------------------------------------
// Minimal EventSource mock
// ---------------------------------------------------------------------------

interface MockEventSourceInstance {
  url: string;
  onmessage: ((e: MessageEvent) => void) | null;
  onerror: ((e: Event) => void) | null;
  close: ReturnType<typeof vi.fn>;
  /** Helper to fire a message event */
  _dispatchMessage: (data: string) => void;
  /** Helper to fire an error event */
  _dispatchError: () => void;
  readyState: number;
}

type MockEventSourceConstructor = ReturnType<typeof vi.fn> & {
  CONNECTING: number;
  OPEN: number;
  CLOSED: number;
  instances: MockEventSourceInstance[];
};

function createMockEventSourceClass(): MockEventSourceConstructor {
  const instances: MockEventSourceInstance[] = [];

  const MockEventSource = vi.fn(function (this: MockEventSourceInstance, url: string) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
    this.readyState = 1; // OPEN
    this.close = vi.fn(() => {
      this.readyState = 2; // CLOSED
    });
    this._dispatchMessage = (data: string) => {
      const event = new MessageEvent("message", { data });
      if (this.onmessage) this.onmessage(event);
    };
    this._dispatchError = () => {
      const event = new Event("error");
      if (this.onerror) this.onerror(event);
    };
    instances.push(this);
  }) as MockEventSourceConstructor;

  MockEventSource.CONNECTING = 0;
  MockEventSource.OPEN = 1;
  MockEventSource.CLOSED = 2;
  MockEventSource.instances = instances;

  return MockEventSource;
}

describe("useSSE", () => {
  let MockEventSource: MockEventSourceConstructor;

  beforeEach(() => {
    MockEventSource = createMockEventSourceClass();
    vi.stubGlobal("EventSource", MockEventSource);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("opens EventSource on /api/events on mount", () => {
    renderHook(() => useSSE(vi.fn()));

    expect(MockEventSource).toHaveBeenCalledWith("/api/events");
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it("calls onEvent with parsed data when a message arrives", () => {
    const onEvent = vi.fn();
    renderHook(() => useSSE(onEvent));

    const instance = MockEventSource.instances[0];
    const payload = { type: "stage.changed", stage: "profiling", ts: 1779784970000 };

    act(() => {
      instance._dispatchMessage(JSON.stringify(payload));
    });

    expect(onEvent).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith(payload);
  });

  it("reconnects after 2s on error", () => {
    renderHook(() => useSSE(vi.fn()));

    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];

    act(() => {
      first._dispatchError();
    });

    // close should have been called on error
    expect(first.close).toHaveBeenCalled();

    // no new instance yet — reconnect is delayed 2s
    expect(MockEventSource.instances).toHaveLength(1);

    // advance fake clock by 2 seconds
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1].url).toBe("/api/events");
  });

  it("closes EventSource on unmount", () => {
    const { unmount } = renderHook(() => useSSE(vi.fn()));
    const instance = MockEventSource.instances[0];

    unmount();

    expect(instance.close).toHaveBeenCalled();
  });

  it("returns { connected: true } when EventSource is open", () => {
    const { result } = renderHook(() => useSSE(vi.fn()));

    expect(result.current.connected).toBe(true);
  });

  it("returns { connected: false } while reconnecting after error", () => {
    const { result } = renderHook(() => useSSE(vi.fn()));
    const instance = MockEventSource.instances[0];

    act(() => {
      instance._dispatchError();
    });

    expect(result.current.connected).toBe(false);
  });

  it("dispatches a heartbeat event correctly", () => {
    const onEvent = vi.fn();
    renderHook(() => useSSE(onEvent));

    const instance = MockEventSource.instances[0];
    const payload = { type: "heartbeat", ts: 1779784980000 };

    act(() => {
      instance._dispatchMessage(JSON.stringify(payload));
    });

    expect(onEvent).toHaveBeenCalledWith(payload);
  });

  it("dispatches a section.proposed event with all fields", () => {
    const onEvent = vi.fn();
    renderHook(() => useSSE(onEvent));

    const instance = MockEventSource.instances[0];
    const payload = {
      type: "section.proposed",
      section_id: "sec_02",
      py_path: "analyses/sec_02_churn_by_tier.py",
      png_path: "charts/sec_02_churn_by_tier.png",
      md_path: "sections/sec_02_churn_by_tier.md",
      ts: 1779784990000,
    };

    act(() => {
      instance._dispatchMessage(JSON.stringify(payload));
    });

    expect(onEvent).toHaveBeenCalledWith(payload);
  });

  it("silently discards a message with malformed JSON and keeps delivering subsequent events", () => {
    const onEvent = vi.fn();
    renderHook(() => useSSE(onEvent));

    const instance = MockEventSource.instances[0];

    // Malformed JSON must not call onEvent and must not throw.
    act(() => {
      instance._dispatchMessage("this is not json {{");
    });
    expect(onEvent).not.toHaveBeenCalled();

    // A valid subsequent message must still be dispatched normally.
    act(() => {
      instance._dispatchMessage(JSON.stringify({ type: "session.idle", ts: 1 }));
    });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({ type: "session.idle", ts: 1 });
  });
});
