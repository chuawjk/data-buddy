// SetupView — N1-S15
// Entry screen: collect CSV + aim, POST to /setup.
// Coded against docs/contracts/API_CONTRACT.html §1 · POST /setup.
// Mockup reference: docs/mockups/DATA_BUDDY_MOCKUPS_STRIPPED.html · Stage 1.

import { useRef, useState } from "react";
import { api } from "../../hooks/useApi";
import type { ApiError } from "../../types/api";

export default function SetupView() {
  const [file, setFile] = useState<File | null>(null);
  const [aim, setAim] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Submit is enabled only when a file is selected and aim is non-empty.
  const canSubmit = file !== null && aim.trim().length > 0 && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || file === null) return;

    setSubmitting(true);
    setError(null);

    try {
      await api.postSetup(file, aim.trim());
      // App.tsx listens for stage.changed via useSSE and will re-render
      // when the backend transitions to "profiling". No local navigation needed.
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      setError(apiErr.message ?? "Setup failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(true);
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer?.files?.[0] ?? null;
    if (dropped) {
      setFile(dropped);
      setError(null);
    }
  }

  function handleDropZoneClick() {
    fileInputRef.current?.click();
  }

  return (
    <div data-testid="setup-view" className="flex items-center justify-center py-12">
      <div className="bg-white border border-[#ddd5c5] rounded-xl p-8 shadow-sm max-w-lg w-full">
        <h2 className="text-xl font-semibold text-[#1a1a17] mb-2">Upload your dataset</h2>
        <p className="text-sm text-[#5d5a52] mb-6">
          Drop a CSV file below, then tell the agent what you&apos;re trying to learn. The plan and
          the brief follow from there.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          {/* CSV upload zone */}
          <div>
            <label className="block text-sm font-medium text-[#1a1a17]">
              CSV file
              <span className="ml-1 text-xs text-[#9b9489] font-normal">(up to 200 MB)</span>
            </label>

            {/* Hidden native file input — triggered by click on drop zone */}
            <input
              ref={fileInputRef}
              data-testid="csv-input"
              type="file"
              accept=".csv"
              className="sr-only"
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                setFile(selected);
                setError(null);
              }}
            />

            {/* Drag-and-drop zone */}
            <div
              data-testid="drop-zone"
              data-dragging={dragging ? "true" : undefined}
              onClick={handleDropZoneClick}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={[
                "mt-1 w-full border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
                dragging
                  ? "border-[#b8732a] bg-[#b8732a]/5"
                  : "border-[#ddd5c5] hover:border-[#b8732a]/50",
              ].join(" ")}
            >
              <p className="text-sm text-[#5d5a52]">Drop a CSV, or browse</p>
              {file && (
                <p className="mt-2 text-xs text-[#5d5a52]">
                  Selected: <strong>{file.name}</strong>
                </p>
              )}
            </div>
          </div>

          {/* Aim textarea */}
          <div className="mt-4">
            <label className="block text-sm font-medium text-[#1a1a17]">
              Aim of investigation
            </label>
            <textarea
              data-testid="aim-input"
              placeholder="e.g. understand drivers of customer churn in Q3 2025"
              value={aim}
              rows={2}
              className="mt-1 w-full border border-[#ddd5c5] rounded-lg p-3 text-sm text-[#1a1a17] resize-none focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30"
              onChange={(e) => {
                setAim(e.target.value);
                setError(null);
              }}
            />
          </div>

          {/* Error surface */}
          {error !== null && (
            <div data-testid="setup-error" className="mt-3 text-sm text-[#a85c4a]">
              {error}
            </div>
          )}

          {/* Submit button */}
          <button
            data-testid="submit-btn"
            type="submit"
            disabled={!canSubmit}
            className="mt-6 w-full bg-[#b8732a] text-white rounded-lg py-2.5 text-sm font-medium hover:bg-[#a06120] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting ? "Starting..." : "Start analysis"}
          </button>
        </form>
      </div>
    </div>
  );
}
