// ProfileView — renders profile.json data and the bottom-bar re-profile input.
//
// Props:
//   profile — the current Profile (null while loading / before profiling completes)
//
// Layout (per DATA_BUDDY_MOCKUPS_STRIPPED.html Stage 2):
//   - shape strip: rows, columns counts   data-testid="shape-strip"
//   - column list: one row per column     data-testid="column-row" (multiple)
//   - bottom bar: input + submit          data-testid="reprof-input" / "reprof-submit"
//
// On profile.ready SSE: re-calls api.getState() and updates internal profile state.

import { useCallback, useState } from "react";
import { api } from "../../hooks/useApi";
import { useSSE } from "../../hooks/useSSE";
import type { Profile } from "../../types/api";
import type { SSEEvent } from "../../types/events";

interface ProfileViewProps {
  /** Profile hydrated from GET /state on load (null until profiling completes). */
  profile: Profile | null;
}

export default function ProfileView({ profile: initialProfile }: ProfileViewProps) {
  const [profile, setProfile] = useState<Profile | null>(initialProfile);
  const [inputText, setInputText] = useState("");
  const [isTurnInFlight, setIsTurnInFlight] = useState(false);

  const handleEvent = useCallback((event: SSEEvent) => {
    if (event.type === "profile.ready") {
      api
        .getState()
        .then((state) => {
          if (state.profile !== null) {
            setProfile(state.profile);
          }
        })
        .catch(() => {
          setProfile(event.profile);
        });
    }
  }, []);

  useSSE(handleEvent);

  const handleSubmit = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isTurnInFlight) return;
    setIsTurnInFlight(true);
    try {
      await api.postTurn(text);
      setInputText("");
    } finally {
      setIsTurnInFlight(false);
    }
  }, [inputText, isTurnInFlight]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        void handleSubmit();
      }
    },
    [handleSubmit]
  );

  const isSubmitDisabled = inputText.trim() === "" || isTurnInFlight;

  return (
    <div data-testid="profile-view" className="profile-view">
      {profile !== null && (
        <div data-testid="shape-strip" className="profile-shape">
          <div className="shape-item">
            <span className="shape-num">{profile.shape.rows}</span>
            <span className="shape-label">rows</span>
          </div>
          <div className="shape-item">
            <span className="shape-num">{profile.shape.columns}</span>
            <span className="shape-label">columns</span>
          </div>
          {profile.shape.nulls_pct !== undefined && (
            <div className="shape-item">
              <span className="shape-num">{profile.shape.nulls_pct}%</span>
              <span className="shape-label">nulls overall</span>
            </div>
          )}
          {profile.shape.target !== null && (
            <div className="shape-item">
              <span className="shape-sub">{profile.shape.target}</span>
              <span className="shape-label">target (inferred)</span>
            </div>
          )}
        </div>
      )}

      {profile !== null && profile.columns.length > 0 && (
        <div className="col-rows">
          {profile.columns.map((col) => (
            <div key={col.name} data-testid="column-row" className="col-row">
              <span className="col-name">{col.name}</span>
              <span className="col-type">{col.type}</span>
              <span className="col-summary">{col.summary}</span>
              {col.flags.length > 0 && (
                <span className="col-flags">
                  {col.flags.map((flag) => (
                    <span key={flag} className="flag-chip">
                      {flag}
                    </span>
                  ))}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="botbar-input-row">
        <input
          data-testid="reprof-input"
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Anything to flag before the plan? e.g. 'cap support_tickets at p99'…"
          disabled={isTurnInFlight}
          className="reprof-input"
        />
        <button
          data-testid="reprof-submit"
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isSubmitDisabled}
          className="reprof-submit"
        >
          Send
        </button>
      </div>
    </div>
  );
}
