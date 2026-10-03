"use client";

import {
  CaretRightOutlined, CheckCircleFilled, DeleteOutlined, EditOutlined, LinkOutlined, MinusCircleOutlined, NodeIndexOutlined,
} from "@ant-design/icons";
import {
  Alert, App, Button, Card, Checkbox, Col, Descriptions, Flex, Form, InputNumber, Modal, Popconfirm, Row, Space, Switch, Table, Tag,
  Tooltip, Typography,
} from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AudioPlayer, EmptyState, ErrorAlert, GateTag, KpiCard, KpiGrid, Loading, Num, PageHead, QaTag, SourceTag, StatusTag } from "@/components/common";
import { EnginePicker, type EngineValue } from "@/components/EnginePicker";
import { EpisodeDrawer } from "@/components/EpisodeDrawer";
import { MediaTag, ThemeTag } from "@/components/ProductionCard";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type EpisodeStatus, type ResumeIn, type SeriesDetail, type SeriesRole } from "@/lib/api";
import { fmtClock, fmtUsd } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

const Flag = ({ on, label }: { on: boolean; label: string }) => (
  <Tooltip title={`${label}: ${on ? "done" : "not yet"}`}>
    {on ? <CheckCircleFilled style={{ color: "#52c41a" }} aria-label={`${label} done`} /> : <MinusCircleOutlined className="muted" aria-label={`${label} not yet`} />}
  </Tooltip>
);

function ContinueModal({ s, open, onClose }: { s: SeriesDetail; open: boolean; onClose: () => void }) {
  const { config } = useStudio();
  const { message } = App.useApp();
  const router = useRouter();
  const remaining = s.remaining.length;
  const [next, setNext] = useState(Math.max(1, Math.min(5, remaining || 1)));
  const [engine, setEngine] = useState<EngineValue>({ provider: s.run?.tts_provider ?? config?.tts.provider ?? "gemini", model: s.run?.tts_model ?? null, batching: "auto" });
  const [autoApprove, setAutoApprove] = useState(config?.defaults.auto_approve ?? false);
  const [retries, setRetries] = useState(config?.defaults.max_retries ?? 2);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    const body: ResumeIn = {
      next, tts_provider: engine.provider, tts_model: engine.model, tts_batching: engine.batching, auto_approve: autoApprove, max_retries: retries, force,
    };
    try {
      const run = await api.resume(s.series_id, body);
      message.success("Production resumed");
      router.push(`/pipeline/?id=${encodeURIComponent(run.run_id)}`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="Continue producing"
      okText="Start run"
      onOk={submit}
      confirmLoading={busy}
      destroyOnHidden
      width={640}
    >
      {!config ? <Loading card={false} /> : (
        <Form layout="vertical">
          <Typography.Paragraph type="secondary">
            {remaining ? <>Episodes {s.remaining.slice(0, 8).join(", ")}{remaining > 8 ? "…" : ""} are still to produce ({remaining} left).</> : "Every planned episode is produced; this re-runs the latest ones."}
          </Typography.Paragraph>
          <Form.Item label="Next episodes">
            <InputNumber min={1} max={Math.max(1, remaining || s.planned)} value={next} onChange={(v) => setNext(v ?? 1)} />
          </Form.Item>
          <Form.Item label="TTS engine">
            <EnginePicker config={config} value={engine} onChange={setEngine} />
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} sm={8}>
              <Form.Item label="QA max retries"><InputNumber min={0} max={5} value={retries} onChange={(v) => setRetries(v ?? 0)} /></Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item label="Auto-approve PASS" tooltip="Episodes that pass QA skip the human gate"><Switch checked={autoApprove} onChange={setAutoApprove} /></Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item label="Force re-render" tooltip="Ignore cached drafts and stems"><Checkbox checked={force} onChange={(e) => setForce(e.target.checked)}>Force</Checkbox></Form.Item>
            </Col>
          </Row>
          {err && <Alert type="error" showIcon title="Could not start" description={err} />}
        </Form>
      )}
    </Modal>
  );
}

function CastTable({ roles }: { roles: SeriesRole[] }) {
  if (!roles.length) return <EmptyState description="Not cast yet. The Casting agent assigns Voice IPs after the bible is written." />;
  return (
    <Table<SeriesRole>
      size="small"
      rowKey="role"
      pagination={false}
      dataSource={roles}
      scroll={{ x: 640 }}
      rowClassName={(r) => (r.voice_source === "cloned" ? "ev-cloned" : "")}
      columns={[
        { title: "Role", dataIndex: "role", render: (v: string, r) => <div><div>{v}</div>{r.type && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.type}</Typography.Text>}</div> },
        { title: "Voice IP", key: "actor", render: (_, r) => r.actor ? <Link href="/voices/">{r.actor_name ?? r.actor}</Link> : <span className="muted">–</span> },
        { title: "Engine / voice", key: "voice", render: (_, r) => r.provider ? <span style={{ fontSize: 12 }}>{r.provider}{r.voice ? <span className="muted mono"> · {r.voice}</span> : null}</span> : <span className="muted">–</span> },
        { title: "Source", dataIndex: "voice_source", render: (v: SeriesRole["voice_source"]) => <SourceTag source={v ?? null} /> },
        { title: "Assigned by", dataIndex: "assigned_by", render: (v: string | null) => <span className="muted">{v ?? "–"}</span> },
      ]}
    />
  );
}

function Detail() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const router = useRouter();
  const { message } = App.useApp();
  const [live, setLive] = useState(false);
  const { data, error, loading, refresh } = usePoll(() => api.series(id), live ? 5000 : 0, [id], !!id);
  const [episode, setEpisode] = useState<number | null>(null);
  const [continueOpen, setContinueOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => { setLive(!!data?.active_run); }, [data?.active_run]);

  if (!id) return <EmptyState description="No production selected" action={<Link href="/productions/"><Button>All productions</Button></Link>} />;
  if (loading && !data) return <Loading rows={10} />;
  if (!data) return <ErrorAlert error={error ?? "Not found"} onRetry={refresh} title="Could not load this production" />;
  const s = data;

  const del = async () => {
    setDeleting(true);
    try { await api.deleteSeries(s.series_id); message.success(`Deleted ${s.title || s.series_id}`); router.push("/productions/"); }
    catch (e) { message.error((e as Error).message); setDeleting(false); }
  };

  const briefId = s.trend_brief?.brief_id ?? s.bible?.trend_brief_id ?? null;

  return (
    <>
      <PageHead
        title={s.title || s.series_id}
        sub={<Space wrap size={6}><span className="mono">{s.series_id}</span><StatusTag status={s.active_run ? "running" : s.status}>{s.active_run ? "Producing" : undefined}</StatusTag><MediaTag media={s.media} /><ThemeTag theme={s.theme_category} />{s.mode && <Tooltip title={s.mode === "segment" ? "Pasted dialogue kept verbatim" : "Treatment expanded by the Script Writer"}><Tag>{s.mode} mode</Tag></Tooltip>}{s.genre && <Tag>{s.genre}</Tag>}</Space>}
        extra={
          <>
            <Button type="primary" icon={<CaretRightOutlined />} onClick={() => setContinueOpen(true)} disabled={!!s.active_run}>Continue producing</Button>
            <Link href={`/new/?edit=${encodeURIComponent(s.series_id)}`}><Button icon={<EditOutlined />}>Edit story &amp; re-run</Button></Link>
            <Popconfirm
              title="Delete this production?"
              description="Removes the story, scripts, stems, masters and reports. This cannot be undone."
              okText="Delete" okButtonProps={{ danger: true, loading: deleting }} onConfirm={del}
            >
              <Button danger icon={<DeleteOutlined />} aria-label="Delete production">Delete</Button>
            </Popconfirm>
          </>
        }
      />
      <ErrorAlert error={error} onRetry={refresh} />
      {s.active_run && (
        <Alert
          type="info" showIcon style={{ marginBottom: 16 }}
          title="A run is producing this series"
          action={<Link href={`/pipeline/?id=${encodeURIComponent(s.active_run)}`}><Button size="small" icon={<NodeIndexOutlined />}>Open pipeline</Button></Link>}
        />
      )}
      <Flex vertical gap={16}>
        <KpiGrid>
          {[
            <KpiCard key="p" title="Produced" value={s.produced} suffix={<span className="muted" style={{ fontSize: 14 }}>/ {s.planned}</span>} />,
            <KpiCard key="a" title="Approved" value={s.approved} />,
            <KpiCard key="w" title="Awaiting / review" value={`${s.awaiting} / ${s.needs_review}`} />,
            <KpiCard key="q" title="QA pass / flagged" value={`${s.qa_pass} / ${s.qa_flagged}`} />,
            <KpiCard key="d" title="Audio" value={fmtClock(s.duration_ms_total)} />,
            <KpiCard key="c" title="Cost" value={fmtUsd(s.cost_usd)} />,
          ]}
        </KpiGrid>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={10}>
            <Card title="Story" size="small" style={{ height: "100%" }}>
              <Descriptions
                size="small"
                column={1}
                items={[
                  { key: "l", label: "Logline", children: s.bible?.logline || s.logline || "–" },
                  { key: "p", label: "Premise", children: s.bible?.premise ? <span className="clamp-3" title={s.bible.premise}>{s.bible.premise}</span> : "–" },
                  { key: "t", label: "Tone", children: s.bible?.tone || "–" },
                  { key: "s", label: "Setting", children: s.setting || "–" },
                  { key: "f", label: "Format", children: s.bible?.episode_format ? <Num>{s.bible.episode_format.count} × {s.bible.episode_format.min_duration_sec}-{s.bible.episode_format.max_duration_sec}s</Num> : "–" },
                  {
                    key: "b", label: "Trend brief",
                    children: briefId ? <Link href={`/research/?id=${encodeURIComponent(briefId)}`}><LinkOutlined /> {s.trend_brief?.topic ?? briefId}</Link> : <span className="muted">Own story</span>,
                  },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24} xl={14}>
            <Card title="Cast" size="small" style={{ height: "100%" }} extra={<Link href="/voices/">Voice IPs</Link>}>
              <CastTable roles={s.roles} />
            </Card>
          </Col>
        </Row>

        <Card title={`Episodes (${s.episodes.length})`} size="small">
          <Table<EpisodeStatus>
            rowKey="number"
            size="small"
            dataSource={s.episodes}
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            scroll={{ x: 1100 }}
            rowClassName={() => "ev-click-row"}
            onRow={(e) => ({ onClick: () => setEpisode(e.number) })}
            locale={{ emptyText: <EmptyState description="No episodes planned yet" /> }}
            columns={[
              { title: "#", dataIndex: "number", width: 52, fixed: "left", render: (n: number) => <Num>{n}</Num> },
              {
                title: "Episode", key: "title", width: 280,
                render: (_, e) => (
                  <div>
                    <Typography.Text strong>{e.title ?? `Episode ${e.number}`}</Typography.Text>
                    {e.logline && <div><Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: e.logline }}>{e.logline}</Typography.Text></div>}
                  </div>
                ),
              },
              { title: "Hook", dataIndex: "hook_score", width: 64, align: "right", render: (v: number | null) => <Num>{v ?? "–"}</Num> },
              {
                title: "Pipeline", key: "flags", width: 150,
                render: (_, e) => (
                  <Space size={10}>
                    <Flag on={e.draft} label="Draft" />
                    <Flag on={e.direct} label="Directed" />
                    <Tooltip title={`${e.stems} stems`}><span className="num muted" style={{ fontSize: 12 }}>{e.stems}♪</span></Tooltip>
                    <Flag on={e.master} label="Master" />
                  </Space>
                ),
              },
              { title: "Master", key: "audio", width: 260, render: (_, e) => e.master ? <AudioPlayer src={e.master_url ?? api.masterUrl(s.series_id, e.number)} /> : <span className="muted">–</span> },
              { title: "Length", dataIndex: "duration_ms", width: 72, align: "right", render: (v: number | null) => <Num>{fmtClock(v)}</Num> },
              { title: "QA", dataIndex: "qa", width: 120, render: (q: EpisodeStatus["qa"]) => <QaTag qa={q} /> },
              { title: "Gate", key: "gate", width: 150, render: (_, e) => <GateTag state={e.release?.state} /> },
            ]}
          />
        </Card>
      </Flex>
      <EpisodeDrawer seriesId={s.series_id} episode={episode} onClose={() => setEpisode(null)} />
      {continueOpen && <ContinueModal s={s} open={continueOpen} onClose={() => setContinueOpen(false)} />}
    </>
  );
}

export default function ProductionDetailPage() {
  return <Suspense fallback={<Loading rows={10} />}><Detail /></Suspense>;
}
