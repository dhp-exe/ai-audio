"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { CharacterCard } from "@/components/CharacterCard";
import { CharacterForm } from "@/components/CharacterForm";
import { SidePanel } from "@/components/SidePanel";
import { Empty } from "@/components/ui";

function CharactersInner() {
  const router = useRouter();
  const params = useSearchParams();
  const creating = params.get("new") === "1";
  const editId = params.get("edit");
  const { data: cfg } = usePoll(api.config, 0);
  const { data, error, refresh } = usePoll(api.characters, 0);
  const [toast, setToast] = useState<string | null>(null);
  const editing = editId ? data?.characters.find((c) => c.character_id === editId) ?? null : null;
  const panelOpen = creating || !!editId;
  const close = () => router.push("/characters/");

  const del = async (id: string) => {
    const unlock = confirm(`Delete ${id}?\n\nOK deletes it (locked IP assets are unlocked for this action). Cancel keeps it.`);
    if (!unlock) return;
    try { await api.deleteCharacter(id, true); setToast(`Deleted ${id}`); refresh(); } catch (e) { alert((e as Error).message); }
  };

  return (
    <div className="flex min-h-[calc(100vh-56px)]">
      {panelOpen && cfg && (
        <SidePanel
          storageKey="character"
          title={editing ? `Edit character IP · ${editing.display_name}` : creating ? "New character IP" : "Edit character IP"}
          subtitle={editing ? `${editing.character_id} · ${editing.is_ip_asset ? "locked IP asset" : "one-off"}` : creating ? "Identity, voices, registry" : editId ?? ""}
          onClose={close}
        >
          {editId && !editing && data && <div className="text-[12px] text-bad">No character with id “{editId}”.</div>}
          {(creating || editing) && (
            <CharacterForm key={editId ?? "new"} cfg={cfg} existing={editing} onCancel={close} onSaved={(msg) => { setToast(`Saved: ${msg}`); refresh(); close(); }} />
          )}
        </SidePanel>
      )}
      <main className="min-w-0 flex-1 p-5">
        <div className="mb-4 flex items-center gap-3">
          <h1 className="text-[17px] font-semibold">Character IPs</h1>
          {data && <span className="text-[12px] text-muted">{data.characters.length} characters · registry {data.locked ? "locked" : "unlocked"}</span>}
          {toast && <span className="text-[12px] text-ok">{toast}</span>}
          <button className="btn-primary ml-auto h-8" onClick={() => router.push("/characters/?new=1")}><Plus size={14} /> New character</button>
        </div>
        <p className="mb-4 text-[12px] text-muted">Each voice row has a ▶ preview. A dashed button means the ~5 s clip is not rendered yet: the first press renders it once and caches it; after that it only plays.</p>
        {error && <div className="text-[12px] text-bad">{error}</div>}
        {!data ? <div className="text-[13px] text-muted">Loading…</div> : data.characters.length === 0 ? <Empty>No character IPs yet. Add one with “New character”.</Empty> : (
          <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
            {data.characters.map((c) => (
              <CharacterCard key={c.character_id} c={c} providers={cfg?.catalog.providers ?? []} onEdit={() => router.push(`/characters/?edit=${c.character_id}`)} onDelete={() => del(c.character_id)} />
            ))}
          </div>
        )}
        {data && data.changelog.length > 0 && (
          <details className="mt-6"><summary className="cursor-pointer text-[12px] text-muted">Registry changelog</summary><pre className="log">{data.changelog.join("\n")}</pre></details>
        )}
      </main>
    </div>
  );
}

export default function CharactersPage() {
  return <Suspense fallback={<main className="p-5 text-[13px] text-muted">Loading…</main>}><CharactersInner /></Suspense>;
}
