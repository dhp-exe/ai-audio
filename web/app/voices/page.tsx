"use client";

import {
  ApiOutlined, DeleteOutlined, EditOutlined, LinkOutlined, LockOutlined, PlusOutlined, StarFilled, StarOutlined,
} from "@ant-design/icons";
import {
  Alert, App, Button, Card, Checkbox, Col, Collapse, Divider, Drawer, Flex, Form, Input, Modal, Popconfirm, Row, Select, Space, Switch,
  Tag, Tooltip, Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";
import { EmptyState, ErrorAlert, Loading, PageHead, PlayButton, SourceTag } from "@/components/common";
import { ModelSelect, visibleProviders } from "@/components/EnginePicker";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type Character, type CharacterIn, type Config, type PlugVoiceIn, type Provider, type ProviderInfo, type VoiceSource } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { SOURCE_LABEL } from "@/lib/status";

const SOURCES: VoiceSource[] = ["cloned", "library", "premade", "prebuilt", "placeholder"];

/* ---------------------------------------------------------------- voice picker */

function VoiceIdField({ provider, value, onChange, model }: { provider: ProviderInfo; value: string; onChange: (v: string) => void; model: string | null }) {
  if (provider.voices && !provider.free_voice_id) {
    const group = (g: "female" | "male") => provider.voices!.filter((v) => v.gender === g).map((v) => ({ value: v.id, label: `${v.id} · ${v.character}`, search: `${v.id} ${v.character}` }));
    return (
      <Flex gap={6} align="center">
        <Select
          allowClear
          showSearch={{ optionFilterProp: "search" }}
          value={value || undefined}
          onChange={(v) => onChange(v ?? "")}
          placeholder="Pick a prebuilt voice"
          style={{ flex: 1, minWidth: 0 }}
          aria-label={`${provider.label} voice`}
          options={[{ label: "Female", options: group("female") }, { label: "Male", options: group("male") }]}
        />
        <PlayButton
          key={`${provider.id}-${value}-${model}`}
          resolve={value ? async () => (await api.voicePreview(provider.id, value, model)).preview.url : undefined}
          label={value ? `Preview ${value}` : "Pick a voice to preview"}
        />
      </Flex>
    );
  }
  return (
    <Flex gap={6} align="center">
      <Input value={value} onChange={(e) => onChange(e.target.value.trim())} placeholder={`${provider.label} voice id`} className="mono" aria-label={`${provider.label} voice id`} />
      <PlayButton
        key={`${provider.id}-${value}-${model}`}
        resolve={value ? async () => (await api.voicePreview(provider.id, value, model)).preview.url : undefined}
        label={value ? "Preview this voice" : "Enter a voice id to preview"}
      />
    </Flex>
  );
}

/* ---------------------------------------------------------------- edit drawer */

type ProviderForm = NonNullable<CharacterIn["providers"][Provider]>;

function toForm(c: Character | null): CharacterIn {
  if (!c) return { character_id: "", display_name: "", persona: "", voice_description: "", gender: null, age: null, tags: [], is_ip_asset: true, providers: {} };
  const providers: CharacterIn["providers"] = {};
  (Object.entries(c.providers) as [Provider, NonNullable<Character["providers"][Provider]>][]).forEach(([p, v]) => {
    providers[p] = { voice_id: v.voice_id, model_id: v.model_id, voice_url: v.voice_url, fallback_voice_id: v.fallback_voice_id, source: v.source, label: v.label };
  });
  return { character_id: c.character_id, display_name: c.display_name, persona: c.persona, voice_description: c.voice_description, gender: c.gender, age: c.age, tags: c.tags, is_ip_asset: c.is_ip_asset, providers };
}

function CharacterDrawer({ config, character, open, locked, onClose, onSaved }: {
  config: Config; character: Character | null; open: boolean; locked: boolean; onClose: () => void; onSaved: () => void;
}) {
  const { message } = App.useApp();
  const isNew = !character;
  const [f, setF] = useState<CharacterIn>(() => toForm(character));
  const [unlock, setUnlock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = <K extends keyof CharacterIn>(k: K, v: CharacterIn[K]) => setF((x) => ({ ...x, [k]: v }));
  const setProv = (p: Provider, patch: Partial<ProviderForm>) => setF((x) => {
    const cur: ProviderForm = x.providers[p] ?? { voice_id: "", model_id: null };
    return { ...x, providers: { ...x.providers, [p]: { ...cur, ...patch } } };
  });
  const needsUnlock = !isNew && locked && !!character?.is_ip_asset;

  const save = async () => {
    setErr(null);
    if (isNew && !/^[a-z0-9][a-z0-9-]{0,23}$/.test(f.character_id)) { setErr("Character id: lowercase letters, digits and hyphens (no underscores), max 24."); return; }
    if (!f.display_name.trim()) { setErr("Display name is required."); return; }
    // Drop engines left empty.
    const providers: CharacterIn["providers"] = {};
    (Object.entries(f.providers) as [Provider, ProviderForm][]).forEach(([p, v]) => { if (v.voice_id) providers[p] = v; });
    const body = { ...f, providers };
    setBusy(true);
    try {
      const r = isNew ? await api.addCharacter(body) : await api.editCharacter(f.character_id, body, unlock);
      message.success(r.changelog || "Saved");
      onSaved(); onClose();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      size="min(640px, 100vw)"
      destroyOnHidden
      title={isNew ? "New Voice IP" : `Edit ${character?.display_name}`}
      footer={
        <Flex justify="flex-end" gap={8}>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="primary" onClick={save} loading={busy} disabled={needsUnlock && !unlock}>Save</Button>
        </Flex>
      }
    >
      <Form layout="vertical">
        {needsUnlock && (
          <Alert
            type="warning" showIcon icon={<LockOutlined />} style={{ marginBottom: 16 }}
            title="This Voice IP is locked"
            description={<Checkbox checked={unlock} onChange={(e) => setUnlock(e.target.checked)}>Unlock to change it (recorded in the registry changelog)</Checkbox>}
          />
        )}
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item label="Character id" required extra={isNew ? "Used in stems and scripts. Cannot change later." : undefined}>
              <Input value={f.character_id} onChange={(e) => set("character_id", e.target.value.toLowerCase())} disabled={!isNew} className="mono" placeholder="minh-khoi" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item label="Display name" required><Input value={f.display_name} onChange={(e) => set("display_name", e.target.value)} placeholder="Minh Khôi" /></Form.Item>
          </Col>
          <Col xs={12} sm={8}>
            <Form.Item label="Gender">
              <Select allowClear value={f.gender ?? undefined} onChange={(v) => set("gender", v ?? null)} options={[{ value: "female", label: "Female" }, { value: "male", label: "Male" }, { value: "other", label: "Other" }]} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={8}><Form.Item label="Age"><Input value={f.age ?? ""} onChange={(e) => set("age", e.target.value || null)} placeholder="25-30" /></Form.Item></Col>
          <Col xs={24} sm={8}>
            <Form.Item label="IP asset" tooltip="A recurring Virtual Actor (locked, builds fans across series) vs a one-off voice.">
              <Switch checked={f.is_ip_asset} onChange={(v) => set("is_ip_asset", v)} checkedChildren="IP asset" unCheckedChildren="One-off" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item label="Tags"><Select mode="tags" value={f.tags} onChange={(v) => set("tags", v)} tokenSeparators={[","]} placeholder="ấm áp, lạnh lùng, CEO" /></Form.Item>
        <Form.Item label="Persona"><Input.TextArea value={f.persona} onChange={(e) => set("persona", e.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
        <Form.Item label="Voice description"><Input.TextArea value={f.voice_description} onChange={(e) => set("voice_description", e.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
        <Divider titlePlacement="start" plain>Voices per engine</Divider>
        {visibleProviders(config).map((p) => {
          const v = f.providers[p.id];
          return (
            <Card key={p.id} size="small" title={p.label} style={{ marginBottom: 12 }} extra={v?.source && <SourceTag source={v.source} />}>
              <Form.Item label="Voice" style={{ marginBottom: 8 }}>
                <VoiceIdField provider={p} value={v?.voice_id ?? ""} onChange={(id) => setProv(p.id, { voice_id: id })} model={v?.model_id ?? null} />
              </Form.Item>
              <Row gutter={8}>
                <Col xs={24} sm={12}>
                  <Form.Item label="Model" style={{ marginBottom: 8 }}>
                    <ModelSelect provider={p} value={v?.model_id ?? null} onChange={(m) => setProv(p.id, { model_id: m })} allowFree={p.id === "wavespeed"} style={{ width: "100%", minWidth: 0 }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item label="Source" style={{ marginBottom: 8 }}>
                    <Select allowClear value={v?.source} onChange={(s) => setProv(p.id, { source: s })} options={SOURCES.map((s) => ({ value: s, label: SOURCE_LABEL[s] }))} placeholder="auto" />
                  </Form.Item>
                </Col>
                {p.free_voice_id && (
                  <>
                    <Col xs={24} sm={12}>
                      <Form.Item label="Voice page URL" style={{ marginBottom: 8 }}><Input value={v?.voice_url ?? ""} onChange={(e) => setProv(p.id, { voice_url: e.target.value || null })} /></Form.Item>
                    </Col>
                    <Col xs={24} sm={12}>
                      <Form.Item label="Fallback voice id" style={{ marginBottom: 8 }}><Input value={v?.fallback_voice_id ?? ""} onChange={(e) => setProv(p.id, { fallback_voice_id: e.target.value || null })} className="mono" /></Form.Item>
                    </Col>
                  </>
                )}
              </Row>
            </Card>
          );
        })}
        {err && <Alert type="error" showIcon title={err} />}
      </Form>
    </Drawer>
  );
}

/* ---------------------------------------------------------------- plug in a cloned voice */

function PlugVoiceModal({ config, character, locked, onClose, onSaved }: { config: Config; character: Character; locked: boolean; onClose: () => void; onSaved: () => void }) {
  const { message } = App.useApp();
  const providers = visibleProviders(config).filter((p) => p.id !== "mock");
  const [f, setF] = useState<PlugVoiceIn>({
    provider: providers.find((p) => p.id === "elevenlabs")?.id ?? providers[0]?.id ?? "elevenlabs",
    voice_id: "", model_id: null, source: "cloned", label: "", voice_url: "", fallback_voice_id: null, make_preferred: true, unlock: false,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const prov = config.catalog.providers.find((p) => p.id === f.provider);
  const needsUnlock = locked && character.is_ip_asset;
  const set = <K extends keyof PlugVoiceIn>(k: K, v: PlugVoiceIn[K]) => setF((x) => ({ ...x, [k]: v }));

  const submit = async () => {
    if (!f.voice_id.trim()) { setErr("Enter the voice id."); return; }
    if (needsUnlock && !f.unlock) { setErr("This Voice IP is locked: switch on unlock to replace its voice."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await api.plugVoice(character.character_id, { ...f, label: f.label || null, voice_url: f.voice_url || null });
      message.success(r.changelog || "Voice plugged in");
      onSaved(); onClose();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onCancel={onClose} title={<Space><ApiOutlined />Plug in cloned voice · {character.display_name}</Space>} okText="Plug in" onOk={submit} confirmLoading={busy} destroyOnHidden width={600}>
      <Typography.Paragraph type="secondary">
        Attach the voice you cloned for this Voice IP. The next run that casts {character.display_name} on this engine uses it automatically;
        stems are re-rendered because the voice id is part of their cache hash.
      </Typography.Paragraph>
      <Form layout="vertical">
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item label="Engine">
              <Select value={f.provider} onChange={(p) => setF((x) => ({ ...x, provider: p, model_id: null, voice_id: "" }))} options={providers.map((p) => ({ value: p.id, label: p.label }))} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item label="Source">
              <Select value={f.source} onChange={(s) => set("source", s)} options={SOURCES.map((s) => ({ value: s, label: SOURCE_LABEL[s] }))} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item label="Voice id" required>
          {prov && <VoiceIdField provider={prov} value={f.voice_id} onChange={(v) => set("voice_id", v)} model={f.model_id ?? null} />}
        </Form.Item>
        <Form.Item label="Model" extra={f.provider === "wavespeed" ? "Free text allowed: paste the WaveSpeed model path." : undefined}>
          <ModelSelect provider={prov} value={f.model_id ?? null} onChange={(m) => set("model_id", m)} allowFree={f.provider === "wavespeed"} style={{ width: "100%" }} />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={24} sm={12}><Form.Item label="Label"><Input value={f.label ?? ""} onChange={(e) => set("label", e.target.value)} placeholder="Ngân, PVC v2" /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item label="Voice page URL"><Input value={f.voice_url ?? ""} onChange={(e) => set("voice_url", e.target.value)} placeholder="https://…" /></Form.Item></Col>
        </Row>
        <Flex gap={24} wrap>
          <Form.Item label="Make preferred engine" tooltip="Casting picks this engine for the actor when the run allows per-actor engines.">
            <Switch checked={f.make_preferred} onChange={(v) => set("make_preferred", v)} />
          </Form.Item>
          {needsUnlock && (
            <Form.Item label="Unlock" tooltip="Locked IP assets need an explicit unlock to change a voice.">
              <Switch checked={f.unlock} onChange={(v) => set("unlock", v)} />
            </Form.Item>
          )}
        </Flex>
        {err && <Alert type="error" showIcon title={err} />}
      </Form>
    </Modal>
  );
}

/* ---------------------------------------------------------------- card */

function DeleteButton({ c, locked, onDone }: { c: Character; locked: boolean; onDone: () => void }) {
  const { message } = App.useApp();
  const [unlock, setUnlock] = useState(false);
  const needsUnlock = locked && c.is_ip_asset;
  const del = async () => {
    try { await api.deleteCharacter(c.character_id, unlock); message.success(`Deleted ${c.display_name}`); onDone(); }
    catch (e) { message.error((e as Error).message); }
  };
  return (
    <Popconfirm
      title={`Delete ${c.display_name}?`}
      description={
        <div style={{ maxWidth: 260 }}>
          {c.series.length > 0 && <div>Appears in {c.series.length} series; their casting will need a new voice.</div>}
          {needsUnlock && <Checkbox checked={unlock} onChange={(e) => setUnlock(e.target.checked)}>Unlock this IP asset</Checkbox>}
        </div>
      }
      okText="Delete"
      okButtonProps={{ danger: true, disabled: needsUnlock && !unlock }}
      onConfirm={del}
      onOpenChange={(o) => { if (!o) setUnlock(false); }}
    >
      <Tooltip title="Delete"><Button type="text" danger icon={<DeleteOutlined />} aria-label={`Delete ${c.display_name}`} /></Tooltip>
    </Popconfirm>
  );
}

function CharacterCard({ c, config, locked, onEdit, onPlug, onChanged }: {
  c: Character; config: Config; locked: boolean; onEdit: () => void; onPlug: () => void; onChanged: () => void;
}) {
  const hasCloned = Object.values(c.providers).some((v) => v?.source === "cloned");
  return (
    <Card
      size="small"
      style={{ height: "100%", display: "flex", flexDirection: "column", borderColor: hasCloned ? "var(--ev-gold)" : undefined }}
      styles={{ body: { display: "flex", flexDirection: "column", gap: 10, flex: 1 } }}
      title={
        <Flex align="center" gap={8} style={{ minWidth: 0 }}>
          <Typography.Text strong ellipsis>{c.display_name}</Typography.Text>
          <span className="mono muted" style={{ fontSize: 11, fontWeight: 400 }}>{c.character_id}</span>
        </Flex>
      }
      extra={
        <Space size={0}>
          <Tooltip title="Edit"><Button type="text" icon={<EditOutlined />} onClick={onEdit} aria-label={`Edit ${c.display_name}`} /></Tooltip>
          <DeleteButton c={c} locked={locked} onDone={onChanged} />
        </Space>
      }
    >
      <Flex gap={4} wrap>
        {c.is_ip_asset
          ? <Tooltip title="Recurring Virtual Actor: locked voice, builds fans across series"><Tag color="geekblue" icon={locked ? <LockOutlined /> : undefined} style={{ marginInlineEnd: 0 }}>IP asset</Tag></Tooltip>
          : <Tag style={{ marginInlineEnd: 0 }}>One-off</Tag>}
        {c.gender && <Tag style={{ marginInlineEnd: 0 }}>{c.gender}</Tag>}
        {c.age && <Tag style={{ marginInlineEnd: 0 }}>{c.age}</Tag>}
        {c.tags.map((t) => <Tag key={t} color="default" style={{ marginInlineEnd: 0 }}>{t}</Tag>)}
      </Flex>
      {c.persona && <Typography.Paragraph className="clamp-3" style={{ margin: 0, fontSize: 13 }} title={c.persona}>{c.persona}</Typography.Paragraph>}
      {c.voice_description && <Typography.Paragraph type="secondary" className="clamp-2" style={{ margin: 0, fontSize: 12 }} title={c.voice_description}>{c.voice_description}</Typography.Paragraph>}
      <Flex vertical gap={6} style={{ borderTop: "1px solid var(--ev-border)", paddingTop: 8 }}>
        {visibleProviders(config).map((p) => {
          const v = c.providers[p.id];
          const preview = c.previews[p.id];
          return (
            <Flex key={p.id} align="center" gap={6} className={v?.source === "cloned" ? "ev-cloned" : undefined} style={{ paddingInlineStart: v?.source === "cloned" ? 8 : 0, minHeight: 28 }}>
              <Tooltip title={c.preferred_provider === p.id ? "Preferred engine" : "Not the preferred engine"}>
                {c.preferred_provider === p.id ? <StarFilled style={{ color: "#faad14" }} aria-label="Preferred engine" /> : <StarOutlined className="muted" aria-label="Not preferred" />}
              </Tooltip>
              <span style={{ width: 82, flex: "none", fontSize: 12 }}>{p.label}</span>
              {v ? (
                <>
                  <PlayButton url={preview?.url ?? null} resolve={async () => (await api.characterPreview(c.character_id, p.id)).preview.url} label={`Preview on ${p.label}`} />
                  <Tooltip title={`${v.voice_id} @ ${v.model_id}${v.label ? ` (${v.label})` : ""}`}>
                    <span className="mono" style={{ fontSize: 11, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {v.voice_id}<span className="muted"> @ {v.model_id}</span>
                    </span>
                  </Tooltip>
                  <SourceTag source={v.source} />
                  {v.voice_url && <Tooltip title="Voice page"><a href={v.voice_url} target="_blank" rel="noreferrer" aria-label="Open voice page"><LinkOutlined /></a></Tooltip>}
                </>
              ) : <Typography.Text type="secondary" style={{ fontSize: 12, flex: 1 }}>not set</Typography.Text>}
            </Flex>
          );
        })}
      </Flex>
      {c.series.length > 0 && (
        <Flex gap={4} wrap>
          <span className="muted" style={{ fontSize: 12 }}>In:</span>
          {c.series.map((s) => (
            <Tooltip key={s.series_id} title={`as ${s.role}`}>
              <Link href={`/productions/detail/?id=${encodeURIComponent(s.series_id)}`}><Tag color="blue" style={{ marginInlineEnd: 0 }}>{s.title || s.series_id}</Tag></Link>
            </Tooltip>
          ))}
        </Flex>
      )}
      <Button block icon={<ApiOutlined />} onClick={onPlug} style={{ marginTop: "auto" }} type={hasCloned ? "default" : "primary"} ghost={!hasCloned}>
        Plug in cloned voice
      </Button>
    </Card>
  );
}

/* ---------------------------------------------------------------- page */

export default function VoicesPage() {
  const { config, configError, refreshConfig } = useStudio();
  const { data, error, loading, refresh } = usePoll(() => api.characters(), 0);
  const [editing, setEditing] = useState<{ c: Character | null } | null>(null);
  const [plugging, setPlugging] = useState<Character | null>(null);
  const [filter, setFilter] = useState<"all" | "ip" | "oneoff">("all");
  const chars = useMemo(() => {
    const list = [...(data?.characters ?? [])].sort((a, b) => Number(b.is_ip_asset) - Number(a.is_ip_asset) || a.display_name.localeCompare(b.display_name));
    return list.filter((c) => filter === "all" || (filter === "ip" ? c.is_ip_asset : !c.is_ip_asset));
  }, [data, filter]);
  const changed = () => { refresh(); refreshConfig(); };

  return (
    <>
      <PageHead
        title="Voice IPs"
        sub="The Character IP asset library: fixed AI actors with their own voice on every engine."
        extra={
          <>
            <Select value={filter} onChange={setFilter} style={{ width: 140 }} aria-label="Filter actors"
              options={[{ value: "all", label: "All actors" }, { value: "ip", label: "IP assets" }, { value: "oneoff", label: "One-off" }]} />
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ c: null })} disabled={!config}>New Voice IP</Button>
          </>
        }
      />
      <ErrorAlert error={error ?? configError} onRetry={() => { refresh(); refreshConfig(); }} />
      {data?.locked && (
        <Alert type="info" showIcon icon={<LockOutlined />} style={{ marginBottom: 16 }} title="The registry is locked" description="IP assets keep their voice across series. Changing or deleting one needs an explicit unlock, recorded in the changelog." />
      )}
      {(loading && !data) || !config ? <Loading rows={8} /> : (
        <>
          {chars.length ? (
            <Row gutter={[12, 12]}>
              {chars.map((c) => (
                <Col key={c.character_id} xs={24} md={12} xl={8} xxl={6}>
                  <CharacterCard c={c} config={config} locked={!!data?.locked} onEdit={() => setEditing({ c })} onPlug={() => setPlugging(c)} onChanged={changed} />
                </Col>
              ))}
            </Row>
          ) : (
            <Card><EmptyState description="No Voice IPs yet" action={<Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ c: null })}>Create the first actor</Button>} /></Card>
          )}
          <Collapse
            style={{ marginTop: 16 }}
            items={[{
              key: "log",
              label: `Registry changelog (${data?.changelog.length ?? 0})`,
              children: data?.changelog.length
                ? <pre className="ev-pre" style={{ maxHeight: 360 }}>{[...data.changelog].reverse().join("\n")}</pre>
                : <Typography.Text type="secondary">No changes recorded.</Typography.Text>,
            }]}
          />
        </>
      )}
      {config && editing && (
        <CharacterDrawer
          key={editing.c?.character_id ?? "new"}
          config={config} character={editing.c} open locked={!!data?.locked}
          onClose={() => setEditing(null)} onSaved={changed}
        />
      )}
      {config && plugging && (
        <PlugVoiceModal config={config} character={plugging} locked={!!data?.locked} onClose={() => setPlugging(null)} onSaved={changed} />
      )}
    </>
  );
}
