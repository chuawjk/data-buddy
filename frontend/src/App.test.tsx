import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import App from "./App";
import type { SSEEvent } from "./types/events";

// Collect all onEvent callbacks registered by any component using useSSE.
// Firing capturedOnEvent broadcasts to all of them (App.tsx + ActivityRail etc).
const registeredCallbacks: Array<(event: SSEEvent) => void> = [];
const capturedOnEvent = (event: SSEEvent) => registeredCallbacks.forEach((cb) => cb(event));

vi.mock("./hooks/useSSE", () => ({
  useSSE: (onEvent: (event: SSEEvent) => void) => {
    registeredCallbacks.push(onEvent);
    return { connected: false };
  },
}));

describe("App stage routing", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    registeredCallbacks.length = 0;
  });

  it("renders setup-view when stage is 'setup'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ stage: "setup" }),
      })
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("setup-view")).toBeInTheDocument();
    });
  });

  it("renders profile-view when stage is 'profiling'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ stage: "profiling" }),
      })
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("profile-view")).toBeInTheDocument();
    });
  });

  it("renders plan-view when stage is 'planning'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ stage: "planning" }),
      })
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("plan-view")).toBeInTheDocument();
    });
  });

  it("renders build-view when stage is 'building'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ stage: "building" }),
      })
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("build-view")).toBeInTheDocument();
    });
  });

  it("renders build-view when stage is 'done'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ stage: "done" }),
      })
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("build-view")).toBeInTheDocument();
    });
  });

  it("shows loading state while fetching", async () => {
    let resolveFetch!: (value: unknown) => void;
    const pending = new Promise((res) => {
      resolveFetch = res;
    });

    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pending));

    render(<App />);

    expect(screen.getByTestId("loading-indicator")).toBeInTheDocument();

    // Resolve so that pending state is flushed before cleanup
    await act(async () => {
      resolveFetch({
        ok: true,
        json: async () => ({ stage: "setup" }),
      });
    });
  });

  it("shows error state when fetch fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      })
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    });
  });

  it("calls GET /api/state on mount", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ stage: "setup" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<App />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/state");
    });
  });

  it("reacts to stage.changed — calls api.getState and updates stage", async () => {
    // First call: mount fetch returns "setup". Second call: SSE-triggered fetch returns "profiling".
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ stage: "setup", profile: null }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ stage: "profiling", profile: null }),
      });
    vi.stubGlobal("fetch", mockFetch);

    render(<App />);

    // Wait for mount fetch to settle on setup-view.
    await waitFor(() => {
      expect(screen.getByTestId("setup-view")).toBeInTheDocument();
    });

    // Simulate a stage.changed SSE event.
    await act(async () => {
      capturedOnEvent!({ type: "stage.changed", stage: "profiling", ts: Date.now() });
    });

    // api.getState() should have been called again (/api/state via fetch).
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/state", { method: "GET" });
    });

    // UI should now show profile-view.
    await waitFor(() => {
      expect(screen.getByTestId("profile-view")).toBeInTheDocument();
    });
  });

  it("reacts to profile.ready — calls api.getState and refreshes state", async () => {
    const profilePayload = {
      shape: { rows: 100, columns: 5, nulls_pct: 0, target: null },
      columns: [],
      flags: [],
    };

    // First call: mount fetch returns "profiling" with no profile.
    // Second call: SSE-triggered fetch returns profiling with a full profile.
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ stage: "profiling", profile: null }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ stage: "profiling", profile: profilePayload }),
      });
    vi.stubGlobal("fetch", mockFetch);

    render(<App />);

    // Wait for mount fetch to settle.
    await waitFor(() => {
      expect(screen.getByTestId("profile-view")).toBeInTheDocument();
    });

    // Simulate a profile.ready SSE event.
    await act(async () => {
      capturedOnEvent!({ type: "profile.ready", profile: profilePayload, ts: Date.now() });
    });

    // api.getState() should have been called again.
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/state", { method: "GET" });
    });
  });
});
