// RetryBanner tests — N3-S05
// TDD: tests written alongside implementation.
// Contract: docs/contracts/SSE_CONTRACT.md turn.error shape (reason enum, no retryable bool).
// Covers: happy path, timeout reason, unknown reason, callback, edge cases.

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import RetryBanner from "./RetryBanner";

describe("RetryBanner", () => {
  // ── happy path ─────────────────────────────────────────────────────────────

  it("renders the banner container with data-testid=retry-banner", () => {
    render(<RetryBanner reason="provider_error" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner")).toBeInTheDocument();
  });

  it("always shows the Retry button (every turn.error is retryable from UI)", () => {
    render(<RetryBanner reason="structured_output_failed" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner-btn")).toBeInTheDocument();
    expect(screen.getByTestId("retry-banner-btn")).toHaveTextContent("Retry");
  });

  it("retry button has type=button to avoid form submission", () => {
    render(<RetryBanner reason="provider_error" onRetry={vi.fn()} />);
    const btn = screen.getByTestId("retry-banner-btn");
    expect(btn.tagName).toBe("BUTTON");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("clicking Retry button calls onRetry callback once", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<RetryBanner reason="provider_error" onRetry={onRetry} />);

    await user.click(screen.getByTestId("retry-banner-btn"));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  // ── reason-specific copy ───────────────────────────────────────────────────

  it("shows timeout-specific copy when reason is 'timeout'", () => {
    render(<RetryBanner reason="timeout" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner")).toHaveTextContent("Agent timed out — retry?");
  });

  it("shows generic copy for structured_output_failed reason", () => {
    render(<RetryBanner reason="structured_output_failed" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner")).toHaveTextContent(
      "Couldn't complete this step — retry."
    );
  });

  it("shows generic copy for provider_error reason", () => {
    render(<RetryBanner reason="provider_error" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner")).toHaveTextContent(
      "Couldn't complete this step — retry."
    );
  });

  // ── unknown reason handling ────────────────────────────────────────────────

  it("shows generic copy for any unknown reason string (graceful handling)", () => {
    render(<RetryBanner reason="some_future_error_code" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner")).toHaveTextContent(
      "Couldn't complete this step — retry."
    );
    // Retry button still present
    expect(screen.getByTestId("retry-banner-btn")).toBeInTheDocument();
  });

  // ── edge cases ─────────────────────────────────────────────────────────────

  it("renders without crash when reason is empty string", () => {
    render(<RetryBanner reason="" onRetry={vi.fn()} />);
    expect(screen.getByTestId("retry-banner")).toBeInTheDocument();
    // Empty string falls through to generic copy
    expect(screen.getByTestId("retry-banner")).toHaveTextContent(
      "Couldn't complete this step — retry."
    );
  });

  it("multiple rapid Retry clicks each invoke onRetry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<RetryBanner reason="timeout" onRetry={onRetry} />);

    await user.click(screen.getByTestId("retry-banner-btn"));
    await user.click(screen.getByTestId("retry-banner-btn"));
    expect(onRetry).toHaveBeenCalledTimes(2);
  });
});
