"use client";

import { CheckCircleOutlined, ExclamationCircleOutlined, SoundOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { Card, Flex, Progress, Space, Tag, Tooltip, Typography } from "antd";
import { useRouter } from "next/navigation";
import type { SeriesSummary } from "@/lib/api";
import { fmtAgo, fmtUsd } from "@/lib/format";
import { THEME_COLOR } from "@/lib/status";
import { useStudio } from "./providers/StudioProvider";
import { StatusTag } from "./common";

export function MediaTag({ media }: { media: "audio" | "video" }) {
  return media === "video"
    ? <Tag icon={<VideoCameraOutlined />} color="purple" style={{ marginInlineEnd: 0 }}>Video</Tag>
    : <Tag icon={<SoundOutlined />} color="blue" style={{ marginInlineEnd: 0 }}>Audio</Tag>;
}

export function ThemeTag({ theme }: { theme: string | null | undefined }) {
  const { config } = useStudio();
  if (!theme) return null;
  const label = config?.theme_categories.find((t) => t.id === theme)?.label ?? theme.replace(/_/g, " ");
  return <Tag color={THEME_COLOR[theme] ?? "default"} style={{ marginInlineEnd: 0 }}>{label}</Tag>;
}

export function ProductionCard({ s }: { s: SeriesSummary }) {
  const router = useRouter();
  const pct = s.planned ? Math.round((s.produced / s.planned) * 100) : 0;
  const href = `/productions/detail/?id=${encodeURIComponent(s.series_id)}`;
  return (
    <Card
      hoverable
      size="small"
      style={{ height: "100%" }}
      styles={{ body: { display: "flex", flexDirection: "column", gap: 10, height: "100%" } }}
      onClick={() => router.push(href)}
      role="link"
      aria-label={`Open ${s.title || s.series_id}`}
    >
      <Flex justify="space-between" align="flex-start" gap={8}>
        <div style={{ minWidth: 0 }}>
          <Typography.Text strong style={{ fontSize: 15 }} ellipsis={{ tooltip: s.title }}>{s.title || s.series_id}</Typography.Text>
          <div className="muted mono" style={{ fontSize: 11 }}>{s.series_id}</div>
        </div>
        <StatusTag status={s.active_run ? "running" : s.status}>{s.active_run ? "Producing" : undefined}</StatusTag>
      </Flex>
      <Flex gap={4} wrap>
        <MediaTag media={s.media} />
        <ThemeTag theme={s.theme_category} />
        {s.genre && <Tag style={{ marginInlineEnd: 0 }}>{s.genre}</Tag>}
        {s.run && <Tooltip title={`Last run: ${s.run.tts_provider}${s.run.tts_model ? ` / ${s.run.tts_model}` : ""}`}><Tag style={{ marginInlineEnd: 0 }}>{s.run.tts_provider}</Tag></Tooltip>}
      </Flex>
      {s.logline && <Typography.Paragraph type="secondary" className="clamp-2" style={{ margin: 0, fontSize: 13 }}>{s.logline}</Typography.Paragraph>}
      <div>
        <Flex justify="space-between" style={{ fontSize: 12 }}>
          <span className="muted">Produced</span>
          <span className="num">{s.produced}/{s.planned}</span>
        </Flex>
        <Progress percent={pct} size="small" showInfo={false} />
      </div>
      <Flex gap={6} wrap align="center">
        <Tooltip title="QA passed"><Tag icon={<CheckCircleOutlined />} color={s.qa_pass ? "success" : "default"} style={{ marginInlineEnd: 0 }}><span className="num">{s.qa_pass}</span></Tag></Tooltip>
        <Tooltip title="QA flagged"><Tag icon={<ExclamationCircleOutlined />} color={s.qa_flagged ? "warning" : "default"} style={{ marginInlineEnd: 0 }}><span className="num">{s.qa_flagged}</span></Tag></Tooltip>
        {s.awaiting > 0 && <Tag color="gold" style={{ marginInlineEnd: 0 }}><span className="num">{s.awaiting}</span> awaiting</Tag>}
        {s.needs_review > 0 && <Tag color="error" style={{ marginInlineEnd: 0 }}><span className="num">{s.needs_review}</span> review</Tag>}
        {s.approved > 0 && <Tag color="success" style={{ marginInlineEnd: 0 }}><span className="num">{s.approved}</span> approved</Tag>}
      </Flex>
      {s.roles.length > 0 && (
        <Flex gap={4} wrap>
          {s.roles.slice(0, 5).map((r) => (
            <Tooltip key={r.role} title={`${r.role}${r.type ? ` (${r.type})` : ""}${r.actor_name ? ` · voiced by ${r.actor_name}` : ""}`}>
              <Tag color={r.voice_source === "cloned" ? "gold" : undefined} style={{ marginInlineEnd: 0, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
                {r.actor_name ?? r.actor ?? r.role}
              </Tag>
            </Tooltip>
          ))}
          {s.roles.length > 5 && <Tag style={{ marginInlineEnd: 0 }}>+{s.roles.length - 5}</Tag>}
        </Flex>
      )}
      <Flex justify="space-between" align="center" style={{ marginTop: "auto", fontSize: 12 }}>
        <Space size={6}>
          {s.run && <StatusTag status={s.run.status} />}
          <span className="muted">{fmtAgo(s.updated_at)}</span>
        </Space>
        <span className="num muted">{fmtUsd(s.cost_usd)}</span>
      </Flex>
    </Card>
  );
}
