import { useEffect, useState } from "react";
import SetupView from "./components/StageViews/SetupView";
import ProfileView from "./components/StageViews/ProfileView";
import PlanView from "./components/StageViews/PlanView";
import BuildView from "./components/StageViews/BuildView";
import ActivityRail from "./components/ActivityRail";
import ExportButton from "./components/ExportButton";
import { useSSE } from "./hooks/useSSE";
import { api } from "./hooks/useApi";
import type { Profile, Section } from "./types/api";
import type { SSEEvent } from "./types/events";

type Stage = "setup" | "profiling" | "planning" | "building" | "done";

interface AppState {
  stage: Stage | null;
  profile: Profile | null;
  plan: Section[];
  loading: boolean;
  error: string | null;
}

function renderStageView(
  stage: Stage,
  profile: Profile | null,
  plan: Section[],
  onSectionsChange: (sections: Section[]) => void
): JSX.Element {
  switch (stage) {
    case "setup":
      return <SetupView />;
    case "profiling":
      return <ProfileView profile={profile} />;
    case "planning":
      return <PlanView initialSections={plan} />;
    case "building":
    case "done":
      return <BuildView sections={plan} onSectionsChange={onSectionsChange} />;
  }
}

export default function App() {
  const [state, setState] = useState<AppState>({
    stage: null,
    profile: null,
    plan: [],
    loading: true,
    error: null,
  });

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
    }
  });

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

  const acceptedSectionCount = state.plan.filter((s) => s.status === "accepted").length;
  const showExport = state.stage === "building" || state.stage === "done";

  const handleSectionsChange = (sections: Section[]) => {
    setState((s) => ({ ...s, plan: sections }));
  };

  return (
    <div className="min-h-screen bg-[#f6f2e9] text-[#1a1a17]">
      <header className="border-b border-[#ddd5c5] bg-[#faf7f0] px-8 py-4 flex items-center justify-between">
        <span className="font-serif text-[17.6px] font-medium tracking-tight text-[#1a1a17]">Data Buddy</span>
        {showExport && <ExportButton disabled={acceptedSectionCount === 0} />}
      </header>
      <div className="max-w-6xl mx-auto px-8 py-10 flex gap-6">
        <div className="flex-1">
          {renderStageView(state.stage, state.profile, state.plan, handleSectionsChange)}
        </div>
        {state.stage !== "setup" && (
          <div className="w-72 shrink-0">
            <div className="bg-white border border-[#ddd5c5] rounded p-4">
              <ActivityRail />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
