"use client";

import { DeleteOutlined, FileTextOutlined, RadarChartOutlined, RocketOutlined } from "@ant-design/icons";
import {
  Alert, App, Button, Card, Checkbox, Col, Descriptions, Flex, Form, Input, Popconfirm, Progress, Row, Select, Space, Switch, Table, Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorAlert, Loading, Meter, Num, PageHead } from "@/components/common";
import { ThemeTag } from "@/components/ProductionCard";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type ContentInsight, type TrendBrief, type TrendCandidate } from "@/lib/api";
import { PLATFORMS } from "@/lib/constants";
import { fmtAgo, fmtTime } from "@/lib/format";
import { useNow, usePoll } from "@/lib/hooks";

/** Scores may be 0-1, 0-10 or 0-100 depending on the agent prompt; pick a sensible scale. */
const scaleOf = (v: number) => (v <= 1 ? 1 : v <= 10 ? 10 : 100);
const fmtScore = (v: number) => (v <= 1 ? v.toFixed(2) : v.toFixed(v < 10 ? 1 : 0));

function ScanForm({ onScanned }: { onScanned: (b: TrendBrief) => void }) {
  const { config } = useStudio();
  const { message } = App.useApp();
  const [seeds, setSeeds] = useState("");
  const [platforms, setPlatforms] = useState<string[]>(["dramabox", "reelshort", "tiktok"]);
  const [useBrowser, setUseBrowser] = useState<boolean>(config?.defaults.research_use_browser ?? false);
  const [focus, setFocus] = useState<string>("");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const now = useNow(startedAt ? 500 : 60000);
  const elapsed = startedAt ? (now - startedAt) / 1000 : 0;

  const scan = async () => {
    if (!seeds.trim() && !platforms.length) { setErr("Add seed notes or pick at least one platform."); return; }
    setErr(null); setStartedAt(Date.now());
    try {
      const b = await api.scan({ seeds, platforms, use_browser: useBrowser, focus });
      message.success(`New brief: ${b.topic}`);
      onScanned(b);
    } catch (e) { setErr((e as Error).message); }
    finally { setStartedAt(null); }
  };

  return (
    <Card title={<Space><RadarChartOutlined />Scan the market</Space>} size="small">
      <Form layout="vertical" disabled={!!startedAt}>
        <Form.Item label="Seed notes" extra="Trend notes, titles, comments you collected. Optional when platforms are scanned.">
          <Input.TextArea rows={5} value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder="Ví dụ: top DramaBox tuần này: tổng tài, trọng sinh…" />
        </Form.Item>
        <Form.Item label="Platforms">
          <Checkbox.Group options={PLATFORMS} value={platforms} onChange={(v) => setPlatforms(v as string[])} />
        </Form.Item>
        <Form.Item label="Use a browser" extra="Reads live platform pages. Needs Playwright on the engine host (playwright install chromium).">
          <Switch checked={useBrowser} onChange={setUseBrowser} />
        </Form.Item>
        <Form.Item label="Focus">
          <Select allowClear placeholder="Any theme" value={focus || undefined} onChange={(v) => setFocus(v ?? "")} options={(config?.theme_categories ?? []).map((t) => ({ value: t.id, label: t.label }))} />
        </Form.Item>
      </Form>
      {startedAt ? (
        <div>
          <Progress percent={Math.min(95, Math.round((elapsed / 30) * 100))} status="active" showInfo={false} />
          <Typography.Text type="secondary" className="num">Researching… {elapsed.toFixed(0)} s (usually about 30 s)</Typography.Text>
        </div>
      ) : (
        <Button type="primary" icon={<RadarChartOutlined />} onClick={scan} block>Run research</Button>
      )}
      {err && <Alert type="error" showIcon title="Scan failed" description={err} style={{ marginTop: 12 }} />}
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

function BriefDetail({ b, onDeleted }: { b: TrendBrief; onDeleted: () => void }) {
  const router = useRouter();
  const { message } = App.useApp();
  const del = async () => {
    try { await api.deleteBrief(b.brief_id); message.success("Brief deleted"); onDeleted(); }
    catch (e) { message.error((e as Error).message); }
  };
  const ranked = [...b.candidates].sort((x, y) => y.score - x.score);
  return (
    <Card
      size="small"
      title={<span style={{ whiteSpace: "normal" }}>{b.topic}</span>}
      extra={
        <Space>
          <Button type="primary" icon={<RocketOutlined />} onClick={() => router.push(`/new/?brief=${encodeURIComponent(b.brief_id)}`)}>Produce this brief</Button>
          <Popconfirm title="Delete this brief?" okText="Delete" okButtonProps={{ danger: true }} onConfirm={del}>
            <Button danger icon={<DeleteOutlined />} aria-label="Delete brief" />
          </Popconfirm>
        </Space>
      }
    >
      <Flex vertical gap={16}>
        <Space wrap size={6}>
          <ThemeTag theme={b.theme_category} />
          <Tag><Num>score {fmtScore(b.score)}</Num></Tag>
          {b.platforms.map((p) => <Tag key={p}>{p}</Tag>)}
          <span className="muted" style={{ fontSize: 12 }}>{fmtTime(b.created_at)}</span>
        </Space>
        <Descriptions
          size="small"
          bordered
          column={1}
          items={[
            { key: "a", label: "Audience", children: b.target_audience },
            { key: "h", label: "Hook", children: b.hook },
            { key: "p", label: "Premise", children: b.premise },
            { key: "x", label: "Anti-trope angle", children: b.anti_trope_angle },
            { key: "f", label: "Format", children: <Num>{b.format_spec.episodes} × {b.format_spec.episode_seconds_min}-{b.format_spec.episode_seconds_max}s · {b.format_spec.medium} · {b.format_spec.language}</Num> },
            ...(b.reference_titles.length ? [{ key: "r", label: "References", children: <Flex gap={4} wrap>{b.reference_titles.map((t) => <Tag key={t} style={{ marginInlineEnd: 0 }}>{t}</Tag>)}</Flex> }] : []),
            ...(b.notes ? [{ key: "n", label: "Notes", children: b.notes }] : []),
          ]}
        />
        <div>
          <Typography.Title level={5}>Ranked candidates</Typography.Title>
          <Table<TrendCandidate>
            size="small"
            rowKey="topic"
            pagination={false}
            dataSource={ranked}
            scroll={{ x: 860 }}
            expandable={{ expandedRowRender: (c) => <div style={{ fontSize: 13 }}><div><b>Hook:</b> {c.hook}</div><div><b>Premise:</b> {c.premise}</div><div><b>Anti-trope:</b> {c.anti_trope_angle}</div><div className="muted">{c.rationale}</div></div> }}
            columns={[
              { title: "#", key: "i", width: 40, render: (_, __, i) => <Num>{i + 1}</Num> },
              { title: "Topic", dataIndex: "topic", render: (v: string, c) => <div>{v}<div className="muted" style={{ fontSize: 12 }}>{c.target_audience}</div></div> },
              { title: "Theme", dataIndex: "theme_category", width: 170, render: (t: string) => <ThemeTag theme={t} /> },
              { title: "Audience fit", dataIndex: "audience_fit", width: 130, render: (v: number) => <Meter value={v} max={scaleOf(v)} label={fmtScore(v)} /> },
              { title: "Momentum", dataIndex: "momentum", width: 130, render: (v: number) => <Meter value={v} max={scaleOf(v)} label={fmtScore(v)} /> },
              { title: "Production fit", dataIndex: "production_fit", width: 130, render: (v: number) => <Meter value={v} max={scaleOf(v)} label={fmtScore(v)} /> },
              { title: "Score", dataIndex: "score", width: 80, align: "right", render: (v: number) => <Typography.Text strong className="num">{fmtScore(v)}</Typography.Text> },
            ]}
          />
        </div>
        {b.insights.length > 0 && (
          <div>
            <Typography.Title level={5}>Insights</Typography.Title>
            <Table<ContentInsight>
              size="small"
              rowKey={(r) => `${r.platform}-${r.title}`}
              pagination={false}
              dataSource={b.insights}
              scroll={{ x: 760 }}
              columns={[
                { title: "Title", dataIndex: "title" },
                { title: "Platform", dataIndex: "platform", width: 100, render: (v: string) => <Tag>{v}</Tag> },
                { title: "Genre", dataIndex: "genre", width: 120 },
                { title: "Hook", dataIndex: "hook" },
                { title: "Pacing", dataIndex: "pacing", width: 120 },
                { title: "Tropes", dataIndex: "tropes", render: (t: string[]) => <Flex gap={2} wrap>{t.map((x) => <Tag key={x} style={{ marginInlineEnd: 0 }}>{x}</Tag>)}</Flex> },
              ]}
            />
          </div>
        )}
        {b.sources.length > 0 && (
          <div>
            <Typography.Title level={5}>Sources</Typography.Title>
            <Flex vertical gap={2}>
              {b.sources.map((s) => /^https?:\/\//.test(s)
                ? <a key={s} href={s} target="_blank" rel="noreferrer" style={{ fontSize: 12, wordBreak: "break-all" }}>{s}</a>
                : <span key={s} className="muted" style={{ fontSize: 12 }}>{s}</span>)}
            </Flex>
          </div>
        )}
      </Flex>
    </Card>
  );
}

function Research() {
  const params = useSearchParams();
  const router = useRouter();
  const { data, error, loading, refresh } = usePoll(() => api.briefs(), 0);
  const [selected, setSelected] = useState<string | null>(params.get("id"));
  const briefs = useMemo(() => [...(data?.briefs ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)), [data]);
  useEffect(() => { if (!selected && briefs.length) setSelected(briefs[0].brief_id); }, [briefs, selected]);
  const brief = briefs.find((b) => b.brief_id === selected) ?? null;
  const select = (id: string) => { setSelected(id); router.replace(`/research/?id=${encodeURIComponent(id)}`, { scroll: false }); };

  return (
    <>
      <PageHead title="Market research" sub="The Market Research agent turns platform trends into scored TrendBriefs you can produce." />
      <ErrorAlert error={error} onRetry={refresh} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9} xl={8}>
          <Flex vertical gap={16}>
            <ScanForm onScanned={(b) => { refresh(); select(b.brief_id); }} />
            <SeedFiles />
          </Flex>
        </Col>
        <Col xs={24} lg={15} xl={16}>
          <Flex vertical gap={16}>
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
                      <Flex justify="space-between" gap={8} align="center">
                        <Typography.Text strong ellipsis style={{ minWidth: 0 }}>{b.topic}</Typography.Text>
                        <Space size={6}>
                          <ThemeTag theme={b.theme_category} />
                          <Tag style={{ marginInlineEnd: 0 }}><Num>{fmtScore(b.score)}</Num></Tag>
                        </Space>
                      </Flex>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{fmtAgo(b.created_at)} · {b.candidates.length} candidates</Typography.Text>
                    </div>
                  ))}
                </Flex>
              ) : <EmptyState description="No briefs yet. Run a scan to get the first one." />}
            </Card>
            {brief ? <BriefDetail key={brief.brief_id} b={brief} onDeleted={() => { setSelected(null); router.replace("/research/"); refresh(); }} />
              : briefs.length > 0 && selected ? <Card><EmptyState description="This brief no longer exists" action={<Link href="/research/">Show all</Link>} /></Card> : null}
          </Flex>
        </Col>
      </Row>
    </>
  );
}

export default function ResearchPage() {
  return <Suspense fallback={<Loading rows={10} />}><Research /></Suspense>;
}
