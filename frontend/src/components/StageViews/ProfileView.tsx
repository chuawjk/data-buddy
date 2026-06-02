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
    } catch {
      // On failure the input is intentionally preserved so the user can retry.
      // The backend will emit a turn.error SSE event for the activity rail.
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
    <div data-testid="profile-view" className="flex flex-col gap-4">
      {profile !== null && (
        <div
          data-testid="shape-strip"
          className="flex gap-6 bg-[#f4e5d0] border border-[#ddd5c5] rounded-lg px-5 py-3 text-sm font-medium text-[#5d5a52] mb-6"
        >
          <div className="flex flex-col items-center">
            <span className="text-lg font-semibold text-[#1a1a17]">{profile.shape.rows}</span>
            <span className="text-xs">rows</span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-lg font-semibold text-[#1a1a17]">{profile.shape.columns}</span>
            <span className="text-xs">columns</span>
          </div>
          {profile.shape.nulls_pct !== undefined && (
            <div className="flex flex-col items-center">
              <span className="text-lg font-semibold text-[#1a1a17]">
                {profile.shape.nulls_pct}%
              </span>
              <span className="text-xs">nulls overall</span>
            </div>
          )}
          {profile.shape.target !== null && (
            <div className="flex flex-col items-center">
              <span className="text-base font-semibold text-[#1a1a17]">
                {profile.shape.target}
              </span>
              <span className="text-xs">target (inferred)</span>
            </div>
          )}
        </div>
      )}

      {profile !== null && profile.columns.length > 0 && (
        <div className="rounded-lg border border-[#ddd5c5] overflow-hidden">
          {profile.columns.map((col, idx) => (
            <div
              key={col.name}
              data-testid="column-row"
              className={`flex items-start gap-4 px-4 py-3 border-b border-[#e8e1d1] last:border-0 text-sm ${
                idx % 2 === 0 ? "bg-white" : "bg-[#faf7f0]"
              }`}
            >
              <span className="font-medium text-[#1a1a17] w-40 shrink-0">{col.name}</span>
              <span className="bg-[#dbeae8] text-[#4a7a76] text-xs px-2 py-0.5 rounded shrink-0">
                {col.type}
              </span>
              <span className="text-[#5d5a52] flex-1">{col.summary}</span>
              {col.flags.length > 0 && (
                <span className="flex gap-1 shrink-0">
                  {col.flags.map((flag) => (
                    <span
                      key={flag}
                      className="bg-[#f4e5d0] text-[#b8732a] text-xs px-2 py-0.5 rounded"
                    >
                      {flag}
                    </span>
                  ))}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-6 flex gap-3">
        <input
          data-testid="reprof-input"
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Anything to flag before the plan? e.g. 'cap support_tickets at p99'…"
          disabled={isTurnInFlight}
          className="flex-1 border border-[#ddd5c5] rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#b8732a]/30"
        />
        <button
          data-testid="reprof-submit"
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isSubmitDisabled}
          className="bg-[#b8732a] text-white rounded-lg px-5 py-2.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </div>
    </div>
  );
}
