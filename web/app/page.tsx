"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus, RefreshCw } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { api, type SeriesDetail, type SeriesSummary } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { StoryDetail } from "@/components/StoryDetail";
import { Badge, Empty, Meter, StatusPill } from "@/components/ui";

function StoryCard({ s, selected, onClick, engineLabel }: { s: SeriesSummary; selected: boolean; onClick: () => void; engineLabel?: string }) {
  return (
    <button onClick={onClick} className={`w-full rounded-md border bg-panel p-4 text-left transition-colors ${selected ? "border-accent" : "border-line hover:border-line-strong"}`}>
      <div className="flex items-center gap-2">
        <h3 className="min-w-0 flex-1 truncate text-[15px] font-semibold">{s.title}</h3>
        <StatusPill status={s.status} />
        {s.active_run && <Badge tone="warn">running</Badge>}
      </div>
      <div className="mt-0.5 truncate font-mono text-[11px] text-muted">{s.series_id}{s.genre ? ` · ${s.genre}` : ""}{s.mode ? ` · ${s.mode} mode` : ""}</div>
      {s.logline && <p className="mt-2 line-clamp-2 text-[12px] text-muted">{s.logline}</p>}
      <div className="mt-3 flex items-center gap-3 text-[12px] text-muted">
        <span><b className="font-medium text-ink">{s.produced}</b>/{s.planned} mastered</span>
        {s.qa_warn > 0 && <span className="text-warn">⚠ {s.qa_warn} QA</span>}
        {engineLabel && <span>{engineLabel}</span>}
        {s.run && <span>last run {s.run.status}</span>}
      </div>
      <Meter value={s.produced} max={s.planned || null} className="mt-2" />
      <div className="mt-2 flex flex-wrap gap-1">{s.roles.map((r) => <span key={r.role} className="rounded-full border border-line bg-sunken px-2 py-0.5 text-[11px]">{r.role} → {r.actor_name ?? r.actor ?? "?"}</span>)}</div>
    </button>
  );
}

function LibraryInner() {
  const router = useRouter();
  const params = useSearchParams();
  const sel = params.get("id");
  const { data: cfg } = usePoll(api.config, 0);
  const { data, error, refresh } = usePoll(api.library, 10_000);
  const [detail, setDetail] = useState<SeriesDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const list = data?.series ?? [];
  const current = sel ?? list[0]?.series_id ?? null;

  useEffect(() => {
    if (!current) { setDetail(null); return; }
    let alive = true;
    api.series(current).then((d) => alive && setDetail(d)).catch((e) => alive && setDetailErr(String(e.message)));
    return () => { alive = false; };
  }, [current, data]);

  const engine = (id?: string) => cfg?.catalog.providers.find((p) => p.id === id)?.label;

  return (
    <main className="mx-auto max-w-[1440px] p-5">
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-[17px] font-semibold">Story library</h1>
        <span className="text-[12px] text-muted">{list.length} {list.length === 1 ? "story" : "stories"}</span>
        <button className="btn-ghost h-8" onClick={refresh}><RefreshCw size={13} /> Refresh</button>
        <Link href="/story/" className="btn-primary ml-auto h-8"><Plus size={14} /> New story</Link>
      </div>
      {error && <div className="mb-3 text-[12px] text-bad">{error}</div>}
      <div className="grid gap-4 lg:grid-cols-[minmax(320px,1fr)_1.5fr]">
        <div className="space-y-3">
          {!data ? <div className="text-[13px] text-muted">Loading…</div> : list.length === 0 ? <Empty>No stories yet. Start one with “New story”.</Empty> :
            list.map((s) => <StoryCard key={s.series_id} s={s} selected={s.series_id === current} engineLabel={engine(s.run?.tts_provider)} onClick={() => router.replace(`/?id=${s.series_id}`)} />)}
        </div>
        <div>
          {detailErr && <div className="text-[12px] text-bad">{detailErr}</div>}
          {detail && cfg ? <StoryDetail d={detail} cfg={cfg} onDeleted={() => { setDetail(null); router.replace("/"); refresh(); }} /> :
            list.length > 0 && <Empty>Select a story to see its episodes, listen to masters, or continue producing.</Empty>}
        </div>
      </div>
    </main>
  );
}

export default function LibraryPage() {
  return <Suspense fallback={<main className="p-5 text-[13px] text-muted">Loading…</main>}><LibraryInner /></Suspense>;
}
