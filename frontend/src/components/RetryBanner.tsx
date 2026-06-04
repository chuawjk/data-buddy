// RetryBanner
// Inline error banner rendered at the top of a stage view when turn.error arrives.
// Every turn.error is retryable from the UI perspective (no retryable prop needed).
// Copy varies by reason: "timeout" → "Agent timed out — retry?"
//                        otherwise → "Couldn't complete this step — retry."
//
// data-testid: retry-banner, retry-banner-btn

interface RetryBannerProps {
  /** The reason string from the turn.error event. Controls copy. */
  reason: string;
  /** Called when the user clicks Retry. */
  onRetry: () => void;
}

export default function RetryBanner({ reason, onRetry }: RetryBannerProps) {
  const message =
    reason === "timeout"
      ? "Agent timed out — retry?"
      : "Couldn't complete this step — retry.";

  return (
    <div
      data-testid="retry-banner"
      className="flex items-center justify-between gap-4 bg-[#fdf0ed] border border-[#e8c4bb] rounded px-4 py-3 text-sm text-[#a85c4a]"
    >
      <span>{message}</span>
      <button
        data-testid="retry-banner-btn"
        type="button"
        onClick={onRetry}
        className="shrink-0 bg-[#a85c4a] text-white rounded-sm px-3 py-1 text-xs font-medium hover:bg-[#8f4e3e] transition-colors"
      >
        Retry
      </button>
    </div>
  );
}
