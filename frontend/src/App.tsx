import { useCallback, useEffect, useState } from "react";
import SetupView from "./components/StageViews/SetupView";
import ProfileView from "./components/StageViews/ProfileView";
import PlanView from "./components/StageViews/PlanView";
import BuildView from "./components/StageViews/BuildView";
import DoneView from "./components/StageViews/DoneView";
import ActivityRail from "./components/ActivityRail";
import RetryBanner from "./components/RetryBanner";
import { useSSE } from "./hooks/useSSE";
import { api } from "./hooks/useApi";
import type { Profile, Section } from "./types/api";
import type { SSEEvent, TurnErrorEvent } from "./types/events";

type Stage = "setup" | "profiling" | "planning" | "building" | "done";

interface AppState {
  stage: Stage | null;
  profile: Profile | null;
  plan: Section[];
  loading: boolean;
  error: string | null;
}

export default function App() {
  const [state, setState] = useState<AppState>({
    stage: null,
    profile: null,
    plan: [],
    loading: true,
    error: null,
  });
  const [turnError, setTurnError] = useState<TurnErrorEvent | null>(null);
  const [failedSections, setFailedSections] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    fetch("/api/state")
      .then((res) => {
        if (!res.ok) {
          throw new Error(`GET /api/state returned ${res.status}`);
        }
        return res.json() as Promise<{ stage: Stage; profile: Profile | null; plan: Section[] }>;
      })
      .then((data) => {
        setState({
          stage: data.stage,
          profile: data.profile ?? null,
          plan: data.plan ?? [],
          loading: false,
          error: null,
        });
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Failed to load state";
        setState({ stage: null, profile: null, plan: [], loading: false, error: message });
      });
  }, []);

  useSSE((event: SSEEvent) => {
    if (event.type === "stage.changed" || event.type === "profile.ready") {
      // Clear turn error and failed sections on stage transition
      setTurnError(null);
      setFailedSections(new Map());
      api
        .getState()
        .then((data) => {
          setState({
            stage: data.stage,
            profile: data.profile ?? null,
            plan: data.plan ?? [],
            loading: false,
            error: null,
          });
        })
        .catch(() => {
          // SSE-triggered refresh failure is silent — the current state remains.
        });
    }
    if (event.type === "plan.ready") {
      setState((s) => ({ ...s, plan: event.sections }));
      setTurnError(null);
    }
    if (event.type === "turn.error") {
      setTurnError(event);
    }
    if (event.type === "section.failed") {
      setFailedSections((prev) => {
        const next = new Map(prev);
        next.set(event.section_id, event.reason);
        return next;
      });
    }
  });

  const handleSectionsChange = useCallback((sections: Section[]) => {
    setState((s) => ({ ...s, plan: sections }));
  }, []);

  const handleRetryTurn = useCallback(async () => {
    setTurnError(null);
    try {
      await api.postTurnRetry();
    } catch {
      // Retry failed silently — banner was already dismissed
    }
  }, []);

  const handleExport = useCallback(async () => {
    try {
      const blob = await api.getExport();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "data-buddy-export.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Export error is silent — user can retry via the export button
    }
  }, []);

  if (state.loading) {
    return (
      <div
        data-testid="loading-indicator"
        className="min-h-screen bg-[#f6f2e9] text-[#1a1a17] flex items-center justify-center"
      >
        <p className="text-[#9b9489] text-sm">Loading…</p>
      </div>
    );
  }

  if (state.error !== null || state.stage === null) {
    return (
      <div
        data-testid="error-banner"
        className="min-h-screen bg-[#f6f2e9] text-[#1a1a17] flex items-center justify-center"
      >
        <p className="text-[#a85c4a] text-sm">{state.error ?? "Unknown error"}</p>
      </div>
    );
  }

  function renderStageView(): JSX.Element {
    switch (state.stage) {
      case "setup":
        return <SetupView />;
      case "profiling":
        return <ProfileView profile={state.profile} />;
      case "planning":
        return <PlanView initialSections={state.plan} />;
      case "building":
        return (
          <BuildView
            sections={state.plan}
            onSectionsChange={handleSectionsChange}
            failedSections={failedSections}
          />
        );
      case "done":
        return (
          <DoneView
            sections={state.plan}
            onExport={() => void handleExport()}
          />
        );
      default:
        return <SetupView />;
    }
  }

  return (
    <div className="min-h-screen bg-[#f6f2e9] text-[#1a1a17]">
      <header className="border-b border-[#ddd5c5] bg-[#faf7f0] px-8 py-4 flex items-center justify-between">
        <span className="font-serif text-[17.6px] font-medium tracking-tight text-[#1a1a17]">Data Buddy</span>
      </header>
      <div className="max-w-6xl mx-auto px-8 py-10 flex gap-6">
        <div className="flex-1">
          {renderStageView()}
        </div>
        {state.stage !== "setup" && (
          <div className="w-72 shrink-0 flex flex-col gap-3">
            <div className="bg-white border border-[#ddd5c5] rounded p-4">
              <ActivityRail />
            </div>
            {turnError != null && (
              <RetryBanner reason={turnError.reason} onRetry={() => void handleRetryTurn()} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
