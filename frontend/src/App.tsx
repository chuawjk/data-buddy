import { useEffect, useState } from "react";
import SetupView from "./components/StageViews/SetupView";
import ProfileView from "./components/StageViews/ProfileView";
import PlanView from "./components/StageViews/PlanView";
import BuildView from "./components/StageViews/BuildView";

type Stage = "setup" | "profiling" | "planning" | "building" | "done";

interface AppState {
  stage: Stage | null;
  loading: boolean;
  error: string | null;
}

function renderStageView(stage: Stage): JSX.Element {
  switch (stage) {
    case "setup":
      return <SetupView />;
    case "profiling":
      return <ProfileView />;
    case "planning":
      return <PlanView />;
    case "building":
    case "done":
      return <BuildView />;
  }
}

export default function App() {
  const [state, setState] = useState<AppState>({
    stage: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    fetch("/api/state")
      .then((res) => {
        if (!res.ok) {
          throw new Error(`GET /api/state returned ${res.status}`);
        }
        return res.json() as Promise<{ stage: Stage }>;
      })
      .then((data) => {
        setState({ stage: data.stage, loading: false, error: null });
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Failed to load state";
        setState({ stage: null, loading: false, error: message });
      });
  }, []);

  if (state.loading) {
    return (
      <div data-testid="loading-indicator" className="p-8 text-center">
        Loading…
      </div>
    );
  }

  if (state.error !== null || state.stage === null) {
    return (
      <div data-testid="error-banner" className="p-8 text-center text-red-600">
        {state.error ?? "Unknown error"}
      </div>
    );
  }

  return <>{renderStageView(state.stage)}</>;
}
