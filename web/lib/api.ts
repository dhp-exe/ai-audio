/* Typed client for the Emvoox Engine API (FastAPI, emvoox/api/app.py).
   Same-origin /api/* : the static export is served by the backend, and `npm run dev` / Vercel proxy /api to API_BASE.
   This file is the contract between the web client and the backend; keep both in step. */

export type Provider = "gemini" | "elevenlabs" | "wavespeed" | "mock";
export type LlmProviderId = "gemini" | "wavespeed" | "openai" | "anthropic" | "mock";
export type Batching = "auto" | "line" | "scene";
export type RunStatus = "pending" | "running" | "done" | "failed" | "cancelled" | "halted" | "awaiting_approval";
export type StepStatus = "pending" | "running" | "done" | "warn" | "failed" | "skipped" | "waiting" | "approved" | "rejected";
export type GateState = "awaiting_approval" | "needs_review" | "approved" | "rejected";
export type VoiceSource = "prebuilt" | "premade" | "library" | "cloned" | "placeholder";
export type ThemeCategory = "urban_ceo" | "rebirth_butterfly_effect" | "intellectual_slap_anti_trope" | "other";
export type RoleType = "protagonist" | "antagonist" | "supporting" | "minor";

/* ---------------------------------------------------------------- config / catalog */
export interface ModelInfo { id: string; label: string; tags: boolean; note: string }
export interface VoiceInfo { id: string; gender: "female" | "male"; character: string }
export interface ProviderInfo {
  id: Provider; label: string; models: ModelInfo[]; default_model: string; voices: VoiceInfo[] | null; billing: string;
  key_env: string; scene_batching: boolean; free_voice_id: boolean; // free_voice_id: any voice id can be typed (not a fixed list)
}
export interface Preview { url: string; placeholder: boolean; voice: string; requested_voice?: string; duration_ms?: number; rendered_at?: string }
export interface ActorSummary {
  character_id: string; display_name: string; gender: string | null; age: string | null; is_ip_asset: boolean; persona: string; tags: string[];
  voices: Partial<Record<Provider, string>>; sources: Partial<Record<Provider, VoiceSource>>; preferred_provider: Provider | null;
  previews: Partial<Record<Provider, Preview | null>>;
}
export interface Config {
  version: string;
  llm: { provider: LlmProviderId; model: string; providers: LlmProviderId[] };
  tts: { provider: Provider; model: string; batching: Batching };
  keys: { gemini: boolean; elevenlabs: boolean; wavespeed: boolean; openai: boolean; anthropic: boolean };
  storage: { backend: string; root: string };
  catalog: { providers: ProviderInfo[] };
  defaults: {
    episodes: number; produce: number; min_sec: number; max_sec: number; max_retries: number; auto_approve: boolean; halt_on_qa_fail: boolean;
    qa_transcribe: boolean; enable_bgm: boolean; enable_sfx: boolean; research_use_browser: boolean; loudness_lufs: number; true_peak_dbtp: number;
  };
  actors: ActorSummary[];
  active_run: string | null;
  active_series: string | null;
  theme_categories: { id: ThemeCategory; label: string }[];
  mock_enabled: boolean;
}

export interface AgentSkill { id: string; name: string; description: string }
export interface AgentInfo { id: string; title: string; description: string; consumes: string; produces: string | null; skills: AgentSkill[] }

/* ---------------------------------------------------------------- runs */
export interface StepState {
  id: string; step: "research" | "script" | "casting" | "draft" | "direct" | "voice" | "master" | "qa" | "gate"; agent: string; label: string;
  episode: number | null; status: StepStatus; attempts: number; started_at: string | null; finished_at: string | null; elapsed_s: number;
  summary: Record<string, unknown>; error: string | null; cost_usd: number; log_key: string | null;
}
export interface CastRow {
  role: string; type: RoleType; actor: string; actor_name: string; assigned_by: string; reason: string;
  provider: Provider; model: string; voice: string; voice_source: VoiceSource;
}
export interface RunTotals {
  cost_usd: number; llm_calls: number; tokens_in: number; tokens_out: number; tts_requests: number; tts_characters: number; audio_ms: number; qa_retries: number;
}
export interface RunParams {
  series_id: string; episodes: number; produce: number | null; only: number[] | null; min_sec: number; max_sec: number; force: boolean;
  source: "story" | "brief" | "research" | "existing"; brief_id: string | null;
  research: { seeds: string; platforms: string[]; use_browser: boolean | null; focus: string };
  tts_provider: Provider; tts_model: string | null; tts_batching: Batching; tier: "test" | "final";
  llm_provider: LlmProviderId | null; llm_model: string | null; max_retries: number; auto_approve: boolean; halt_on_qa_fail: boolean;
}
export interface Run {
  run_id: string; series_id: string; status: RunStatus; error: string | null; created_at: string; finished_at: string | null;
  params: RunParams; steps: StepState[]; notes: string[]; casting: CastRow[]; totals: RunTotals; engine: { llm?: string; tts?: string; storage?: string };
}
export interface RunSummary {
  run_id: string; series_id: string; title: string; status: RunStatus; created_at: string; finished_at: string | null;
  progress: { done: number; total: number }; current_step: string | null; current_agent: string | null; cost_usd: number; episodes: number[];
}
export interface PipelineEvent {
  seq: number; at: string; run_id: string; series_id: string; type: string; step_id: string | null; agent: string | null;
  episode: number | null; status: string | null; message: string; data: Record<string, unknown>;
}

export interface RoleIn { name: string; description: string; actor_id: string | null }
export interface EngineRef { provider: Provider; model?: string | null }
export interface StartRun {
  series_id?: string | null;
  source: "story" | "brief" | "research";
  brief_id?: string | null;
  research?: { seeds: string; platforms: string[]; use_browser: boolean | null; focus: string };
  // story (source = "story")
  title?: string; total_minutes?: number | null; genre?: string; setting?: string; roles?: RoleIn[]; roles_text?: string; script?: string;
  // production
  episodes: number; produce: number | null; min_sec: number; max_sec: number; force: boolean;
  tts_provider: Provider; tts_model: string | null; tts_batching: Batching; tier: "test" | "final";
  engine_by_role_type?: Partial<Record<RoleType, EngineRef>>;
  llm_provider?: LlmProviderId | null; llm_model?: string | null;
  max_retries: number; auto_approve: boolean; halt_on_qa_fail: boolean;
}
export interface ResumeIn {
  next?: number; episodes?: number[]; tts_provider?: Provider; tts_model?: string | null; tts_batching?: Batching; force?: boolean;
  auto_approve?: boolean; max_retries?: number; llm_provider?: LlmProviderId | null;
}

/* ---------------------------------------------------------------- market research */
export interface TrendCandidate {
  topic: string; theme_category: ThemeCategory; target_audience: string; hook: string; premise: string; anti_trope_angle: string;
  reference_titles: string[]; audience_fit: number; momentum: number; production_fit: number; score: number; rationale: string;
}
export interface ContentInsight { title: string; platform: string; genre: string; hook: string; pacing: string; tropes: string[] }
export interface TrendBrief {
  brief_id: string; created_at: string; topic: string; target_audience: string;
  format_spec: { medium: string; language: string; episodes: number; episode_seconds_min: number; episode_seconds_max: number };
  theme_category: ThemeCategory; hook: string; premise: string; anti_trope_angle: string; reference_titles: string[]; score: number;
  candidates: TrendCandidate[]; insights: ContentInsight[]; sources: string[]; platforms: string[]; notes: string;
}
export interface ResearchScanIn { seeds: string; platforms: string[]; use_browser: boolean | null; focus: string; llm_provider?: LlmProviderId | null }

/* ---------------------------------------------------------------- library */
export interface QaBrief { status: "PASS" | "FLAGGED" | null; score: number | null; attempt: number; issues: number; codes: string[]; legacy?: boolean }
export interface EpisodeStatus {
  number: number; title: string | null; logline: string | null; hook_score: number | null;
  draft: boolean; direct: boolean; stems: number; master: boolean; master_url: string | null; duration_ms: number | null;
  qa: QaBrief | null; release: { state: GateState; reviewer: string | null; at: string | null } | null; updated_at: string | null;
}
export interface SeriesRole { role: string; type: RoleType | null; actor: string | null; actor_name: string | null; assigned_by: string | null; provider?: Provider | null; voice?: string | null; voice_source?: VoiceSource | null }
export interface RunBrief { run_id: string; status: RunStatus; created_at: string; finished_at: string | null; error: string | null; tts_provider: Provider; tts_model: string | null; llm_provider: string | null; min_sec: number | null; max_sec: number | null }
export interface SeriesSummary {
  series_id: string; title: string; genre: string; setting: string; logline: string; mode: "segment" | "write" | null; theme_category: ThemeCategory | null;
  media: "audio" | "video";
  planned: number; drafted: number; directed: number; produced: number; approved: number; awaiting: number; needs_review: number;
  qa_pass: number; qa_flagged: number; next_episode: number | null; remaining: number[];
  status: "complete" | "in_progress" | "new"; run: RunBrief | null; roles: SeriesRole[]; updated_at: string | null;
  active_run: string | null; cost_usd: number; duration_ms_total: number;
}
export interface SeriesDetail extends SeriesSummary {
  story: { overview: { title: string; total_minutes: number | null; genre: string; setting: string }; roles: RoleIn[]; script: string } | null;
  story_raw?: string;
  bible: { title?: string; logline?: string; premise?: string; tone?: string; mode?: string; protagonist_role?: string; trend_brief_id?: string | null;
           episode_format?: { count: number; min_duration_sec: number; max_duration_sec: number } } | null;
  episodes: EpisodeStatus[]; run_state: Run | null; trend_brief: TrendBrief | null;
}

/* ---------------------------------------------------------------- episode detail, QA, gate */
export interface DirectedUnit {
  unit_id: string; scene_id: string; order: number; type: "dialogue" | "monologue" | "pause"; speaker_id: string; role_name: string | null;
  text: string; tts_text: string; emotion_tag: string; emotional_intensity: number; audio_tags: string[]; direction: string;
  pause_after_ms: number; speed: number; pitch: number; volume: string; provider: string; model_id: string; voice_id: string;
}
export interface RenderUnit { id: string; kind: "line" | "conversation"; scene_id: string; unit_ids: string[]; speakers: string[]; provider: string; model_id: string; voice_id: string; stem: string; pause_after_ms: number; attempt: number }
export interface Directed { series_id: string; episode_number: number; title: string; target_duration_sec: number; batching: string; units: DirectedUnit[]; render_plan: RenderUnit[]; cliffhanger: string; director_notes: string }
export interface QAIssue { code: string; severity: "blocker" | "major" | "minor"; message: string; unit_id: string | null; line_id: string | null; at_ms: number | null; value: number | string | null }
export interface RetryInstruction { action: "rerender" | "rerender_line_mode" | "reassemble" | "redirect"; step: string; unit_ids: string[]; params: Record<string, unknown>; reason: string }
export interface QAReport {
  series_id: string; episode_number: number; attempt: number; status: "PASS" | "FLAGGED"; score: number; checks: Record<string, Record<string, unknown>>;
  error_logs: QAIssue[]; retry_instructions: RetryInstruction[]; review_lines: string[];
  human: { verdict: "approved" | "rejected"; reviewer: string | null; notes: string; at: string } | null; generated_at: string;
}
export interface PublishMetadata {
  title: string; description: string; tags: string[]; hashtags: string[]; playlist_title: string; thumbnail_text: string; language: string;
  category: string; made_for_kids: boolean; contains_synthetic_media: boolean; generated_by: string;
}
export interface ReleasePackage {
  series_id: string; episode_number: number; title: string; state: GateState; qa_status: "PASS" | "FLAGGED"; qa_score: number; qa_attempts: number;
  reason: string; duration_ms: number; master_mp3: string; master_wav: string; metadata: PublishMetadata;
  decision: { decision: "approved" | "rejected"; reviewer: string; notes: string; lines: string[]; override_flagged: boolean; at: string } | null;
  exported: { kind: "mp3" | "wav" | "metadata"; path: string; bytes: number }[]; publish: { platform?: string; status?: string; at?: string; note?: string };
  created_at: string; updated_at: string;
}
export interface ApprovalItem extends ReleasePackage { series_title: string; master_url: string | null; qa: QAReport | null; episode_title: string | null }
export interface CliffhangerCheck { episode_number: number; hook_score: number; twist_within_30s: boolean; antagonist_is_smart: boolean; independent_motivations: boolean; issues: string[]; suggestion: string; checked_by: string; passed: boolean }
export interface EpisodeDetail {
  number: number; plan: { number: number; title: string; logline: string; key_beats: string[]; cliffhanger: string; hook_score: number | null } | null;
  raw_script: string | null; directed: Directed | null; qa: QAReport | null; release: ReleasePackage | null; cliffhanger: CliffhangerCheck | null;
  master_url: string | null; timeline_ms: number | null; roles: { role_name: string; role_type: string; actor_id: string | null }[];
}
export interface OutputItem { series_id: string; file: string; key: string; bytes: number; url: string; metadata: (PublishMetadata & { approved_by?: string; approved_at?: string; duration_seconds?: number; series_title?: string }) | null }

/* ---------------------------------------------------------------- voice IPs */
export interface ProviderVoice {
  voice_id: string; model_id: string; voice_url: string | null; fallback_voice_id: string | null; default_settings: Record<string, unknown>;
  source: VoiceSource; label: string | null; added_at: string | null;
}
export interface Character {
  character_id: string; display_name: string; persona: string; voice_description: string; gender: string | null; age: string | null; tags: string[]; language: string;
  providers: Partial<Record<Provider, ProviderVoice>>; preferred_provider: Provider | null; is_ip_asset: boolean;
  previews: Partial<Record<Provider, Preview | null>>; series: { series_id: string; title: string; role: string }[];
}
export interface CharacterIn {
  character_id: string; display_name: string; persona: string; voice_description: string; gender: string | null; age: string | null; tags: string[]; is_ip_asset: boolean;
  providers: Partial<Record<Provider, { voice_id: string; model_id: string | null; voice_url?: string | null; fallback_voice_id?: string | null; source?: VoiceSource; label?: string | null }>>;
}
export interface PlugVoiceIn {
  provider: Provider; voice_id: string; model_id?: string | null; source: VoiceSource; label?: string | null; voice_url?: string | null;
  fallback_voice_id?: string | null; make_preferred: boolean; unlock: boolean;
}

/* ---------------------------------------------------------------- costs and quotas */
export interface UsageRecord {
  at: string; kind: "llm" | "tts" | "sfx" | "agent"; run_id?: string; series_id?: string; episode?: number; agent?: string; skill?: string;
  provider?: string; model?: string; requests: number; tokens_in: number; tokens_out: number; characters: number; audio_ms: number;
  elapsed_s: number; cost_usd: number; ok: boolean; note: string; unit_id?: string;
}
export interface CostSummary {
  generated_at: string; currency: "USD";
  totals: { cost_usd: number; cost_month_usd: number; cost_today_usd: number; llm_calls: number; tts_requests: number; tokens_in: number; tokens_out: number; characters: number; audio_minutes: number };
  by_provider: { provider: string; label: string; cost_usd: number; requests: number; tokens_in: number; tokens_out: number; characters: number }[];
  by_model: { provider: string; model: string; kind: "llm" | "tts" | "sfx"; cost_usd: number; requests: number; tokens_in: number; tokens_out: number; characters: number; audio_ms: number }[];
  by_agent: { agent: string; title: string; cost_usd: number; requests: number; elapsed_s: number; steps: number }[];
  by_series: { series_id: string; title: string; cost_usd: number; episodes_mastered: number; audio_minutes: number; cost_per_minute: number | null }[];
  by_day: { date: string; llm_usd: number; tts_usd: number }[];
  recent: UsageRecord[];
  pricing: { llm_per_1m_tokens: Record<string, number[]>; tts_per_1k_chars: Record<string, number>; tts_per_1m_tokens: Record<string, number[]>; note: string };
  wavespeed: { available: boolean; balance?: number; reason?: string };
}
export interface UsageModel {
  provider: Provider; provider_label: string; model: string; label: string; kind: "llm" | "tts"; period: string; period_start: string; resets_at: string | null;
  requests: number; tokens_in: number; tokens_out: number; characters: number; limit: { requests_per_day?: number; source?: string } | null;
  status: "ok" | "rate_limited" | "exhausted"; status_until: string | null; note: string; last_call_at: string | null;
  last_event: { at: string; kind: string; status: number | null; quota_id: string | null; quota_value: string | number | null; retry_after_s: number | null; message: string } | null;
  requests_month: number;
}
export interface UsageEvent { at: string; provider: string; model: string; kind: string; status: number | null; quota_id: string | null; quota_value: string | number | null; retry_after_s: number | null; message: string }
export interface Usage {
  generated_at: string;
  providers: Record<string, { label: string; key: boolean; resets_at: string | null; note?: string; credits_used?: number; credits_limit?: number; credits_source?: string; balance_usd?: number | null }>;
  models: UsageModel[]; events: UsageEvent[];
}

/* ---------------------------------------------------------------- dashboard, doctor */
export interface AttentionItem { series_id: string; title: string; episode: number; state: GateState; reason: string; at: string }
export interface Dashboard {
  kpis: { series: number; episodes_planned: number; episodes_mastered: number; awaiting_approval: number; needs_review: number; approved: number;
          cost_month_usd: number; cost_total_usd: number; audio_minutes: number };
  active_runs: RunSummary[]; recent_runs: RunSummary[]; productions: SeriesSummary[]; attention: AttentionItem[];
  cost_by_day: { date: string; cost_usd: number }[];
}
export interface DoctorCheck { id: string; label: string; ok: boolean | null; detail: string }

/* ---------------------------------------------------------------- client */
export class ApiError extends Error { status: number; constructor(status: number, message: string) { super(message); this.status = status; } }

export const WRONG_BACKEND =
  "the server on the API port is not Emvoox Engine 1.x (an older backend may still be running). Stop it and start `python -m emvoox serve`.";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) }, cache: "no-store" });
  if (!r.ok) {
    let msg = await r.text();
    try { const j = JSON.parse(msg); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* raw text */ }
    // an HTML body means something other than the engine answered (an older backend's page, a proxy error)
    if (/^\s*<(!doctype|html)/i.test(msg)) msg = `${r.status} ${r.statusText || "error"} for ${path}: ${WRONG_BACKEND}`;
    throw new ApiError(r.status, msg || `${r.status} ${r.statusText}`);
  }
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}
const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  // config, fleet, dashboard
  // handshake: every page builds on this payload, so reject anything that is not the engine's config (e.g. a pre-1.0 backend)
  config: async () => {
    const c = await request<Config>("/api/config");
    if (!c || typeof c !== "object" || !c.version || !c.defaults || !c.llm || !c.tts) throw new ApiError(502, `Unexpected /api/config response: ${WRONG_BACKEND}`);
    return c;
  },
  agents: () => request<{ agents: AgentInfo[] }>("/api/agents"),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  doctor: (live = false) => request<{ checks: DoctorCheck[] }>(`/api/doctor${live ? "?live=1" : ""}`),
  // market research
  scan: (body: ResearchScanIn) => post<TrendBrief>("/api/research/scan", body),
  briefs: () => request<{ briefs: TrendBrief[] }>("/api/research/briefs"),
  brief: (id: string) => request<TrendBrief>(`/api/research/briefs/${id}`),
  deleteBrief: (id: string) => del<{ ok: boolean }>(`/api/research/briefs/${id}`),
  seeds: () => request<{ seeds: { name: string; chars: number }[] }>("/api/research/seeds"),
  // runs
  startRun: (body: StartRun) => post<Run>("/api/runs", body),
  runs: () => request<{ active: Run[]; recent: RunSummary[] }>("/api/runs"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) => post<{ ok: boolean }>(`/api/runs/${id}/cancel`),
  stepLog: (id: string, step: string) => request<string>(`/api/runs/${id}/steps/${step}/log`),
  events: (id: string, after = 0) => request<{ events: PipelineEvent[] }>(`/api/runs/${id}/events?after=${after}`),
  // productions
  library: () => request<{ series: SeriesSummary[] }>("/api/library"),
  series: (id: string) => request<SeriesDetail>(`/api/series/${id}`),
  episode: (id: string, n: number) => request<EpisodeDetail>(`/api/series/${id}/episodes/${n}`),
  resume: (id: string, body: ResumeIn) => post<Run>(`/api/series/${id}/resume`, body),
  deleteSeries: (id: string) => del<{ ok: boolean }>(`/api/series/${id}`),
  masterUrl: (id: string, n: number) => `/api/series/${id}/master/${n}.mp3`,
  // human gate
  approvals: () => request<{ items: ApprovalItem[] }>("/api/approvals"),
  approve: (id: string, n: number, body: { reviewer: string; notes?: string; metadata?: PublishMetadata }) => post<ReleasePackage>(`/api/series/${id}/episodes/${n}/approve`, body),
  reject: (id: string, n: number, body: { reviewer: string; notes?: string; lines?: string[] }) => post<ReleasePackage>(`/api/series/${id}/episodes/${n}/reject`, body),
  saveMetadata: (id: string, n: number, body: PublishMetadata) => put<ReleasePackage>(`/api/series/${id}/episodes/${n}/metadata`, body),
  outputs: () => request<{ items: OutputItem[] }>("/api/outputs"),
  // voice IPs
  characters: () => request<{ locked: boolean; default_provider: Provider; characters: Character[]; changelog: string[] }>("/api/characters"),
  addCharacter: (body: CharacterIn) => post<{ ok: boolean; changelog: string }>("/api/characters", body),
  editCharacter: (id: string, body: CharacterIn, unlock: boolean) => put<{ ok: boolean; changelog: string }>(`/api/characters/${id}?unlock=${unlock}`, body),
  deleteCharacter: (id: string, unlock: boolean) => del<{ ok: boolean }>(`/api/characters/${id}?unlock=${unlock}`),
  plugVoice: (id: string, body: PlugVoiceIn) => post<{ ok: boolean; changelog: string }>(`/api/characters/${id}/voices`, body),
  removeVoice: (id: string, provider: Provider, unlock: boolean) => del<{ ok: boolean }>(`/api/characters/${id}/voices/${provider}?unlock=${unlock}`),
  characterPreview: (id: string, provider: Provider) => post<{ ok: boolean; preview: Preview }>(`/api/characters/${id}/preview?provider=${provider}`),
  voicePreview: (provider: Provider, voice_id: string, model_id: string | null) => post<{ ok: boolean; preview: Preview }>("/api/voices/preview", { provider, voice_id, model_id }),
  // costs and quotas
  costs: () => request<CostSummary>("/api/costs"),
  usage: () => request<Usage>("/api/usage"),
};
