"use client";

import { ArrowRightOutlined, PlusOutlined, SoundOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { Button, Card, Col, Flex, Progress, Row, Segmented, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useMemo } from "react";
import { EmptyState, ErrorAlert, KpiCard, KpiGrid, Legend, Loading, MiniBars, PageHead, StatusTag } from "@/components/common";
import { ProductionCard } from "@/components/ProductionCard";
import { useThemeMode } from "@/components/providers/ThemeProvider";
import { api, type RunSummary } from "@/lib/api";
import { fmtAgo, fmtMinutes, fmtUsd } from "@/lib/format";
import { usePoll, useStoredState } from "@/lib/hooks";
import { FLEET } from "@/lib/agents";

function agentName(id: string | null) {
  if (!id) return null;
  return FLEET.find((a) => a.id === id)?.short ?? id;
}

function ActiveRun({ r }: { r: RunSummary }) {
  const pct = r.progress.total ? Math.round((r.progress.done / r.progress.total) * 100) : 0;
  return (
    <Link href={`/pipeline/?id=${encodeURIComponent(r.run_id)}`} style={{ color: "inherit", display: "block" }}>
      <Flex vertical gap={4} style={{ padding: "10px 0", borderBottom: "1px solid var(--ev-border)" }}>
        <Flex justify="space-between" gap={8} align="center">
          <Typography.Text strong ellipsis>{r.title || r.series_id}</Typography.Text>
          <StatusTag status={r.status} />
        </Flex>
        <Progress percent={pct} size="small" status={r.status === "running" ? "active" : undefined} format={() => <span className="num">{r.progress.done}/{r.progress.total}</span>} />
        <Flex justify="space-between" style={{ fontSize: 12 }} className="muted" gap={8}>
          <span>{agentName(r.current_agent) ?? "Queued"}{r.current_step ? ` · ${r.current_step}` : ""}</span>
          <span className="num">{fmtUsd(r.cost_usd)}</span>
        </Flex>
      </Flex>
    </Link>
  );
}

export default function DashboardPage() {
  const { data, error, loading, refresh } = usePoll(() => api.dashboard(), 10000);
  const [media, setMedia] = useStoredState<"all" | "audio" | "video">("emvoox-dash-media", "all");
  const { resolved } = useThemeMode();
  const productions = useMemo(() => (data?.productions ?? []).filter((p) => media === "all" || p.media === media), [data, media]);
  const days = useMemo(() => (data?.cost_by_day ?? []).slice(-14), [data]);
  const barColor = resolved === "dark" ? "#5b82c4" : "#284979";

  if (loading && !data) return <><PageHead title="Dashboard" /><Loading rows={10} /></>;
  const k = data?.kpis;

  return (
    <>
      <PageHead
        title={<span className="serif" style={{ letterSpacing: 1 }}>EMVOOX</span>}
        sub="Emotion + Voice. One story in, a season of audio micro-drama out."
        extra={<Link href="/new/"><Button type="primary" icon={<PlusOutlined />}>New production</Button></Link>}
      />
      <ErrorAlert error={error} onRetry={refresh} />
      {data && k && (
        <Flex vertical gap={16}>
          <KpiGrid>
            {[
              <KpiCard key="s" title="Series" value={k.series} />,
              <KpiCard key="e" title="Episodes mastered" value={k.episodes_mastered} suffix={<span className="muted" style={{ fontSize: 14 }}>/ {k.episodes_planned}</span>} />,
              <KpiCard key="a" title="Awaiting approval" value={k.awaiting_approval} />,
              <KpiCard key="n" title="Needs review" value={k.needs_review} />,
              <KpiCard key="ap" title="Approved" value={k.approved} />,
              <KpiCard key="c" title="Cost this month" value={fmtUsd(k.cost_month_usd)} hint={`${fmtUsd(k.cost_total_usd)} all time`} />,
              <KpiCard key="m" title="Audio produced" value={fmtMinutes(k.audio_minutes)} />,
            ]}
          </KpiGrid>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title="In production" size="small" style={{ height: "100%" }} extra={<Link href="/pipeline/">Pipeline <ArrowRightOutlined /></Link>}>
                {data.active_runs.length ? data.active_runs.map((r) => <ActiveRun key={r.run_id} r={r} />) : (
                  <EmptyState description="Nothing is rendering right now" action={<Link href="/new/"><Button size="small" type="primary">Start a production</Button></Link>} />
                )}
                {!data.active_runs.length && data.recent_runs.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>Recent runs</Typography.Text>
                    {data.recent_runs.slice(0, 3).map((r) => (
                      <Flex key={r.run_id} justify="space-between" align="center" style={{ padding: "6px 0" }} gap={8}>
                        <Link href={`/pipeline/?id=${encodeURIComponent(r.run_id)}`} style={{ minWidth: 0 }}>
                          <Typography.Text ellipsis>{r.title || r.series_id}</Typography.Text>
                        </Link>
                        <Space size={6}><span className="muted" style={{ fontSize: 12 }}>{fmtAgo(r.finished_at ?? r.created_at)}</span><StatusTag status={r.status} /></Space>
                      </Flex>
                    ))}
                  </div>
                )}
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card title="Needs your attention" size="small" style={{ height: "100%" }} extra={<Link href="/approvals/">Approvals <ArrowRightOutlined /></Link>}>
                {data.attention.length ? (
                  <Flex vertical>
                    {data.attention.slice(0, 8).map((a) => (
                      <Link key={`${a.series_id}-${a.episode}`} href="/approvals/" style={{ color: "inherit" }}>
                        <Flex justify="space-between" gap={8} align="center" style={{ padding: "8px 0", borderBottom: "1px solid var(--ev-border)" }}>
                          <div style={{ minWidth: 0 }}>
                            <Typography.Text strong ellipsis style={{ display: "block" }}>{a.title} · Ep {a.episode}</Typography.Text>
                            <Typography.Text type="secondary" ellipsis style={{ fontSize: 12, display: "block" }}>{a.reason}</Typography.Text>
                          </div>
                          <StatusTag status={a.state} />
                        </Flex>
                      </Link>
                    ))}
                  </Flex>
                ) : <EmptyState description="All clear. No episodes are waiting for you." />}
              </Card>
            </Col>
          </Row>

          <Card
            title="Productions"
            size="small"
            extra={
              <Segmented
                size="small"
                value={media}
                onChange={(v) => setMedia(v as "all" | "audio" | "video")}
                options={[
                  { value: "all", label: "All" },
                  { value: "audio", label: "Audio", icon: <SoundOutlined /> },
                  { value: "video", label: <span>Video <Tag style={{ marginInlineEnd: 0, fontSize: 10, lineHeight: "16px" }}>planned</Tag></span>, icon: <VideoCameraOutlined /> },
                ]}
              />
            }
          >
            {productions.length ? (
              <Row gutter={[12, 12]}>
                {productions.map((s) => (
                  <Col key={s.series_id} xs={24} sm={12} xl={8} xxl={6}><ProductionCard s={s} /></Col>
                ))}
              </Row>
            ) : media === "video" ? (
              <EmptyState
                description={
                  <span>
                    Video productions come after audio validation.<br />
                    <span className="muted">Only series whose audio episodes prove retention get a video render.</span>
                  </span>
                }
              />
            ) : (
              <EmptyState description="No productions yet" action={<Link href="/new/"><Button type="primary">Create the first one</Button></Link>} />
            )}
          </Card>

          <Card title="Cost by day" size="small" extra={<Link href="/costs/">Costs <ArrowRightOutlined /></Link>}>
            <MiniBars
              data={days.map((d) => ({ label: d.date.slice(5), parts: [{ name: "Cost", value: d.cost_usd, color: barColor }] }))}
              height={110}
              format={fmtUsd}
            />
            <div style={{ marginTop: 6 }}><Legend items={[{ name: "Estimated spend, last 14 days (USD)", color: barColor }]} /></div>
          </Card>
        </Flex>
      )}
    </>
  );
}
