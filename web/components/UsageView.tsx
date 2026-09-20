"use client";

import { RefreshCw } from "lucide-react";
import { api, type Usage, type UsageModel } from "@/lib/api";
import { fmtCountdown, fmtInt, fmtTime } from "@/lib/format";
import { useNow, usePoll } from "@/lib/hooks";
import { Badge, Empty, Meter } from "./ui";

function StatusBadge({ m, now }: { m: UsageModel; now: number }) {
  if (m.status === "exhausted") return <Badge tone="bad" title={m.note}>quota exhausted · resets in {fmtCountdown(m.status_until ?? m.resets_at, now)}</Badge>;
  if (m.status === "rate_limited") return <Badge tone="warn" title={m.note}>rate limited · {fmtCountdown(m.status_until, now)}</Badge>;
  return <Badge tone="ok">ok</Badge>;
}

function ModelRow({ m, now }: { m: UsageModel; now: number }) {
  const limit = m.limit?.requests_per_day ?? null;
  return (
    <tr className="align-top">
      <td className="border-b border-line px-2 py-2.5">
        <div className="font-medium">{m.label}</div>
        <div className="font-mono text-[11px] text-muted">{m.model}</div>
      </td>
      <td className="border-b border-line px-2 py-2.5"><StatusBadge m={m} now={now} /><div className="mt-1 text-[11px] text-muted">{m.note}</div></td>
      <td className="border-b border-line px-2 py-2.5">
        <div className="flex items-baseline gap-1"><span className="text-[15px] font-semibold">{fmtInt(m.requests)}</span>{limit != null && <span className="text-[12px] text-muted">/ {limit}</span>}</div>
        {limit != null ? <Meter value={m.requests} max={limit} className="mt-1 w-[120px]" /> : <div className="text-[11px] text-muted">limit not reported yet</div>}
        {m.limit?.source && <div className="mt-0.5 text-[11px] text-muted">{m.limit.source}</div>}
      </td>
      <td className="border-b border-line px-2 py-2.5 font-mono text-[12px]">{m.provider === "gemini" ? <>{fmtInt(m.tokens_in)} in<br />{fmtInt(m.tokens_out)} out</> : <>{fmtInt(m.characters)} chars</>}</td>
      <td className="border-b border-line px-2 py-2.5 text-[12px] text-muted">{m.period}<br />resets in {fmtCountdown(m.resets_at, now)}</td>
      <td className="border-b border-line px-2 py-2.5 text-[12px] text-muted">{m.last_call_at ? fmtTime(m.last_call_at) : "never"}{m.last_event && <div title={m.last_event.message}>last {m.last_event.kind.replace("_", " ")} {fmtTime(m.last_event.at)}</div>}</td>
    </tr>
  );
}

function Table({ rows, now, usage }: { rows: UsageModel[]; now: number; usage: string }) {
  return (
    <table className="w-full text-[13px]">
      <thead><tr className="text-left text-[12px] text-muted">{["Model", "Status", "Requests this period", usage, "Period", "Last call"].map((h) => <th key={h} className="border-b border-line px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
      <tbody>{rows.map((m) => <ModelRow key={m.model} m={m} now={now} />)}</tbody>
    </table>
  );
}

export function UsageView() {
  const { data, error, refresh, loading } = usePoll<Usage>(api.usage, 30_000);
  const now = useNow();
  if (error) return <Empty>Could not load usage: {error}</Empty>;
  if (!data || loading) return <div className="text-[13px] text-muted">Loading usage…</div>;
  const g = data.providers.gemini, e = data.providers.elevenlabs;
  const gemTts = data.models.filter((m) => m.provider === "gemini" && m.kind === "tts");
  const gemLlm = data.models.filter((m) => m.provider === "gemini" && m.kind === "llm");
  const el = data.models.filter((m) => m.provider === "elevenlabs");
  const elPct = e.credits_limit ? Math.round((100 * e.credits_used) / e.credits_limit) : 0;
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 text-[12px] text-muted">
        Updated {fmtTime(data.generated_at)} · refreshes every 30 s · countdowns tick live
        <button className="btn-ghost h-7 px-2" onClick={refresh}><RefreshCw size={13} /> Refresh now</button>
      </div>

      <section className="rounded-md border border-line bg-panel p-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-[15px] font-semibold">ElevenLabs</h2>
          <Badge tone={e.key ? "ok" : "bad"}>{e.key ? "key set" : "no key"}</Badge>
          {e.subscription.available ? <Badge tone="accent">vendor counters live</Badge> : <span className="text-[12px] text-warn">{e.subscription.reason}</span>}
        </div>
        <div className="mt-3 grid gap-4 sm:grid-cols-[1fr_auto]">
          <div>
            <div className="flex items-baseline gap-2"><span className="text-[22px] font-semibold">{fmtInt(e.credits_used)}</span><span className="text-[12px] text-muted">of {fmtInt(e.credits_limit)} credits this billing period ({elPct}%)</span></div>
            <Meter value={e.credits_used} max={e.credits_limit} className="mt-2 max-w-[520px]" />
            <div className="mt-1 text-[11px] text-muted">Source: {e.credits_source}. Credits reset in {fmtCountdown(e.resets_at, now) || "?"}{e.resets_at ? ` (${fmtTime(e.resets_at)})` : ""}.</div>
          </div>
          {e.subscription.available && (
            <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-[12px]">
              <dt className="text-muted">voice slots</dt><dd>{e.subscription.voice_slots_used} / {e.subscription.voice_limit}</dd>
              <dt className="text-muted">professional cloning</dt><dd>{e.subscription.professional_voice_cloning ? "yes" : "no"}</dd>
            </dl>
          )}
        </div>
        <div className="mt-4"><Table rows={el} now={now} usage="Characters" /></div>
      </section>

      <section className="rounded-md border border-line bg-panel p-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-[15px] font-semibold">Gemini</h2>
          <Badge tone={g.key ? "ok" : "bad"}>{g.key ? "key set" : "no key"}</Badge>
          <span className="text-[12px] text-muted">daily quotas reset in {fmtCountdown(g.resets_at, now)} ({fmtTime(g.resets_at)})</span>
        </div>
        <p className="mt-1 text-[12px] text-muted">{g.note} A model turns red when a request is refused for the day and back to green at the reset.</p>
        <h3 className="mt-4 mb-1 text-[13px] font-semibold">Text-to-speech</h3>
        <Table rows={gemTts} now={now} usage="Tokens" />
        <h3 className="mt-5 mb-1 text-[13px] font-semibold">Language model (outline, drafts, direction)</h3>
        <Table rows={gemLlm} now={now} usage="Tokens" />
      </section>

      <section className="rounded-md border border-line bg-panel p-4">
        <h2 className="text-[15px] font-semibold">Limit events</h2>
        <p className="mt-1 text-[12px] text-muted">Every 429 or 402 the engines returned, with the quota the vendor named.</p>
        {data.events.length === 0 ? <div className="mt-3 text-[12px] text-muted">No limit events recorded yet.</div> : (
          <table className="mt-3 w-full text-[12px]">
            <thead><tr className="text-left text-muted">{["When", "Model", "Kind", "Quota", "Message"].map((h) => <th key={h} className="border-b border-line px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>{data.events.map((ev, i) => (
              <tr key={i} className="align-top">
                <td className="border-b border-line px-2 py-1.5 whitespace-nowrap text-muted">{fmtTime(ev.at)}</td>
                <td className="border-b border-line px-2 py-1.5 font-mono">{ev.model}</td>
                <td className="border-b border-line px-2 py-1.5"><Badge tone={ev.kind === "rate_limit" ? "warn" : "bad"}>{ev.kind.replace("_", " ")}</Badge></td>
                <td className="border-b border-line px-2 py-1.5 font-mono text-[11px]">{ev.quota_id ?? "–"}{ev.quota_value ? ` = ${ev.quota_value}` : ""}{ev.retry_after_s ? ` · retry ${ev.retry_after_s}s` : ""}</td>
                <td className="border-b border-line px-2 py-1.5 text-muted">{ev.message}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  );
}
