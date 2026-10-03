"use client";

import { Alert, Card, Col, Descriptions, Flex, Progress, Row, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import { useMemo } from "react";
import { ErrorAlert, KpiCard, KpiGrid, Legend, Loading, MiniBars, Num, PageHead, StatusTag } from "@/components/common";
import { useThemeMode } from "@/components/providers/ThemeProvider";
import { api, type CostSummary, type UsageEvent, type UsageModel, type UsageRecord } from "@/lib/api";
import { FLEET } from "@/lib/agents";
import { fmtAgo, fmtClock, fmtCompact, fmtCountdown, fmtInt, fmtMinutes, fmtTime, fmtUsd } from "@/lib/format";
import { useNow, usePoll } from "@/lib/hooks";

function QuotaStatus({ m, now }: { m: UsageModel; now: number }) {
  const until = m.status !== "ok" ? m.status_until ?? m.resets_at : null;
  return (
    <Flex vertical gap={2}>
      <StatusTag status={m.status} tooltip={m.last_event?.message} />
      {until && <span className="num muted" style={{ fontSize: 12 }}>{m.status === "exhausted" ? "resets" : "retry"} in {fmtCountdown(until, now)}</span>}
    </Flex>
  );
}

export default function CostsPage() {
  const costs = usePoll(() => api.costs(), 15000);
  const usage = usePoll(() => api.usage(), 15000);
  const now = useNow();
  const { resolved } = useThemeMode();
  const c = costs.data;
  const u = usage.data;
  const llmColor = resolved === "dark" ? "#5b82c4" : "#284979";
  const ttsColor = resolved === "dark" ? "#d9a441" : "#c99a2e";
  const days = useMemo(() => (c?.by_day ?? []).slice(-30), [c]);

  if (costs.loading && !c) return <><PageHead title="Costs" /><Loading rows={10} /></>;

  const ws = c?.wavespeed;
  return (
    <>
      <PageHead title="Costs" sub="Spend, usage and vendor quotas. Costs are estimates from the usage ledger and the pricing table below." />
      <ErrorAlert error={costs.error} onRetry={costs.refresh} />
      {c && (
        <Flex vertical gap={16}>
          <KpiGrid>
            {[
              <KpiCard key="t" title="Total" value={fmtUsd(c.totals.cost_usd)} />,
              <KpiCard key="m" title="This month" value={fmtUsd(c.totals.cost_month_usd)} />,
              <KpiCard key="d" title="Today" value={fmtUsd(c.totals.cost_today_usd)} />,
              <KpiCard key="l" title="LLM calls" value={fmtInt(c.totals.llm_calls)} hint={`${fmtCompact(c.totals.tokens_in)} in / ${fmtCompact(c.totals.tokens_out)} out tokens`} />,
              <KpiCard key="r" title="TTS requests" value={fmtInt(c.totals.tts_requests)} />,
              <KpiCard key="ch" title="Characters" value={fmtCompact(c.totals.characters)} />,
              <KpiCard key="a" title="Audio" value={fmtMinutes(c.totals.audio_minutes)} />,
              <KpiCard
                key="w" title="WaveSpeed balance"
                value={ws?.available && ws.balance != null ? fmtUsd(ws.balance) : "n/a"}
                hint={!ws?.available ? ws?.reason ?? "not configured" : undefined}
              />,
            ]}
          </KpiGrid>

          <Card title="Cost by day" size="small" extra={<Legend items={[{ name: "LLM", color: llmColor }, { name: "TTS", color: ttsColor }]} />}>
            <MiniBars
              height={150}
              format={fmtUsd}
              data={days.map((d) => ({ label: d.date.slice(5), parts: [{ name: "LLM", value: d.llm_usd, color: llmColor }, { name: "TTS", value: d.tts_usd, color: ttsColor }] }))}
            />
          </Card>

          <Card size="small">
            <Tabs
              items={[
                {
                  key: "provider", label: "By provider",
                  children: (
                    <Table<CostSummary["by_provider"][number]>
                      size="small" rowKey="provider" pagination={false} dataSource={c.by_provider} scroll={{ x: 640 }}
                      columns={[
                        { title: "Provider", dataIndex: "label" },
                        { title: "Cost", dataIndex: "cost_usd", align: "right", sorter: (a, b) => a.cost_usd - b.cost_usd, defaultSortOrder: "descend", render: (v: number) => <Num>{fmtUsd(v)}</Num> },
                        { title: "Requests", dataIndex: "requests", align: "right", render: (v: number) => <Num>{fmtInt(v)}</Num> },
                        { title: "Tokens in/out", key: "tok", align: "right", render: (_, r) => <Num>{fmtCompact(r.tokens_in)} / {fmtCompact(r.tokens_out)}</Num> },
                        { title: "Characters", dataIndex: "characters", align: "right", render: (v: number) => <Num>{fmtCompact(v)}</Num> },
                      ]}
                    />
                  ),
                },
                {
                  key: "model", label: "By model",
                  children: (
                    <Table<CostSummary["by_model"][number]>
                      size="small" rowKey={(r) => `${r.provider}/${r.model}/${r.kind}`} pagination={false} dataSource={c.by_model} scroll={{ x: 820 }}
                      columns={[
                        { title: "Model", key: "m", render: (_, r) => <div>{r.model}<div className="muted" style={{ fontSize: 12 }}>{r.provider}</div></div> },
                        { title: "Kind", dataIndex: "kind", width: 80, render: (v: string) => <Tag>{v}</Tag> },
                        { title: "Cost", dataIndex: "cost_usd", align: "right", sorter: (a, b) => a.cost_usd - b.cost_usd, defaultSortOrder: "descend", render: (v: number) => <Num>{fmtUsd(v)}</Num> },
                        { title: "Requests", dataIndex: "requests", align: "right", render: (v: number) => <Num>{fmtInt(v)}</Num> },
                        { title: "Tokens in/out", key: "tok", align: "right", render: (_, r) => <Num>{fmtCompact(r.tokens_in)} / {fmtCompact(r.tokens_out)}</Num> },
                        { title: "Characters", dataIndex: "characters", align: "right", render: (v: number) => <Num>{fmtCompact(v)}</Num> },
                        { title: "Audio", dataIndex: "audio_ms", align: "right", render: (v: number) => <Num>{fmtClock(v)}</Num> },
                      ]}
                    />
                  ),
                },
                {
                  key: "agent", label: "By agent",
                  children: (
                    <Table<CostSummary["by_agent"][number]>
                      size="small" rowKey="agent" pagination={false} dataSource={c.by_agent} scroll={{ x: 640 }}
                      columns={[
                        { title: "Agent", key: "a", render: (_, r) => r.title || FLEET.find((f) => f.id === r.agent)?.title || r.agent },
                        { title: "Cost", dataIndex: "cost_usd", align: "right", sorter: (a, b) => a.cost_usd - b.cost_usd, defaultSortOrder: "descend", render: (v: number) => <Num>{fmtUsd(v)}</Num> },
                        { title: "Requests", dataIndex: "requests", align: "right", render: (v: number) => <Num>{fmtInt(v)}</Num> },
                        { title: "Steps", dataIndex: "steps", align: "right", render: (v: number) => <Num>{fmtInt(v)}</Num> },
                        { title: "Time", dataIndex: "elapsed_s", align: "right", render: (v: number) => <Num>{v < 120 ? `${v.toFixed(0)}s` : `${(v / 60).toFixed(1)} min`}</Num> },
                      ]}
                    />
                  ),
                },
                {
                  key: "series", label: "By series",
                  children: (
                    <Table<CostSummary["by_series"][number]>
                      size="small" rowKey="series_id" pagination={false} dataSource={c.by_series} scroll={{ x: 640 }}
                      columns={[
                        { title: "Series", key: "s", render: (_, r) => <div>{r.title || r.series_id}<div className="mono muted" style={{ fontSize: 11 }}>{r.series_id}</div></div> },
                        { title: "Cost", dataIndex: "cost_usd", align: "right", sorter: (a, b) => a.cost_usd - b.cost_usd, defaultSortOrder: "descend", render: (v: number) => <Num>{fmtUsd(v)}</Num> },
                        { title: "Episodes mastered", dataIndex: "episodes_mastered", align: "right", render: (v: number) => <Num>{v}</Num> },
                        { title: "Audio", dataIndex: "audio_minutes", align: "right", render: (v: number) => <Num>{fmtMinutes(v)}</Num> },
                        { title: "Cost / audio min", dataIndex: "cost_per_minute", align: "right", render: (v: number | null) => <Num>{v == null ? "–" : fmtUsd(v)}</Num> },
                      ]}
                    />
                  ),
                },
              ]}
            />
          </Card>

          <Card title="Quotas & limits" size="small">
            <ErrorAlert error={usage.error} onRetry={usage.refresh} title="Could not load vendor usage" />
            {u && (
              <Flex vertical gap={12}>
                <Flex gap={8} wrap>
                  {Object.entries(u.providers).map(([id, p]) => (
                    <Tooltip key={id} title={p.note}>
                      <Card size="small" style={{ minWidth: 200, flex: "1 1 200px" }} styles={{ body: { padding: "8px 12px" } }}>
                        <Flex justify="space-between" align="center"><Typography.Text strong>{p.label}</Typography.Text><Tag color={p.key ? "success" : "default"} style={{ marginInlineEnd: 0 }}>{p.key ? "key set" : "no key"}</Tag></Flex>
                        {p.credits_limit != null && p.credits_used != null && (
                          <div>
                            <Progress size="small" percent={Math.round((p.credits_used / Math.max(1, p.credits_limit)) * 100)} />
                            <span className="num muted" style={{ fontSize: 12 }}>{fmtInt(p.credits_used)} / {fmtInt(p.credits_limit)} credits{p.credits_source ? ` (${p.credits_source})` : ""}</span>
                          </div>
                        )}
                        {p.balance_usd != null && <div className="num" style={{ fontSize: 12 }}>Balance {fmtUsd(p.balance_usd)}</div>}
                        {p.resets_at && <div className="num muted" style={{ fontSize: 12 }}>Resets in {fmtCountdown(p.resets_at, now)}</div>}
                      </Card>
                    </Tooltip>
                  ))}
                </Flex>
                <Table<UsageModel>
                  size="small"
                  rowKey={(m) => `${m.provider}/${m.model}`}
                  pagination={false}
                  dataSource={u.models}
                  scroll={{ x: 980 }}
                  columns={[
                    { title: "Model", key: "m", render: (_, m) => <div>{m.label || m.model}<div className="muted" style={{ fontSize: 12 }}>{m.provider_label} · <span className="mono">{m.model}</span></div></div> },
                    { title: "Kind", dataIndex: "kind", width: 70, render: (v: string) => <Tag>{v}</Tag> },
                    { title: "Status", key: "s", width: 150, render: (_, m) => <QuotaStatus m={m} now={now} /> },
                    {
                      title: `Requests (${u.models[0]?.period ?? "period"})`, key: "r", width: 200,
                      render: (_, m) => {
                        const lim = m.limit?.requests_per_day;
                        return lim ? (
                          <Tooltip title={m.limit?.source}>
                            <div><Progress size="small" percent={Math.round((m.requests / lim) * 100)} status={m.requests >= lim ? "exception" : undefined} format={() => <Num>{m.requests}/{lim}</Num>} /></div>
                          </Tooltip>
                        ) : <Num>{fmtInt(m.requests)}</Num>;
                      },
                    },
                    { title: "Month", dataIndex: "requests_month", width: 80, align: "right", render: (v: number) => <Num>{fmtInt(v)}</Num> },
                    { title: "Tokens / chars", key: "t", width: 140, align: "right", render: (_, m) => <Num>{m.kind === "llm" ? `${fmtCompact(m.tokens_in)} / ${fmtCompact(m.tokens_out)}` : fmtCompact(m.characters)}</Num> },
                    { title: "Resets", key: "rs", width: 100, render: (_, m) => <span className="num muted" style={{ fontSize: 12 }}>{m.resets_at ? fmtCountdown(m.resets_at, now) : "–"}</span> },
                    { title: "Last call", dataIndex: "last_call_at", width: 100, render: (v: string | null) => <span className="muted" style={{ fontSize: 12 }}>{fmtAgo(v, now) || "–"}</span> },
                    { title: "Note", dataIndex: "note", render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v}</Typography.Text> },
                  ]}
                />
              </Flex>
            )}
            {!u && usage.loading && <Loading card={false} rows={3} />}
          </Card>

          <Row gutter={[16, 16]}>
            <Col xs={24} xl={12}>
              <Card title="Vendor events" size="small" style={{ height: "100%" }}>
                <Table<UsageEvent & { _k: string }>
                  size="small"
                  rowKey="_k"
                  pagination={{ pageSize: 10, hideOnSinglePage: true }}
                  dataSource={[...(u?.events ?? [])].reverse().map((e, i) => ({ ...e, _k: `${e.at}-${i}` }))}
                  scroll={{ x: 620 }}
                  locale={{ emptyText: "No rate-limit or quota events" }}
                  columns={[
                    { title: "When", dataIndex: "at", width: 110, render: (v: string) => <span className="muted" style={{ fontSize: 12 }}>{fmtTime(v)}</span> },
                    { title: "Model", key: "m", width: 160, render: (_, e) => <span style={{ fontSize: 12 }}>{e.provider} / {e.model}</span> },
                    { title: "Kind", key: "k", width: 110, render: (_, e) => <Tag color={e.status === 429 ? "warning" : e.status === 402 ? "error" : "default"}>{e.kind}{e.status ? ` ${e.status}` : ""}</Tag> },
                    { title: "Message", dataIndex: "message", render: (v: string, e) => <Typography.Text style={{ fontSize: 12 }}>{v}{e.retry_after_s ? <span className="muted"> · retry after {e.retry_after_s}s</span> : null}</Typography.Text> },
                  ]}
                />
              </Card>
            </Col>
            <Col xs={24} xl={12}>
              <Card title="Pricing basis" size="small" style={{ height: "100%" }}>
                <Alert type="info" showIcon title="These are estimates" description={c.pricing.note || "Costs are computed from logged tokens and characters with the list prices below; check the vendor invoice for exact amounts."} style={{ marginBottom: 12 }} />
                <Descriptions
                  size="small"
                  bordered
                  column={1}
                  items={[
                    ...Object.entries(c.pricing.llm_per_1m_tokens).map(([m, [i, o]]) => ({ key: `l-${m}`, label: <span className="mono" style={{ fontSize: 12 }}>{m}</span>, children: <Num>${i} in / ${o} out per 1M tokens</Num> })),
                    ...Object.entries(c.pricing.tts_per_1k_chars).map(([m, p]) => ({ key: `c-${m}`, label: <span className="mono" style={{ fontSize: 12 }}>{m}</span>, children: <Num>${p} per 1K characters</Num> })),
                    ...Object.entries(c.pricing.tts_per_1m_tokens).map(([m, [i, o]]) => ({ key: `t-${m}`, label: <span className="mono" style={{ fontSize: 12 }}>{m}</span>, children: <Num>${i} in / ${o} out per 1M tokens (TTS)</Num> })),
                  ]}
                />
              </Card>
            </Col>
          </Row>

          <Card title="Recent ledger records" size="small">
            <Table<UsageRecord & { _k: string }>
              size="small"
              rowKey="_k"
              pagination={{ pageSize: 15, hideOnSinglePage: true }}
              dataSource={c.recent.map((r, i) => ({ ...r, _k: `${r.at}-${i}` }))}
              scroll={{ x: 1100 }}
              columns={[
                { title: "When", dataIndex: "at", width: 120, render: (v: string) => <span className="muted" style={{ fontSize: 12 }}>{fmtTime(v)}</span> },
                { title: "Kind", dataIndex: "kind", width: 70, render: (v: string) => <Tag>{v}</Tag> },
                { title: "Series / ep", key: "s", width: 150, render: (_, r) => <span style={{ fontSize: 12 }}>{r.series_id ?? "–"}{r.episode != null ? ` · ep${String(r.episode).padStart(2, "0")}` : ""}</span> },
                { title: "Agent", key: "a", width: 150, render: (_, r) => <span style={{ fontSize: 12 }}>{r.agent ? FLEET.find((f) => f.id === r.agent)?.short ?? r.agent : "–"}{r.skill ? ` · ${r.skill}` : ""}</span> },
                { title: "Model", key: "m", width: 200, render: (_, r) => <span style={{ fontSize: 12 }}>{r.provider ?? "–"}{r.model ? ` / ${r.model}` : ""}</span> },
                { title: "Tokens / chars", key: "t", width: 130, align: "right", render: (_, r) => <Num>{r.kind === "llm" ? `${fmtCompact(r.tokens_in)} / ${fmtCompact(r.tokens_out)}` : r.characters ? fmtCompact(r.characters) : "–"}</Num> },
                { title: "Audio", dataIndex: "audio_ms", width: 70, align: "right", render: (v: number) => <Num>{v ? fmtClock(v) : "–"}</Num> },
                { title: "Cost", dataIndex: "cost_usd", width: 90, align: "right", render: (v: number) => <Num>{fmtUsd(v)}</Num> },
                { title: "OK", dataIndex: "ok", width: 60, render: (v: boolean, r) => <Tooltip title={r.note}><Tag color={v ? "success" : "error"} style={{ marginInlineEnd: 0 }}>{v ? "ok" : "fail"}</Tag></Tooltip> },
              ]}
            />
          </Card>
        </Flex>
      )}
    </>
  );
}
