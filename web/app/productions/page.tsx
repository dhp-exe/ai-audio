"use client";

import { AppstoreOutlined, PlusOutlined, SearchOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { Button, Card, Col, Flex, Input, Progress, Row, Segmented, Select, Table, Tag, Tooltip, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { EmptyState, ErrorAlert, Loading, Num, PageHead, StatusTag } from "@/components/common";
import { MediaTag, ProductionCard, ThemeTag } from "@/components/ProductionCard";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type SeriesSummary } from "@/lib/api";
import { fmtAgo, fmtClock, fmtUsd } from "@/lib/format";
import { usePoll, useStoredState } from "@/lib/hooks";

export default function ProductionsPage() {
  const router = useRouter();
  const { config } = useStudio();
  const { data, error, loading, refresh } = usePoll(() => api.library(), 15000);
  const [view, setView] = useStoredState<"table" | "cards">("emvoox-productions-view", "table");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string | undefined>();
  const [engine, setEngine] = useState<string | undefined>();
  const [theme, setTheme] = useState<string | undefined>();

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.series ?? []).filter((s) =>
      (!needle || `${s.title} ${s.series_id} ${s.logline} ${s.genre} ${s.setting}`.toLowerCase().includes(needle)) &&
      (!status || s.status === status) &&
      (!engine || s.run?.tts_provider === engine) &&
      (!theme || s.theme_category === theme),
    );
  }, [data, q, status, engine, theme]);

  const engines = useMemo(() => Array.from(new Set((data?.series ?? []).map((s) => s.run?.tts_provider).filter(Boolean))) as string[], [data]);

  return (
    <>
      <PageHead
        title="Productions"
        sub="Every series in the studio, its progress and its spend."
        extra={<Link href="/new/"><Button type="primary" icon={<PlusOutlined />}>New production</Button></Link>}
      />
      <ErrorAlert error={error} onRetry={refresh} />
      {loading && !data ? <Loading rows={8} /> : (
        <Card size="small">
          <Flex gap={8} wrap style={{ marginBottom: 12 }}>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="Search title, id, logline"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ flex: "1 1 220px", maxWidth: 360 }}
              aria-label="Search productions"
            />
            <Select
              allowClear placeholder="Status" value={status} onChange={setStatus} style={{ width: 150 }} aria-label="Filter by status"
              options={[{ value: "new", label: "New" }, { value: "in_progress", label: "In production" }, { value: "complete", label: "Complete" }]}
            />
            <Select allowClear placeholder="Engine" value={engine} onChange={setEngine} style={{ width: 140 }} aria-label="Filter by engine"
              options={engines.map((e) => ({ value: e, label: e }))} />
            <Select allowClear placeholder="Theme" value={theme} onChange={setTheme} style={{ width: 200 }} aria-label="Filter by theme"
              options={(config?.theme_categories ?? []).map((t) => ({ value: t.id, label: t.label }))} />
            <div style={{ marginLeft: "auto" }}>
              <Segmented
                value={view}
                onChange={(v) => setView(v as "table" | "cards")}
                options={[
                  { value: "table", icon: <UnorderedListOutlined aria-label="Table view" /> },
                  { value: "cards", icon: <AppstoreOutlined aria-label="Card view" /> },
                ]}
              />
            </div>
          </Flex>
          {!rows.length ? (
            <EmptyState
              description={data?.series.length ? "No production matches these filters" : "No productions yet"}
              action={!data?.series.length && <Link href="/new/"><Button type="primary">Start one</Button></Link>}
            />
          ) : view === "cards" ? (
            <Row gutter={[12, 12]}>
              {rows.map((s) => <Col key={s.series_id} xs={24} sm={12} xl={8} xxl={6}><ProductionCard s={s} /></Col>)}
            </Row>
          ) : (
            <Table<SeriesSummary>
              rowKey="series_id"
              dataSource={rows}
              pagination={{ pageSize: 20, hideOnSinglePage: true }}
              scroll={{ x: 1100 }}
              rowClassName={() => "ev-click-row"}
              onRow={(s) => ({ onClick: () => router.push(`/productions/detail/?id=${encodeURIComponent(s.series_id)}`) })}
              columns={[
                {
                  title: "Production", key: "title", fixed: "left", width: 300,
                  sorter: (a, b) => a.title.localeCompare(b.title),
                  render: (_, s) => (
                    <div style={{ minWidth: 0 }}>
                      <Typography.Text strong>{s.title || s.series_id}</Typography.Text>
                      <div className="muted mono" style={{ fontSize: 11 }}>{s.series_id}</div>
                      {s.logline && <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: s.logline }}>{s.logline}</Typography.Text>}
                    </div>
                  ),
                },
                { title: "Status", key: "status", width: 130, render: (_, s) => <StatusTag status={s.active_run ? "running" : s.status}>{s.active_run ? "Producing" : undefined}</StatusTag> },
                { title: "Media", dataIndex: "media", width: 90, render: (m: "audio" | "video") => <MediaTag media={m} /> },
                { title: "Theme", dataIndex: "theme_category", width: 170, render: (t: string | null) => (t ? <ThemeTag theme={t} /> : <span className="muted">–</span>) },
                {
                  title: "Engine", key: "engine", width: 130,
                  render: (_, s) => s.run ? <Tooltip title={s.run.tts_model ?? "default model"}><Tag>{s.run.tts_provider}</Tag></Tooltip> : <span className="muted">–</span>,
                },
                {
                  title: "Produced", key: "produced", width: 150, sorter: (a, b) => a.produced - b.produced,
                  render: (_, s) => (
                    <div>
                      <Num>{s.produced}/{s.planned}</Num>
                      <Progress percent={s.planned ? (s.produced / s.planned) * 100 : 0} size="small" showInfo={false} />
                    </div>
                  ),
                },
                { title: "Approved", dataIndex: "approved", width: 95, align: "right", sorter: (a, b) => a.approved - b.approved, render: (v: number) => <Num>{v}</Num> },
                {
                  title: "QA", key: "qa", width: 110,
                  render: (_, s) => (
                    <Flex gap={4}>
                      <Tooltip title="QA passed"><Tag color={s.qa_pass ? "success" : "default"} style={{ marginInlineEnd: 0 }}><Num>{s.qa_pass}</Num></Tag></Tooltip>
                      <Tooltip title="QA flagged"><Tag color={s.qa_flagged ? "warning" : "default"} style={{ marginInlineEnd: 0 }}><Num>{s.qa_flagged}</Num></Tag></Tooltip>
                    </Flex>
                  ),
                },
                { title: "Audio", dataIndex: "duration_ms_total", width: 80, align: "right", render: (v: number) => <Num>{fmtClock(v)}</Num> },
                { title: "Cost", dataIndex: "cost_usd", width: 90, align: "right", sorter: (a, b) => a.cost_usd - b.cost_usd, render: (v: number) => <Num>{fmtUsd(v)}</Num> },
                {
                  title: "Updated", dataIndex: "updated_at", width: 110, defaultSortOrder: "descend",
                  sorter: (a, b) => (a.updated_at ?? "").localeCompare(b.updated_at ?? ""),
                  render: (v: string | null) => <span className="muted">{fmtAgo(v)}</span>,
                },
              ]}
            />
          )}
        </Card>
      )}
    </>
  );
}
