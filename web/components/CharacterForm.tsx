"use client";

import { useEffect, useState } from "react";
import { api, type Character, type CharacterIn, type Config, type Preview } from "@/lib/api";
import { ErrorText, Field, PlayButton, SectionTitle } from "./ui";

/** Add or edit a Character IP. `existing` switches to edit mode (id locked, unlock checkbox for locked voices). */
export function CharacterForm({ cfg, existing, onSaved, onCancel }: { cfg: Config; existing?: Character | null; onSaved: (msg: string) => void; onCancel: () => void }) {
  const editing = !!existing;
  const el = existing?.providers.elevenlabs, gm = existing?.providers.gemini;
  const gemini = cfg.catalog.providers.find((p) => p.id === "gemini")!;
  const eleven = cfg.catalog.providers.find((p) => p.id === "elevenlabs")!;
  const [id, setId] = useState(existing?.character_id ?? "");
  const [name, setName] = useState(existing?.display_name ?? "");
  const [gender, setGender] = useState(existing?.gender ?? "");
  const [age, setAge] = useState(existing?.age ?? "");
  const [tags, setTags] = useState((existing?.tags ?? []).join(", "));
  const [persona, setPersona] = useState(existing?.persona ?? "");
  const [voiceDesc, setVoiceDesc] = useState(existing?.voice_description ?? "");
  const [elVoice, setElVoice] = useState(el?.voice_id ?? "");
  const [elModel, setElModel] = useState(el?.model_id ?? eleven.default_model);
  const [elUrl, setElUrl] = useState(el?.voice_url ?? "");
  const [elFallback, setElFallback] = useState(el?.fallback_voice_id ?? "");
  const [gmVoice, setGmVoice] = useState(gm?.voice_id ?? "");
  const [gmModel, setGmModel] = useState(gm?.model_id ?? gemini.default_model);
  const [isIp, setIsIp] = useState(existing?.is_ip_asset ?? true);
  const [unlock, setUnlock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const savedGm = existing?.previews?.gemini ?? null;
  const [gmPreview, setGmPreview] = useState<Preview | null>(savedGm);

  // The preview below the picker reflects the selected voice/model: the actor's cached clip while unchanged, otherwise a (once-rendered) voice clip.
  useEffect(() => { setGmPreview(gmVoice === gm?.voice_id && gmModel === gm?.model_id ? savedGm : null); }, [gmVoice, gmModel, gm?.voice_id, gm?.model_id, savedGm]);

  const byGender = { female: gemini.voices!.filter((v) => v.gender === "female"), male: gemini.voices!.filter((v) => v.gender === "male") };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    const body: CharacterIn = {
      character_id: id.trim(), display_name: name.trim(), persona, voice_description: voiceDesc, gender: gender || null, age: age || null,
      tags: tags.split(",").map((s) => s.trim()).filter(Boolean), is_ip_asset: isIp, providers: {},
    };
    if (elVoice.trim()) body.providers.elevenlabs = { voice_id: elVoice.trim(), model_id: elModel, voice_url: elUrl || null, fallback_voice_id: elFallback || null };
    if (gmVoice) body.providers.gemini = { voice_id: gmVoice, model_id: gmModel };
    try {
      const r = editing ? await api.editCharacter(existing!.character_id, body, unlock) : await api.addCharacter(body);
      onSaved(r.changelog);
    } catch (ex) { setErr((ex as Error).message); } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="pb-6">
      <SectionTitle>Identity</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Id (lowercase, no spaces)"><input className="field font-mono" value={id} onChange={(e) => setId(e.target.value)} pattern="[a-z][a-z0-9-]{0,23}" placeholder="ngan" required readOnly={editing} /></Field>
        <Field label="Display name"><input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ngân" required /></Field>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Field label="Gender">
          <select className="field" value={gender} onChange={(e) => setGender(e.target.value)}><option value="">—</option><option value="female">female</option><option value="male">male</option><option value="other">other</option></select>
        </Field>
        <Field label="Age"><input className="field" value={age} onChange={(e) => setAge(e.target.value)} placeholder="23" /></Field>
        <Field label="Tags (comma)"><input className="field" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="cute, innocent" /></Field>
      </div>
      <Field label="Personality" className="mt-3" hint="Used for casting and for the Director's delivery notes.">
        <textarea className="field min-h-[110px]" value={persona} onChange={(e) => setPersona(e.target.value)} placeholder="Tính cách, cách nói chuyện, nhịp điệu, điều gì làm nhân vật này khác biệt…" />
      </Field>
      <Field label="Voice description" className="mt-3" hint="Timbre, age, accent. The casting model reads this.">
        <textarea className="field min-h-[80px]" value={voiceDesc} onChange={(e) => setVoiceDesc(e.target.value)} placeholder="Nữ, 23, trong trẻo, ngọt, giọng miền Trung nhẹ…" />
      </Field>

      <SectionTitle>ElevenLabs voice</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        <Field label="voice_id"><input className="field font-mono" value={elVoice} onChange={(e) => setElVoice(e.target.value)} placeholder="a3AkyqGG4v8Pg7SWQ0Y3" /></Field>
        <Field label="Model"><select className="field" value={elModel} onChange={(e) => setElModel(e.target.value)}>{eleven.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></Field>
        <Field label="Voice link"><input className="field" value={elUrl} onChange={(e) => setElUrl(e.target.value)} placeholder="https://elevenlabs.io/voices/…" /></Field>
        <Field label="Fallback premade voice_id" hint="Used when the plan refuses the voice."><input className="field font-mono" value={elFallback} onChange={(e) => setElFallback(e.target.value)} /></Field>
      </div>

      <SectionTitle>Gemini voice</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Voice">
          <select className="field" value={gmVoice} onChange={(e) => setGmVoice(e.target.value)}>
            <option value="">— none —</option>
            {(["female", "male"] as const).map((g) => (
              <optgroup key={g} label={g}>{byGender[g].map((v) => <option key={v.id} value={v.id}>{v.id} · {v.character}</option>)}</optgroup>
            ))}
          </select>
        </Field>
        <Field label="Model"><select className="field" value={gmModel} onChange={(e) => setGmModel(e.target.value)}>{gemini.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></Field>
      </div>
      {gmVoice && (
        <div className="mt-2 flex items-center gap-2 text-[12px] text-muted">
          <PlayButton preview={gmPreview} title="Hear this voice" render={async () => { const r = await api.voicePreview("gemini", gmVoice, gmModel); setGmPreview(r.preview); return r.preview; }} />
          Hear {gmVoice} on {gemini.models.find((m) => m.id === gmModel)?.label}. Rendered once per voice and model, then cached.
        </div>
      )}

      <SectionTitle>Registry</SectionTitle>
      <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={isIp} onChange={(e) => setIsIp(e.target.checked)} /> IP asset (locked; recurring across series)</label>
      {editing && <label className="mt-2 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={unlock} onChange={(e) => setUnlock(e.target.checked)} /> Unlock: allow changing or removing a locked voice</label>}
      <div className="mt-4 flex gap-2">
        <button className="btn-primary flex-1" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Add character"}</button>
        <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
      <ErrorText>{err}</ErrorText>
    </form>
  );
}
