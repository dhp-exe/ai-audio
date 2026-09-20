/* Typed client for the FastAPI backend. Same-origin /api/* (static export served by the backend,
   or the Next rewrite in dev / on Vercel). */

export type Provider = "elevenlabs" | "gemini";
export type Batching = "auto" | "line" | "scene";

export interface ModelInfo { id: string; label: string; tags: boolean; note: string }
export interface VoiceInfo { id: string; gender: "female" | "male"; character: string }
export interface ProviderInfo { id: Provider; label: string; models: ModelInfo[]; default_model: string; voices: VoiceInfo[] | null; billing: string }
export interface Preview { url: string; placeholder: boolean; voice: string; requested_voice?: string; duration_ms?: number; rendered_at?: string }
export interface ActorSummary {
  character_id: string; display_name: string; gender: string | null; age: string | null; is_ip_asset: boolean; persona: string; tags: string[];
  voices: Partial<Record<Provider, string>>; previews: Partial<Record<Provider, Preview | null>>;
}
export interface Config {
  llm_model: string; tts: { provider: Provider; model: string; batching: Batching }; keys: { gemini: boolean; elevenlabs: boolean };
  catalog: { providers: ProviderInfo[] }; defaults: { episodes: number; produce: number; min_sec: number; max_sec: number };
  actors: ActorSummary[]; active_run: string | null;
}

export interface Job { id: string; stage: string; episode: number | null; status: string; started_at: string | null; finished_at: string | null; summary: Record<string, unknown>; error: string | null; label: string }
export interface Casting { role: string; type: string; actor: string | null; assigned_by: string; reason: string; actor_name: string | null; voice: string | null }
export interface Run {
  run_id: string; series_id: string; status: string; error: string | null; created_at: string; finished_at: string | null;
  params: { episodes: number; produce: number | null; min_sec: number; max_sec: number; tts_provider: Provider; tts_model: string | null; tts_batching?: Batching; only: number[] | null; force: boolean };
  notes: string[]; casting: Casting[]; jobs: Job[];
}

export interface RoleIn { name: string; description: string; actor_id: string | null }
export interface StartRun {
  series_id?: string | null; title: string; total_minutes: number | null; genre: string; setting: string; roles: RoleIn[]; roles_text: string; script: string;
  episodes: number; produce: number | null; min_sec: number; max_sec: number; force: boolean; tts_provider: Provider; tts_model: string | null; tts_batching: Batching;
}

export interface EpisodeStatus { number: number; title: string | null; logline: string | null; draft: boolean; direct: boolean; stems: number; master: boolean; master_url: string | null; duration_ms: number | null; qa: { ok: boolean; failed_checks: string[]; verdict: string | null } | null }
export interface SeriesRole { role: string; type: string | null; actor: string | null; actor_name: string | null; assigned_by: string | null }
export interface SeriesSummary {
  series_id: string; title: string; genre: string; setting: string; total_minutes: number | null; logline: string; mode: string | null;
  planned: number; drafted: number; directed: number; produced: number; qa_pass: number; qa_warn: number; next_episode: number | null; remaining: number[];
  status: "complete" | "in_progress" | "new";
  run: { run_id: string; status: string; created_at: string; finished_at: string | null; error: string | null; tts_provider: Provider; tts_model: string | null; min_sec: number | null; max_sec: number | null } | null;
  roles: SeriesRole[]; updated_at: string | null; active_run?: string | null;
}
export interface SeriesDetail extends SeriesSummary {
  story: { overview: { title: string; total_minutes: number | null; genre: string; setting: string }; roles: { name: string; description: string; actor_id: string | null }[]; script: string } | null;
  story_raw?: string; bible: { title?: string; logline?: string; premise?: string; tone?: string; mode?: string; protagonist_role?: string } | null;
  episodes: EpisodeStatus[]; run_state: Run | null;
}

export interface ProviderVoice { voice_id: string; model_id: string; voice_url: string | null; fallback_voice_id: string | null; default_settings: Record<string, unknown> }
export interface Character {
  character_id: string; display_name: string; persona: string; voice_description: string; gender: string | null; age: string | null; tags: string[]; language: string;
  providers: Partial<Record<Provider, ProviderVoice>>; is_ip_asset: boolean; previews: Partial<Record<Provider, Preview | null>>;
}
export interface CharacterIn {
  character_id: string; display_name: string; persona: string; voice_description: string; gender: string | null; age: string | null; tags: string[]; is_ip_asset: boolean;
  providers: Partial<Record<Provider, { voice_id: string; model_id: string | null; voice_url?: string | null; fallback_voice_id?: string | null }>>;
}

export interface UsageModel {
  provider: Provider; provider_label: string; model: string; label: string; kind: "llm" | "tts"; period: string; period_start: string; resets_at: string | null;
  requests: number; tokens_in: number; tokens_out: number; characters: number; limit: { requests_per_day?: number; source?: string } | null;
  status: "ok" | "rate_limited" | "exhausted"; status_until: string | null; note: string; last_call_at: string | null;
  last_event: { at: string; kind: string; status: number | null; quota_id: string | null; quota_value: string | number | null; retry_after_s: number | null; message: string } | null; requests_month: number;
}
export interface UsageEvent { at: string; provider: Provider; model: string; kind: string; status: number | null; quota_id: string | null; quota_value: string | number | null; retry_after_s: number | null; message: string }
export interface Usage {
  generated_at: string;
  providers: {
    gemini: { label: string; key: boolean; resets_at: string; note: string };
    elevenlabs: { label: string; key: boolean; resets_at: string | null; credits_used: number; credits_limit: number; credits_source: string; subscription: { available: boolean; reason?: string; tier?: string; voice_slots_used?: number; voice_limit?: number; professional_voice_cloning?: boolean } };
  };
  models: UsageModel[]; events: UsageEvent[]; totals: { calls_logged: number; gemini_requests_today: number; elevenlabs_characters_period: number };
}

export class ApiError extends Error { status: number; constructor(status: number, message: string) { super(message); this.status = status; } }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) }, cache: "no-store" });
  if (!r.ok) {
    let msg = await r.text();
    try { const j = JSON.parse(msg); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* raw text */ }
    throw new ApiError(r.status, msg || `${r.status} ${r.statusText}`);
  }
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  config: () => request<Config>("/api/config"),
  startRun: (body: StartRun) => request<Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<{ ok: boolean }>(`/api/runs/${id}/cancel`, { method: "POST" }),
  jobLog: (id: string, job: string) => request<string>(`/api/runs/${id}/jobs/${job}/log`),
  library: () => request<{ series: SeriesSummary[] }>("/api/library"),
  series: (id: string) => request<SeriesDetail>(`/api/series/${id}`),
  resume: (id: string, body: { next?: number; episodes?: number[]; tts_provider?: Provider; tts_model?: string | null; tts_batching?: Batching; force?: boolean }) =>
    request<Run>(`/api/series/${id}/resume`, { method: "POST", body: JSON.stringify(body) }),
  deleteSeries: (id: string) => request<{ ok: boolean }>(`/api/series/${id}`, { method: "DELETE" }),
  characters: () => request<{ locked: boolean; default_provider: Provider; characters: Character[]; changelog: string[] }>("/api/characters"),
  addCharacter: (body: CharacterIn) => request<{ ok: boolean; changelog: string }>("/api/characters", { method: "POST", body: JSON.stringify(body) }),
  editCharacter: (id: string, body: CharacterIn, unlock: boolean) => request<{ ok: boolean; changelog: string }>(`/api/characters/${id}?unlock=${unlock}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteCharacter: (id: string, unlock: boolean) => request<{ ok: boolean }>(`/api/characters/${id}?unlock=${unlock}`, { method: "DELETE" }),
  characterPreview: (id: string, provider: Provider) => request<{ ok: boolean; preview: Preview }>(`/api/characters/${id}/preview?provider=${provider}`, { method: "POST" }),
  voicePreview: (provider: Provider, voice_id: string, model_id: string | null) => request<{ ok: boolean; preview: Preview }>("/api/voices/preview", { method: "POST", body: JSON.stringify({ provider, voice_id, model_id }) }),
  usage: () => request<Usage>("/api/usage"),
};
