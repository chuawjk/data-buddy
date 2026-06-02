// useSSE — React hook that subscribes to GET /api/events (standard SSE).
// Coded against docs/contracts/SSE_CONTRACT.md — the ground truth for event shapes.
// Auto-reconnects on connection drop after a 2 s delay.

import { useCallback, useEffect, useRef, useState } from "react";
import type { SSEEvent } from "../types/events";

const EVENTS_URL = "/api/events";
const RECONNECT_DELAY_MS = 2000;

interface UseSSEResult {
  connected: boolean;
}

/**
 * Opens an EventSource to GET /api/events, parses each message as an SSEEvent
 * (discriminated union by `type`), and calls onEvent for each.
 *
 * Returns { connected } — true while the EventSource is open and false while
 * a reconnect is pending (error + waiting for the 2 s timer to fire).
 *
 * Cleans up (closes EventSource, cancels any pending reconnect) on unmount.
 */
export function useSSE(onEvent: (event: SSEEvent) => void): UseSSEResult {
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep onEvent stable across renders without triggering the effect.
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    const es = new EventSource(EVENTS_URL);
    esRef.current = es;
    setConnected(true);

    es.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data as string) as SSEEvent;
        onEventRef.current(event);
      } catch {
        // Malformed JSON — log at debug level and continue.
        // Unknown event types must not crash the hook (SSE_CONTRACT.md §5 rule 3).
        console.debug("[useSSE] failed to parse event data:", e.data);
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setConnected(false);

      // Schedule reconnect after RECONNECT_DELAY_MS.
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, RECONNECT_DELAY_MS);
    };
    // connect is intentionally stable; onEvent is accessed via ref
  }, []);

  useEffect(() => {
    connect();

    return () => {
      // Cancel pending reconnect timer.
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      // Close the EventSource.
      if (esRef.current !== null) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [connect]);

  return { connected };
}
