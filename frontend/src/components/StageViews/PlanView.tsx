// PlanView — N2-S15
// Interactive plan-proposal screen.
//
// Layout:
//   - Heading + eyebrow
//   - Section list: title, hypothesis, edit/drop/reorder controls per row
//   - Add section button
//   - Error banner
//   - Bottom bar: agent revision input + Accept plan button
//
// Data flow:
//   - initialSections: Section[] from App.tsx (GET /state on load)
//   - Inline edits / drop / reorder: POST /plan/update (no agent turn)
//   - Bottom-bar text: POST /turn (agent revision)
//   - Accept: POST /plan/accept (advance to building stage)
//   - plan.ready SSE: reset sections from event.sections, clear isTurnInFlight
//   - turn.error SSE: show error in plan-error banner

import { useCallback, useState } from "react";
import { api } from "../../hooks/useApi";
import { useSSE } from "../../hooks/useSSE";
import type { Section } from "../../types/api";
import type { ApiError } from "../../types/api";
import type { SSEEvent } from "../../types/events";

export interface PlanViewProps {
  initialSections: Section[];
}

function getErrorMessage(err: unknown): string {
  const apiErr = err as ApiError;
  return typeof apiErr?.message === "string"
    ? apiErr.message
    : "An error occurred. Please try again.";
}

export default function PlanView({ initialSections }: PlanViewProps) {
  const [sections, setSections] = useState<Section[]>(initialSections);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [editingHypothesis, setEditingHypothesis] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isAccepting, setIsAccepting] = useState(false);
  const [isTurnInFlight, setIsTurnInFlight] = useState(false);
  const [turnText, setTurnText] = useState("");
  const [error, setError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // SSE handler
  // ---------------------------------------------------------------------------

  const handleEvent = useCallback((event: SSEEvent) => {
    if (event.type === "plan.ready") {
      setSections(event.sections);
      setIsTurnInFlight(false);
      setTurnText("");
    }
    if (event.type === "turn.error" && event.stage === "planning") {
      setError("Plan revision failed. Please try again.");
      setIsTurnInFlight(false);
    }
  }, []);

  useSSE(handleEvent);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  // Build the sections array with status: "queued" for all items (contract requirement)
  function asPlanUpdatePayload(s: Section[]): Section[] {
    return s.map((sec) => ({ ...sec, status: "queued" as const }));
  }

  async function callPlanUpdate(updated: Section[]) {
    setIsSaving(true);
    setError(null);
    try {
      await api.postPlanUpdate(asPlanUpdatePayload(updated));
      setSections(updated);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Edit handlers
  // ---------------------------------------------------------------------------

  const handleEditClick = useCallback((section: Section) => {
    setEditingId(section.id);
    setEditingTitle(section.title);
    setEditingHypothesis(section.hypothesis);
  }, []);

  const handleSaveEdit = useCallback(
    async (id: string) => {
      const updated = sections.map((s) =>
        s.id === id ? { ...s, title: editingTitle, hypothesis: editingHypothesis } : s
      );
      setEditingId(null);
      await callPlanUpdate(updated);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sections, editingTitle, editingHypothesis]
  );

  const handleCancelEdit = useCallback(() => {
    setEditingId(null);
    setEditingTitle("");
    setEditingHypothesis("");
  }, []);

  // ---------------------------------------------------------------------------
  // Drop handler
  // ---------------------------------------------------------------------------

  const handleDrop = useCallback(
    async (id: string) => {
      if (sections.length <= 1) return;
      const updated = sections.filter((s) => s.id !== id);
      await callPlanUpdate(updated);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sections]
  );

  // ---------------------------------------------------------------------------
  // Reorder handlers
  // ---------------------------------------------------------------------------

  const handleMoveUp = useCallback(
    async (id: string) => {
      const idx = sections.findIndex((s) => s.id === id);
      if (idx <= 0) return;
      const updated = [...sections];
      [updated[idx - 1], updated[idx]] = [updated[idx], updated[idx - 1]];
      await callPlanUpdate(updated);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sections]
  );

  const handleMoveDown = useCallback(
    async (id: string) => {
      const idx = sections.findIndex((s) => s.id === id);
      if (idx < 0 || idx >= sections.length - 1) return;
      const updated = [...sections];
      [updated[idx], updated[idx + 1]] = [updated[idx + 1], updated[idx]];
      await callPlanUpdate(updated);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sections]
  );

  // ---------------------------------------------------------------------------
  // Add section handler
  // ---------------------------------------------------------------------------

  const handleAddSection = useCallback(() => {
    const newId = `sec_new_${Date.now()}`;
    const newSection: Section = {
      id: newId,
      title: "",
      hypothesis: "",
      status: "queued",
      py_path: null,
      png_path: null,
      md_path: null,
    };
    setSections((prev) => [...prev, newSection]);
    setEditingId(newId);
    setEditingTitle("");
    setEditingHypothesis("");
  }, []);

  // ---------------------------------------------------------------------------
  // Bottom-bar turn handler
  // ---------------------------------------------------------------------------

  const handleTurnSubmit = useCallback(async () => {
    const text = turnText.trim();
    if (!text || isTurnInFlight) return;
    setIsTurnInFlight(true);
    setError(null);
    try {
      await api.postTurn(text);
      setTurnText("");
      // Plan refresh happens via plan.ready SSE
    } catch (err) {
      setError(getErrorMessage(err));
      setIsTurnInFlight(false);
      // Input preserved on error for retry
    }
  }, [turnText, isTurnInFlight]);

  const handleTurnKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        void handleTurnSubmit();
      }
    },
    [handleTurnSubmit]
  );

  // ---------------------------------------------------------------------------
  // Accept handler
  // ---------------------------------------------------------------------------

  const handleAccept = useCallback(async () => {
    if (isAccepting) return;
    setIsAccepting(true);
    setError(null);
    try {
      await api.postPlanAccept();
      // App.tsx handles stage.changed SSE to advance to BuildView
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsAccepting(false);
    }
  }, [isAccepting]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isTurnSubmitDisabled = turnText.trim() === "" || isTurnInFlight;
  const showLoading = sections.length === 0 || isTurnInFlight;

  return (
    <div data-testid="plan-view" className="flex flex-col gap-6">
      {/* Header */}
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-[#9b9489] mb-1">
          Analysis Plan
        </p>
        <h2 className="text-2xl font-serif font-light text-[#1a1a17]">Review your plan</h2>
        <p className="text-sm text-[#5d5a52] mt-1">
          Edit sections and hypotheses inline, reorder, or ask the agent to revise. Accept when
          ready to build.
        </p>
      </div>

      {/* Error banner */}
      {error !== null && (
        <div
          data-testid="plan-error"
          className="bg-[#fdf0ed] border border-[#e8c4bb] rounded-lg px-4 py-3 text-sm text-[#a85c4a]"
        >
          {error}
        </div>
      )}

      {/* Saving indicator */}
      {isSaving && (
        <div data-testid="plan-saving-indicator" className="text-xs text-[#9b9489]">
          Saving…
        </div>
      )}

      {showLoading && (
        <div
          data-testid="plan-loading-spinner"
          className="flex items-center gap-3 py-6 text-[#9b9489]"
        >
          <svg
            className="animate-spin h-5 w-5 text-[#b8732a]"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          <span className="text-sm">
            {sections.length === 0 ? "Drafting analysis plan..." : "Revising plan..."}
          </span>
        </div>
      )}

      {/* Section list */}
      {sections.length > 0 && (
        <div data-testid="plan-section-list" className="flex flex-col gap-2">
          {sections.map((section, idx) => {
            const isEditing = editingId === section.id;
            const isFirst = idx === 0;
            const isLast = idx === sections.length - 1;
            const isOnlyOne = sections.length <= 1;

            return (
              <div
                key={section.id}
                data-testid={`plan-section-${section.id}`}
                className="bg-white border border-[#ddd5c5] rounded-lg px-4 py-3"
              >
                {isEditing ? (
                  /* Edit mode */
                  <div className="flex flex-col gap-2">
                    <input
                      data-testid={`plan-section-title-${section.id}`}
                      type="text"
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      placeholder="Section title"
                      className="border border-[#ddd5c5] rounded px-3 py-1.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30"
                    />
                    <input
                      data-testid={`plan-section-hyp-${section.id}`}
                      type="text"
                      value={editingHypothesis}
                      onChange={(e) => setEditingHypothesis(e.target.value)}
                      placeholder="Hypothesis"
                      className="border border-[#ddd5c5] rounded px-3 py-1.5 text-sm text-[#5d5a52] focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30"
                    />
                    <div className="flex gap-2 mt-1">
                      <button
                        data-testid={`plan-save-edit-${section.id}`}
                        type="button"
                        onClick={() => void handleSaveEdit(section.id)}
                        className="bg-[#1a1a17] text-white rounded px-3 py-1 text-xs font-medium hover:bg-[#333330]"
                      >
                        Save
                      </button>
                      <button
                        data-testid={`plan-cancel-edit-${section.id}`}
                        type="button"
                        onClick={handleCancelEdit}
                        className="border border-[#ddd5c5] rounded px-3 py-1 text-xs text-[#5d5a52] hover:bg-[#f6f2e9]"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Display mode */
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <span
                        data-testid={`plan-section-title-${section.id}`}
                        className="block font-medium text-[#1a1a17] text-sm"
                      >
                        {section.title || <span className="text-[#9b9489] italic">Untitled</span>}
                      </span>
                      <span
                        data-testid={`plan-section-hyp-${section.id}`}
                        className="block text-xs text-[#5d5a52] mt-0.5"
                      >
                        {section.hypothesis}
                      </span>
                    </div>

                    {/* Row controls */}
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        data-testid={`plan-move-up-${section.id}`}
                        type="button"
                        disabled={isFirst}
                        onClick={() => void handleMoveUp(section.id)}
                        className="p-1 rounded text-[#9b9489] hover:bg-[#f6f2e9] disabled:opacity-30 disabled:cursor-not-allowed"
                        aria-label="Move up"
                      >
                        ↑
                      </button>
                      <button
                        data-testid={`plan-move-down-${section.id}`}
                        type="button"
                        disabled={isLast}
                        onClick={() => void handleMoveDown(section.id)}
                        className="p-1 rounded text-[#9b9489] hover:bg-[#f6f2e9] disabled:opacity-30 disabled:cursor-not-allowed"
                        aria-label="Move down"
                      >
                        ↓
                      </button>
                      <button
                        data-testid={`plan-edit-${section.id}`}
                        type="button"
                        onClick={() => handleEditClick(section)}
                        className="p-1 rounded text-[#9b9489] hover:bg-[#f6f2e9] text-xs"
                        aria-label="Edit"
                      >
                        Edit
                      </button>
                      <button
                        data-testid={`plan-drop-${section.id}`}
                        type="button"
                        disabled={isOnlyOne}
                        onClick={() => void handleDrop(section.id)}
                        className="p-1 rounded text-[#9b9489] hover:bg-[#fdf0ed] hover:text-[#a85c4a] text-xs disabled:opacity-30 disabled:cursor-not-allowed"
                        aria-label="Drop section"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Add section */}
      {sections.length > 0 && (
        <div>
          <button
            data-testid="plan-add-section"
            type="button"
            onClick={handleAddSection}
            className="text-sm text-[#b8732a] border border-dashed border-[#ddd5c5] rounded-lg px-4 py-2 w-full hover:bg-[#f4e5d0]/50 transition-colors"
          >
            + Add section
          </button>
        </div>
      )}

      {/* Bottom bar — agent revision */}
      <div className="border-t border-[#ddd5c5] pt-4 flex flex-col gap-3">
        <div className="flex gap-3">
          <input
            data-testid="plan-turn-input"
            type="text"
            value={turnText}
            onChange={(e) => setTurnText(e.target.value)}
            onKeyDown={handleTurnKeyDown}
            placeholder="Tell the agent what to change…"
            disabled={isTurnInFlight}
            className="flex-1 border border-[#ddd5c5] rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30 disabled:opacity-50"
          />
          <button
            data-testid="plan-turn-submit"
            type="button"
            disabled={isTurnSubmitDisabled}
            onClick={() => void handleTurnSubmit()}
            className="bg-[#b8732a] text-white rounded-lg px-5 py-2.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Revise
          </button>
        </div>

        <button
          data-testid="plan-accept-btn"
          type="button"
          disabled={isAccepting || sections.length === 0}
          onClick={() => void handleAccept()}
          className="bg-[#4a7a76] text-white rounded-lg px-6 py-3 text-sm font-medium self-start disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#3f6965] transition-colors"
        >
          {isAccepting ? "Accepting..." : "Accept plan & start building"}
        </button>
      </div>
    </div>
  );
}
