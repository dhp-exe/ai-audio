/* The 7-agent fleet in pipeline order, with the handoff contract each one produces. The live list comes from
   api.agents(); this static copy keeps the Pipeline page readable when that call fails, and maps run steps to agents. */
import type { StepState, StepStatus } from "./api";

export interface FleetAgent { id: string; short: string; title: string; produces: string; steps: StepState["step"][] }

export const FLEET: FleetAgent[] = [
  { id: "market_research", short: "Market Research", title: "Market Research Agent", produces: "TrendBrief", steps: ["research"] },
  { id: "script_writer", short: "Script Writer", title: "Script Writer Agent", produces: "StoryInput + SeriesBible", steps: ["script", "draft"] },
  { id: "casting", short: "Casting & Voice IP", title: "Casting & Voice IP Curator Agent", produces: "ResolvedCast", steps: ["casting"] },
  { id: "director", short: "AI Director", title: "AI Director Agent", produces: "DirectedConversationUnits", steps: ["direct"] },
  { id: "sound_engineer", short: "Sound Engineer", title: "Sound Engineer Agent", produces: "MasteredEpisode", steps: ["voice", "master"] },
  { id: "qa_critic", short: "QA Critic", title: "QA Critic Agent", produces: "QAReport", steps: ["qa"] },
  { id: "publisher", short: "Approval & Publisher", title: "Human Approval Gate & Publisher", produces: "ReleasePackage", steps: ["gate"] },
];

export const STEP_AGENT: Record<StepState["step"], string> = {
  research: "market_research", script: "script_writer", casting: "casting", draft: "script_writer",
  direct: "director", voice: "sound_engineer", master: "sound_engineer", qa: "qa_critic", gate: "publisher",
};

export type AggStatus = StepStatus | "partial";

/** Aggregate many step statuses into one agent status. */
export function aggregate(statuses: StepStatus[]): AggStatus {
  if (!statuses.length) return "skipped";
  const has = (s: StepStatus) => statuses.includes(s);
  if (has("running")) return "running";
  if (has("failed")) return "failed";
  if (has("rejected")) return "rejected";
  if (has("waiting")) return "waiting";
  const finished = statuses.filter((s) => s === "done" || s === "skipped" || s === "approved" || s === "warn").length;
  if (finished === statuses.length) return has("warn") ? "warn" : statuses.every((s) => s === "skipped") ? "skipped" : "done";
  if (finished > 0) return "partial";
  return "pending";
}
