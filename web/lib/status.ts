/* One place for status -> Tag colour and label, so every page reads the same. Colours are antd preset/status colours. */
import type { GateState, StepStatus, VoiceSource } from "./api";

export const STATUS_COLOR: Record<string, string> = {
  // steps and runs
  pending: "default",
  running: "processing",
  done: "success",
  warn: "warning",
  waiting: "warning",
  failed: "error",
  skipped: "default",
  cancelled: "default",
  halted: "warning",
  // gate
  approved: "success",
  rejected: "error",
  needs_review: "error",
  awaiting_approval: "gold",
  // QA
  PASS: "success",
  FLAGGED: "warning",
  // series
  complete: "success",
  in_progress: "processing",
  new: "default",
  // quotas
  ok: "success",
  rate_limited: "warning",
  exhausted: "error",
};

export const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  done: "Done",
  warn: "Warning",
  waiting: "Waiting",
  failed: "Failed",
  skipped: "Skipped",
  cancelled: "Cancelled",
  halted: "Halted",
  approved: "Approved",
  rejected: "Rejected",
  needs_review: "Needs review",
  awaiting_approval: "Awaiting approval",
  complete: "Complete",
  in_progress: "In production",
  new: "New",
  ok: "OK",
  rate_limited: "Rate limited",
  exhausted: "Exhausted",
};

export const statusColor = (s: string | null | undefined) => (s ? STATUS_COLOR[s] ?? "default" : "default");
export const statusLabel = (s: string | null | undefined) => (s ? STATUS_LABEL[s] ?? s : "–");

export const LIVE_RUN = new Set(["pending", "running"]);
export const isLive = (s: string | null | undefined) => !!s && LIVE_RUN.has(s);

export const GATE_ORDER: GateState[] = ["awaiting_approval", "needs_review", "approved", "rejected"];

export const SOURCE_COLOR: Record<VoiceSource, string> = {
  cloned: "gold",
  library: "blue",
  premade: "default",
  prebuilt: "cyan",
  placeholder: "warning",
};
export const SOURCE_LABEL: Record<VoiceSource, string> = {
  cloned: "Cloned IP voice",
  library: "Library voice",
  premade: "Premade",
  prebuilt: "Prebuilt",
  placeholder: "Placeholder",
};
export const SOURCE_HINT: Record<VoiceSource, string> = {
  cloned: "A voice cloned for this Voice IP: the asset we are building fans around.",
  library: "A voice from the vendor's shared library.",
  premade: "A vendor premade voice.",
  prebuilt: "One of the engine's prebuilt voices.",
  placeholder: "Temporary voice until the real one is plugged in.",
};

/** Steps status -> antd Steps item status. */
export function stepsStatus(s: StepStatus | "partial" | null | undefined): "wait" | "process" | "finish" | "error" {
  switch (s) {
    case "running":
    case "partial":
    case "waiting":
      return "process";
    case "done":
    case "approved":
    case "skipped":
    case "warn":
      return "finish";
    case "failed":
    case "rejected":
      return "error";
    default:
      return "wait";
  }
}

export const THEME_COLOR: Record<string, string> = {
  urban_ceo: "geekblue",
  rebirth_butterfly_effect: "purple",
  intellectual_slap_anti_trope: "magenta",
  other: "default",
};
