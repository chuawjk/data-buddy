// SectionPane
// Renders the active section's artefacts: code block, chart image, interpretation.
// Receives a Section prop and fetches text artefacts via api.getFile.
// Chart is rendered as <img src="/api/file?path=..."> — the browser handles
// the binary GET; api.getFile returns text and would produce a broken image.
//
// data-testid list:
//   section-pane, section-pane-title, section-building-spinner,
//   section-code, section-chart, section-interpretation,
//   section-file-error, section-accept-btn, section-drop-btn,
//   section-failed-notice, section-retry-btn, section-drop-failed-btn, watchdog-notice

import { useEffect, useRef, useState } from "react";
import { api } from "../hooks/useApi";
import type { Section } from "../types/api";

export interface SectionPaneProps {
  section: Section;
  onAccept: (id: string) => void;
  onDrop: (id: string) => void;
  onRevise?: (id: string, text: string) => Promise<void> | void;
  /** Optional: re-fetch trigger key from file.ready events */
  fileReadyPath?: string | null;
  /**
   * When true, show failed-section controls (Retry / Drop).
   * Set by BuildView when section.failed is received for this section.
   */
  isFailed?: boolean;
  /**
   * The failure reason from section.failed.
   * "timeout" triggers the watchdog-notice variant (distinct copy + testid).
   */
  failedReason?: string;
  /**
   * Called when the user clicks Retry on a failed section.
   * Re-queues the section build via POST /turn with section_id.
   */
  onRetry?: (id: string) => void;
}

interface ArtefactState {
  pyContent: string | null;
  mdBody: string | null;
  fileError: string | null;
}

export default function SectionPane({
  section,
  onAccept,
  onDrop,
  onRevise,
  fileReadyPath,
  isFailed = false,
  failedReason,
  onRetry,
}: SectionPaneProps) {
  const [artefacts, setArtefacts] = useState<ArtefactState>({
    pyContent: null,
    mdBody: null,
    fileError: null,
  });
  const [artefactsLoaded, setArtefactsLoaded] = useState(false);
  const [codeExpanded, setCodeExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [revisionText, setRevisionText] = useState("");
  const [isRevising, setIsRevising] = useState(false);
  const [revisionError, setRevisionError] = useState<string | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Collapse code when the section changes so stale expand state doesn't carry over.
  useEffect(() => {
    setCodeExpanded(false);
  }, [section.id]);

  const isBuilding = section.status === "building";
  const isProposed =
    section.status === "proposed" || section.status === "accepted" || section.status === "dropped";
  const hasArtefacts =
    section.py_path != null || section.md_path != null || section.png_path != null;

  // Fetch text artefacts when paths change (not on every re-render).
  // Key: py_path + md_path so heartbeats don't cause spurious re-fetches.
  useEffect(() => {
    if (!hasArtefacts) return;

    setArtefactsLoaded(false);
    let cancelled = false;

    async function fetchArtefacts() {
      const results: Partial<ArtefactState> = { fileError: null };

      if (section.py_path != null) {
        try {
          results.pyContent = await api.getFile(section.py_path);
        } catch {
          if (!cancelled) {
            setArtefacts((prev) => ({
              ...prev,
              fileError: `Failed to load code: ${section.py_path ?? ""}`,
            }));
          }
          return;
        }
      }

      if (section.md_path != null) {
        try {
          const raw = await api.getFile(section.md_path);
          // Strip YAML frontmatter (--- ... ---) if present
          const withoutFrontmatter = raw.replace(/^---[\s\S]*?---\n?/, "");
          results.mdBody = withoutFrontmatter.trim();
        } catch {
          if (!cancelled) {
            setArtefacts((prev) => ({
              ...prev,
              fileError: `Failed to load interpretation: ${section.md_path ?? ""}`,
            }));
          }
          return;
        }
      }

      if (!cancelled) {
        setArtefacts((prev) => ({
          ...prev,
          pyContent: results.pyContent ?? prev.pyContent,
          mdBody: results.mdBody ?? prev.mdBody,
          fileError: null,
        }));
        setArtefactsLoaded(true);
      }
    }

    void fetchArtefacts();

    return () => {
      cancelled = true;
    };
    // Intentionally keyed on py_path and md_path only — not section object ref.
    // fileReadyPath triggers a re-fetch when a specific file is written.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section.py_path, section.md_path, fileReadyPath]);

  async function handleRevise() {
    const text = revisionText.trim();
    if (!text || isRevising || onRevise == null) return;

    setIsRevising(true);
    setRevisionError(null);
    try {
      await onRevise(section.id, text);
      setRevisionText("");
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setRevisionError(apiErr.message ?? "Could not revise this section.");
    } finally {
      setIsRevising(false);
    }
  }

  return (
    <div data-testid="section-pane" className="border border-[#ddd5c5] rounded-lg bg-white p-6">
      <h3 data-testid="section-pane-title" className="text-lg font-semibold text-[#1a1a17] mb-4">
        {section.title}
      </h3>

      {/* Failed section controls */}
      {isFailed && (
        <>
          {failedReason === "timeout" ? (
            <div
              data-testid="watchdog-notice"
              className="mt-3 bg-[#fdf0ed] border border-[#e8c4bb] rounded px-4 py-3 text-sm text-[#a85c4a]"
            >
              <p className="font-medium mb-2">Agent timed out on this section.</p>
              <div className="flex gap-2">
                <button
                  data-testid="section-retry-btn"
                  type="button"
                  onClick={() => onRetry?.(section.id)}
                  className="bg-[#a85c4a] text-white rounded-sm px-3 py-1 text-xs font-medium hover:bg-[#8f4e3e] transition-colors"
                >
                  Retry
                </button>
                <button
                  data-testid="section-drop-failed-btn"
                  type="button"
                  onClick={() => onDrop(section.id)}
                  className="border border-[#c8563d] text-[#c8563d] rounded-sm px-3 py-1 text-xs font-medium hover:bg-[#c8563d]/5 transition-colors"
                >
                  Drop section
                </button>
              </div>
            </div>
          ) : (
            <div
              data-testid="section-failed-notice"
              className="mt-3 bg-[#fdf0ed] border border-[#e8c4bb] rounded px-4 py-3 text-sm text-[#a85c4a]"
            >
              <p className="font-medium mb-2">Build failed for this section.</p>
              <div className="flex gap-2">
                <button
                  data-testid="section-retry-btn"
                  type="button"
                  onClick={() => onRetry?.(section.id)}
                  className="bg-[#a85c4a] text-white rounded-sm px-3 py-1 text-xs font-medium hover:bg-[#8f4e3e] transition-colors"
                >
                  Retry
                </button>
                <button
                  data-testid="section-drop-failed-btn"
                  type="button"
                  onClick={() => onDrop(section.id)}
                  className="border border-[#c8563d] text-[#c8563d] rounded-sm px-3 py-1 text-xs font-medium hover:bg-[#c8563d]/5 transition-colors"
                >
                  Drop section
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Building spinner */}
      {isBuilding && (
        <div
          data-testid="section-building-spinner"
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
          <span className="text-sm">Building section…</span>
        </div>
      )}

      {/* File error */}
      {artefacts.fileError !== null && (
        <div
          data-testid="section-file-error"
          className="mt-3 text-sm text-[#a85c4a] bg-[#f9f0ed] border border-[#e8cfc8] rounded px-3 py-2"
        >
          {artefacts.fileError}
        </div>
      )}

      {/* Artefacts (shown when proposed or hydrated from state) */}
      {isProposed && (
        <>
          {/* Chart image — browser handles binary GET, not api.getFile */}
          {section.png_path != null && (
            <div className="mt-4">
              <img
                data-testid="section-chart"
                src={`/api/file?path=${encodeURIComponent(section.png_path)}`}
                alt={`Chart for ${section.title}`}
                className="rounded border border-[#ddd5c5] max-w-full"
              />
            </div>
          )}

          {/* Interpretation */}
          {artefacts.mdBody != null && (
            <div
              data-testid="section-interpretation"
              className="mt-4 text-sm text-[#1a1a17] leading-relaxed"
            >
              {artefacts.mdBody}
            </div>
          )}

          {/* Section-scoped revision + Accept / Drop actions */}
          {section.status === "proposed" && (
            <div className="mt-6 flex flex-col gap-3">
              <div className="flex gap-2">
                <input
                  data-testid="section-revise-input"
                  type="text"
                  value={revisionText}
                  onChange={(e) => {
                    setRevisionText(e.target.value);
                    if (revisionError !== null) setRevisionError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void handleRevise();
                    }
                  }}
                  placeholder="Ask for a revision to this section..."
                  disabled={!artefactsLoaded || isRevising || onRevise == null}
                  className="flex-1 border border-[#ddd5c5] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30 disabled:opacity-50"
                />
                <button
                  data-testid="section-revise-btn"
                  type="button"
                  onClick={() => void handleRevise()}
                  disabled={
                    !artefactsLoaded || isRevising || onRevise == null || revisionText.trim() === ""
                  }
                  className="border border-[#b8732a] text-[#b8732a] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#b8732a]/5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Revise
                </button>
              </div>
              {revisionError !== null && (
                <div
                  data-testid="section-revise-error"
                  className="text-sm text-[#a85c4a] bg-[#f9f0ed] border border-[#e8cfc8] rounded px-3 py-2"
                >
                  {revisionError}
                </div>
              )}
              <div className="flex gap-3">
                <button
                  data-testid="section-accept-btn"
                  type="button"
                  onClick={() => onAccept(section.id)}
                  disabled={!artefactsLoaded}
                  className="bg-[#b8732a] text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-[#a06120] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Accept &amp; continue
                </button>
                <button
                  data-testid="section-drop-btn"
                  type="button"
                  onClick={() => onDrop(section.id)}
                  disabled={!artefactsLoaded}
                  className="border border-[#c8563d] text-[#c8563d] rounded-lg px-5 py-2 text-sm font-medium hover:bg-[#c8563d]/5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Drop section
                </button>
              </div>
            </div>
          )}

          {/* Show / hide code toggle — always at the bottom when code is available */}
          {artefacts.pyContent != null && (
            <div className="mt-4 pt-3 border-t border-[#ece8df]">
              <button
                data-testid="section-code-toggle"
                type="button"
                onClick={() => setCodeExpanded((e) => !e)}
                className="text-xs text-[#9b9489] hover:text-[#1a1a17] flex items-center gap-1 transition-colors"
              >
                <svg
                  className={`h-3 w-3 transition-transform ${codeExpanded ? "rotate-90" : ""}`}
                  viewBox="0 0 12 12"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {codeExpanded ? "Hide code" : "Show code"}
              </button>

              {/* Code block renders beneath the toggle when expanded */}
              {codeExpanded && (
                <div data-testid="section-code" className="mt-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-[#9b9489]">
                      {section.py_path ?? "code"}
                    </span>
                    <button
                      data-testid="section-code-copy-btn"
                      type="button"
                      onClick={() => {
                        void navigator.clipboard.writeText(artefacts.pyContent ?? "");
                        setCopied(true);
                        if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
                        copyTimerRef.current = setTimeout(() => setCopied(false), 1500);
                      }}
                      className="text-xs text-[#9b9489] hover:text-[#1a1a17] px-2 py-0.5 rounded border border-[#ddd5c5] hover:border-[#b8b0a4] transition-colors"
                    >
                      {copied ? "Copied!" : "Copy"}
                    </button>
                  </div>
                  <pre className="bg-[#f6f2e9] border border-[#ddd5c5] rounded p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap text-[#1a1a17]">
                    {artefacts.pyContent}
                  </pre>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
