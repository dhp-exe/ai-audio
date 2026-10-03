"use client";

import { PlusOutlined } from "@ant-design/icons";
import { Button, Card, Flex, Progress, Table, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { EmptyState, ErrorAlert, Loading, Num, PageHead, StatusTag } from "@/components/common";
import { RunView } from "@/components/pipeline/RunView";
import { api, type Run, type RunSummary } from "@/lib/api";
import { FLEET } from "@/lib/agents";
import { fmtAgo, fmtDuration, fmtUsd } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

function activeToRow(r: Run): RunSummary {
  const total = r.steps.length;
  const done = r.steps.filter((s) => ["done", "skipped", "approved", "warn"].includes(s.status)).length;
  const cur = r.steps.find((s) => s.status === "running");
  return {
    run_id: r.run_id, series_id: r.series_id, title: r.series_id, status: r.status, created_at: r.created_at, finished_at: r.finished_at,
    progress: { done, total }, current_step: cur?.label ?? null, current_agent: cur?.agent ?? null, cost_usd: r.totals.cost_usd,
    episodes: Array.from(new Set(r.steps.map((s) => s.episode).filter((e): e is number => e != null))),
  };
}

function RunsTable({ rows, empty }: { rows: RunSummary[]; empty: React.ReactNode }) {
  const router = useRouter();
  return (
    <Table<RunSummary>
      size="small"
      rowKey="run_id"
      dataSource={rows}
      pagination={{ pageSize: 15, hideOnSinglePage: true }}
      scroll={{ x: 900 }}
      rowClassName={() => "ev-click-row"}
      onRow={(r) => ({ onClick: () => router.push(`/pipeline/?id=${encodeURIComponent(r.run_id)}`) })}
      locale={{ emptyText: empty }}
      columns={[
        {
          title: "Production", key: "t",
          render: (_, r) => <div><Typography.Text strong>{r.title || r.series_id}</Typography.Text><div className="mono muted" style={{ fontSize: 11 }}>{r.run_id}</div></div>,
        },
        { title: "Status", dataIndex: "status", width: 150, render: (s: string) => <StatusTag status={s} /> },
        {
          title: "Progress", key: "p", width: 180,
          render: (_, r) => <Progress size="small" percent={r.progress.total ? Math.round((r.progress.done / r.progress.total) * 100) : 0} format={() => <Num>{r.progress.done}/{r.progress.total}</Num>} />,
        },
        {
          title: "Current", key: "c", width: 200,
          render: (_, r) => r.current_agent ? <span style={{ fontSize: 12 }}>{FLEET.find((f) => f.id === r.current_agent)?.short ?? r.current_agent}{r.current_step ? ` · ${r.current_step}` : ""}</span> : <span className="muted">–</span>,
        },
        { title: "Episodes", dataIndex: "episodes", width: 110, render: (e: number[]) => <Num>{e.length ? (e.length > 3 ? `${e[0]}–${e[e.length - 1]}` : e.join(", ")) : "–"}</Num> },
        { title: "Cost", dataIndex: "cost_usd", width: 90, align: "right", render: (v: number) => <Num>{fmtUsd(v)}</Num> },
        { title: "Duration", key: "d", width: 90, align: "right", render: (_, r) => <Num>{fmtDuration(r.created_at, r.finished_at)}</Num> },
        { title: "Started", dataIndex: "created_at", width: 100, render: (v: string) => <span className="muted">{fmtAgo(v)}</span> },
      ]}
    />
  );
}

function RunList() {
  const { data, error, loading, refresh } = usePoll(() => api.runs(), 5000);
  return (
    <>
      <PageHead title="Pipeline" sub="Runs of the 7-agent fleet: live ones first, then history." extra={<Link href="/new/"><Button type="primary" icon={<PlusOutlined />}>New production</Button></Link>} />
      <ErrorAlert error={error} onRetry={refresh} />
      {loading && !data ? <Loading /> : (
        <Flex vertical gap={16}>
          <Card title="Active runs" size="small">
            <RunsTable rows={(data?.active ?? []).map(activeToRow)} empty={<EmptyState description="No run is in progress" action={<Link href="/new/"><Button size="small" type="primary">Start a production</Button></Link>} />} />
          </Card>
          <Card title="Recent runs" size="small">
            <RunsTable rows={data?.recent ?? []} empty={<EmptyState description="No runs yet" />} />
          </Card>
        </Flex>
      )}
    </>
  );
}

function Pipeline() {
  const id = useSearchParams().get("id");
  return id ? <RunView key={id} id={id} /> : <RunList />;
}

export default function PipelinePage() {
  return <Suspense fallback={<Loading rows={10} />}><Pipeline /></Suspense>;
}
