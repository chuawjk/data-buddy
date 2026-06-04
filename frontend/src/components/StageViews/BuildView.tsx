// BuildView — N2-S16, updated N3-S05/S06/S07
// Section-by-section build screen. Hydrates sections from GET /state on mount
// and handles section.* SSE events to update state live.
//
// Component hierarchy:
//   BuildView [data-testid="build-view"]
//   ├── section list [data-testid="section-list"]
//   │   └── section-row-{id}, section-status-{id} per section
//   ├── SectionPane [data-testid="section-pane"] (sections that started/finished)
//       ├── failed controls when isFailed=true — N3-S06/S07
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
  /** Called whenever sections change locally (accept/drop) so App can update its plan state. */
  onSectionsChange?: (sections: Section[]) => void;
  /**
   * N3-S06/S07: map of section id → section.failed reason for sections that failed.
   * Each failed section shows Retry/Drop controls in its SectionPane.
   */
  failedSections?: Map<string, string>;
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

export default function BuildView({
  sections: initialSections = [],
  onSectionsChange,
  failedSections = new Map<string, string>(),
}: BuildViewProps) {
  const [sections, setSections] = useState<Section[]>(initialSections);
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
    setSections((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, status: "accepted" as const } : s));
      onSectionsChange?.(next);
      return next;
    });
    try {
      await api.postSectionAccept(id);
    } catch {
      setSections((prev) => {
        const reverted = prev.map((s) => (s.id === id ? { ...s, status: "proposed" as const } : s));
        onSectionsChange?.(reverted);
        return reverted;
      });
    }
  }, [onSectionsChange]);

  const handleDrop = useCallback(async (id: string) => {
    setSections((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, status: "dropped" as const } : s));
      onSectionsChange?.(next);
      return next;
    });
    try {
      await api.postSectionDrop(id);
    } catch {
      setSections((prev) => {
        const reverted = prev.map((s) => (s.id === id ? { ...s, status: "proposed" as const } : s));
        onSectionsChange?.(reverted);
        return reverted;
      });
    }
  }, [onSectionsChange]);

  const handleRevise = useCallback(async (id: string, text: string) => {
    await api.postTurn(text, id);
    setSections((prev) => {
      const next = prev.map((s) =>
        s.id === id
          ? { ...s, status: "building" as const, py_path: null, png_path: null, md_path: null }
          : s
      );
      onSectionsChange?.(next);
      return next;
    });
  }, [onSectionsChange]);

  // N3-S06: retry a failed section — POST /turn with section_id (no text = retry)
  const handleSectionRetry = useCallback(async (id: string) => {
    setSections((prev) => {
      const next = prev.map((s) =>
        s.id === id
          ? { ...s, status: "building" as const, py_path: null, png_path: null, md_path: null }
          : s
      );
      onSectionsChange?.(next);
      return next;
    });
    try {
      await api.postTurnRetry(id);
    } catch {
      // On failure, keep the failed state so the user can retry again
      setSections((prev) => {
        const reverted = prev.map((s) => (s.id === id ? { ...s, status: "failed" as const } : s));
        onSectionsChange?.(reverted);
        return reverted;
      });
    }
  }, [onSectionsChange]);

  const sectionPanes = getSectionPanes(sections);

  return (
    <div data-testid="build-view" className="flex flex-col gap-6">
      {/* Section list */}
      {sections.length > 0 && (
        <div
          data-testid="section-list"
          className="bg-white border border-[#ddd5c5] rounded overflow-hidden"
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
                className={`text-xs px-2 py-0.5 rounded-sm font-medium ${STATUS_CLASS[section.status]}`}
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
          onRevise={(id, text) => handleRevise(id, text)}
          fileReadyPath={fileReadyPath}
          isFailed={failedSections.has(section.id)}
          failedReason={failedSections.get(section.id)}
          onRetry={(id) => void handleSectionRetry(id)}
        />
      ))}
    </div>
  );
}
