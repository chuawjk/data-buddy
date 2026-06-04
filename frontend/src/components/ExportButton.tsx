// ExportButton
// Renders in the App header for planning and building/done stages.
// Calls GET /api/export and triggers a .zip file download.
// Disabled when no sections have status "accepted".

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../hooks/useApi";
import type { ApiError } from "../types/api";

interface ExportButtonProps {
  /** True when no sections have been accepted — disables the button. */
  disabled: boolean;
}

export default function ExportButton({ disabled }: ExportButtonProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-dismiss error after 4 seconds
  useEffect(() => {
    if (error !== null) {
      dismissTimerRef.current = setTimeout(() => {
        setError(null);
      }, 4000);
    }
    return () => {
      if (dismissTimerRef.current !== null) {
        clearTimeout(dismissTimerRef.current);
        dismissTimerRef.current = null;
      }
    };
  }, [error]);

  const handleClick = useCallback(async () => {
    if (disabled || isExporting) return;

    setIsExporting(true);
    setError(null);

    try {
      const blob = await api.getExport();

      // Trigger browser download
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "brief.zip";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      const apiError = err as ApiError;
      const message =
        typeof apiError?.message === "string"
          ? apiError.message
          : "Export failed. Please try again.";
      setError(message);
    } finally {
      setIsExporting(false);
    }
  }, [disabled, isExporting]);

  return (
    <div className="flex items-center gap-2">
      <button
        data-testid="export-btn"
        type="button"
        disabled={disabled || isExporting}
        onClick={() => void handleClick()}
        className="flex items-center gap-1.5 bg-[#1a1a17] text-white rounded-sm px-4 py-1.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#333330] transition-colors"
      >
        {isExporting ? "Exporting…" : "↓ Export zip"}
      </button>
      {error !== null && (
        <span
          data-testid="export-error"
          className="text-xs text-[#a85c4a]"
        >
          {error}
        </span>
      )}
    </div>
  );
}
