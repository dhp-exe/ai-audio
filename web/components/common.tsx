"use client";

import { ClockCircleOutlined, PauseCircleFilled, PlayCircleFilled, ReloadOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Descriptions, Empty, Flex, Skeleton, Statistic, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";
import type { GateState, QAIssue, QaBrief, VoiceSource } from "@/lib/api";
import { toggleAudio, usePlaying } from "@/lib/audio";
import { fmtClock } from "@/lib/format";
import { SOURCE_COLOR, SOURCE_HINT, SOURCE_LABEL, statusColor, statusLabel } from "@/lib/status";

/* ---------------------------------------------------------------- page scaffolding */

export function PageHead({ title, sub, extra }: { title: React.ReactNode; sub?: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <div className="ev-page-head">
      <div style={{ minWidth: 0 }}>
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {extra && <Flex gap={8} wrap align="center">{extra}</Flex>}
    </div>
  );
}

export function ErrorAlert({ error, onRetry, title = "Could not reach the Emvoox engine" }: { error: string | null | undefined; onRetry?: () => void; title?: string }) {
  if (!error) return null;
  return (
    <Alert
      type="error"
      showIcon
      title={title}
      description={error}
      style={{ marginBottom: 16 }}
      action={onRetry ? <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>Retry</Button> : undefined}
    />
  );
}

export function Loading({ rows = 6, card = true }: { rows?: number; card?: boolean }) {
  const sk = <Skeleton active title paragraph={{ rows }} />;
  return card ? <Card>{sk}</Card> : sk;
}

export function EmptyState({ description, action }: { description: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} style={{ padding: "16px 0" }}>
      {action}
    </Empty>
  );
}

/* ---------------------------------------------------------------- tags */

export function StatusTag({ status, children, tooltip }: { status: string | null | undefined; children?: React.ReactNode; tooltip?: React.ReactNode }) {
  const tag = <Tag color={statusColor(status)} style={{ marginInlineEnd: 0 }}>{children ?? statusLabel(status)}</Tag>;
  return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag;
}

export function GateTag({ state }: { state: GateState | null | undefined }) {
  if (!state) return <span className="muted">–</span>;
  return <StatusTag status={state} />;
}

export function QaTag({ qa }: { qa: QaBrief | null | undefined }) {
  if (!qa) return <span className="muted">–</span>;
  if (!qa.status) {
    return <StatusTag status="pending" tooltip="Legacy QA report without a PASS/FLAGGED verdict">QA n/a</StatusTag>;
  }
  const tip = (
    <div>
      <div>{qa.status} · score {qa.score ?? "–"} · attempt {qa.attempt}</div>
      {qa.issues > 0 && <div>{qa.issues} issue{qa.issues === 1 ? "" : "s"}: {qa.codes.join(", ")}</div>}
    </div>
  );
  return (
    <StatusTag status={qa.status} tooltip={tip}>
      <span className="num">{qa.status}{qa.score != null ? ` ${Math.round(qa.score)}` : ""}{qa.attempt > 1 ? ` ×${qa.attempt}` : ""}</span>
    </StatusTag>
  );
}

export function SourceTag({ source }: { source: VoiceSource | null | undefined }) {
  if (!source) return null;
  return (
    <Tooltip title={SOURCE_HINT[source]}>
      <Tag color={SOURCE_COLOR[source]} variant={source === "cloned" ? "solid" : undefined} style={{ marginInlineEnd: 0 }}>
        {SOURCE_LABEL[source]}
      </Tag>
    </Tooltip>
  );
}

export const Num = ({ children }: { children: React.ReactNode }) => <span className="num">{children}</span>;

/* ---------------------------------------------------------------- audio */

/** Play/stop through the one shared preview player. `resolve` renders a preview on demand when there is no url yet. */
export function PlayButton({ url, resolve, label = "Play preview", size = "small", text }: {
  url?: string | null; resolve?: () => Promise<string>; label?: string; size?: "small" | "medium" | "large"; text?: React.ReactNode;
}) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const [rendered, setRendered] = useState<string | null>(null);
  const u = url ?? rendered;
  const playing = usePlaying(u);
  const click = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (u) { toggleAudio(u); return; }
    if (!resolve) return;
    setBusy(true);
    try { const r = await resolve(); setRendered(r); toggleAudio(r); }
    catch (ex) { message.error((ex as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <Tooltip title={playing ? "Stop" : u ? label : `${label} (renders once, then cached)`}>
      <Button
        size={size}
        type={text ? "default" : "text"}
        shape={text ? undefined : "circle"}
        aria-label={playing ? "Stop preview" : label}
        icon={playing ? <PauseCircleFilled /> : <PlayCircleFilled />}
        loading={busy}
        disabled={!u && !resolve}
        onClick={click}
      >
        {text}
      </Button>
    </Tooltip>
  );
}

export function AudioPlayer({ src, wide, audioRef }: { src: string | null | undefined; wide?: boolean; audioRef?: React.Ref<HTMLAudioElement> }) {
  if (!src) return <span className="muted">–</span>;
  return (
    // eslint-disable-next-line jsx-a11y/media-has-caption
    <audio ref={audioRef} className={`ev-audio${wide ? " wide" : ""}`} controls preload="none" src={src} onClick={(e) => e.stopPropagation()} />
  );
}

/* ---------------------------------------------------------------- QA issues */

const SEVERITY_COLOR: Record<string, string> = { blocker: "error", major: "warning", minor: "default" };

export function QaIssues({ issues, onSeek }: { issues: QAIssue[]; onSeek?: (ms: number) => void }) {
  if (!issues.length) return <Typography.Text type="secondary">No issues.</Typography.Text>;
  return (
    <Flex vertical gap={2}>
      {issues.map((i, k) => {
        const seekable = i.at_ms != null && !!onSeek;
        return (
          <div
            key={k}
            className={`ev-issue${seekable ? " seekable" : ""}`}
            role={seekable ? "button" : undefined}
            tabIndex={seekable ? 0 : undefined}
            onClick={seekable ? () => onSeek!(i.at_ms!) : undefined}
            onKeyDown={seekable ? (e) => { if (e.key === "Enter") onSeek!(i.at_ms!); } : undefined}
            title={seekable ? "Jump to this moment" : undefined}
          >
            <Flex gap={8} wrap align="baseline">
              <Tag color={SEVERITY_COLOR[i.severity]} style={{ marginInlineEnd: 0 }}>{i.severity}</Tag>
              <Typography.Text code>{i.code}</Typography.Text>
              {i.at_ms != null && (
                <Typography.Link className="num" onClick={(e) => { e.stopPropagation(); onSeek?.(i.at_ms!); }}>
                  <ClockCircleOutlined /> {fmtClock(i.at_ms)}
                </Typography.Link>
              )}
              {(i.unit_id || i.line_id) && <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>{i.unit_id ?? i.line_id}</Typography.Text>}
            </Flex>
            <div style={{ marginTop: 2 }}>{i.message}{i.value != null && <span className="muted"> ({String(i.value)})</span>}</div>
          </div>
        );
      })}
    </Flex>
  );
}

/** Seek an <audio> element to `ms` and play. */
export function seekAudio(el: HTMLAudioElement | null, ms: number) {
  if (!el) return;
  const go = () => { el.currentTime = ms / 1000; el.play().catch(() => {}); };
  if (el.readyState >= 1) go();
  else { el.preload = "auto"; el.addEventListener("loadedmetadata", go, { once: true }); el.load(); }
}

/* ---------------------------------------------------------------- data display */

function renderValue(v: unknown): React.ReactNode {
  if (v == null || v === "") return <span className="muted">–</span>;
  if (typeof v === "boolean") return <Tag color={v ? "success" : "default"} style={{ marginInlineEnd: 0 }}>{v ? "yes" : "no"}</Tag>;
  if (typeof v === "number") return <span className="num">{Number.isInteger(v) ? v.toLocaleString() : v.toFixed(3)}</span>;
  if (Array.isArray(v)) {
    if (!v.length) return <span className="muted">none</span>;
    if (v.every((x) => typeof x !== "object")) return <Flex gap={4} wrap>{v.map((x, i) => <Tag key={i} style={{ marginInlineEnd: 0 }}>{String(x)}</Tag>)}</Flex>;
  }
  if (typeof v === "object") return <pre className="ev-pre" style={{ maxHeight: 200 }}>{JSON.stringify(v, null, 2)}</pre>;
  return String(v);
}

/** A flat JSON object (step summary, QA check) as antd Descriptions. */
export function ObjectDescriptions({ data, column = 2 }: { data: Record<string, unknown> | null | undefined; column?: number }) {
  const entries = Object.entries(data ?? {});
  if (!entries.length) return <Typography.Text type="secondary">Nothing reported.</Typography.Text>;
  return (
    <Descriptions
      size="small"
      bordered
      column={{ xs: 1, sm: 1, md: column }}
      items={entries.map(([k, v]) => ({ key: k, label: k.replace(/_/g, " "), children: renderValue(v) }))}
    />
  );
}

export function KpiCard({ title, value, suffix, prefix, precision, hint, loading }: {
  title: React.ReactNode; value: number | string | null | undefined; suffix?: React.ReactNode; prefix?: React.ReactNode; precision?: number; hint?: React.ReactNode; loading?: boolean;
}) {
  return (
    <Card size="small" style={{ height: "100%" }} styles={{ body: { padding: "14px 16px" } }}>
      <Statistic
        title={title}
        value={value ?? "–"}
        suffix={suffix}
        prefix={prefix}
        precision={precision}
        loading={loading}
        styles={{ content: { fontVariantNumeric: "tabular-nums" } }}
      />
      {hint && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{hint}</div>}
    </Card>
  );
}

/** Responsive KPI row: as many equal columns as fit, never a lone stretched card. */
export function KpiGrid({ children, min = 140 }: { children: React.ReactNode; min?: number }) {
  return <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: 12 }}>{children}</div>;
}

/** A tiny horizontal meter, for scores in tables. */
export function Meter({ value, max = 1, color, label }: { value: number | null | undefined; max?: number; color?: string; label?: React.ReactNode }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <span className="ev-meter">
      <span className="track"><span className="fill" style={{ display: "block", width: `${pct}%`, background: color }} /></span>
      <span className="num" style={{ fontSize: 12, minWidth: 28, textAlign: "right" }}>{label ?? (value == null ? "–" : value.toFixed(max <= 1 ? 2 : 0))}</span>
    </span>
  );
}

export interface BarDatum { label: string; parts: { name: string; value: number; color: string }[] }

/** Lightweight stacked column chart (no chart library, static-export friendly). */
export function MiniBars({ data, height = 120, format = (n) => String(n), showAxis = true }: {
  data: BarDatum[]; height?: number; format?: (n: number) => string; showAxis?: boolean;
}) {
  if (!data.length) return <EmptyState description="No data yet" />;
  const max = Math.max(...data.map((d) => d.parts.reduce((s, p) => s + p.value, 0)), 0);
  return (
    <div>
      <div className="ev-bars" style={{ height }} role="img" aria-label="Bar chart">
        {data.map((d) => {
          const total = d.parts.reduce((s, p) => s + p.value, 0);
          const tip = (
            <div className="num">
              <div style={{ fontWeight: 600 }}>{d.label}</div>
              {d.parts.map((p) => <div key={p.name}><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: p.color, marginRight: 6 }} />{p.name}: {format(p.value)}</div>)}
              {d.parts.length > 1 && <div>Total: {format(total)}</div>}
            </div>
          );
          return (
            <Tooltip key={d.label} title={tip}>
              <div className="col" style={{ height: "100%" }}>
                {d.parts.map((p) => (
                  <div key={p.name} style={{ height: max ? `${(p.value / max) * 100}%` : 0, background: p.color, minHeight: p.value > 0 ? 2 : 0 }} />
                ))}
                {total === 0 && <div style={{ height: 2, background: "var(--ev-border)" }} />}
              </div>
            </Tooltip>
          );
        })}
      </div>
      {showAxis && (
        <div className="ev-bars-axis">
          <span>{data[0].label}</span>
          <span>max {format(max)}</span>
          <span>{data[data.length - 1].label}</span>
        </div>
      )}
    </div>
  );
}

export function Legend({ items }: { items: { name: string; color: string }[] }) {
  return (
    <Flex gap={12} wrap style={{ fontSize: 12 }}>
      {items.map((i) => (
        <span key={i.name} className="muted"><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: i.color, marginRight: 6, verticalAlign: -1 }} />{i.name}</span>
      ))}
    </Flex>
  );
}
