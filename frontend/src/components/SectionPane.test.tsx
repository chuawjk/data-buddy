// SectionPane tests — N2-S16
// TDD: tests written before/alongside implementation.
// Acceptance criteria from docs/plans/2026-06-03-n2-s16.md

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import SectionPane from "./SectionPane";
import type { Section } from "../types/api";

// ---------------------------------------------------------------------------
// Mock useApi
// ---------------------------------------------------------------------------

const mockGetFile = vi.fn();

vi.mock("../hooks/useApi", () => ({
  api: {
    getFile: (...args: unknown[]) => mockGetFile(...args),
  },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PROPOSED_SECTION: Section = {
  id: "sec-01",
  title: "Cohort overview",
  hypothesis: "Check churn baseline",
  status: "proposed",
  py_path: "analyses/01_cohort.py",
  png_path: "charts/01_cohort.png",
  md_path: "sections/01_cohort.md",
};

const BUILDING_SECTION: Section = {
  id: "sec-02",
  title: "Churn by plan tier",
  hypothesis: "Higher tiers have lower churn",
  status: "building",
  py_path: null,
  png_path: null,
  md_path: null,
};

const QUEUED_SECTION: Section = {
  id: "sec-03",
  title: "Engagement signals",
  hypothesis: "Engagement predicts churn",
  status: "queued",
  py_path: null,
  png_path: null,
  md_path: null,
};

const MOCK_PY_CONTENT = `import pandas as pd\ndf = pd.read_csv("data.csv")`;
const MOCK_MD_CONTENT = `Churn rate is 14.3% for the cohort.`;

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe("SectionPane", () => {
  const mockOnAccept = vi.fn();
  const mockOnDrop = vi.fn();
  const mockOnRevise = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFile.mockImplementation((path: string) => {
      if (path.endsWith(".py")) return Promise.resolve(MOCK_PY_CONTENT);
      if (path.endsWith(".md")) return Promise.resolve(MOCK_MD_CONTENT);
      return Promise.reject(new Error("Unknown file"));
    });
  });

  // ── test_renders_pane_title ──────────────────────────────────────────────

  it("test_renders_pane_title — section-pane-title displays section title", async () => {
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    expect(screen.getByTestId("section-pane-title")).toHaveTextContent("Cohort overview");
  });

  // ── test_shows_spinner_when_building ────────────────────────────────────

  it("test_shows_spinner_when_building — section-building-spinner visible when status=building", () => {
    render(<SectionPane section={BUILDING_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    expect(screen.getByTestId("section-building-spinner")).toBeInTheDocument();
  });

  // ── test_no_spinner_when_proposed ───────────────────────────────────────

  it("test_no_spinner_when_proposed — spinner absent when status=proposed", async () => {
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    expect(screen.queryByTestId("section-building-spinner")).toBeNull();
  });

  // ── test_renders_code_and_interpretation_for_proposed ───────────────────

  it("test_renders_code_and_interpretation_for_proposed — interpretation shown; code collapsed behind toggle", async () => {
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    // Interpretation renders immediately after fetch.
    await waitFor(() => {
      expect(screen.getByTestId("section-interpretation")).toHaveTextContent("Churn rate is 14.3%");
    });

    // Code block is collapsed by default.
    expect(screen.queryByTestId("section-code")).toBeNull();
    // Toggle button is visible.
    expect(screen.getByTestId("section-code-toggle")).toHaveTextContent("Show code");
  });

  // ── test_code_toggle_expands_and_collapses ───────────────────────────────

  it("test_code_toggle_expands_and_collapses — clicking toggle shows then hides code block", async () => {
    const user = userEvent.setup();
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-code-toggle")).toBeInTheDocument();
    });

    // Expand.
    await user.click(screen.getByTestId("section-code-toggle"));
    expect(screen.getByTestId("section-code")).toHaveTextContent("import pandas");
    expect(screen.getByTestId("section-code-toggle")).toHaveTextContent("Hide code");

    // Collapse.
    await user.click(screen.getByTestId("section-code-toggle"));
    expect(screen.queryByTestId("section-code")).toBeNull();
    expect(screen.getByTestId("section-code-toggle")).toHaveTextContent("Show code");
  });

  // ── test_copy_button_calls_clipboard ────────────────────────────────────

  it("test_copy_button_calls_clipboard — copy button writes py content to clipboard", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-code-toggle")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("section-code-toggle"));
    await user.click(screen.getByTestId("section-code-copy-btn"));

    expect(writeText).toHaveBeenCalledWith(MOCK_PY_CONTENT);
  });

  // ── test_renders_chart_img_with_correct_src ──────────────────────────────

  it("test_renders_chart_img_with_correct_src — section-chart img uses /api/file?path=... src", async () => {
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-chart")).toBeInTheDocument();
    });

    const img = screen.getByTestId("section-chart") as HTMLImageElement;
    expect(img.src).toContain("/api/file?path=");
    expect(img.src).toContain(encodeURIComponent("charts/01_cohort.png"));
  });

  // ── test_shows_accept_and_drop_when_proposed ─────────────────────────────

  it("test_shows_accept_and_drop_when_proposed — accept/drop buttons visible for proposed section", async () => {
    render(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        onRevise={mockOnRevise}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("section-accept-btn")).toBeInTheDocument();
    });

    expect(screen.getByTestId("section-drop-btn")).toBeInTheDocument();
    expect(screen.getByTestId("section-revise-input")).toBeInTheDocument();
    expect(screen.getByTestId("section-revise-btn")).toBeInTheDocument();
  });

  // ── test_accept_calls_onAccept ────────────────────────────────────────────

  it("test_accept_calls_onAccept — clicking accept button calls onAccept with section id", async () => {
    const user = userEvent.setup();
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-accept-btn")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("section-accept-btn"));
    expect(mockOnAccept).toHaveBeenCalledOnce();
    expect(mockOnAccept).toHaveBeenCalledWith("sec-01");
  });

  // ── test_drop_calls_onDrop ────────────────────────────────────────────────

  it("test_drop_calls_onDrop — clicking drop button calls onDrop with section id", async () => {
    const user = userEvent.setup();
    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-drop-btn")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("section-drop-btn"));
    expect(mockOnDrop).toHaveBeenCalledOnce();
    expect(mockOnDrop).toHaveBeenCalledWith("sec-01");
  });

  it("test_revise_calls_onRevise — clicking revise calls onRevise with section id and text", async () => {
    const user = userEvent.setup();
    mockOnRevise.mockResolvedValue(undefined);
    render(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        onRevise={mockOnRevise}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("section-revise-input")).not.toBeDisabled();
    });

    await user.type(screen.getByTestId("section-revise-input"), "use grouped bars");
    await user.click(screen.getByTestId("section-revise-btn"));

    expect(mockOnRevise).toHaveBeenCalledOnce();
    expect(mockOnRevise).toHaveBeenCalledWith("sec-01", "use grouped bars");
  });

  it("test_revise_clears_on_success — revision input clears after onRevise resolves", async () => {
    const user = userEvent.setup();
    mockOnRevise.mockResolvedValue(undefined);
    render(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        onRevise={mockOnRevise}
      />
    );

    const input = screen.getByTestId("section-revise-input") as HTMLInputElement;
    await waitFor(() => {
      expect(input).not.toBeDisabled();
    });

    await user.type(input, "tighten the interpretation");
    await user.click(screen.getByTestId("section-revise-btn"));

    await waitFor(() => {
      expect(input.value).toBe("");
    });
  });

  it("test_revise_error — failed revision preserves input and shows error", async () => {
    const user = userEvent.setup();
    mockOnRevise.mockRejectedValue(new Error("Agent is busy."));
    render(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        onRevise={mockOnRevise}
      />
    );

    const input = screen.getByTestId("section-revise-input") as HTMLInputElement;
    await waitFor(() => {
      expect(input).not.toBeDisabled();
    });

    await user.type(input, "use grouped bars");
    await user.click(screen.getByTestId("section-revise-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("section-revise-error")).toHaveTextContent("Agent is busy.");
    });
    expect(input.value).toBe("use grouped bars");
  });

  // ── test_shows_file_error_on_fetch_failure ────────────────────────────────

  it("test_shows_file_error_on_fetch_failure — section-file-error shown when api.getFile rejects", async () => {
    mockGetFile.mockRejectedValue(new Error("Network error"));

    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-file-error")).toBeInTheDocument();
    });
  });

  // ── test_no_buttons_for_building ─────────────────────────────────────────

  it("test_no_buttons_for_building — accept/drop absent when status=building", () => {
    render(<SectionPane section={BUILDING_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    expect(screen.queryByTestId("section-accept-btn")).toBeNull();
    expect(screen.queryByTestId("section-drop-btn")).toBeNull();
  });

  // ── test_no_buttons_for_queued ────────────────────────────────────────────

  it("test_no_buttons_for_queued — accept/drop absent when status=queued", () => {
    render(<SectionPane section={QUEUED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    expect(screen.queryByTestId("section-accept-btn")).toBeNull();
    expect(screen.queryByTestId("section-drop-btn")).toBeNull();
  });

  // ── test_does_not_refetch_on_unrelated_state_changes ─────────────────────

  it("test_does_not_refetch_on_unrelated_state_changes — getFile called only once when fileReadyPath stays the same", async () => {
    const { rerender } = render(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        fileReadyPath={null}
      />
    );

    await waitFor(() => {
      expect(mockGetFile).toHaveBeenCalled();
    });

    const callCountAfterMount = mockGetFile.mock.calls.length;

    // Re-render with same paths — should NOT re-fetch
    rerender(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        fileReadyPath={null}
      />
    );

    // Give React a tick to process effects
    await act(async () => {
      await Promise.resolve();
    });

    expect(mockGetFile.mock.calls.length).toBe(callCountAfterMount);
  });

  // ── test_refetches_when_file_ready_path_changes ───────────────────────────

  it("test_refetches_when_file_ready_path_changes — getFile called again when fileReadyPath changes", async () => {
    const { rerender } = render(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        fileReadyPath={null}
      />
    );

    await waitFor(() => {
      expect(mockGetFile).toHaveBeenCalled();
    });

    const callCountAfterMount = mockGetFile.mock.calls.length;

    // Simulate file.ready event changing the path
    rerender(
      <SectionPane
        section={PROPOSED_SECTION}
        onAccept={mockOnAccept}
        onDrop={mockOnDrop}
        fileReadyPath="analyses/01_cohort.py"
      />
    );

    await waitFor(() => {
      expect(mockGetFile.mock.calls.length).toBeGreaterThan(callCountAfterMount);
    });
  });

  // ── test_strips_frontmatter_from_md ──────────────────────────────────────

  it("test_strips_frontmatter_from_md — YAML frontmatter stripped from interpretation", async () => {
    const mdWithFrontmatter = `---\ntitle: Section 1\nstatus: proposed\n---\nChurn baseline is 14.3%.`;
    mockGetFile.mockImplementation((path: string) => {
      if (path.endsWith(".py")) return Promise.resolve(MOCK_PY_CONTENT);
      if (path.endsWith(".md")) return Promise.resolve(mdWithFrontmatter);
      return Promise.reject(new Error("Unknown file"));
    });

    render(<SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-interpretation")).toBeInTheDocument();
    });

    const interp = screen.getByTestId("section-interpretation");
    expect(interp.textContent).not.toContain("title: Section 1");
    expect(interp.textContent).toContain("Churn baseline is 14.3%");
  });

  // ── test_no_code_when_no_py_path ─────────────────────────────────────────

  it("test_no_code_when_no_py_path — section-code and toggle absent when py_path is null", async () => {
    const sectionNoPy: Section = {
      ...PROPOSED_SECTION,
      py_path: null,
    };
    mockGetFile.mockImplementation((path: string) => {
      if (path.endsWith(".md")) return Promise.resolve(MOCK_MD_CONTENT);
      return Promise.reject(new Error("Unknown file"));
    });

    render(<SectionPane section={sectionNoPy} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-interpretation")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("section-code")).toBeNull();
    expect(screen.queryByTestId("section-code-toggle")).toBeNull();
  });

  // ── test_no_chart_when_no_png_path ────────────────────────────────────────

  it("test_no_chart_when_no_png_path — section-chart absent when png_path is null", async () => {
    const sectionNoPng: Section = {
      ...PROPOSED_SECTION,
      png_path: null,
    };

    render(<SectionPane section={sectionNoPng} onAccept={mockOnAccept} onDrop={mockOnDrop} />);

    // Wait for artefacts to load (code toggle appears when pyContent is ready).
    await waitFor(() => {
      expect(screen.getByTestId("section-code-toggle")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("section-chart")).toBeNull();
  });

  // ── test_accept_drop_disabled_until_artefacts_loaded ─────────────────────

  it("test_accept_drop_disabled_until_artefacts_loaded — buttons disabled before fetch, enabled after", async () => {
    const resolvers: Array<(v: string) => void> = [];
    mockGetFile.mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          resolvers.push(resolve);
        })
    );

    render(
      <SectionPane section={PROPOSED_SECTION} onAccept={mockOnAccept} onDrop={mockOnDrop} />
    );

    // Buttons present but disabled while fetches are in flight.
    await waitFor(() => {
      expect(screen.getByTestId("section-accept-btn")).toBeDisabled();
      expect(screen.getByTestId("section-drop-btn")).toBeDisabled();
    });

    // Resolve all pending fetches (py_path and md_path are fetched sequentially).
    act(() => {
      resolvers.forEach((r) => r("content"));
    });
    // Second fetch starts after first resolves — drain any newly added resolver.
    await waitFor(() => resolvers.length >= 2);
    act(() => {
      resolvers.forEach((r) => r("content"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("section-accept-btn")).not.toBeDisabled();
      expect(screen.getByTestId("section-drop-btn")).not.toBeDisabled();
    });
  });
});
