// BuildView — N2-S16
// Section-by-section build screen. Hydrates sections from GET /state on mount
// and handles section.* SSE events to update state live.
//
// Component hierarchy:
//   BuildView [data-testid="build-view"]
//   ├── section list [data-testid="section-list"]
//   │   └── section-row-{id}, section-status-{id} per section
//   ├── SectionPane [data-testid="section-pane"] (active section only)
//   └── BottomBar [data-testid="build-bottom-bar"]
//       ├── input [data-testid="bottom-bar-input"]
//       ├── send [data-testid="bottom-bar-send"]
//       └── error [data-testid="turn-busy-error"]
//
// Coded against docs/contracts/API_CONTRACT.html — never backend internals.

import { useCallback, useEffect, useState } from "react";
import { api } from "../../hooks/useApi";
import { useSSE } from "../../hooks/useSSE";
import SectionPane from "../SectionPane";
import type { Section } from "../../types/api";
import type { SSEEvent } from "../../types/events";

interface BuildViewProps {
  /** Sections injected from App.tsx (hydrated from GET /state). */
  sections?: Section[];
}

const STATUS_LABEL: Record<Section["status"], string> = {
  queued: "queued",
  building: "building",
  proposed: "proposed",
  accepted: "accepted",
  dropped: "dropped",
  failed: "failed",
};

const STATUS_CLASS: Record<Section["status"], string> = {
  queued: "bg-[#e8e1d1] text-[#9b9489]",
  building: "bg-[#fef3e2] text-[#b8732a]",
  proposed: "bg-[#dbeae8] text-[#4a7a76]",
  accepted: "bg-[#d4edda] text-[#2d6a4f]",
  dropped: "bg-[#f8d7da] text-[#721c24]",
  failed: "bg-[#f8d7da] text-[#721c24]",
};

/** Sections that deserve a detail pane: anything that has started building or finished. */
function getSectionPanes(sections: Section[]): Section[] {
  return sections.filter((s) => s.status !== "queued");
}

export default function BuildView({ sections: initialSections = [] }: BuildViewProps) {
  const [sections, setSections] = useState<Section[]>(initialSections);
  const [redirectText, setRedirectText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [turnError, setTurnError] = useState<string | null>(null);
  const [fileReadyPath, setFileReadyPath] = useState<string | null>(null);

  // Hydrate sections from GET /state on mount (covers page refresh with pre-existing sections)
  useEffect(() => {
    api
      .getState()
      .then((state) => {
        setSections(state.plan ?? []);
      })
      .catch(() => {
        // If initial fetch fails, keep what was passed via props (may be empty)
      });
  }, []);

  const handleEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case "plan.ready":
        // Refresh sections from state after plan is ready
        api
          .getState()
          .then((state) => setSections(state.plan ?? []))
          .catch(() => {
            // Use sections from event as fallback
            setSections(event.sections ?? []);
          });
        break;

      case "section.building":
        // Mark the building section; leave others unchanged
        setSections((prev) =>
          prev.map((s) =>
            s.id === event.section_id ? { ...s, status: "building", title: event.title } : s
          )
        );
        break;

      case "section.proposed":
        // Refresh full section data from state
        api
          .getState()
          .then((state) => setSections(state.plan ?? []))
          .catch(() => {
            // Patch in what we know from the event
            setSections((prev) =>
              prev.map((s) =>
                s.id === event.section_id
                  ? {
                      ...s,
                      status: "proposed",
                      py_path: event.py_path,
                      png_path: event.png_path,
                      md_path: event.md_path,
                    }
                  : s
              )
            );
          });
        break;

      case "section.failed":
        setSections((prev) =>
          prev.map((s) => (s.id === event.section_id ? { ...s, status: "failed" } : s))
        );
        break;

      case "file.ready":
        setFileReadyPath(event.path);
        break;

      default:
        break;
    }
  }, []);

  useSSE(handleEvent);

  const handleAccept = useCallback(async (id: string) => {
    // Optimistic update
    setSections((prev) => prev.map((s) => (s.id === id ? { ...s, status: "accepted" } : s)));
    try {
      await api.postSectionAccept(id);
    } catch {
      // Revert optimistic update on failure
      setSections((prev) => prev.map((s) => (s.id === id ? { ...s, status: "proposed" } : s)));
    }
  }, []);

  const handleDrop = useCallback(async (id: string) => {
    // Optimistic update
    setSections((prev) => prev.map((s) => (s.id === id ? { ...s, status: "dropped" } : s)));
    try {
      await api.postSectionDrop(id);
    } catch {
      // Revert optimistic update on failure
      setSections((prev) => prev.map((s) => (s.id === id ? { ...s, status: "proposed" } : s)));
    }
  }, []);

  const handleSend = useCallback(async () => {
    const text = redirectText.trim();
    if (!text || isSending) return;
    setIsSending(true);
    setTurnError(null);
    try {
      await api.postTurn(text);
      setRedirectText("");
    } catch (err: unknown) {
      const apiErr = err as { error?: string; message?: string };
      if (apiErr.error === "turn_busy") {
        setTurnError(apiErr.message ?? "Agent is busy. Please wait.");
      }
      // Non-busy errors: preserve input, no error shown (agent will recover)
    } finally {
      setIsSending(false);
    }
  }, [redirectText, isSending]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        void handleSend();
      }
    },
    [handleSend]
  );

  const sectionPanes = getSectionPanes(sections);

  return (
    <div data-testid="build-view" className="flex flex-col gap-6">
      {/* Section list */}
      {sections.length > 0 && (
        <div
          data-testid="section-list"
          className="bg-white border border-[#ddd5c5] rounded-lg overflow-hidden"
        >
          {sections.map((section, idx) => (
            <div
              key={section.id}
              data-testid={`section-row-${section.id}`}
              className={`flex items-center gap-3 px-4 py-3 border-b border-[#e8e1d1] last:border-0 text-sm ${
                idx % 2 === 0 ? "bg-white" : "bg-[#faf7f0]"
              }`}
            >
              <span className="text-[#9b9489] text-xs w-6 shrink-0">{idx + 1}</span>
              <span className="flex-1 font-medium text-[#1a1a17]">{section.title}</span>
              <span
                data-testid={`section-status-${section.id}`}
                className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_CLASS[section.status]}`}
              >
                {STATUS_LABEL[section.status]}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* One pane per section that has started building or finished, top-to-bottom */}
      {sectionPanes.map((section) => (
        <SectionPane
          key={section.id}
          section={section}
          onAccept={(id) => void handleAccept(id)}
          onDrop={(id) => void handleDrop(id)}
          fileReadyPath={fileReadyPath}
        />
      ))}

      {/* Bottom bar */}
      <div
        data-testid="build-bottom-bar"
        className="bg-white border border-[#ddd5c5] rounded-lg px-4 py-3 flex gap-3 items-center"
      >
        <input
          data-testid="bottom-bar-input"
          type="text"
          value={redirectText}
          onChange={(e) => {
            setRedirectText(e.target.value);
            if (turnError !== null) setTurnError(null);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Comment on this section, or ask the agent to revise…"
          disabled={isSending}
          className="flex-1 border border-[#ddd5c5] rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30 disabled:opacity-50"
        />
        <button
          data-testid="bottom-bar-send"
          type="button"
          onClick={() => void handleSend()}
          disabled={redirectText.trim() === "" || isSending}
          className="bg-[#b8732a] text-white rounded-lg px-5 py-2.5 text-sm font-medium hover:bg-[#a06120] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </div>

      {/* Turn busy error */}
      {turnError !== null && (
        <div
          data-testid="turn-busy-error"
          className="text-sm text-[#a85c4a] bg-[#f9f0ed] border border-[#e8cfc8] rounded px-3 py-2"
        >
          {turnError}
        </div>
      )}
    </div>
  );
}
