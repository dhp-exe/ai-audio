"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Batching, type Config, type Provider, type SeriesDetail } from "@/lib/api";
import { fmtSeconds, pad2 } from "@/lib/format";
import { Badge, ErrorText, Field, StatusPill } from "./ui";

export function StoryDetail({ d, cfg, onDeleted }: { d: SeriesDetail; cfg: Config; onDeleted: () => void }) {
  const router = useRouter();
  const run = d.run;
  const [provider, setProvider] = useState<Provider>(run?.tts_provider ?? cfg.tts.provider);
  const [model, setModel] = useState<string>(run?.tts_model ?? "");
  const [next, setNext] = useState(Math.min(5, d.remaining.length || 5));
  const [batching, setBatching] = useState<Batching>("auto");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const prov = cfg.catalog.providers.find((p) => p.id === provider)!;
  useEffect(() => { if (!prov.models.some((m) => m.id === model)) setModel(prov.default_model); }, [prov, model]);
  const engine = cfg.catalog.providers.find((p) => p.id === run?.tts_provider);

  const cont = async () => {
    setErr(null); setBusy(true);
    try { const r = await api.resume(d.series_id, { next, tts_provider: provider, tts_model: model, tts_batching: provider === "gemini" ? batching : "auto", force }); router.push(`/run/?id=${r.run_id}`); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const del = async () => {
    if (!confirm(`Delete "${d.title}" (${d.series_id}) and all its files? This cannot be undone.`)) return;
    try { await api.deleteSeries(d.series_id); onDeleted(); } catch (e) { alert((e as Error).message); }
  };

  return (
    <div className="space-y-4">
      <section className="rounded-md border border-line bg-panel p-4">
        <h2 className="flex items-center gap-2 text-[17px] font-semibold">{d.title} <StatusPill status={d.status} />{d.active_run && <Badge tone="warn">running now</Badge>}</h2>
        <dl className="mt-3 grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-[12px]">
          <dt className="text-muted">series id</dt><dd className="font-mono">{d.series_id}</dd>
          <dt className="text-muted">genre · setting</dt><dd>{d.genre || "—"}{d.setting ? ` · ${d.setting}` : ""}</dd>
          <dt className="text-muted">premise</dt><dd>{d.bible?.premise || d.logline || "—"}</dd>
          <dt className="text-muted">episodes</dt><dd>{d.produced}/{d.planned} mastered · {d.directed} directed · {d.drafted} drafted · {d.mode ?? "?"} mode · {run?.min_sec ?? 50}-{run?.max_sec ?? 70}s</dd>
          <dt className="text-muted">last run</dt>
          <dd>{run ? <><Link className="text-accent" href={`/run/?id=${run.run_id}`}>{run.run_id}</Link> · {run.status}{run.error ? ` · ${run.error}` : ""}</> : "—"}{d.active_run && <> · <Link className="font-medium text-accent" href={`/run/?id=${d.active_run}`}>watch</Link></>}</dd>
          <dt className="text-muted">engine</dt><dd>{engine?.label ?? "—"}{run?.tts_model ? ` / ${run.tts_model}` : ""}</dd>
        </dl>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {d.roles.map((r) => <span key={r.role} className="rounded-full border border-line bg-sunken px-2.5 py-0.5 text-[11px]">{r.role} <i className="text-muted">({r.type})</i> → {r.actor_name ?? r.actor ?? "?"} · {r.assigned_by}</span>)}
        </div>
        <div className="mt-4 flex gap-2">
          <Link href={`/story/?id=${d.series_id}`} className="btn-ghost">Edit story and re-run</Link>
          <button className="btn-danger" onClick={del}>Delete</button>
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-4">
        <h3 className="text-[15px] font-semibold">Continue producing</h3>
        <p className="mt-1 text-[12px] text-muted">{d.remaining.length ? `${d.remaining.length} episode(s) left: ${d.remaining.slice(0, 12).join(", ")}${d.remaining.length > 12 ? "…" : ""}` : "Every planned episode has a master."}</p>
        <div className="mt-3 grid grid-cols-3 gap-3">
          <Field label="Next N episodes"><input className="field" type="number" min={1} max={99} value={next} onChange={(e) => setNext(+e.target.value)} /></Field>
          <Field label="Engine"><select className="field" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>{cfg.catalog.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></Field>
          <Field label="Model"><select className="field" value={model} onChange={(e) => setModel(e.target.value)}>{prov.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></Field>
        </div>
        {provider === "gemini" && (
          <Field label="Requests per episode" className="mt-3">
            <select className="field" value={batching} onChange={(e) => setBatching(e.target.value as Batching)}>
              <option value="auto">Fewest requests (per scene, usually 1–3)</option>
              <option value="line">One per line (8–12)</option>
            </select>
          </Field>
        )}
        <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Re-render from the first episode (overwrite drafts and stems)</label>
        <div className="mt-3 flex items-center gap-3">
          <button className="btn-primary" disabled={busy || !!d.active_run} onClick={cont}>{busy ? "Starting…" : "Continue"}</button>
          <ErrorText>{err}</ErrorText>
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-4">
        <h3 className="text-[15px] font-semibold">Episodes</h3>
        <table className="mt-2 w-full text-[13px]">
          <thead><tr className="text-left text-muted">{["#", "Title", "Draft", "Direct", "Stems", "Master", "QA"].map((h) => <th key={h} className="border-b border-line px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
          <tbody>
            {d.episodes.map((e) => (
              <tr key={e.number}>
                <td className="border-b border-line px-2 py-2 font-mono font-medium">{pad2(e.number)}</td>
                <td className="border-b border-line px-2 py-2">{e.title}<div className="text-[12px] text-muted">{e.logline}</div></td>
                <td className="border-b border-line px-2 py-2">{e.draft ? "✓" : "·"}</td>
                <td className="border-b border-line px-2 py-2">{e.direct ? "✓" : "·"}</td>
                <td className="border-b border-line px-2 py-2">{e.stems || "·"}</td>
                <td className="border-b border-line px-2 py-2">{e.master_url ? <span className="inline-flex items-center gap-2"><audio controls preload="none" src={e.master_url} />{e.duration_ms ? <span className="text-[11px] text-muted">{fmtSeconds(e.duration_ms)}</span> : null}</span> : "·"}</td>
                <td className="border-b border-line px-2 py-2 text-[12px] text-muted">{e.qa ? `${e.qa.ok ? "pass" : `⚠ ${e.qa.failed_checks.join(", ")}`}${e.qa.verdict ? ` · ${e.qa.verdict}` : ""}` : "·"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
