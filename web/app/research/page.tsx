"use client";

import {
  CheckCircleFilled, CloseCircleFilled, DeleteOutlined, FileTextOutlined, LoadingOutlined, MinusCircleOutlined, RadarChartOutlined, RocketOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  Alert, App, Button, Card, Checkbox, Col, Collapse, Descriptions, Flex, Form, Image, Input, Popconfirm, Row, Select, Space, Steps, Switch, Table, Tag,
  Tooltip, Typography,
} from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorAlert, Loading, Meter, Num, PageHead } from "@/components/common";
import { ThemeTag } from "@/components/ProductionCard";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type ContentInsight, type ScanState, type ScanStep, type TrendBrief, type TrendCandidate } from "@/lib/api";
import { PLATFORM_LABEL, PLATFORMS } from "@/lib/constants";
import { fmtAgo, fmtDuration, fmtTime } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

/** Scores may be 0-1, 0-10 or 0-100 depending on the agent prompt; pick a sensible scale. */
const scaleOf = (v: number) => (v <= 1 ? 1 : v <= 10 ? 10 : 100);
const fmtScore = (v: number) => (v <= 1 ? v.toFixed(2) : v.toFixed(v < 10 ? 1 : 0));
const platformName = (p: string) => PLATFORM_LABEL[p] ?? p;
const DEFAULT_GUIDE = "Scan the platforms and document the 3 most trending short drama film genres.";

function ScanForm({ running, onStarted }: { running: boolean; onStarted: (s: ScanState) => void }) {
  const { config } = useStudio();
  const [guide, setGuide] = useState(DEFAULT_GUIDE);
  const [seeds, setSeeds] = useState("");
  const [platforms, setPlatforms] = useState<string[]>(PLATFORMS.map((p) => p.value));
  const [useBrowser, setUseBrowser] = useState<boolean>(true);
  const [focus, setFocus] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const scan = async () => {
    if (!seeds.trim() && !(useBrowser && platforms.length)) { setErr("Add seed notes, or turn on the browser and pick at least one platform."); return; }
    setErr(null); setBusy(true);
    try { onStarted(await api.scan({ seeds, platforms, use_browser: useBrowser, focus, guide })); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <Card title={<Space><RadarChartOutlined />Scan the market</Space>} size="small">
      <Form layout="vertical" disabled={running || busy}>
        <Form.Item label="Research guide" extra="What the agent should look for. It always documents the three most trending genres.">
          <Input.TextArea rows={3} value={guide} onChange={(e) => setGuide(e.target.value)} />
        </Form.Item>
        <Form.Item label="Platforms" extra={useBrowser ? "Public pages are read as an anonymous visitor; a site that shows a robot check is reported as blocked." : "Turn on the browser to read these."}>
          <Checkbox.Group options={PLATFORMS} value={platforms} onChange={(v) => setPlatforms(v as string[])} disabled={!useBrowser} />
        </Form.Item>
        <Form.Item label="Use a browser" extra="Reads live platform pages with a headless browser on the engine host.">
          <Switch checked={useBrowser} onChange={setUseBrowser} />
        </Form.Item>
        <Form.Item label="Seed notes" extra="Optional: trend notes, titles or comments your team collected.">
          <Input.TextArea rows={3} value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder="Ví dụ: top DramaBox tuần này: tổng tài, trọng sinh…" />
        </Form.Item>
        <Form.Item label="Focus" extra="Optional: rank one Mặc Khải content line first.">
          <Select allowClear placeholder="Any theme" value={focus || undefined} onChange={(v) => setFocus(v ?? "")} options={(config?.theme_categories ?? []).map((t) => ({ value: t.id, label: t.label }))} />
        </Form.Item>
      </Form>
      <Button type="primary" icon={<RadarChartOutlined />} onClick={scan} loading={running || busy} block>{running ? "Scanning…" : "Run research"}</Button>
      {err && <Alert type="error" showIcon title="Could not start the scan" description={err} style={{ marginTop: 12 }} />}
    </Card>
  );
}

function SeedFiles() {
  const { data, error, loading } = usePoll(() => api.seeds(), 0);
  return (
    <Card title={<Space><FileTextOutlined />Local seed files</Space>} size="small">
      {loading && !data ? <Loading card={false} rows={2} /> : error ? <Typography.Text type="secondary">{error}</Typography.Text> : data?.seeds.length ? (
        <Flex vertical gap={4}>
          {data.seeds.map((s) => (
            <Flex key={s.name} justify="space-between" gap={8}>
              <span className="mono" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>{s.name}</span>
              <span className="num muted" style={{ fontSize: 12 }}>{s.chars.toLocaleString()} chars</span>
            </Flex>
          ))}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>Every scan reads these files as extra seed notes.</Typography.Text>
        </Flex>
      ) : <Typography.Text type="secondary" style={{ fontSize: 12 }}>No seed files. Drop .txt/.md notes into the engine&apos;s research seeds folder to include them in every scan.</Typography.Text>}
    </Card>
  );
}

const STEP_TAG: Record<ScanStep["status"], { color: string; text: string; icon: React.ReactNode }> = {
  pending: { color: "default", text: "Waiting", icon: <MinusCircleOutlined /> },
  running: { color: "processing", text: "Reading", icon: <LoadingOutlined spin /> },
  ok: { color: "success", text: "Read", icon: <CheckCircleFilled /> },
  blocked: { color: "warning", text: "Blocked", icon: <StopOutlined /> },
  error: { color: "error", text: "Failed", icon: <CloseCircleFilled /> },
};

function SourceRow({ scanId, s }: { scanId: string; s: ScanStep }) {
  const t = STEP_TAG[s.status];
  return (
    <Flex gap={12} align="flex-start" className="ev-issue" style={{ borderBottom: "1px solid var(--ev-border)", borderRadius: 0, padding: "10px 4px" }}>
      <div style={{ width: 112, flex: "none" }}>
        {s.screenshot ? (
          <Image src={api.scanShotUrl(scanId, s.screenshot)} alt={`${platformName(s.platform)} page as the agent saw it`} width={112} height={78}
            style={{ objectFit: "cover", objectPosition: "top", borderRadius: 6, border: "1px solid var(--ev-border)" }} />
        ) : (
          <Flex align="center" justify="center" style={{ width: 112, height: 78, borderRadius: 6, background: "var(--ev-sunken)", border: "1px solid var(--ev-border)" }}>
            <span className="muted" style={{ fontSize: 11 }}>{s.platform === "local" ? "notes" : s.status === "running" ? "loading…" : "no image"}</span>
          </Flex>
        )}
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <Flex gap={8} wrap align="center">
          <Typography.Text strong>{platformName(s.platform)}</Typography.Text>
          <Tag color={t.color} icon={t.icon} style={{ marginInlineEnd: 0 }}>{t.text}</Tag>
          {s.status === "ok" && <span className="num muted" style={{ fontSize: 12 }}>{s.chars.toLocaleString()} characters</span>}
          {s.elapsed_s > 0 && <span className="num muted" style={{ fontSize: 12 }}>{s.elapsed_s.toFixed(1)} s</span>}
        </Flex>
        <div style={{ fontSize: 12, wordBreak: "break-all" }}>
          {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.label || s.url}</a> : <span className="muted">{s.label}</span>}
        </div>
        {s.detail && <Typography.Text type={s.status === "error" ? "danger" : "warning"} style={{ fontSize: 12 }}>{s.detail}</Typography.Text>}
        {s.status === "ok" && s.excerpt && (
          <Typography.Paragraph type="secondary" ellipsis={{ rows: 2, expandable: "collapsible" }} style={{ fontSize: 12, margin: "4px 0 0", whiteSpace: "pre-line" }}>
            {s.excerpt}
          </Typography.Paragraph>
        )}
      </div>
    </Flex>
  );
}

const PHASES = ["scan", "analyze", "rank"] as const;

function ScanProgress({ scan }: { scan: ScanState }) {
  const running = scan.status === "running";
  const failed = scan.status === "failed";
  const current = scan.status === "done" ? 3 : PHASES.indexOf(scan.phase as (typeof PHASES)[number]);
  const read = scan.steps.filter((s) => s.status === "ok").length;
  const blocked = scan.steps.filter((s) => s.status === "blocked" || s.status === "error");
  const stepStatus = (i: number) => (i < current ? "finish" : i > current ? "wait" : failed ? "error" : "process") as "finish" | "wait" | "error" | "process";
  return (
    <Card
      size="small"
      title={<Space><RadarChartOutlined />{running ? "Scanning now" : "Scan record"}<span className="mono muted" style={{ fontSize: 12, fontWeight: 400 }}>{scan.scan_id}</span></Space>}
      extra={<span className="muted num" style={{ fontSize: 12 }}>{running ? `started ${fmtAgo(scan.created_at)}` : `${fmtTime(scan.created_at)} · ${fmtDuration(scan.created_at, scan.finished_at)}`}</span>}
    >
      <Flex vertical gap={12}>
        <Steps
          size="small"
          current={Math.max(0, current)}
          items={[
            { title: "Market Scan", description: `${read} of ${scan.steps.length} sources read`, status: stepStatus(0), icon: running && current === 0 ? <LoadingOutlined /> : undefined },
            { title: "Content Analyze", description: "LLM reads the collected text", status: stepStatus(1), icon: running && current === 1 ? <LoadingOutlined /> : undefined },
            { title: "Trend Ranking", description: "Top 3 genres scored", status: stepStatus(2), icon: running && current === 2 ? <LoadingOutlined /> : undefined },
          ]}
        />
        {scan.guide && <Typography.Text type="secondary" style={{ fontSize: 12 }}><b>Guide:</b> {scan.guide}</Typography.Text>}
        {failed && <Alert type="error" showIcon title="The scan failed" description={scan.error} />}
        {!running && !failed && blocked.length > 0 && (
          <Alert type="warning" showIcon title={`${blocked.length} source${blocked.length > 1 ? "s were" : " was"} not readable`}
            description={`${Array.from(new Set(blocked.map((b) => platformName(b.platform)))).join(", ")} answered with a robot check or an error page. The genres below are based on the other sources only.`} />
        )}
        <div>
          {scan.steps.length ? scan.steps.map((s, i) => <SourceRow key={`${s.platform}-${i}`} scanId={scan.scan_id} s={s} />)
            : <Typography.Text type="secondary">Preparing the browser…</Typography.Text>}
        </div>
        <Collapse
          size="small"
          ghost
          defaultActiveKey={running ? ["log"] : []}
          items={[{ key: "log", label: `Agent log (${scan.log.length})`, children: (
            <pre className="mono" style={{ fontSize: 11.5, margin: 0, maxHeight: 220, overflow: "auto", whiteSpace: "pre-wrap" }}>{scan.log.join("\n") || "…"}</pre>
          ) }]}
        />
      </Flex>
    </Card>
  );
}

function GenreCard({ c, rank, selected, picking, onPick }: { c: TrendCandidate; rank: number; selected: boolean; picking: boolean; onPick: () => void }) {
  return (
    <Card
      size="small"
      style={{ height: "100%", borderColor: selected ? "var(--ev-navy)" : undefined, boxShadow: selected ? "inset 0 3px 0 var(--ev-navy)" : undefined }}
      styles={{ body: { display: "flex", flexDirection: "column", gap: 10, height: "100%" } }}
    >
      <Flex justify="space-between" align="flex-start" gap={8}>
        <div style={{ minWidth: 0 }}>
          <Typography.Text type="secondary" className="num" style={{ fontSize: 12 }}>#{rank} trending genre</Typography.Text>
          <Typography.Title level={5} style={{ margin: 0 }}>{c.genre || c.topic}</Typography.Title>
        </div>
        <Tooltip title="Weighted score: 45% audience fit, 30% momentum, 25% production fit">
          <Tag color={selected ? "blue" : undefined} style={{ marginInlineEnd: 0 }}><Num>{fmtScore(c.score)}</Num></Tag>
        </Tooltip>
      </Flex>
      <Flex gap={4} wrap>
        <ThemeTag theme={c.theme_category} />
        {c.platforms.filter((p) => p !== "local").map((p) => <Tag key={p} style={{ marginInlineEnd: 0 }}>{platformName(p)}</Tag>)}
      </Flex>
      {c.evidence && <div style={{ fontSize: 13 }}><Typography.Text type="secondary" style={{ fontSize: 12 }}>Why it is trending</Typography.Text><div>{c.evidence}</div></div>}
      <div style={{ fontSize: 13 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>Proposed story</Typography.Text>
        <div><b>{c.topic}</b></div>
        <div>{c.hook}</div>
      </div>
      <Flex vertical gap={2}>
        <Meter value={c.audience_fit} max={scaleOf(c.audience_fit)} label={`Audience fit ${fmtScore(c.audience_fit)}`} />
        <Meter value={c.momentum} max={scaleOf(c.momentum)} label={`Momentum ${fmtScore(c.momentum)}`} />
        <Meter value={c.production_fit} max={scaleOf(c.production_fit)} label={`Production fit ${fmtScore(c.production_fit)}`} />
      </Flex>
      <Collapse size="small" ghost items={[{ key: "d", label: "Premise and angle", children: (
        <div style={{ fontSize: 13 }}>
          <div><b>Audience:</b> {c.target_audience}</div>
          <div><b>Premise:</b> {c.premise}</div>
          <div><b>Anti-trope angle:</b> {c.anti_trope_angle}</div>
          {c.reference_titles.length > 0 && <div><b>Seen in:</b> {c.reference_titles.join(" · ")}</div>}
          {c.rationale && <div className="muted">{c.rationale}</div>}
        </div>
      ) }]} />
      <Button type={selected ? "primary" : "default"} icon={<RocketOutlined />} onClick={onPick} loading={picking} block style={{ marginTop: "auto" }}>
        {selected ? "Produce this genre" : "Pick and produce"}
      </Button>
    </Card>
  );
}

function BriefDetail({ b, onDeleted, onChanged, record }: { b: TrendBrief; onDeleted: () => void; onChanged: () => void; record?: React.ReactNode }) {
  const router = useRouter();
  const { message } = App.useApp();
  const [picking, setPicking] = useState<number | null>(null);
  const del = async () => {
    try { await api.deleteBrief(b.brief_id); message.success("Brief deleted"); onDeleted(); }
    catch (e) { message.error((e as Error).message); }
  };
  // The pick is saved on the brief, then New production opens with it: the Script Writer receives the chosen genre.
  const pick = async (index: number) => {
    setPicking(index);
    try {
      if (index !== b.selected) { await api.selectGenre(b.brief_id, index); onChanged(); }
      router.push(`/new/?brief=${encodeURIComponent(b.brief_id)}`);
    } catch (e) { message.error((e as Error).message); setPicking(null); }
  };
  return (
    <Card
      size="small"
      title={<span style={{ whiteSpace: "normal" }}>Pick one of the {b.candidates.length} trending genres</span>}
      extra={
        <Popconfirm title="Delete this brief?" okText="Delete" okButtonProps={{ danger: true }} onConfirm={del}>
          <Button danger icon={<DeleteOutlined />} aria-label="Delete brief" />
        </Popconfirm>
      }
    >
      <Flex vertical gap={16}>
        <Space wrap size={6}>
          {b.platforms.map((p) => <Tag key={p}>{platformName(p)}</Tag>)}
          <span className="muted" style={{ fontSize: 12 }}>{fmtTime(b.created_at)} · the pick goes to the Script Writer agent</span>
        </Space>
        <Row gutter={[12, 12]}>
          {b.candidates.map((c, i) => (
            <Col key={`${c.genre}-${c.topic}`} xs={24} xl={8}>
              <GenreCard c={c} rank={i + 1} selected={i === b.selected} picking={picking === i} onPick={() => pick(i)} />
            </Col>
          ))}
        </Row>
        <Descriptions
          size="small"
          bordered
          column={1}
          items={[
            { key: "s", label: "Selected", children: <span><b>{b.genre || b.topic}</b>: {b.topic}</span> },
            { key: "f", label: "Format", children: <Num>{b.format_spec.episodes} × {b.format_spec.episode_seconds_min}-{b.format_spec.episode_seconds_max}s · {b.format_spec.medium} · {b.format_spec.language}</Num> },
            ...(b.guide ? [{ key: "g", label: "Guide", children: b.guide }] : []),
            ...(b.notes ? [{ key: "n", label: "Focus", children: b.notes }] : []),
          ]}
        />
        {record}
        {b.insights.length > 0 && (
          <div>
            <Typography.Title level={5}>Titles the agent analysed</Typography.Title>
            <Table<ContentInsight>
              size="small"
              rowKey={(r) => `${r.platform}-${r.title}`}
              pagination={false}
              dataSource={b.insights}
              scroll={{ x: 760 }}
              columns={[
                { title: "Title", dataIndex: "title" },
                { title: "Platform", dataIndex: "platform", width: 100, render: (v: string) => <Tag>{platformName(v)}</Tag> },
                ...(b.insights.some((r) => r.genre) ? [{ title: "Genre", dataIndex: "genre", width: 140 }] : []),
                { title: "Hook", dataIndex: "hook" },
                { title: "Pacing", dataIndex: "pacing", width: 140 },
                { title: "Tropes", dataIndex: "tropes", render: (t: string[]) => <Flex gap={2} wrap>{t.map((x) => <Tag key={x} style={{ marginInlineEnd: 0 }}>{x}</Tag>)}</Flex> },
              ]}
            />
          </div>
        )}
      </Flex>
    </Card>
  );
}

function Research() {
  const params = useSearchParams();
  const router = useRouter();
  const { message } = App.useApp();
  const { data, error, loading, refresh } = usePoll(() => api.briefs(), 0);
  const [selected, setSelected] = useState<string | null>(params.get("id"));
  const [scanId, setScanId] = useState<string | null>(null);
  const [live, setLive] = useState<ScanState | null>(null);
  const briefs = useMemo(() => [...(data?.briefs ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)), [data]);
  useEffect(() => { if (!selected && briefs.length) setSelected(briefs[0].brief_id); }, [briefs, selected]);
  const brief = briefs.find((b) => b.brief_id === selected) ?? null;
  const select = (id: string) => { setSelected(id); router.replace(`/research/?id=${encodeURIComponent(id)}`, { scroll: false }); };

  // Re-attach to a scan that is still running (page reload, second tab).
  useEffect(() => {
    api.scans().then((r) => { const s = r.scans.find((x) => x.status === "running"); if (s) { setLive(s); setScanId(s.scan_id); } }).catch(() => {});
  }, []);
  // Follow the running scan once a second; when it ends, open its brief.
  const running = live?.status === "running";
  useEffect(() => {
    if (!scanId || !running) return;
    let alive = true;
    const tick = async () => {
      try {
        const s = await api.scanState(scanId);
        if (!alive) return;
        setLive(s);
        if (s.status === "done" && s.brief_id) { message.success("Scan finished: pick one of the three genres"); await refresh(); select(s.brief_id); }
      } catch { /* keep polling */ }
    };
    const id = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanId, running]);
  // The record of the scan behind the selected brief (what the agent read, with screenshots).
  const recordId = !running ? brief?.scan_id ?? null : null;
  const record = usePoll(() => (recordId ? api.scanState(recordId) : Promise.resolve(null)), 0, [recordId]);
  const shown = running || live?.status === "failed" ? live : record.data ?? (live && live.brief_id === brief?.brief_id ? live : null);

  return (
    <>
      <PageHead title="Market research" sub="The Market Research agent reads the platforms, documents the three most trending genres, and you pick the one to produce." />
      <ErrorAlert error={error} onRetry={refresh} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8} xl={7}>
          <Flex vertical gap={16}>
            <ScanForm running={!!running} onStarted={(s) => { setLive(s); setScanId(s.scan_id); }} />
            <Card title={`Briefs (${briefs.length})`} size="small" styles={{ body: { padding: briefs.length ? 8 : undefined } }}>
              {loading && !data ? <Loading card={false} rows={3} /> : briefs.length ? (
                <Flex vertical gap={2} style={{ maxHeight: 280, overflowY: "auto" }}>
                  {briefs.map((b) => (
                    <div
                      key={b.brief_id}
                      role="button"
                      tabIndex={0}
                      onClick={() => select(b.brief_id)}
                      onKeyDown={(e) => { if (e.key === "Enter") select(b.brief_id); }}
                      className="ev-issue seekable"
                      style={{ background: b.brief_id === selected ? "var(--ev-sunken)" : undefined, boxShadow: b.brief_id === selected ? "inset 3px 0 0 var(--ev-navy)" : undefined }}
                    >
                      <Typography.Text strong ellipsis style={{ display: "block" }}>{b.genre || b.topic}</Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{fmtAgo(b.created_at)} · {b.candidates.length} genres · {b.platforms.map(platformName).join(", ")}</Typography.Text>
                    </div>
                  ))}
                </Flex>
              ) : <EmptyState description="No briefs yet. Run a scan to get the first one." />}
            </Card>
            <SeedFiles />
          </Flex>
        </Col>
        <Col xs={24} lg={16} xl={17}>
          <Flex vertical gap={16}>
            {running && live && <ScanProgress scan={live} />}
            {!running && brief && (
              <BriefDetail key={brief.brief_id} b={brief} onChanged={refresh} onDeleted={() => { setSelected(null); router.replace("/research/"); refresh(); }}
                record={shown && shown.brief_id === brief.brief_id ? <ScanProgress scan={shown} /> : undefined} />
            )}
            {!running && shown && shown.brief_id !== brief?.brief_id && <ScanProgress scan={shown} />}
            {!running && !brief && !shown && (briefs.length > 0 && selected
              ? <Card><EmptyState description="This brief no longer exists" action={<Link href="/research/">Show all</Link>} /></Card>
              : <Card><EmptyState description="Run a scan to see the platforms being read here, then pick one of the three trending genres." /></Card>)}
          </Flex>
        </Col>
      </Row>
    </>
  );
}

export default function ResearchPage() {
  return <Suspense fallback={<Loading rows={10} />}><Research /></Suspense>;
}
