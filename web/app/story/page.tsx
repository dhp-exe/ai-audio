"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, type Config, type SeriesDetail } from "@/lib/api";
import { SidePanel } from "@/components/SidePanel";
import { StoryForm } from "@/components/StoryForm";
import { Empty } from "@/components/ui";

function StoryInner() {
  const router = useRouter();
  const id = useSearchParams().get("id");
  const [cfg, setCfg] = useState<Config | null>(null);
  const [existing, setExisting] = useState<SeriesDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoaded(false);
    Promise.all([api.config(), id ? api.series(id) : Promise.resolve(null)])
      .then(([c, s]) => { if (!alive) return; setCfg(c); setExisting(s); setLoaded(true); })
      .catch((e) => alive && setErr(String(e.message)));
    return () => { alive = false; };
  }, [id]);

  const editing = !!id;
  return (
    <div className="flex min-h-[calc(100vh-56px)]">
      <SidePanel
        storageKey="story"
        title={editing ? "Edit story" : "New story"}
        subtitle={editing ? (existing ? `${existing.title} · ${existing.series_id}` : id) : "Overview, characters, script, engine, production"}
        onClose={() => router.push("/")}
        defaultWidth={520}
      >
        {err && <div className="text-[12px] text-bad">{err}</div>}
        {cfg && loaded && <StoryForm key={id ?? "new"} cfg={cfg} existing={existing} onStarted={(runId) => router.push(`/run/?id=${runId}`)} />}
        {!cfg && !err && <div className="text-[13px] text-muted">Loading…</div>}
      </SidePanel>
      <main className="min-w-0 flex-1 p-6">
        {editing && existing ? (
          <div className="max-w-[720px] space-y-3">
            <h1 className="text-[17px] font-semibold">Editing “{existing.title}”</h1>
            <p className="text-[13px] text-muted">
              The form on the left is filled from the saved story. Change anything and choose <b>Save and re-run</b>: the outline and casting are recomputed for
              <span className="font-mono"> {existing.series_id}</span>, drafts are rewritten, and only stems whose final text changed are rendered again.
              To add episodes without touching the story, use <Link className="text-accent" href={`/?id=${existing.series_id}`}>Continue producing</Link> in the Library instead.
            </p>
            <dl className="grid grid-cols-[140px_1fr] gap-x-3 gap-y-1 text-[12px]">
              <dt className="text-muted">episodes mastered</dt><dd>{existing.produced} / {existing.planned}</dd>
              <dt className="text-muted">last run</dt><dd>{existing.run ? `${existing.run.run_id} · ${existing.run.status}` : "—"}</dd>
            </dl>
          </div>
        ) : (
          <div className="max-w-[720px]">
            <h1 className="text-[17px] font-semibold">Start a new story</h1>
            <p className="mt-2 text-[13px] text-muted">
              Fill the five sections on the left. Overview and character descriptions drive casting; the script is split into episodes at its tensest points.
              Once the run starts you will land on its board, and the story appears in the Library where you can continue it later.
            </p>
            <div className="mt-6"><Empty>The run board opens here when you start producing.</Empty></div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function StoryPage() {
  return <Suspense fallback={<main className="p-5 text-[13px] text-muted">Loading…</main>}><StoryInner /></Suspense>;
}
