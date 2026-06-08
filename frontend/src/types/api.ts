// API types derived from docs/contracts/API_CONTRACT.html
// Ground truth: API_CONTRACT.html §1 (REST endpoints) and §3 (GET /state schema)

// ---------------------------------------------------------------------------
// Shared sub-types
// ---------------------------------------------------------------------------

export type Stage = "setup" | "profiling" | "planning" | "building" | "done";

export type SectionStatus = "queued" | "building" | "proposed" | "accepted" | "dropped" | "failed";

export type ColumnType = "str" | "int" | "num" | "cat" | "date" | "bool";

export interface ColumnProfile {
  name: string;
  type: ColumnType;
  summary: string;
  nulls_pct: number;
  flags: string[];
}

export interface ProfileShape {
  /** Schema uses rows/columns; agent sometimes emits total_rows/total_columns */
  rows?: number;
  total_rows?: number;
  columns?: number;
  total_columns?: number;
  nulls_pct?: number;
  /** null if not inferred */
  target: string | null;
}

export interface Profile {
  shape: ProfileShape;
  columns: ColumnProfile[];
  /** Dataset-level concerns */
  flags: string[];
}

export interface Section {
  id: string;
  title: string;
  hypothesis: string;
  status: SectionStatus;
  /** null until built */
  py_path: string | null;
  /** null until built */
  png_path: string | null;
  /** null until built */
  md_path: string | null;
  /**
   * Reason a build failed, persisted in state.json alongside status="failed".
   * Cleared (null/absent) once the section is rebuilt, proposed, accepted, or
   * dropped. Drives the failed-section Retry/Drop UI across page refreshes.
   */
  failure_reason?: string | null;
}

// ---------------------------------------------------------------------------
// GET /state — full response schema (API_CONTRACT.html §3)
// ---------------------------------------------------------------------------

export interface StateResponse {
  version: string;
  stage: Stage;
  aim: string;
  dataset_path: string;
  last_saved: string;
  /** null until profiling complete */
  profile: Profile | null;
  /** [] until planning complete */
  plan: Section[];
}

// ---------------------------------------------------------------------------
// POST /setup — response
// ---------------------------------------------------------------------------

export interface SetupResponse {
  ok: true;
  session_id: string;
}

// ---------------------------------------------------------------------------
// POST /plan/update — request body
// ---------------------------------------------------------------------------

export interface PlanUpdateRequest {
  sections: Section[];
}

// ---------------------------------------------------------------------------
// POST /plan/update — response
// ---------------------------------------------------------------------------

export interface PlanUpdateResponse {
  ok: true;
}

// ---------------------------------------------------------------------------
// Error envelope (API_CONTRACT.html §4)
// ---------------------------------------------------------------------------

export interface ApiError {
  error: string;
  message: string;
}
