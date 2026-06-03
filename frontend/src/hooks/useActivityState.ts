import { useCallback, useEffect, useRef, useState } from "react";
import { useSSE } from "./useSSE";
import type { SSEEvent } from "../types/events";

export interface ActivityRailState {
  isRunning: boolean;
  bashCount: number;
  fileCount: number;
  dotPhase: 0 | 1 | 2;
  log: string[];
}

const INITIAL: ActivityRailState = {
  isRunning: false,
  bashCount: 0,
  fileCount: 0,
  dotPhase: 0,
  log: [],
};

const LOG_CAP = 20;

function appendLog(existing: string[], entry: string): string[] {
  const next = [...existing, entry];
  return next.length > LOG_CAP ? next.slice(next.length - LOG_CAP) : next;
}

export function useActivityState(): ActivityRailState {
  const [state, setState] = useState<ActivityRailState>(INITIAL);
  const wasIdleRef = useRef(true);

  const handleEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case "tool.bash_running":
      case "tool.bash_done":
      case "tool.file_written":
      case "message.part": {
        const resetting = wasIdleRef.current;
        if (resetting) wasIdleRef.current = false;
        setState((prev) => {
          const base = resetting ? { ...INITIAL, isRunning: true } : { ...prev, isRunning: true };

          if (event.type === "tool.bash_done") {
            return {
              ...base,
              bashCount: base.bashCount + 1,
              log: appendLog(base.log, `$ ${event.command as string}`),
            };
          }
          if (event.type === "tool.file_written") {
            return {
              ...base,
              fileCount: base.fileCount + 1,
              log: appendLog(base.log, `✎ ${event.file as string}`),
            };
          }
          return base;
        });
        break;
      }
      case "session.idle":
        wasIdleRef.current = true;
        setState((prev) => ({ ...prev, isRunning: false, dotPhase: 0 }));
        break;

      default:
        break;
    }
  }, []);

  useSSE(handleEvent);

  useEffect(() => {
    if (!state.isRunning) return;
    const id = setInterval(() => {
      setState((prev) => ({
        ...prev,
        dotPhase: ((prev.dotPhase + 1) % 3) as 0 | 1 | 2,
      }));
    }, 500);
    return () => clearInterval(id);
  }, [state.isRunning]);

  return state;
}
