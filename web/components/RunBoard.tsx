"use client";

import { useEffect, useState } from "react";
import { api, type Job, type Run } from "@/lib/api";
import { ep, fmtDuration } from "@/lib/format";
import { Badge, StatusPill } from "./ui";

const STAGES = ["draft", "direct", "voice", "assemble", "qa"] as const;

function summaryText(j: Job) {
  const s = j.summary as Record<string, unknown>;
  const arr = (k: string) => (Array.isArray(s[k]) ? (s[k] as unknown[]) : null);
  if (j.stage === "draft" && arr("drafted")) return arr("drafted")!.length ? "drafted" : "kept";
  if (j.stage === "direct" && s.lines) return `${s.lines} lines`;
  if (j.stage === "voice" && s.planned != null) return `${s.rendered}/${s.planned} stems${s.cached ? ` (${s.cached} cached)` : ""}${arr("placeholder_voices")?.length ? " · placeholder" : ""}`;
  if (j.stage === "assemble" && s.total_ms) return `${((s.total_ms as number) / 1000).toFixed(0)}s master`;
  if (j.stage === "qa" && arr("failed_checks")) return arr("failed_checks")!.length ? `⚠ ${arr("failed_checks")!.join(",")}` : `✓ ${s.review_lines} to review`;
  if (j.stage === "outline" && s.ok) return `${s.outline ? (s.mode ?? "") : "kept"}${arr("new_characters")?.length ? ` · +${arr("new_characters")!.length} uncast` : ""}`;
  if (j.stage === "cast" && s.ok) return `${s.provider}${arr("placeholders")?.length ? ` · ${arr("placeholders")!.length} placeholder` : ""}${arr("auto_voiced")?.length ? ` · ${arr("auto_voiced")!.length} auto` : ""}`;
  return "";
}

function Chip({ job, selected, onClick }: { job?: Job; selected: boolean; onClick: () => void }) {
  if (!job) return null;
  return (
    <span className={`chip ${selected ? "sel" : ""}`} onClick={onClick} title={job.error ?? ""}>
      <span className={`dot ${job.status}`} />{job.status}
      <small className="text-muted">{fmtDuration(job.started_at, job.finished_at)}</small>
      <small className="text-muted">{summaryText(job)}</small>
    </span>
  );
}

export function RunBoard({ run, engineLabel }: { run: Run; engineLabel: string }) {
  const [selJob, setSelJob] = useState<string | null>(null);
  const [log, setLog] = useState("");
  const byId = Object.fromEntries(run.jobs.map((j) => [j.id, j]));
  const finished = run.jobs.filter((j) => ["done", "warn", "failed", "skipped"].includes(j.status)).length;
  const eps = [...new Set(run.jobs.filter((j) => j.episode).map((j) => j.episode as number))].sort((a, b) => a - b);
  const live = ["pending", "running"].includes(run.status);

  useEffect(() => {
    if (!selJob) return;
    let alive = true;
    const load = () => api.jobLog(run.run_id, selJob).then((t) => alive && setLog(t)).catch((e) => alive && setLog(String(e)));
    load();
    const id = live ? setInterval(load, 2000) : undefined;
    return () => { alive = false; if (id) clearInterval(id); };
  }, [selJob, run.run_id, live, run.status]);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill status={run.status} />
        <span className="font-mono text-[13px] font-medium">{run.run_id}</span>
        <span className="text-[12px] text-muted">
          {finished}/{run.jobs.length} jobs · {run.params.episodes} planned · producing {eps.length > 6 ? `${eps[0]}–${eps[eps.length - 1]}` : eps.map(ep).join(", ") || "none"} · {run.params.min_sec}-{run.params.max_sec}s · {engineLabel}{run.params.tts_model ? ` / ${run.params.tts_model}` : ""}
        </span>
        <div className="meter min-w-[140px] flex-1"><i style={{ width: `${run.jobs.length ? (100 * finished) / run.jobs.length : 0}%` }} /></div>
        {live && <button className="btn-ghost" onClick={() => api.cancelRun(run.run_id).catch((e) => alert(e.message))}>Cancel</button>}
      </div>
      {run.notes.map((n) => <div key={n} className="mt-3 rounded-md bg-tint-warn px-3 py-2 text-[12px] text-warn">{n}</div>)}
      {run.error && <div className="mt-3 text-[12px] text-bad">{run.error}</div>}
      {run.casting.length > 0 && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {run.casting.map((c) => (
            <div key={c.role} className="rounded-md border border-line bg-panel px-3 py-2 text-[12px]">
              <b>{c.role}</b> <Badge>{c.type}</Badge> → <b>{c.actor_name ?? c.actor}</b> <span className="text-muted">({c.actor}, {c.assigned_by}{c.voice ? `, voice ${c.voice}` : ""})</span>
              <div className="text-muted">{c.reason}</div>
            </div>
          ))}
        </div>
      )}
      <table className="mt-4 w-full text-[13px]">
        <thead><tr className="text-left text-muted">
          <th className="border-b border-line px-2 py-1.5 font-medium">Episode</th>
          {STAGES.map((s) => <th key={s} className="border-b border-line px-2 py-1.5 font-medium capitalize">{s === "qa" ? "QA" : s}</th>)}
          <th className="border-b border-line px-2 py-1.5 font-medium">Output</th>
        </tr></thead>
        <tbody>
          <tr>
            <td className="border-b border-line px-2 py-2 font-medium">Series</td>
            <td className="border-b border-line px-2 py-2" colSpan={2}><span className="inline-flex items-center gap-2">Outline <Chip job={byId.outline} selected={selJob === "outline"} onClick={() => setSelJob("outline")} /></span></td>
            <td className="border-b border-line px-2 py-2" colSpan={3}><span className="inline-flex items-center gap-2">Cast <Chip job={byId.cast} selected={selJob === "cast"} onClick={() => setSelJob("cast")} /></span></td>
            <td className="border-b border-line" />
          </tr>
          {eps.map((n) => {
            const e = ep(n), asm = byId[`${e}.assemble`], qa = byId[`${e}.qa`];
            const failed = (qa?.summary as { failed_checks?: string[] } | undefined)?.failed_checks;
            return (
              <tr key={n}>
                <td className="border-b border-line px-2 py-2 font-mono font-medium">{e}</td>
                {STAGES.map((s) => <td key={s} className="border-b border-line px-2 py-2"><Chip job={byId[`${e}.${s}`]} selected={selJob === `${e}.${s}`} onClick={() => setSelJob(`${e}.${s}`)} /></td>)}
                <td className="border-b border-line px-2 py-2">
                  {asm?.status === "done" && <audio controls preload="none" src={`/api/series/${run.series_id}/master/${n}.mp3`} />}
                  {failed && <span className="ml-2 text-[12px] text-muted">{failed.length ? `QA: ${failed.join(", ")}` : "QA pass"}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-4 flex items-center justify-between text-[12px] text-muted">
        <span>{selJob ? `Log: ${selJob}` : "Click any job to see its log"}</span>
        {selJob && <button className="btn-ghost" onClick={() => api.jobLog(run.run_id, selJob).then(setLog)}>Refresh log</button>}
      </div>
      {selJob && <pre className="log">{log}</pre>}
    </div>
  );
}
