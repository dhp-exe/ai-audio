"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { RunBoard } from "@/components/RunBoard";
import { Empty } from "@/components/ui";

function RunInner() {
  const id = useSearchParams().get("id");
  const { data: cfg } = usePoll(api.config, 0);
  const { data: run, error } = usePoll(() => api.run(id!), 1500, [id], !!id);
  const live = run ? ["pending", "running"].includes(run.status) : true;
  const { data: runFinal } = usePoll(() => api.run(id!), 0, [id, live], !!id && !live);
  const r = runFinal ?? run;
  if (!id) return <main className="p-6"><Empty>No run selected. Start one from <Link className="text-accent" href="/story/">New story</Link> or continue one from the Library.</Empty></main>;
  const engine = cfg?.catalog.providers.find((p) => p.id === r?.params.tts_provider)?.label ?? r?.params.tts_provider ?? "";
  return (
    <main className="mx-auto max-w-[1440px] p-5">
      <div className="mb-3 flex items-center gap-3 text-[12px] text-muted">
        <Link href="/" className="text-accent">Library</Link><span>/</span>{r && <Link href={`/?id=${r.series_id}`} className="text-accent">{r.series_id}</Link>}<span>/</span><span>run</span>
      </div>
      {error && <div className="text-[12px] text-bad">{error}</div>}
      {r ? <RunBoard run={r} engineLabel={engine} /> : !error && <div className="text-[13px] text-muted">Loading run…</div>}
    </main>
  );
}

export default function RunPage() {
  return <Suspense fallback={<main className="p-5 text-[13px] text-muted">Loading…</main>}><RunInner /></Suspense>;
}
