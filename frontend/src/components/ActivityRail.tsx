import { useActivityState } from "../hooks/useActivityState";

const DOTS = [".", "..", "..."] as const;

export default function ActivityRail() {
  const { isRunning, bashCount, fileCount, dotPhase } = useActivityState();

  const hasActivity = bashCount > 0 || fileCount > 0;

  const parts: string[] = [];
  if (bashCount > 0) parts.push(`${bashCount} command${bashCount === 1 ? "" : "s"} run`);
  if (fileCount > 0) parts.push(`${fileCount} file${fileCount === 1 ? "" : "s"} written`);
  const summaryText = parts.join(" · ");

  return (
    <div data-testid="activity-rail">
      <p className="text-xs font-semibold uppercase tracking-wide text-[#9b9489] mb-3">
        Activity
      </p>

      {!isRunning && !hasActivity && (
        <p className="text-xs text-[#c6bfb0] italic">No activity yet.</p>
      )}

      {isRunning && (
        <div
          data-testid="activity-thinking"
          className="text-sm py-1.5 text-[#b8732a]"
        >
          Thinking{DOTS[dotPhase]}
        </div>
      )}

      {hasActivity && (
        <div
          data-testid="activity-summary"
          className="text-xs text-[#9b9489] mt-1"
        >
          {summaryText}
        </div>
      )}
    </div>
  );
}
