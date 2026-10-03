"use client";

import { ArrowRightOutlined, LoadingOutlined, StopOutlined } from "@ant-design/icons";
import {
  Alert, App, Badge, Button, Card, Descriptions, Drawer, Flex, Popconfirm, Space, Steps, Table, Tag, Timeline, Tooltip, Typography,
} from "antd";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AudioPlayer, EmptyState, ErrorAlert, Loading, Num, ObjectDescriptions, PageHead, SourceTag, StatusTag } from "@/components/common";
import { api, type AgentInfo, type CastRow, type PipelineEvent, type Run, type StepState } from "@/lib/api";
import { aggregate, FLEET, STEP_AGENT } from "@/lib/agents";
import { ep, fmtClock, fmtCompact, fmtDuration, fmtInt, fmtTime, fmtUsd } from "@/lib/format";
import { useNow, usePoll } from "@/lib/hooks";
import { isLive, statusColor, stepsStatus } from "@/lib/status";

const EPISODE_STEPS: StepState["step"][] = ["draft", "direct", "voice", "master", "qa", "gate"];
const SERIES_STEPS: StepState["step"][] = ["research", "script", "casting"];
const STEP_TITLE: Record<string, string> = {
  research: "Trend brief", script: "Story + bible", casting: "Cast + engine policy", draft: "Draft", direct: "Direct", voice: "Voice", master: "Master", qa: "QA", gate: "Gate",
};

const n = (v: unknown) => (typeof v === "number" ? v : null);

/** One short line describing a step's result, for the matrix cells. */
export function stepBrief(s: StepState): string {
  const m = s.summary ?? {};
  if (s.status === "pending") return "queued";
  if (s.status === "waiting") return "waiting";
  if (s.status === "skipped") return "skipped";
  if (s.status === "failed") return (s.error ?? "failed").slice(0, 40);
  if (s.status === "running" && !Object.keys(m).length) return "working…";
  switch (s.step) {
    case "research": return m.topic ? String(m.topic).slice(0, 40) : "brief";
    case "script": return [m.episodes != null ? `${m.episodes} eps` : null, m.mode ? String(m.mode) : null].filter(Boolean).join(" · ");
    case "casting": return m.members != null ? `${m.members} roles` : "cast";
    case "draft": return m.reused ? "reused" : [n(m.words) != null ? `${m.words} words` : null, n(m.est_sec) != null ? `~${Math.round(n(m.est_sec)!)}s` : null].filter(Boolean).join(" · ");
    case "direct": return [m.units != null ? `${m.units} units` : null, m.batching ? String(m.batching) : null].filter(Boolean).join(" · ");
    case "voice": return [m.rendered != null ? `${m.rendered}/${m.planned ?? "?"}` : null, n(m.cached) ? `${m.cached} cached` : null, n(m.failed) ? `${m.failed} failed` : null].filter(Boolean).join(" · ");
    case "master": return [n(m.duration_ms) != null ? fmtClock(n(m.duration_ms)) : null, n(m.lufs) != null ? `${n(m.lufs)!.toFixed(1)} LUFS` : null].filter(Boolean).join(" · ");
    case "qa": return m.status ? `${m.status} ${m.score != null ? Math.round(Number(m.score)) : ""}`.trim() : "";
    case "gate": return m.state ? String(m.state).replace(/_/g, " ") : "";
    default: return "";
  }
}

function StepCell({ s, onOpen }: { s: StepState | undefined; onOpen: (s: StepState) => void }) {
  if (!s) return <span className="muted">–</span>;
  const tag = (
    <Tag color={statusColor(s.status)} icon={s.status === "running" ? <LoadingOutlined /> : undefined} style={{ marginInlineEnd: 0 }}>
      {s.status}
    </Tag>
  );
  return (
    <div className="ev-cell" role="button" tabIndex={0} onClick={() => onOpen(s)} onKeyDown={(e) => { if (e.key === "Enter") onOpen(s); }} aria-label={`${s.label} ${s.status}`}>
      <Space size={4}>
        {s.attempts > 1 ? <Badge count={`×${s.attempts}`} size="small" color="orange" offset={[4, -2]}>{tag}</Badge> : tag}
      </Space>
      <span className="meta">
        {stepBrief(s)}
        {s.elapsed_s > 0 && <span className="num"> · {s.elapsed_s < 60 ? `${s.elapsed_s.toFixed(0)}s` : `${Math.floor(s.elapsed_s / 60)}m${Math.round(s.elapsed_s % 60)}s`}</span>}
      </span>
    </div>
  );
}

function StepDrawer({ runId, step, onClose }: { runId: string; step: StepState | null; onClose: () => void }) {
  const running = step?.status === "running";
  const log = usePoll(() => api.stepLog(runId, step!.id), running ? 2000 : 0, [runId, step?.id, step?.status], !!step);
  const pre = useRef<HTMLPreElement>(null);
  useEffect(() => { if (running && pre.current) pre.current.scrollTop = pre.current.scrollHeight; }, [log.data, running]);
  return (
    <Drawer open={!!step} onClose={onClose} size="min(760px, 100vw)" destroyOnHidden title={step ? `${step.episode != null ? `${ep(step.episode)} · ` : ""}${step.label}` : ""}>
      {step && (
        <Flex vertical gap={16}>
          <Descriptions
            size="small"
            bordered
            column={{ xs: 1, sm: 2 }}
            items={[
              { key: "s", label: "Status", children: <StatusTag status={step.status} /> },
              { key: "a", label: "Agent", children: FLEET.find((f) => f.id === step.agent)?.title ?? step.agent },
              { key: "t", label: "Attempts", children: <Num>{step.attempts}</Num> },
              { key: "e", label: "Elapsed", children: <Num>{step.elapsed_s.toFixed(1)}s</Num> },
              { key: "st", label: "Started", children: fmtTime(step.started_at) || "–" },
              { key: "f", label: "Finished", children: fmtTime(step.finished_at) || "–" },
              { key: "c", label: "Cost", children: <Num>{fmtUsd(step.cost_usd)}</Num> },
              { key: "id", label: "Step id", children: <span className="mono">{step.id}</span> },
            ]}
          />
          {step.error && <Alert type="error" showIcon title="Error" description={<span style={{ whiteSpace: "pre-wrap" }}>{step.error}</span>} />}
          <div>
            <Typography.Title level={5}>Summary</Typography.Title>
            <ObjectDescriptions data={step.summary} />
          </div>
          <div>
            <Flex justify="space-between" align="center">
              <Typography.Title level={5} style={{ margin: 0 }}>Log</Typography.Title>
              {running && <Tag color="processing" icon={<LoadingOutlined />}>live</Tag>}
            </Flex>
            <div style={{ marginTop: 8 }}>
              {log.loading && !log.data ? <Loading card={false} rows={4} /> : log.error && !log.data ? (
                <Typography.Text type="secondary">{step.status === "pending" ? "Not started yet." : `No log available (${log.error}).`}</Typography.Text>
              ) : <pre ref={pre} className="ev-pre" style={{ maxHeight: "50vh" }}>{log.data || "(empty)"}</pre>}
            </div>
          </div>
        </Flex>
      )}
    </Drawer>
  );
}

function AgentFleet({ run, agents }: { run: Run; agents: AgentInfo[] | null }) {
  const items = FLEET.map((f) => {
    const live = agents?.find((a) => a.id === f.id);
    const steps = run.steps.filter((s) => (STEP_AGENT[s.step] ?? s.agent) === f.id || s.agent === f.id);
    const agg = aggregate(steps.map((s) => s.status));
    const done = steps.filter((s) => s.status === "done" || s.status === "approved" || s.status === "warn").length;
    const contract = live?.produces ?? f.produces;
    return {
      key: f.id,
      title: <Tooltip title={live?.description ?? f.title}><span>{f.short}</span></Tooltip>,
      status: stepsStatus(agg),
      icon: agg === "running" ? <LoadingOutlined /> : undefined,
      content: (
        <Flex vertical gap={4} align="flex-start">
          <Tag color={statusColor(agg === "partial" ? "running" : agg)} style={{ marginInlineEnd: 0 }}>
            {agg === "partial" ? "in progress" : agg}{steps.length > 1 && <span className="num"> {done}/{steps.length}</span>}
          </Tag>
          <Tooltip title={`Hands off ${contract}`}><span className="mono" style={{ fontSize: 11 }}><ArrowRightOutlined /> {f.produces}</span></Tooltip>
        </Flex>
      ),
    };
  });
  return (
    <div style={{ overflowX: "auto", paddingBottom: 4 }}>
      <div style={{ minWidth: 1060 }}>
        <Steps size="small" responsive={false} items={items} current={-1} />
      </div>
    </div>
  );
}

function useEvents(runId: string, live: boolean) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const last = useRef(0);
  useEffect(() => { setEvents([]); last.current = 0; }, [runId]);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.events(runId, last.current);
        if (!alive || !r.events.length) return;
        last.current = Math.max(last.current, ...r.events.map((e) => e.seq));
        setEvents((prev) => {
          const seen = new Set(prev.map((e) => e.seq));
          return [...prev, ...r.events.filter((e) => !seen.has(e.seq))].sort((a, b) => a.seq - b.seq).slice(-500);
        });
      } catch { /* the run view shows connection errors */ }
    };
    tick();
    if (!live) return () => { alive = false; };
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [runId, live]);
  return events;
}

const EVENT_COLOR: Record<string, string> = { done: "green", approved: "green", failed: "red", rejected: "red", running: "blue", warn: "orange", waiting: "orange" };

function EventTimeline({ events }: { events: PipelineEvent[] }) {
  if (!events.length) return <EmptyState description="No events yet" />;
  const recent = [...events].reverse().slice(0, 200);
  return (
    <div style={{ maxHeight: 520, overflowY: "auto", paddingTop: 8 }}>
      <Timeline
        items={recent.map((e) => ({
          key: e.seq,
          color: EVENT_COLOR[e.status ?? ""] ?? "gray",
          content: (
            <div>
              <Space size={6} wrap>
                <span className="num muted" style={{ fontSize: 12 }}>{new Date(e.at).toLocaleTimeString()}</span>
                {e.episode != null && <Tag style={{ marginInlineEnd: 0 }}>{ep(e.episode)}</Tag>}
                {e.agent && <span className="muted" style={{ fontSize: 12 }}>{FLEET.find((f) => f.id === e.agent)?.short ?? e.agent}</span>}
                {e.status && <Tag color={statusColor(e.status)} style={{ marginInlineEnd: 0 }}>{e.status}</Tag>}
              </Space>
              <div>{e.message}</div>
            </div>
          ),
        }))}
      />
    </div>
  );
}

function CastingTable({ rows }: { rows: CastRow[] }) {
  return (
    <Table<CastRow>
      size="small"
      rowKey="role"
      pagination={false}
      dataSource={rows}
      scroll={{ x: 960 }}
      rowClassName={(r) => (r.voice_source === "cloned" ? "ev-cloned" : "")}
      locale={{ emptyText: <EmptyState description="Casting has not run yet" /> }}
      columns={[
        { title: "Role", dataIndex: "role", width: 160 },
        { title: "Type", dataIndex: "type", width: 110, render: (v: string) => <Tag>{v}</Tag> },
        { title: "Actor", key: "actor", width: 160, render: (_, r) => <Tooltip title={r.actor}>{r.actor_name || r.actor}</Tooltip> },
        { title: "Engine", key: "engine", width: 220, render: (_, r) => <span style={{ fontSize: 12 }}>{r.provider} / {r.model}<div className="mono muted">{r.voice}</div></span> },
        { title: "Source", dataIndex: "voice_source", width: 140, render: (v: CastRow["voice_source"]) => <SourceTag source={v} /> },
        { title: "Assigned by", dataIndex: "assigned_by", width: 120 },
        { title: "Reason", dataIndex: "reason", render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v}</Typography.Text> },
      ]}
    />
  );
}

interface MatrixRow { episode: number; steps: Partial<Record<StepState["step"], StepState>> }

export function RunView({ id }: { id: string }) {
  const { message } = App.useApp();
  const [live, setLive] = useState(true);
  const { data: run, error, loading, refresh } = usePoll(() => api.run(id), live ? 2000 : 0, [id]);
  const agents = usePoll(() => api.agents(), 0);
  const events = useEvents(id, live);
  const [open, setOpen] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const now = useNow(live ? 1000 : 60000);
  useEffect(() => { if (run) setLive(isLive(run.status)); }, [run]);

  const matrix = useMemo<MatrixRow[]>(() => {
    const rows = new Map<number, MatrixRow>();
    for (const s of run?.steps ?? []) {
      if (s.episode == null) continue;
      const r = rows.get(s.episode) ?? { episode: s.episode, steps: {} };
      r.steps[s.step] = s;
      rows.set(s.episode, r);
    }
    return Array.from(rows.values()).sort((a, b) => a.episode - b.episode);
  }, [run]);

  if (loading && !run) return <Loading rows={10} />;
  if (!run) return <ErrorAlert error={error ?? "Run not found"} onRetry={refresh} title="Could not load this run" />;

  const seriesSteps = run.steps.filter((s) => s.episode == null && SERIES_STEPS.includes(s.step));
  const openStep = run.steps.find((s) => s.id === open) ?? null;
  const t = run.totals;
  const cancel = async () => {
    setCancelling(true);
    try { await api.cancelRun(run.run_id); message.success("Cancel requested"); refresh(); }
    catch (e) { message.error((e as Error).message); }
    finally { setCancelling(false); }
  };
  void now; // re-render the elapsed time while live

  return (
    <>
      <PageHead
        title={<Space wrap>Run <span className="mono" style={{ fontSize: 18 }}>{run.run_id}</span><StatusTag status={run.status} /></Space>}
        sub={
          <Space wrap size={6}>
            <Link href={`/productions/detail/?id=${encodeURIComponent(run.series_id)}`}>{run.series_id}</Link>
            <span>· started {fmtTime(run.created_at)}</span>
            {run.engine.llm && <Tag>LLM {run.engine.llm}</Tag>}
            {run.engine.tts && <Tag>TTS {run.engine.tts}</Tag>}
            {run.engine.storage && <Tag>{run.engine.storage}</Tag>}
          </Space>
        }
        extra={isLive(run.status) && (
          <Popconfirm title="Cancel this run?" description="The current step finishes; nothing after it starts." okText="Cancel run" okButtonProps={{ danger: true }} cancelText="Keep running" onConfirm={cancel}>
            <Button danger icon={<StopOutlined />} loading={cancelling}>Cancel</Button>
          </Popconfirm>
        )}
      />
      <ErrorAlert error={error} onRetry={refresh} />
      {run.error && <Alert type="error" showIcon title="Run failed" description={run.error} style={{ marginBottom: 16 }} />}
      {run.status === "awaiting_approval" && (
        <Alert type="warning" showIcon title="Episodes are waiting at the human gate" style={{ marginBottom: 16 }}
          action={<Link href="/approvals/"><Button size="small">Open approvals</Button></Link>} />
      )}
      <Flex vertical gap={16}>
        <Card size="small">
          <Descriptions
            size="small"
            column={{ xs: 2, sm: 3, md: 5 }}
            items={[
              { key: "c", label: "Cost", children: <Num>{fmtUsd(t.cost_usd)}</Num> },
              { key: "l", label: "LLM calls", children: <Num>{fmtInt(t.llm_calls)}</Num> },
              { key: "tok", label: "Tokens in/out", children: <Num>{fmtCompact(t.tokens_in)} / {fmtCompact(t.tokens_out)}</Num> },
              { key: "tts", label: "TTS requests", children: <Num>{fmtInt(t.tts_requests)}</Num> },
              { key: "ch", label: "Characters", children: <Num>{fmtCompact(t.tts_characters)}</Num> },
              { key: "a", label: "Audio", children: <Num>{fmtClock(t.audio_ms)}</Num> },
              { key: "r", label: "QA retries", children: <Num>{t.qa_retries}</Num> },
              { key: "e", label: "Elapsed", children: <Num>{fmtDuration(run.created_at, run.finished_at)}</Num> },
              { key: "p", label: "Episodes", children: <Num>{run.params.only?.length ? run.params.only.join(", ") : `${run.params.produce ?? run.params.episodes} of ${run.params.episodes}`}</Num> },
              { key: "q", label: "Gate", children: run.params.auto_approve ? "auto-approve PASS" : "human approval" },
            ]}
          />
        </Card>

        <Card title="Agent fleet" size="small">
          <AgentFleet run={run} agents={agents.data?.agents ?? null} />
        </Card>

        {run.notes.map((note, i) => <Alert key={i} type="info" showIcon title={note} />)}

        {seriesSteps.length > 0 && (
          <Card title="Series steps" size="small">
            <Flex gap={24} wrap>
              {seriesSteps.map((s) => (
                <div key={s.id}>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 2 }}>{STEP_TITLE[s.step] ?? s.label}</div>
                  <StepCell s={s} onOpen={(x) => setOpen(x.id)} />
                </div>
              ))}
            </Flex>
          </Card>
        )}

        <Card title="Episodes" size="small">
          <Table<MatrixRow>
            size="small"
            rowKey="episode"
            pagination={false}
            dataSource={matrix}
            scroll={{ x: 1000 }}
            locale={{ emptyText: <EmptyState description="Episode steps appear once the bible is written" /> }}
            columns={[
              { title: "Ep", dataIndex: "episode", width: 56, fixed: "left", render: (v: number) => <Num>{ep(v)}</Num> },
              ...EPISODE_STEPS.map((k) => ({
                title: STEP_TITLE[k], key: k, width: 120,
                render: (_: unknown, r: MatrixRow) => <StepCell s={r.steps[k]} onOpen={(x) => setOpen(x.id)} />,
              })),
              {
                title: "Master", key: "player", width: 260,
                render: (_: unknown, r: MatrixRow) => r.steps.master?.status === "done" || r.steps.master?.status === "warn"
                  ? <AudioPlayer src={api.masterUrl(run.series_id, r.episode)} />
                  : <span className="muted">–</span>,
              },
            ]}
          />
        </Card>

        <Card title={`Casting (${run.casting.length})`} size="small">
          <CastingTable rows={run.casting} />
        </Card>

        <Card title="Events" size="small" extra={isLive(run.status) && <Tag color="processing" icon={<LoadingOutlined />}>live</Tag>}>
          <EventTimeline events={events} />
        </Card>
      </Flex>
      <StepDrawer runId={run.run_id} step={openStep} onClose={() => setOpen(null)} />
    </>
  );
}
