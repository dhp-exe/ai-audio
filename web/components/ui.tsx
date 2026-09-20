"use client";

import { Loader2, Play, Square } from "lucide-react";
import { useState } from "react";
import { toggleAudio, usePlaying } from "@/lib/audio";
import type { Preview } from "@/lib/api";

export function Badge({ children, tone = "neutral", title }: { children: React.ReactNode; tone?: "neutral" | "accent" | "ok" | "warn" | "bad"; title?: string }) {
  const cls = { neutral: "bg-sunken text-ink", accent: "bg-tint-accent text-accent", ok: "bg-tint-ok text-ok", warn: "bg-tint-warn text-warn", bad: "bg-tint-bad text-bad" }[tone];
  return <span className={`pill ${cls}`} title={title}>{children}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const tone: Record<string, "neutral" | "ok" | "bad" | "warn" | "accent"> = { done: "ok", complete: "ok", running: "warn", in_progress: "warn", failed: "bad", cancelled: "neutral", pending: "neutral", new: "neutral" };
  return <Badge tone={tone[status] ?? "neutral"}>{status.replace("_", " ")}</Badge>;
}

export function Meter({ value, max, className = "" }: { value: number; max: number | null; className?: string }) {
  const pct = max ? Math.min(100, Math.round((100 * value) / max)) : 0;
  const tone = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "";
  return <div className={`meter ${className}`}><i className={tone} style={{ width: `${max ? pct : 0}%` }} /></div>;
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  return children ? <div className="mt-2 whitespace-pre-wrap text-[12px] text-bad">{children}</div> : null;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed border-line p-8 text-center text-[13px] text-muted">{children}</div>;
}

export function Field({ label, children, hint, className = "" }: { label: string; children: React.ReactNode; hint?: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="label">{label}</label>
      {children}
      {hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>}
    </div>
  );
}

export function SectionTitle({ n, children }: { n?: number; children: React.ReactNode }) {
  return (
    <h2 className="mt-6 mb-2 flex items-baseline gap-2 text-[13px] font-semibold first:mt-0">
      {n != null && <span className="font-mono text-[11px] text-muted">{String(n).padStart(2, "0")}</span>}
      {children}
    </h2>
  );
}

/**
 * Plays a cached preview. If nothing is cached yet, `render` is called exactly once (the backend
 * caches the file by engine/model/voice, so a voice is never rendered twice).
 */
export function PlayButton({ preview, render, title, size = 30 }: { preview: Preview | null | undefined; render?: () => Promise<Preview | null>; title?: string; size?: number }) {
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState<Preview | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  const pv = local === undefined ? preview : local;
  const playing = usePlaying(pv?.url);
  const onClick = async () => {
    if (pv?.url) { toggleAudio(pv.url); return; }
    if (!render || busy) return;
    setBusy(true); setErr(null);
    try { const p = await render(); setLocal(p); if (p?.url) toggleAudio(p.url); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const cached = !!pv?.url;
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        type="button" onClick={onClick} disabled={busy || (!cached && !render)}
        title={err ?? title ?? (cached ? "Play preview" : "Render the preview once, then play")}
        style={{ width: size, height: size }}
        className={`inline-flex flex-none items-center justify-center rounded-full transition-colors ${cached ? "bg-accent text-accent-ink hover:brightness-110" : "border border-dashed border-line-strong text-muted hover:border-accent hover:text-accent"} disabled:opacity-50`}
      >
        {busy ? <Loader2 size={13} className="animate-spin" /> : playing ? <Square size={11} fill="currentColor" /> : <Play size={12} fill="currentColor" />}
      </button>
      {err && <span className="text-[11px] text-bad">{err}</span>}
    </span>
  );
}
