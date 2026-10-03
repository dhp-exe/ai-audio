"use client";

import { DeleteOutlined, PlusOutlined, RocketOutlined } from "@ant-design/icons";
import {
  Alert, App, Button, Card, Checkbox, Col, Descriptions, Divider, Flex, Form, Input, InputNumber, Radio, Row, Segmented, Select, Space,
  Steps, Switch, Tag, Tooltip, Typography,
} from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ErrorAlert, Loading, Num, PageHead, PlayButton } from "@/components/common";
import { EnginePicker, providerHasKey, visibleProviders, type EngineValue } from "@/components/EnginePicker";
import { ThemeTag } from "@/components/ProductionCard";
import { useStudio } from "@/components/providers/StudioProvider";
import {
  api, type ActorSummary, type Config, type LlmProviderId, type Provider, type RoleType, type SeriesDetail, type StartRun, type TrendBrief,
} from "@/lib/api";
import { wordCount } from "@/lib/format";
import { PLATFORMS, WORDS_PER_SEC } from "@/lib/constants";
import { usePoll } from "@/lib/hooks";

type Source = "brief" | "story" | "research";
type StepKey = "source" | "story" | "engines" | "review";
interface RoleRow { key: number; name: string; description: string; actor_id: string }

const emptyRoles = (): RoleRow[] => [{ key: 0, name: "", description: "", actor_id: "" }, { key: 1, name: "", description: "", actor_id: "" }];

/** Older stories keep "/actor" tags inside names; lift them into the actor picker. */
function rolesFromStory(s: SeriesDetail | null, actors: ActorSummary[]): RoleRow[] {
  const ids = new Set(actors.map((a) => a.character_id));
  const untag = (text: string): [string, string | null] => {
    const m = text.match(/(?:^|\s)[/#@]([a-z][a-z0-9-]{0,23})\b/i);
    if (m && ids.has(m[1].toLowerCase())) return [text.replace(m[0], " ").replace(/\s{2,}/g, " ").trim(), m[1].toLowerCase()];
    return [text, null];
  };
  const rows = (s?.story?.roles ?? []).map((r, i) => {
    const [name, t1] = untag(r.name);
    const [description, t2] = untag(r.description);
    return { key: i, name, description, actor_id: r.actor_id ?? t1 ?? t2 ?? "" };
  });
  return rows.length ? rows : emptyRoles();
}

function actorLabel(a: ActorSummary) {
  const bits = [a.gender, a.age].filter(Boolean).join(", ");
  return `${a.display_name}${bits ? ` (${bits})` : ""}`;
}

function BriefSummary({ b }: { b: TrendBrief }) {
  return (
    <Descriptions
      size="small"
      bordered
      column={1}
      items={[
        { key: "t", label: "Topic", children: <Space wrap>{b.topic}<ThemeTag theme={b.theme_category} /><Tag><Num>score {b.score.toFixed(2)}</Num></Tag></Space> },
        { key: "a", label: "Audience", children: b.target_audience },
        { key: "h", label: "Hook", children: b.hook },
        { key: "p", label: "Premise", children: b.premise },
        { key: "x", label: "Anti-trope angle", children: b.anti_trope_angle },
        { key: "f", label: "Format", children: <Num>{b.format_spec.episodes} × {b.format_spec.episode_seconds_min}-{b.format_spec.episode_seconds_max}s · {b.format_spec.medium} · {b.format_spec.language}</Num> },
      ]}
    />
  );
}

function Wizard({ config }: { config: Config }) {
  const params = useSearchParams();
  const router = useRouter();
  const { message } = App.useApp();
  const editId = params.get("edit");
  const briefParam = params.get("brief");

  const briefs = usePoll(() => api.briefs(), 0);
  const existing = usePoll(() => api.series(editId!), 0, [editId], !!editId);

  const [step, setStep] = useState(editId ? 1 : 0);
  const [source, setSource] = useState<Source>(editId ? "story" : briefParam ? "brief" : "story");
  const [briefId, setBriefId] = useState<string | null>(briefParam);
  // research
  const [seeds, setSeeds] = useState("");
  const [platforms, setPlatforms] = useState<string[]>(["dramabox", "reelshort", "tiktok"]);
  const [useBrowser, setUseBrowser] = useState(config.defaults.research_use_browser);
  const [focus, setFocus] = useState<string>("");
  // story
  const [title, setTitle] = useState("");
  const [minutes, setMinutes] = useState<number | null>(null);
  const [genre, setGenre] = useState("");
  const [setting, setSetting] = useState("");
  const [roles, setRoles] = useState<RoleRow[]>(emptyRoles);
  const [rolesText, setRolesText] = useState("");
  const [script, setScript] = useState("");
  // engines
  const [engine, setEngine] = useState<EngineValue>({ provider: config.tts.provider, model: null, batching: config.tts.batching });
  const [overrides, setOverrides] = useState<Partial<Record<RoleType, Provider>>>({});
  const [llmProvider, setLlmProvider] = useState<LlmProviderId>(config.llm.provider);
  const [llmModel, setLlmModel] = useState("");
  // production
  const [episodes, setEpisodes] = useState(config.defaults.episodes);
  const [minSec, setMinSec] = useState(config.defaults.min_sec);
  const [maxSec, setMaxSec] = useState(config.defaults.max_sec);
  const [produce, setProduce] = useState<number | null>(config.defaults.produce);
  const [tier, setTier] = useState<"test" | "final">("test");
  const [maxRetries, setMaxRetries] = useState(config.defaults.max_retries);
  const [autoApprove, setAutoApprove] = useState(config.defaults.auto_approve);
  const [haltOnFail, setHaltOnFail] = useState(config.defaults.halt_on_qa_fail);
  const [seriesId, setSeriesId] = useState("");
  const [force, setForce] = useState(!!editId);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Prefill from an existing series (edit & re-run).
  const prefilled = useRef(false);
  useEffect(() => {
    const s = existing.data;
    if (!s || prefilled.current) return;
    prefilled.current = true;
    const st = s.story;
    setSource("story");
    setTitle(st?.overview.title ?? s.title ?? "");
    setMinutes(st?.overview.total_minutes ?? null);
    setGenre(st?.overview.genre ?? s.genre ?? "");
    setSetting(st?.overview.setting ?? s.setting ?? "");
    setRoles(rolesFromStory(s, config.actors));
    setScript(st?.script ?? s.story_raw ?? "");
    setSeriesId(s.series_id);
    if (s.planned) setEpisodes(s.planned);
    if (s.run) {
      setEngine((e) => ({ ...e, provider: s.run!.tts_provider, model: s.run!.tts_model }));
      if (s.run.min_sec) setMinSec(s.run.min_sec);
      if (s.run.max_sec) setMaxSec(s.run.max_sec);
      if (s.run.llm_provider && config.llm.providers.includes(s.run.llm_provider as LlmProviderId)) setLlmProvider(s.run.llm_provider as LlmProviderId);
    }
    setForce(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing.data]);

  const stepKeys: StepKey[] = source === "story" ? ["source", "story", "engines", "review"] : ["source", "engines", "review"];
  const current = stepKeys[Math.min(step, stepKeys.length - 1)];
  const brief = briefs.data?.briefs.find((b) => b.brief_id === briefId) ?? null;
  const actorsById = useMemo(() => Object.fromEntries(config.actors.map((a) => [a.character_id, a])), [config.actors]);
  const provider = config.catalog.providers.find((p) => p.id === engine.provider);

  // Brief prefill of the production format.
  const briefKey = source === "brief" ? brief?.brief_id ?? null : null;
  useEffect(() => {
    if (!briefKey || !brief) return;
    if (brief.format_spec.episodes) setEpisodes(brief.format_spec.episodes);
    if (brief.format_spec.episode_seconds_min) setMinSec(brief.format_spec.episode_seconds_min);
    if (brief.format_spec.episode_seconds_max) setMaxSec(brief.format_spec.episode_seconds_max);
    // Only when the picked brief changes, not on every poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [briefKey]);

  const words = wordCount(script);
  const segmentThreshold = Math.round(0.5 * episodes * minSec * WORDS_PER_SEC);
  const segmentMode = words >= segmentThreshold;
  const used = (except: number) => new Set(roles.filter((r) => r.key !== except && r.actor_id).map((r) => r.actor_id));
  const updateRole = (key: number, patch: Partial<RoleRow>) => setRoles((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const produceN = produce ?? episodes;
  const batched = provider?.scene_batching && engine.batching !== "line";
  const estTts = produceN * (batched ? 3 : 12);
  const estLlm = (source === "research" ? 1 : 0) + 2 + produceN * 3;

  function validate(k: StepKey): string | null {
    if (k === "source" && source === "brief" && !briefId) return "Pick a trend brief, or switch to writing your own story.";
    if (k === "source" && source === "research" && !seeds.trim() && !platforms.length) return "Add seed notes or pick at least one platform to scan.";
    if (k === "story") {
      if (!title.trim()) return "Give the story a title.";
      if (!script.trim()) return "Paste the script or a treatment.";
    }
    if (k === "engines") {
      if (minSec > maxSec) return "Minimum seconds must not exceed maximum seconds.";
      if (produce != null && produce > episodes) return "Produce now cannot exceed the number of episodes.";
      if (seriesId && !/^[a-z0-9][a-z0-9-]*$/.test(seriesId)) return "Series id: lowercase letters, digits and hyphens only.";
    }
    return null;
  }

  const next = () => {
    const v = validate(current);
    if (v) { setErr(v); return; }
    setErr(null);
    setStep((s) => Math.min(s + 1, stepKeys.length - 1));
  };
  const back = () => { setErr(null); setStep((s) => Math.max(0, s - 1)); };

  const submit = async () => {
    for (const k of stepKeys) { const v = validate(k); if (v) { setErr(v); return; } }
    setBusy(true); setErr(null);
    const engineByRole: StartRun["engine_by_role_type"] = {};
    (Object.entries(overrides) as [RoleType, Provider][]).forEach(([rt, p]) => { if (p) engineByRole[rt] = { provider: p }; });
    const body: StartRun = {
      series_id: seriesId || null,
      source,
      brief_id: source === "brief" ? briefId : null,
      ...(source === "research" ? { research: { seeds, platforms, use_browser: useBrowser, focus } } : {}),
      ...(source === "story" ? {
        title: title.trim(), total_minutes: minutes, genre, setting,
        roles: roles.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), description: r.description.trim(), actor_id: r.actor_id || null })),
        roles_text: rolesText, script,
      } : {}),
      episodes, produce, min_sec: minSec, max_sec: maxSec, force,
      tts_provider: engine.provider, tts_model: engine.model, tts_batching: engine.batching, tier,
      engine_by_role_type: Object.keys(engineByRole).length ? engineByRole : undefined,
      llm_provider: llmProvider, llm_model: llmModel.trim() || null,
      max_retries: maxRetries, auto_approve: autoApprove, halt_on_qa_fail: haltOnFail,
    };
    try {
      const run = await api.startRun(body);
      message.success("Production started");
      router.push(`/pipeline/?id=${encodeURIComponent(run.run_id)}`);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  const providerOptions = visibleProviders(config).map((p) => ({ value: p.id, label: p.label }));

  /* ------------------------------------------------------------ step bodies */
  const sourceStep = (
    <Flex vertical gap={16}>
      <Radio.Group
        value={source}
        onChange={(e) => { setSource(e.target.value); setStep(0); }}
        disabled={!!editId}
        optionType="button"
        buttonStyle="solid"
        options={[
          { value: "brief", label: "From a trend brief" },
          { value: "story", label: "Write my own story" },
          { value: "research", label: "Research now" },
        ]}
      />
      {source === "brief" && (
        <>
          <Select
            showSearch={{ optionFilterProp: "label" }}
            placeholder={briefs.loading ? "Loading briefs…" : "Pick a trend brief"}
            loading={briefs.loading}
            value={briefId ?? undefined}
            onChange={setBriefId}
            style={{ maxWidth: 560, width: "100%" }}
            options={(briefs.data?.briefs ?? []).map((b) => ({ value: b.brief_id, label: `${b.topic} · ${b.score.toFixed(2)}` }))}
            notFoundContent={<span className="muted">No briefs yet. <Link href="/research/">Run a market scan</Link>.</span>}
            aria-label="Trend brief"
          />
          <ErrorAlert error={briefs.error} onRetry={briefs.refresh} title="Could not load briefs" />
          {brief && <BriefSummary b={brief} />}
          <Typography.Text type="secondary">The Script Writer turns the brief into a series bible and episode drafts; Casting assigns Voice IPs.</Typography.Text>
        </>
      )}
      {source === "research" && (
        <Form layout="vertical">
          <Form.Item label="Seed notes" extra="Paste trend notes, titles or observations (Vietnamese is fine). Optional when platforms are scanned.">
            <Input.TextArea rows={5} value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder="Ví dụ: phim ngắn tổng tài, trọng sinh báo thù…" />
          </Form.Item>
          <Form.Item label="Platforms">
            <Checkbox.Group options={PLATFORMS} value={platforms} onChange={(v) => setPlatforms(v as string[])} />
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item label="Use a browser" extra="Needs Playwright installed on the engine host.">
                <Switch checked={useBrowser} onChange={setUseBrowser} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item label="Focus">
                <Select allowClear placeholder="Any theme" value={focus || undefined} onChange={(v) => setFocus(v ?? "")} options={config.theme_categories.map((t) => ({ value: t.id, label: t.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Typography.Text type="secondary">The Market Research agent writes a TrendBrief first, then the run continues as if you had picked that brief.</Typography.Text>
        </Form>
      )}
      {source === "story" && (
        <Typography.Text type="secondary">
          {editId ? "Editing an existing production: the story, roles and script are prefilled." : "Next you will write the overview, roles and script."}
        </Typography.Text>
      )}
    </Flex>
  );

  const storyStep = (
    <Form layout="vertical">
      <Row gutter={16}>
        <Col xs={24} md={12}><Form.Item label="Title" required><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Tên truyện" /></Form.Item></Col>
        <Col xs={12} md={4}><Form.Item label="Total minutes"><InputNumber min={1} value={minutes} onChange={(v) => setMinutes(v)} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={12} md={8}><Form.Item label="Genre"><Input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="Ngôn tình, tổng tài…" /></Form.Item></Col>
        <Col xs={24}><Form.Item label="Setting"><Input value={setting} onChange={(e) => setSetting(e.target.value)} placeholder="Sài Gòn, hiện đại" /></Form.Item></Col>
      </Row>
      <Form.Item label="Roles" extra="One Voice IP per role. Roles left without an IP are cast by the Casting agent.">
        <Flex vertical gap={8}>
          {roles.map((r, i) => {
            const taken = used(r.key);
            const actor = r.actor_id ? actorsById[r.actor_id] : null;
            const cached = actor?.previews[engine.provider]?.url ?? null;
            return (
              <Card key={r.key} size="small" styles={{ body: { padding: 10 } }}>
                <Flex gap={8} wrap align="center">
                  <Input
                    value={r.name} onChange={(e) => updateRole(r.key, { name: e.target.value })}
                    placeholder={i === 0 ? "Tên nhân vật chính" : "Tên nhân vật"} style={{ flex: "1 1 180px" }} aria-label={`Role ${i + 1} name`}
                  />
                  <Select
                    allowClear
                    showSearch={{ optionFilterProp: "label" }}
                    placeholder="Voice IP (auto-cast)"
                    value={r.actor_id || undefined}
                    onChange={(v) => updateRole(r.key, { actor_id: v ?? "" })}
                    style={{ flex: "1 1 200px", maxWidth: 280 }}
                    aria-label={`Role ${i + 1} Voice IP`}
                    options={config.actors.map((a) => ({
                      value: a.character_id,
                      label: actorLabel(a),
                      disabled: taken.has(a.character_id),
                    }))}
                  />
                  <PlayButton
                    url={cached}
                    resolve={actor ? async () => (await api.characterPreview(actor.character_id, engine.provider)).preview.url : undefined}
                    label={actor ? `Preview ${actor.display_name} on ${provider?.label ?? engine.provider}` : "Pick a Voice IP to preview"}
                  />
                  <Tooltip title="Remove role">
                    <Button type="text" icon={<DeleteOutlined />} aria-label={`Remove role ${i + 1}`} onClick={() => setRoles((rs) => rs.filter((x) => x.key !== r.key))} disabled={roles.length <= 1} />
                  </Tooltip>
                </Flex>
                <Input.TextArea
                  value={r.description} onChange={(e) => updateRole(r.key, { description: e.target.value })}
                  autoSize={{ minRows: 1, maxRows: 4 }} placeholder="Mô tả: tính cách, động cơ, quan hệ" style={{ marginTop: 8 }} aria-label={`Role ${i + 1} description`}
                />
              </Card>
            );
          })}
          <Button icon={<PlusOutlined />} onClick={() => setRoles((rs) => [...rs, { key: Date.now(), name: "", description: "", actor_id: "" }])} style={{ alignSelf: "flex-start" }}>Add role</Button>
        </Flex>
      </Form.Item>
      <Form.Item label="Roles as pasted text (optional)" extra="If your notes already list the characters, paste them here; the Script Writer merges them with the rows above.">
        <Input.TextArea rows={3} value={rolesText} onChange={(e) => setRolesText(e.target.value)} />
      </Form.Item>
      <Form.Item
        label="Script" required
        extra={
          <Flex justify="space-between" wrap gap={8} style={{ marginTop: 4 }}>
            <span className="num">{words.toLocaleString()} words · segment threshold {segmentThreshold.toLocaleString()}</span>
            {words > 0 && (
              <Tag color={segmentMode ? "success" : "processing"} style={{ marginInlineEnd: 0 }}>
                {segmentMode ? "Segment mode: your dialogue is kept verbatim" : "Write mode: the treatment is expanded into episodes"}
              </Tag>
            )}
          </Flex>
        }
      >
        <Input.TextArea rows={14} value={script} onChange={(e) => setScript(e.target.value)} className="mono" placeholder="Dán kịch bản hoặc dàn ý ở đây…" />
      </Form.Item>
    </Form>
  );

  const enginesStep = (
    <Form layout="vertical">
      <Typography.Title level={5}>Voice engine</Typography.Title>
      <Form.Item label="TTS engine">
        <EnginePicker config={config} value={engine} onChange={setEngine} />
      </Form.Item>
      <Form.Item label="Per role type (optional)" extra="Give leads a different engine, e.g. ElevenLabs for the protagonist and Gemini for the rest.">
        <Flex gap={12} wrap>
          {(["protagonist", "antagonist"] as RoleType[]).map((rt) => (
            <Space key={rt} orientation="vertical" size={2}>
              <span className="muted" style={{ fontSize: 12, textTransform: "capitalize" }}>{rt}</span>
              <Select
                allowClear placeholder="Same as default" style={{ width: 200 }} value={overrides[rt]}
                onChange={(v) => setOverrides((o) => ({ ...o, [rt]: v }))} options={providerOptions} aria-label={`${rt} engine`}
              />
              {overrides[rt] && !providerHasKey(config, overrides[rt]!) && <Typography.Text type="warning" style={{ fontSize: 12 }}>Key missing</Typography.Text>}
            </Space>
          ))}
        </Flex>
      </Form.Item>
      <Divider />
      <Typography.Title level={5}>Language model</Typography.Title>
      <Row gutter={16}>
        <Col xs={24} sm={10}>
          <Form.Item label="LLM provider">
            <Select value={llmProvider} onChange={setLlmProvider} options={config.llm.providers.map((p) => ({ value: p, label: p }))} />
            {llmProvider !== "mock" && config.keys[llmProvider as keyof Config["keys"]] === false && <Typography.Text type="warning" style={{ fontSize: 12 }}>Key missing for {llmProvider}</Typography.Text>}
          </Form.Item>
        </Col>
        <Col xs={24} sm={14}>
          <Form.Item label="Model"><Input value={llmModel} onChange={(e) => setLlmModel(e.target.value)} placeholder={llmProvider === config.llm.provider ? config.llm.model : "Provider default"} /></Form.Item>
        </Col>
      </Row>
      <Divider />
      <Typography.Title level={5}>Production</Typography.Title>
      <Row gutter={16}>
        <Col xs={12} md={6}><Form.Item label="Episodes"><InputNumber min={1} max={200} value={episodes} onChange={(v) => setEpisodes(v ?? 1)} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={12} md={6}><Form.Item label="Produce now" tooltip="How many episodes this run renders; the rest can be continued later."><InputNumber min={1} max={episodes} value={produce} onChange={(v) => setProduce(v)} placeholder="All" style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={12} md={6}><Form.Item label="Min seconds"><InputNumber min={10} max={600} value={minSec} onChange={(v) => setMinSec(v ?? minSec)} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={12} md={6}><Form.Item label="Max seconds"><InputNumber min={10} max={600} value={maxSec} onChange={(v) => setMaxSec(v ?? maxSec)} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={24} md={8}>
          <Form.Item label="Tier" tooltip="Test renders cheap; final uses the full-quality settings.">
            <Segmented value={tier} onChange={(v) => setTier(v as "test" | "final")} options={[{ value: "test", label: "Test" }, { value: "final", label: "Final" }]} />
          </Form.Item>
        </Col>
        <Col xs={12} md={4}><Form.Item label="QA max retries"><InputNumber min={0} max={5} value={maxRetries} onChange={(v) => setMaxRetries(v ?? 0)} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={12} md={6}><Form.Item label="Auto-approve PASS" tooltip="Episodes that pass QA skip the human gate."><Switch checked={autoApprove} onChange={setAutoApprove} /></Form.Item></Col>
        <Col xs={12} md={6}><Form.Item label="Halt on QA fail" tooltip="Stop the run when an episode is still FLAGGED after its retries."><Switch checked={haltOnFail} onChange={setHaltOnFail} /></Form.Item></Col>
        <Col xs={24} md={12}>
          <Form.Item label="Series id" extra={editId ? "Locked while editing." : "Optional; derived from the title when empty. Lowercase, digits, hyphens."}>
            <Input value={seriesId} onChange={(e) => setSeriesId(e.target.value.toLowerCase())} disabled={!!editId} placeholder="tong-tai-bi-mat" className="mono" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Overwrite">
            <Checkbox checked={force} onChange={(e) => setForce(e.target.checked)}>Overwrite existing drafts for this series id</Checkbox>
            {editId && <div className="muted" style={{ fontSize: 12 }}>Stems whose text did not change are reused.</div>}
          </Form.Item>
        </Col>
      </Row>
    </Form>
  );

  const reviewStep = (
    <Flex vertical gap={16}>
      <Descriptions
        size="small"
        bordered
        column={{ xs: 1, md: 2 }}
        items={[
          { key: "src", label: "Source", children: source === "brief" ? `Trend brief: ${brief?.topic ?? briefId}` : source === "research" ? `Research now (${platforms.join(", ") || "seed notes only"})` : `Own story: ${title}` },
          { key: "sid", label: "Series id", children: <span className="mono">{seriesId || "auto"}</span> },
          ...(source === "story" ? [
            { key: "roles", label: "Roles", children: roles.filter((r) => r.name.trim()).map((r) => `${r.name}${r.actor_id ? ` → ${actorsById[r.actor_id]?.display_name ?? r.actor_id}` : ""}`).join(", ") || "from pasted text" },
            { key: "words", label: "Script", children: <span className="num">{words.toLocaleString()} words · {segmentMode ? "segment" : "write"} mode</span> },
          ] : []),
          { key: "tts", label: "TTS", children: `${provider?.label ?? engine.provider} · ${engine.model ?? provider?.default_model ?? "default"}${provider?.scene_batching ? ` · ${engine.batching}` : ""}` },
          { key: "ovr", label: "Role overrides", children: Object.entries(overrides).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(", ") || "none" },
          { key: "llm", label: "LLM", children: `${llmProvider} · ${llmModel || (llmProvider === config.llm.provider ? config.llm.model : "default")}` },
          { key: "fmt", label: "Format", children: <span className="num">{episodes} episodes × {minSec}-{maxSec}s, produce {produce ?? "all"} now · {tier}</span> },
          { key: "qa", label: "QA & gate", children: `${maxRetries} retries · ${autoApprove ? "auto-approve PASS" : "human approval"} · ${haltOnFail ? "halt on fail" : "continue on fail"}` },
          { key: "force", label: "Overwrite", children: force ? "yes" : "no" },
        ]}
      />
      <Alert
        type={engine.provider === "gemini" && estTts > 10 ? "warning" : "info"}
        showIcon
        title={<span className="num">Estimated ≈ {estLlm} LLM calls and ≈ {estTts} TTS requests</span>}
        description={
          engine.provider === "gemini" && estTts > 10
            ? "Gemini TTS without billing allows about 10 requests per model per day; this run may stop on the daily quota."
            : "A rough estimate; actual numbers depend on scene count and QA retries."
        }
      />
      {!providerHasKey(config, engine.provider) && <Alert type="error" showIcon title={`${provider?.label} key is missing`} description={`Set ${provider?.key_env} in .env before starting.`} />}
    </Flex>
  );

  const bodies: Record<StepKey, React.ReactNode> = { source: sourceStep, story: storyStep, engines: enginesStep, review: reviewStep };
  const titles: Record<StepKey, string> = { source: "Source", story: "Story", engines: "Engines & production", review: "Review & start" };

  if (editId && existing.loading && !existing.data) return <Loading rows={10} />;

  return (
    <>
      <PageHead
        title={editId ? `Edit & re-run: ${existing.data?.title ?? editId}` : "New production"}
        sub={editId ? "Saving re-runs the outline and casting for this series and overwrites its drafts." : "Start from a trend, your own story, or a fresh market scan."}
      />
      <ErrorAlert error={existing.error} onRetry={existing.refresh} title="Could not load the production to edit" />
      <Card>
        <Steps
          current={step}
          size="small"
          onChange={(i) => { if (i < step) { setErr(null); setStep(i); } }}
          items={stepKeys.map((k) => ({ title: titles[k] }))}
          style={{ marginBottom: 24 }}
        />
        {bodies[current]}
        {err && <Alert type="error" showIcon title={err} style={{ marginTop: 16 }} />}
        <Flex justify="space-between" style={{ marginTop: 24 }}>
          <Button onClick={back} disabled={step === 0}>Back</Button>
          {current === "review"
            ? <Button type="primary" icon={<RocketOutlined />} loading={busy} onClick={submit}>Start production</Button>
            : <Button type="primary" onClick={next}>Next</Button>}
        </Flex>
      </Card>
    </>
  );
}

function NewProduction() {
  const { config, configError, refreshConfig } = useStudio();
  if (!config) return configError ? <ErrorAlert error={configError} onRetry={refreshConfig} /> : <Loading rows={10} />;
  return <Wizard config={config} />;
}

export default function NewProductionPage() {
  return <Suspense fallback={<Loading rows={10} />}><NewProduction /></Suspense>;
}
