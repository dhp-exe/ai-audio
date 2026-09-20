"use client";

import { Plus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type ActorSummary, type Batching, type Config, type Provider, type SeriesDetail, type StartRun } from "@/lib/api";
import { wordCount } from "@/lib/format";
import { ErrorText, Field, PlayButton, SectionTitle } from "./ui";

interface RoleRow { key: number; name: string; description: string; actor_id: string }

const WORDS_PER_SEC = 3.3;

/** The sectioned story form. `existing` switches it to edit mode (series id locked, overwrite explained). */
export function StoryForm({ cfg, existing, onStarted }: { cfg: Config; existing?: SeriesDetail | null; onStarted: (runId: string) => void }) {
  const editing = !!existing;
  const st = existing?.story;
  const [title, setTitle] = useState(st?.overview.title ?? existing?.title ?? "");
  const [minutes, setMinutes] = useState<string>(st?.overview.total_minutes ? String(st.overview.total_minutes) : "");
  const [genre, setGenre] = useState(st?.overview.genre ?? existing?.genre ?? "");
  const [setting, setSetting] = useState(st?.overview.setting ?? existing?.setting ?? "");
  const [roles, setRoles] = useState<RoleRow[]>(() => {
    // Older stories keep "/actor" tags inside names; show them as a picked IP instead.
    const ids = new Set(cfg.actors.map((a) => a.character_id));
    const untag = (text: string): [string, string | null] => {
      const m = text.match(/(?:^|\s)[/#@]([a-z][a-z0-9-]{0,23})\b/i);
      if (m && ids.has(m[1].toLowerCase())) return [text.replace(m[0], " ").replace(/\s{2,}/g, " ").trim(), m[1].toLowerCase()];
      return [text, null];
    };
    const base = (st?.roles ?? []).map((r, i) => {
      const [name, t1] = untag(r.name); const [description, t2] = untag(r.description);
      return { key: i, name, description, actor_id: r.actor_id ?? t1 ?? t2 ?? "" };
    });
    return base.length ? base : [{ key: 0, name: "", description: "", actor_id: "" }, { key: 1, name: "", description: "", actor_id: "" }];
  });
  const [rolesText, setRolesText] = useState("");
  const [script, setScript] = useState(st?.script ?? existing?.story_raw ?? "");
  const [provider, setProvider] = useState<Provider>(existing?.run?.tts_provider ?? cfg.tts.provider);
  const [model, setModel] = useState<string>(existing?.run?.tts_model ?? "");
  const [batching, setBatching] = useState<Batching>("auto");
  const [episodes, setEpisodes] = useState(existing?.planned || cfg.defaults.episodes);
  const [minSec, setMinSec] = useState(existing?.run?.min_sec ?? cfg.defaults.min_sec);
  const [maxSec, setMaxSec] = useState(existing?.run?.max_sec ?? cfg.defaults.max_sec);
  const [produce, setProduce] = useState(cfg.defaults.produce);
  const [seriesId, setSeriesId] = useState(existing?.series_id ?? "");
  const [force, setForce] = useState(editing);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const prov = cfg.catalog.providers.find((p) => p.id === provider)!;
  useEffect(() => { if (!prov.models.some((m) => m.id === model)) setModel(prov.default_model); }, [prov, model]);
  const actorsById = useMemo(() => Object.fromEntries(cfg.actors.map((a) => [a.character_id, a])), [cfg.actors]);
  const used = (except: number) => new Set(roles.filter((r) => r.key !== except && r.actor_id).map((r) => r.actor_id));
  const words = wordCount(script);
  const need = Math.round(episodes * minSec * WORDS_PER_SEC);
  const missingVoices = cfg.actors.filter((a) => !a.voices[provider]).map((a) => a.display_name);

  const update = (key: number, patch: Partial<RoleRow>) => setRoles((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addRole = () => setRoles((rs) => [...rs, { key: Date.now(), name: "", description: "", actor_id: "" }]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    const body: StartRun = {
      title, total_minutes: minutes ? +minutes : null, genre, setting,
      roles: roles.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), description: r.description.trim(), actor_id: r.actor_id || null })),
      roles_text: rolesText, script, series_id: seriesId || null, episodes, produce: produce || null, min_sec: minSec, max_sec: maxSec,
      force, tts_provider: provider, tts_model: model || null, tts_batching: provider === "gemini" ? batching : "auto",
    };
    try { const run = await api.startRun(body); onStarted(run.run_id); }
    catch (ex) { setErr((ex as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="pb-6">
      {editing && (
        <div className="mb-4 rounded-md bg-tint-accent px-3 py-2 text-[12px] text-ink">
          Editing <b>{existing?.title}</b>. Saving re-runs the outline and casting for <span className="font-mono">{existing?.series_id}</span> and overwrites its drafts;
          rendered stems whose text did not change are reused.
        </div>
      )}
      <SectionTitle n={1}>Overview</SectionTitle>
      <Field label="Story name"><input className="field" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Bản Hợp Đồng Định Mệnh" required /></Field>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Field label="Length (min)"><input className="field" type="number" min={1} value={minutes} onChange={(e) => { setMinutes(e.target.value); const m = +e.target.value; if (m) setEpisodes(Math.max(1, Math.min(99, Math.round((m * 60) / ((minSec + maxSec) / 2))))); }} placeholder="30" /></Field>
        <Field label="Genre" className="col-span-2"><input className="field" value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="Ngôn tình tổng tài, thanh mai trúc mã" /></Field>
      </div>
      <Field label="Setting" className="mt-3"><input className="field" value={setting} onChange={(e) => setSetting(e.target.value)} placeholder="Hiện đại, thành phố lớn" /></Field>

      <SectionTitle n={2}>Characters in the story</SectionTitle>
      <div className="space-y-3">
        {roles.map((r) => {
          const taken = used(r.key);
          const actor: ActorSummary | undefined = r.actor_id ? actorsById[r.actor_id] : undefined;
          const pv = actor?.previews?.[provider] ?? null;
          return (
            <div key={r.key} className="rounded-md border border-line bg-sunken/60 p-3">
              <div className="grid grid-cols-[1fr_auto_auto] items-end gap-2">
                <Field label="Name"><input className="field" value={r.name} onChange={(e) => update(r.key, { name: e.target.value })} placeholder="Tô Mạn" /></Field>
                <Field label="Character IP">
                  <div className="flex items-center gap-1.5">
                    <select className="field min-w-[180px]" value={r.actor_id} onChange={(e) => update(r.key, { actor_id: e.target.value })}>
                      <option value="">AI chooses</option>
                      {cfg.actors.map((a) => (
                        <option key={a.character_id} value={a.character_id} disabled={taken.has(a.character_id)}>
                          {a.display_name} ({a.gender ?? "?"}{a.age ? `, ${a.age}` : ""}){taken.has(a.character_id) ? " · taken" : ""}
                        </option>
                      ))}
                    </select>
                    {actor && actor.voices[provider] && (
                      <PlayButton preview={pv} title={`${actor.display_name} on ${prov.label}`} render={async () => (await api.characterPreview(actor.character_id, provider)).preview} />
                    )}
                  </div>
                </Field>
                <button type="button" className="btn-icon mb-0.5" title="Remove" onClick={() => setRoles((rs) => rs.filter((x) => x.key !== r.key))}><X size={15} /></button>
              </div>
              <Field label="Description" className="mt-2">
                <textarea className="field min-h-[72px]" rows={3} value={r.description} onChange={(e) => update(r.key, { description: e.target.value })} placeholder="24 tuổi, hoạt bát, thông minh, nhân viên mới của tập đoàn…" />
              </Field>
            </div>
          );
        })}
      </div>
      <button type="button" className="btn-ghost mt-2" onClick={addRole}><Plus size={14} /> Add character</button>
      <p className="mt-2 text-[12px] text-muted">
        Pick a Character IP per role or leave “AI chooses” and the casting model matches the description to the registry. One IP plays one role: a picked IP is greyed out in the other rows. <code className="font-mono">/ngan</code> in a name or description pins too.
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer text-[12px] text-muted">…or paste a character list (one per line: <i>Name (note): description</i>)</summary>
        <textarea className="field mt-2 min-h-[90px]" value={rolesText} onChange={(e) => setRolesText(e.target.value)} placeholder={"Giang Thần (Nam chính): 28 tuổi, Tổng giám đốc… /duong\nTô Mạn (Nữ chính): 24 tuổi, hoạt bát… /ngan"} />
      </details>

      <SectionTitle n={3}>Script</SectionTitle>
      <textarea className="field min-h-[560px] font-mono text-[13px] leading-[1.55]" rows={28} value={script} onChange={(e) => setScript(e.target.value)} placeholder="Dán toàn bộ kịch bản, cảnh theo cảnh…" required />
      <p className="mt-1 text-[12px] text-muted">
        {words ? `${words} words · ${episodes} episodes × ${minSec}s need about ${need} words → ${words >= need * 0.5 ? "segment mode (your dialogue is kept word for word)" : "write mode (a treatment is expanded into dialogue)"}` : "Paste the whole story. A full script is split into episodes verbatim; a synopsis is written out."}
      </p>

      <SectionTitle n={4}>Voice engine</SectionTitle>
      <div className="flex overflow-hidden rounded-md border border-line">
        {cfg.catalog.providers.map((p) => (
          <button key={p.id} type="button" onClick={() => setProvider(p.id)} className={`flex-1 px-3 py-2 text-[13px] font-medium ${provider === p.id ? "bg-accent text-accent-ink" : "bg-sunken text-muted hover:text-ink"}`}>{p.label}</button>
        ))}
      </div>
      <Field label="Model" className="mt-3">
        <select className="field" value={model} onChange={(e) => setModel(e.target.value)}>
          {prov.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </Field>
      <p className="mt-1 text-[12px] text-muted">
        {prov.models.find((m) => m.id === model)?.note}
        {missingVoices.length > 0 && ` No ${prov.label} voice yet for ${missingVoices.join(", ")}; one is assigned at cast time.`}
      </p>
      {provider === "gemini" && (
        <Field label="Requests per episode" className="mt-3" hint={batching === "line" ? "One request per spoken line (8–12 per episode); gives per-line stems." : "One request per scene chunk of up to two speakers (usually 1–3 per episode); best when the daily request quota is small."}>
          <select className="field" value={batching} onChange={(e) => setBatching(e.target.value as Batching)}>
            <option value="auto">Fewest requests (per scene)</option>
            <option value="line">One per line</option>
          </select>
        </Field>
      )}

      <SectionTitle n={5}>Production</SectionTitle>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Episodes"><input className="field" type="number" min={1} max={99} value={episodes} onChange={(e) => setEpisodes(+e.target.value)} /></Field>
        <Field label="Min s / ep"><input className="field" type="number" min={20} value={minSec} onChange={(e) => setMinSec(+e.target.value)} /></Field>
        <Field label="Max s / ep"><input className="field" type="number" min={20} value={maxSec} onChange={(e) => setMaxSec(+e.target.value)} /></Field>
        <Field label="Produce now"><input className="field" type="number" min={1} max={99} value={produce} onChange={(e) => setProduce(+e.target.value)} /></Field>
        <Field label="Series id"><input className="field font-mono" value={seriesId} onChange={(e) => setSeriesId(e.target.value)} placeholder="auto" readOnly={editing} /></Field>
      </div>
      {!editing && (
        <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Overwrite if the series id already exists</label>
      )}
      <button className="btn-primary mt-4 w-full" disabled={busy}>{busy ? "Starting…" : editing ? "Save and re-run" : "Start producing"}</button>
      <p className="mt-2 text-[12px] text-muted">Outline and casting is one LLM call; each produced episode is 1 to 3 draft calls, 1 direction call, then one TTS request per line. Remaining episodes can be continued later from the Library.</p>
      <ErrorText>{err}</ErrorText>
    </form>
  );
}
