import { useEffect, useRef } from "react";
import { useActivityState } from "../hooks/useActivityState";

const DOTS = [".", "..", "..."] as const;

export default function ActivityRail() {
  const { isRunning, bashCount, fileCount, dotPhase, log } = useActivityState();
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  const hasActivity = bashCount > 0 || fileCount > 0;

  const parts: string[] = [];
  if (bashCount > 0) parts.push(`${bashCount} command${bashCount === 1 ? "" : "s"} run`);
  if (fileCount > 0) parts.push(`${fileCount} file${fileCount === 1 ? "" : "s"} written`);
  const summaryText = parts.join(" · ");

  return (
    <div data-testid="activity-rail">
      <p className="text-xs font-semibold uppercase tracking-wide text-[#9b9489] mb-3">
        Agent Activity
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

      {log.length > 0 && (
        <div
          data-testid="activity-log"
          className="mt-2 max-h-[27rem] overflow-y-auto rounded bg-[#1e1c1a] p-2 font-mono text-xs text-[#c6bfb0] space-y-0.5"
        >
          {log.map((entry, i) => (
            <div key={i} className="line-clamp-3 leading-5">
              {entry}
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}
    </div>
  );
}
