// SSE event types derived from docs/contracts/SSE_CONTRACT.md
// Ground truth: SSE_CONTRACT.md §2 — the reconciled event taxonomy.
// All 13 event types present.

import type { Profile, Section } from "./api";

// ---------------------------------------------------------------------------
// §2.1 — Events generated purely by the backend
// ---------------------------------------------------------------------------

export interface StageChangedEvent {
  type: "stage.changed";
  stage: "profiling" | "planning" | "building" | "done";
  ts: number;
}

export interface ProfileReadyEvent {
  type: "profile.ready";
  profile: Profile;
  ts: number;
}

export interface PlanReadyEvent {
  type: "plan.ready";
  sections: Section[];
  ts: number;
}

export interface SectionBuildingEvent {
  type: "section.building";
  section_id: string;
  title: string;
  ts: number;
}

export interface SectionProposedEvent {
  type: "section.proposed";
  section_id: string;
  py_path: string;
  png_path: string;
  md_path: string;
  ts: number;
}

export interface SectionFailedEvent {
  type: "section.failed";
  section_id: string;
  reason: "timeout" | "output_error" | "missing_files";
  ts: number;
}

export interface TurnErrorEvent {
  type: "turn.error";
  stage: string;
  reason: "structured_output_failed" | "timeout" | "provider_error";
  ts: number;
}

export interface HeartbeatEvent {
  type: "heartbeat";
  ts: number;
}

// ---------------------------------------------------------------------------
// §2.2 — Events derived from OpenCode message.part.updated (tool parts)
// ---------------------------------------------------------------------------

export interface ToolBashRunningEvent {
  type: "tool.bash_running";
  command: string;
  description: string | null;
  started_at: number;
  ts: number;
}

export interface ToolBashDoneEvent {
  type: "tool.bash_done";
  command: string;
  exit_code: number;
  elapsed_ms: number;
  ts: number;
}

export interface ToolFileWrittenEvent {
  type: "tool.file_written";
  file: string;
  op: "add" | "modify" | "delete";
  additions: number;
  deletions: number;
  elapsed_ms: number;
  ts: number;
}

// ---------------------------------------------------------------------------
// §2.3 — Events derived from OpenCode message.part.delta
// ---------------------------------------------------------------------------

export interface MessagePartEvent {
  type: "message.part";
  part_id: string;
  content: string;
  ts: number;
}

// ---------------------------------------------------------------------------
// §2.4 — Events derived from OpenCode file.edited
// ---------------------------------------------------------------------------

export interface FileReadyEvent {
  type: "file.ready";
  path: string;
  ts: number;
}

// ---------------------------------------------------------------------------
// Discriminated union — all 13 event types
// ---------------------------------------------------------------------------

export type SSEEvent =
  | StageChangedEvent
  | ProfileReadyEvent
  | PlanReadyEvent
  | SectionBuildingEvent
  | SectionProposedEvent
  | SectionFailedEvent
  | TurnErrorEvent
  | HeartbeatEvent
  | ToolBashRunningEvent
  | ToolBashDoneEvent
  | ToolFileWrittenEvent
  | MessagePartEvent
  | FileReadyEvent;
