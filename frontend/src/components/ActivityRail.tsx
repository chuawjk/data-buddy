// ActivityRail — live feed of agent activity during a turn.
//
// Subscribes to the SSE stream via useSSE and maintains an ordered list of
// activity items derived from the events described in SSE_CONTRACT.md §2.2–§2.3:
//
//   tool.bash_running  → "Running: <command>"   data-testid="activity-tool-running"
//   tool.bash_done     → "Done: <command> (Xms)" data-testid="activity-tool-done"
//   tool.file_written  → "Wrote: <path>"         data-testid="activity-file-written"
//   message.part       → appends to a text buffer data-testid="activity-message"
//
// On session.idle the rail resets (per acceptance criterion: "given a new turn
// when it starts, then the rail resets").  session.idle is the signal the backend
// uses to indicate a turn has completed and the agent is idle — the next prompt
// will start a new turn.
//
// Items render in arrival order.  Out-of-order events are accepted without
// de-duplication or reordering; the list simply grows in the order events arrive.

import { useCallback, useState } from "react";
import { useSSE } from "../hooks/useSSE";
import type { SSEEvent } from "../types/events";

// ---------------------------------------------------------------------------
// Activity item types
// ---------------------------------------------------------------------------

type ToolRunningItem = {
  kind: "tool-running";
  id: string;
  command: string;
};

type ToolDoneItem = {
  kind: "tool-done";
  id: string;
  command: string;
  elapsed_ms: number;
};

type FileWrittenItem = {
  kind: "file-written";
  id: string;
  file: string;
};

type ActivityItem = ToolRunningItem | ToolDoneItem | FileWrittenItem;

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

interface ActivityState {
  items: ActivityItem[];
  messageText: string;
}

const EMPTY_STATE: ActivityState = { items: [], messageText: "" };

// Monotonically increasing key for React list keys.
let _nextKey = 0;
function nextKey(): string {
  return String(++_nextKey);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ActivityRail() {
  const [state, setState] = useState<ActivityState>(EMPTY_STATE);

  const handleEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case "tool.bash_running":
        setState((prev) => ({
          ...prev,
          items: [
            ...prev.items,
            { kind: "tool-running", id: nextKey(), command: event.command },
          ],
        }));
        break;

      case "tool.bash_done":
        setState((prev) => ({
          ...prev,
          items: [
            ...prev.items,
            {
              kind: "tool-done",
              id: nextKey(),
              command: event.command,
              elapsed_ms: event.elapsed_ms,
            },
          ],
        }));
        break;

      case "tool.file_written":
        setState((prev) => ({
          ...prev,
          items: [
            ...prev.items,
            { kind: "file-written", id: nextKey(), file: event.file },
          ],
        }));
        break;

      case "message.part":
        setState((prev) => ({
          ...prev,
          messageText: prev.messageText + event.content,
        }));
        break;

      case "session.idle":
        // A new turn is starting — reset the rail.
        setState(EMPTY_STATE);
        break;

      // All other event types are intentionally ignored here.
      default:
        break;
    }
  }, []);

  useSSE(handleEvent);

  const { items, messageText } = state;

  return (
    <div data-testid="activity-rail" className="rail-section">
      {items.map((item) => {
        if (item.kind === "tool-running") {
          return (
            <div
              key={item.id}
              data-testid="activity-tool-running"
              className="activity-item"
            >
              <span className="activity-line running">Running: {item.command}</span>
            </div>
          );
        }

        if (item.kind === "tool-done") {
          return (
            <div
              key={item.id}
              data-testid="activity-tool-done"
              className="activity-item"
            >
              <span className="activity-line done">
                Done: {item.command} ({item.elapsed_ms}ms)
              </span>
            </div>
          );
        }

        // kind === "file-written"
        return (
          <div
            key={item.id}
            data-testid="activity-file-written"
            className="activity-item"
          >
            <span className="activity-line done">Wrote: {item.file}</span>
          </div>
        );
      })}

      {/* Message text area — always rendered; empty string when no message.part events received */}
      <div data-testid="activity-message" className="activity-detail">
        {messageText}
      </div>
    </div>
  );
}
