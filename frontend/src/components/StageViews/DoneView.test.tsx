// DoneView tests
// TDD: tests written alongside implementation.
// Covers: happy path, filtering, export button, edge cases.

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import DoneView from "./DoneView";
import type { Section } from "../../types/api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ACCEPTED_1: Section = {
  id: "sec-01",
  title: "Cohort overview",
  hypothesis: "Check churn baseline",
  status: "accepted",
  py_path: "analyses/01_cohort.py",
  png_path: "charts/01_cohort.png",
  md_path: "sections/01_cohort.md",
};

const ACCEPTED_2: Section = {
  id: "sec-02",
  title: "Churn by plan tier",
  hypothesis: "Higher tiers have lower churn",
  status: "accepted",
  py_path: "analyses/02_churn.py",
  png_path: "charts/02_churn.png",
  md_path: "sections/02_churn.md",
};

const DROPPED: Section = {
  id: "sec-03",
  title: "Dropped section",
  hypothesis: "Not important",
  status: "dropped",
  py_path: null,
  png_path: null,
  md_path: null,
};

const QUEUED: Section = {
  id: "sec-04",
  title: "Queued section",
  hypothesis: "Not yet built",
  status: "queued",
  py_path: null,
  png_path: null,
  md_path: null,
};

const PROPOSED: Section = {
  id: "sec-05",
  title: "Proposed section",
  hypothesis: "Built, not yet accepted",
  status: "proposed",
  py_path: "analyses/05.py",
  png_path: "charts/05.png",
  md_path: "sections/05.md",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DoneView", () => {
  // ── happy path ─────────────────────────────────────────────────────────────

  it("renders the done-view container", () => {
    render(<DoneView sections={[ACCEPTED_1]} onExport={vi.fn()} />);
    expect(screen.getByTestId("done-view")).toBeInTheDocument();
  });

  it("renders heading with 'Brief complete' text", () => {
    render(<DoneView sections={[]} onExport={vi.fn()} />);
    expect(screen.getByTestId("done-view")).toHaveTextContent("Brief complete");
  });

  it("renders accepted sections in plan order", () => {
    render(<DoneView sections={[ACCEPTED_1, ACCEPTED_2]} onExport={vi.fn()} />);

    expect(screen.getByTestId("done-section-list")).toBeInTheDocument();
    const items = screen.getAllByTestId(/^done-section-item-/);
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Cohort overview");
    expect(items[1]).toHaveTextContent("Churn by plan tier");
  });

  it("renders per-section data-testid done-section-item-{id}", () => {
    render(<DoneView sections={[ACCEPTED_1, ACCEPTED_2]} onExport={vi.fn()} />);
    expect(screen.getByTestId("done-section-item-sec-01")).toBeInTheDocument();
    expect(screen.getByTestId("done-section-item-sec-02")).toBeInTheDocument();
  });

  it("shows export button", () => {
    render(<DoneView sections={[ACCEPTED_1]} onExport={vi.fn()} />);
    expect(screen.getByTestId("done-export-button")).toBeInTheDocument();
  });

  it("clicking export button calls onExport", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();
    render(<DoneView sections={[ACCEPTED_1]} onExport={onExport} />);

    await user.click(screen.getByTestId("done-export-button"));
    expect(onExport).toHaveBeenCalledOnce();
  });

  // ── filtering — only accepted sections ────────────────────────────────────

  it("excludes dropped, queued, and proposed sections", () => {
    render(
      <DoneView
        sections={[ACCEPTED_1, DROPPED, QUEUED, PROPOSED]}
        onExport={vi.fn()}
      />
    );

    const items = screen.getAllByTestId(/^done-section-item-/);
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("Cohort overview");

    expect(screen.queryByTestId(`done-section-item-${DROPPED.id}`)).toBeNull();
    expect(screen.queryByTestId(`done-section-item-${QUEUED.id}`)).toBeNull();
    expect(screen.queryByTestId(`done-section-item-${PROPOSED.id}`)).toBeNull();
  });

  // ── edge cases ─────────────────────────────────────────────────────────────

  it("renders without crash when no sections are accepted", () => {
    render(<DoneView sections={[DROPPED, QUEUED]} onExport={vi.fn()} />);
    expect(screen.getByTestId("done-view")).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^done-section-item-/)).toHaveLength(0);
    // Export button still present even with zero accepted sections
    expect(screen.getByTestId("done-export-button")).toBeInTheDocument();
  });

  it("renders without crash when sections array is empty", () => {
    render(<DoneView sections={[]} onExport={vi.fn()} />);
    expect(screen.getByTestId("done-view")).toBeInTheDocument();
  });

  it("renders a very long section title without breaking", () => {
    const longTitle = "A".repeat(200);
    const section: Section = { ...ACCEPTED_1, title: longTitle };
    render(<DoneView sections={[section]} onExport={vi.fn()} />);
    expect(screen.getByTestId(`done-section-item-${section.id}`)).toHaveTextContent(longTitle);
  });

  it("export button has type=button to avoid form submission", () => {
    render(<DoneView sections={[]} onExport={vi.fn()} />);
    const btn = screen.getByTestId("done-export-button");
    expect(btn.tagName).toBe("BUTTON");
    expect(btn).toHaveAttribute("type", "button");
  });

  // ── null / missing inputs ──────────────────────────────────────────────────

  it("does not render done-section-list when no accepted sections exist", () => {
    render(<DoneView sections={[]} onExport={vi.fn()} />);
    expect(screen.queryByTestId("done-section-list")).toBeNull();
  });
});
