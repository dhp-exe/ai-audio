"use client";

import { ExternalLink, Pencil, Trash2 } from "lucide-react";
import { api, type Character, type Provider, type ProviderInfo } from "@/lib/api";
import { fmtSeconds } from "@/lib/format";
import { Badge, PlayButton } from "./ui";

function VoiceRow({ c, p }: { c: Character; p: ProviderInfo }) {
  const v = c.providers[p.id];
  const pv = c.previews?.[p.id] ?? null;
  return (
    <div className="grid grid-cols-[auto_88px_minmax(0,1fr)_auto] items-center gap-2 border-t border-line py-2 text-[12px] first:border-t-0">
      {v ? (
        <PlayButton preview={pv} title={pv?.url ? `Play ${c.display_name} on ${p.label}` : `Render ${c.display_name} on ${p.label} once, then play`} render={async () => (await api.characterPreview(c.character_id, p.id)).preview} />
      ) : <span className="inline-block h-[30px] w-[30px]" />}
      <span className="font-medium">{p.label}</span>
      {v ? (
        <span className="min-w-0 truncate font-mono text-[11px] text-muted" title={`${v.voice_id} @ ${v.model_id}${v.fallback_voice_id ? ` · fallback ${v.fallback_voice_id}` : ""}`}>
          {v.voice_id} <span className="opacity-70">@ {v.model_id}</span>{v.fallback_voice_id ? <span className="opacity-70"> · fallback {v.fallback_voice_id}</span> : null}
        </span>
      ) : <span className="text-muted">no voice</span>}
      <span className="flex items-center gap-1.5 whitespace-nowrap text-muted">
        {pv?.placeholder && <Badge tone="warn" title={`${pv.requested_voice} was refused by the plan; the preview uses ${pv.voice}`}>placeholder</Badge>}
        {pv?.duration_ms ? fmtSeconds(pv.duration_ms) : v && !pv ? "not rendered" : ""}
        {v?.voice_url && <a href={v.voice_url} target="_blank" rel="noreferrer" className="text-accent" title="Open the voice page"><ExternalLink size={13} /></a>}
      </span>
    </div>
  );
}

export function CharacterCard({ c, providers, onEdit, onDelete }: { c: Character; providers: ProviderInfo[]; onEdit: () => void; onDelete: () => void }) {
  return (
    <div className="flex min-w-0 flex-col rounded-md border border-line bg-panel p-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-2 text-[15px] font-semibold">{c.display_name} <Badge tone={c.is_ip_asset ? "accent" : "warn"}>{c.is_ip_asset ? "IP asset" : "one-off"}</Badge></h3>
          <div className="truncate font-mono text-[11px] text-muted">{c.character_id}{c.gender ? ` · ${c.gender}` : ""}{c.age ? ` · ${c.age}` : ""}{c.tags?.length ? ` · ${c.tags.join(", ")}` : ""}</div>
        </div>
        <button className="btn-icon" title="Edit" onClick={onEdit}><Pencil size={15} /></button>
        <button className="btn-icon hover:text-bad" title="Delete" onClick={onDelete}><Trash2 size={15} /></button>
      </div>
      <p className="mt-2 text-[12px] text-muted"><b className="font-medium text-ink">Personality.</b> {c.persona}</p>
      <p className="mt-1 text-[12px] text-muted"><b className="font-medium text-ink">Voice.</b> {c.voice_description}</p>
      <div className="mt-3 rounded-md border border-line bg-sunken/60 px-3">
        {providers.map((p) => <VoiceRow key={p.id} c={c} p={p} />)}
      </div>
    </div>
  );
}
