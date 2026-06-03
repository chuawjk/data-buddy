// API client functions — typed wrappers around fetch.
// Each function throws ApiError on non-2xx responses.
// Named "useApi" by story convention; this module contains no React hooks.
// Coded against docs/contracts/API_CONTRACT.html — never backend internals.

import type {
  ApiError,
  PlanUpdateResponse,
  Section,
  SetupResponse,
  StateResponse,
} from "../types/api";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function parseErrorEnvelope(res: Response): Promise<ApiError> {
  try {
    return (await res.json()) as ApiError;
  } catch {
    return { error: "unknown_error", message: `HTTP ${res.status}` };
  }
}

async function throwIfError(res: Response): Promise<void> {
  if (!res.ok) {
    throw await parseErrorEnvelope(res);
  }
}

// ---------------------------------------------------------------------------
// api — collection of typed async functions
// ---------------------------------------------------------------------------

export const api = {
  /**
   * GET /api/state — hydrate full UI state on page load.
   * API_CONTRACT.html §1 · GET /state
   */
  async getState(): Promise<StateResponse> {
    const res = await fetch("/api/state", { method: "GET" });
    await throwIfError(res);
    return res.json() as Promise<StateResponse>;
  },

  /**
   * POST /api/setup — upload dataset and aim, start brief.
   * API_CONTRACT.html §1 · POST /setup (multipart/form-data)
   */
  async postSetup(file: File, aim: string): Promise<SetupResponse> {
    const fd = new FormData();
    fd.append("csv", file);
    fd.append("aim", aim);
    const res = await fetch("/api/setup", { method: "POST", body: fd });
    await throwIfError(res);
    return res.json() as Promise<SetupResponse>;
  },

  /**
   * POST /api/turn — bottom-bar free-form input.
   * API_CONTRACT.html §1 · POST /turn
   * Returns 204 No Content; resolves void on success.
   */
  async postTurn(text: string): Promise<void> {
    const res = await fetch("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    await throwIfError(res);
  },

  /**
   * POST /api/plan/update — inline plan edit.
   * API_CONTRACT.html §1 · POST /plan/update
   */
  async postPlanUpdate(sections: Section[]): Promise<PlanUpdateResponse> {
    const res = await fetch("/api/plan/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sections }),
    });
    await throwIfError(res);
    return res.json() as Promise<PlanUpdateResponse>;
  },

  /**
   * POST /api/plan/accept — accept plan, begin section build.
   * API_CONTRACT.html §1 · POST /plan/accept
   * Returns 204 No Content; resolves void on success.
   */
  async postPlanAccept(): Promise<void> {
    const res = await fetch("/api/plan/accept", { method: "POST" });
    await throwIfError(res);
  },

  /**
   * POST /api/section/:id/accept — accept proposed section, trigger next.
   * API_CONTRACT.html §1 · POST /section/:id/accept
   * Returns 204 No Content; resolves void on success.
   */
  async postSectionAccept(id: string): Promise<void> {
    const res = await fetch(`/api/section/${id}/accept`, { method: "POST" });
    await throwIfError(res);
  },

  /**
   * POST /api/section/:id/drop — drop proposed section, trigger next.
   * API_CONTRACT.html §1 · POST /section/:id/drop
   * Returns 204 No Content; resolves void on success.
   */
  async postSectionDrop(id: string): Promise<void> {
    const res = await fetch(`/api/section/${id}/drop`, { method: "POST" });
    await throwIfError(res);
  },

  /**
   * GET /api/export — export brief as Markdown.
   * API_CONTRACT.html §1 · GET /export
   * Returns the raw Markdown text (file download body).
   */
  async getExport(): Promise<string> {
    const res = await fetch("/api/export", { method: "GET" });
    await throwIfError(res);
    return res.text();
  },

  /**
   * GET /api/file?path=... — serve workspace file (code / chart).
   * API_CONTRACT.html §1 · GET /file
   * Returns raw file content as text.
   */
  async getFile(path: string): Promise<string> {
    const url = `/api/file?path=${encodeURIComponent(path)}`;
    const res = await fetch(url, { method: "GET" });
    await throwIfError(res);
    return res.text();
  },
} as const;
