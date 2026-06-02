// SetupView — N1-S15
// Entry screen: collect CSV + aim, POST to /setup.
// Coded against docs/contracts/API_CONTRACT.html §1 · POST /setup.
// Mockup reference: docs/mockups/DATA_BUDDY_MOCKUPS_STRIPPED.html · Stage 1.

import { useState } from "react";
import { api } from "../../hooks/useApi";
import type { ApiError } from "../../types/api";

export default function SetupView() {
  const [file, setFile] = useState<File | null>(null);
  const [aim, setAim] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div data-testid="setup-view">
      {/* top bar */}
      <div className="topbar">
        <div className="brand">
          <div className="brand-mark" />
          <div className="brand-name">Brief</div>
        </div>
        <div className="aim">
          <span className="aim-label">Aim</span>
          <span className="aim-text" style={{ color: "var(--ink-3)", fontStyle: "italic" }}>
            Not yet set
          </span>
        </div>
      </div>

      {/* main content */}
      <div className="center">
        <div className="center-inner">
          <div className="brief-eyebrow">New brief</div>
          <h2 className="brief-h1">
            Start with <em>data</em> and an <em>aim</em>.
          </h2>
          <p className="brief-deck">
            Drop a CSV file below, then tell the agent what you&apos;re trying to learn. The plan
            and the brief follow from there.
          </p>

          <form onSubmit={handleSubmit} noValidate>
            {/* CSV upload zone */}
            <div className="upload">
              <div className="upload-icon" />
              <div className="upload-title">Drop a CSV, or browse</div>
              <div className="upload-sub">CSV up to 200 MB</div>

              <input
                data-testid="csv-input"
                type="file"
                accept=".csv"
                style={{ marginTop: 16 }}
                onChange={(e) => {
                  const selected = e.target.files?.[0] ?? null;
                  setFile(selected);
                  setError(null);
                }}
              />

              {file && (
                <div style={{ marginTop: 8, fontSize: "13.2px", color: "var(--ink-2)" }}>
                  Selected: <strong>{file.name}</strong>
                </div>
              )}
            </div>

            {/* Aim textarea */}
            <div className="aim-input-block">
              <div className="aim-input-label">Aim of investigation</div>
              <textarea
                data-testid="aim-input"
                className="aim-input"
                placeholder="e.g. understand drivers of customer churn in Q3 2025"
                value={aim}
                rows={2}
                style={{ resize: "vertical", width: "100%" }}
                onChange={(e) => {
                  setAim(e.target.value);
                  setError(null);
                }}
              />
            </div>

            {/* Error surface */}
            {error !== null && (
              <div
                data-testid="setup-error"
                style={{
                  marginTop: 12,
                  padding: "10px 14px",
                  background: "var(--rem)",
                  border: "1px solid var(--rem-line)",
                  borderRadius: 3,
                  color: "var(--danger)",
                  fontSize: "13.8px",
                }}
              >
                {error}
              </div>
            )}

            {/* Submit button */}
            <div style={{ marginTop: 20 }}>
              <button
                data-testid="submit-btn"
                type="submit"
                className="btn primary"
                disabled={!canSubmit}
              >
                {submitting ? "Starting..." : "Start analysis"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
