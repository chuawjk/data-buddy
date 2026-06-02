import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";
import { render, screen } from "@testing-library/react";
import ActivityRail from "./ActivityRail";
import { useActivityState } from "../hooks/useActivityState";
import type { ActivityRailState } from "../hooks/useActivityState";

vi.mock("../hooks/useActivityState", () => ({
  useActivityState: vi.fn(),
}));

function setState(s: Partial<ActivityRailState>) {
  (useActivityState as Mock).mockReturnValue({
    isRunning: false,
    bashCount: 0,
    fileCount: 0,
    dotPhase: 0 as const,
    ...s,
  });
}

describe("ActivityRail", () => {
  beforeEach(() => {
    setState({});
  });

  it("renders the rail root always", () => {
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-rail")).toBeInTheDocument();
  });

  it("shows placeholder when idle with no counts", () => {
    setState({ isRunning: false, bashCount: 0, fileCount: 0 });
    render(<ActivityRail />);
    expect(screen.getByText(/no activity yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("activity-thinking")).toBeNull();
    expect(screen.queryByTestId("activity-summary")).toBeNull();
  });

  it("shows activity-thinking with dot phase 0 while running", () => {
    setState({ isRunning: true, dotPhase: 0 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-thinking").textContent).toBe("Thinking.");
    expect(screen.queryByText(/no activity yet/i)).toBeNull();
  });

  it("shows activity-thinking with dot phase 1", () => {
    setState({ isRunning: true, dotPhase: 1 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-thinking").textContent).toBe("Thinking..");
  });

  it("shows activity-thinking with dot phase 2", () => {
    setState({ isRunning: true, dotPhase: 2 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-thinking").textContent).toBe("Thinking...");
  });

  it("shows summary with bash count only", () => {
    setState({ isRunning: false, bashCount: 3, fileCount: 0 });
    render(<ActivityRail />);
    const summary = screen.getByTestId("activity-summary");
    expect(summary.textContent).toBe("3 commands run");
  });

  it("shows summary with file count only", () => {
    setState({ isRunning: false, bashCount: 0, fileCount: 1 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-summary").textContent).toBe("1 file written");
  });

  it("shows summary with both counts joined by ·", () => {
    setState({ isRunning: false, bashCount: 4, fileCount: 2 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-summary").textContent).toBe("4 commands run · 2 files written");
  });

  it("uses singular for count of 1", () => {
    setState({ isRunning: false, bashCount: 1, fileCount: 1 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-summary").textContent).toBe("1 command run · 1 file written");
  });

  it("shows both thinking and summary during active run with counts", () => {
    setState({ isRunning: true, bashCount: 2, fileCount: 1, dotPhase: 0 });
    render(<ActivityRail />);
    expect(screen.getByTestId("activity-thinking")).toBeInTheDocument();
    expect(screen.getByTestId("activity-summary")).toBeInTheDocument();
  });

  it("hides thinking and shows summary as completion snapshot after idle", () => {
    setState({ isRunning: false, bashCount: 3, fileCount: 1 });
    render(<ActivityRail />);
    expect(screen.queryByTestId("activity-thinking")).toBeNull();
    expect(screen.getByTestId("activity-summary").textContent).toBe("3 commands run · 1 file written");
  });
});
