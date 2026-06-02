import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import App from "./App";

describe("App stage routing", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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
});
