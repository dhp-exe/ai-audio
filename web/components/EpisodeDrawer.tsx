"use client";

import { Alert, Collapse, Descriptions, Drawer, Empty, Flex, Space, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import { useRef } from "react";
import { api, type DirectedUnit, type EpisodeDetail, type QAReport, type ReleasePackage, type RenderUnit } from "@/lib/api";
import { ep, fmtBytes, fmtClock, fmtTime } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import { AudioPlayer, EmptyState, ErrorAlert, Loading, Num, ObjectDescriptions, QaIssues, StatusTag, seekAudio } from "./common";

const EMOTION_COLOR: Record<string, string> = {
  neutral: "default", happy: "green", sad: "blue", angry: "red", fearful: "purple", surprised: "orange",
  disgusted: "volcano", tender: "magenta", sarcastic: "gold", desperate: "red",
};

function ScriptTab({ d }: { d: EpisodeDetail }) {
  return (
    <Flex vertical gap={16}>
      {d.plan && (
        <Descriptions
          size="small"
          bordered
          column={1}
          items={[
            { key: "logline", label: "Logline", children: d.plan.logline || "–" },
            { key: "beats", label: "Key beats", children: d.plan.key_beats.length ? <ol style={{ margin: 0, paddingInlineStart: 18 }}>{d.plan.key_beats.map((b, i) => <li key={i}>{b}</li>)}</ol> : "–" },
            { key: "cliff", label: "Cliffhanger", children: d.plan.cliffhanger || "–" },
            { key: "hook", label: "Hook score", children: d.plan.hook_score != null ? <Num>{d.plan.hook_score}</Num> : "–" },
          ]}
        />
      )}
      {d.cliffhanger && (
        <Alert
          type={d.cliffhanger.passed ? "success" : "warning"}
          showIcon
          title={`Cliffhanger check: hook ${d.cliffhanger.hook_score} · ${d.cliffhanger.passed ? "passed" : "needs work"}`}
          description={
            <div>
              <Space wrap size={4} style={{ marginBottom: 4 }}>
                <Tag color={d.cliffhanger.twist_within_30s ? "success" : "default"}>twist within 30 s</Tag>
                <Tag color={d.cliffhanger.antagonist_is_smart ? "success" : "default"}>smart antagonist</Tag>
                <Tag color={d.cliffhanger.independent_motivations ? "success" : "default"}>independent motivations</Tag>
              </Space>
              {d.cliffhanger.issues.map((i, k) => <div key={k}>• {i}</div>)}
              {d.cliffhanger.suggestion && <div style={{ marginTop: 4 }}><b>Suggestion:</b> {d.cliffhanger.suggestion}</div>}
            </div>
          }
        />
      )}
      {d.raw_script ? <pre className="ev-pre" style={{ maxHeight: "60vh" }}>{d.raw_script}</pre> : <EmptyState description="No screenplay drafted yet" />}
    </Flex>
  );
}

function DirectedTab({ d }: { d: EpisodeDetail }) {
  const dir = d.directed;
  if (!dir) return <EmptyState description="Not directed yet" />;
  return (
    <Flex vertical gap={16}>
      <Space wrap size={6}>
        <Tag>{dir.units.length} units</Tag>
        <Tag>{dir.render_plan.length} render requests</Tag>
        <Tag>batching: {dir.batching}</Tag>
        <Tag>target {dir.target_duration_sec}s</Tag>
      </Space>
      <Table<DirectedUnit>
        size="small"
        rowKey="unit_id"
        dataSource={dir.units}
        pagination={false}
        scroll={{ x: 980, y: 480 }}
        columns={[
          { title: "#", dataIndex: "order", width: 48, render: (v: number) => <Num>{v}</Num> },
          {
            title: "Speaker", key: "speaker", width: 140,
            render: (_, u) => u.type === "pause" ? <Tag>pause</Tag> : (
              <div>
                <div>{u.role_name ?? u.speaker_id}</div>
                <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>{u.speaker_id}{u.type === "monologue" ? " · inner" : ""}</Typography.Text>
              </div>
            ),
          },
          {
            title: "Text", key: "text",
            render: (_, u) => (
              <Tooltip title={u.tts_text !== u.text ? <span>TTS: {u.tts_text}</span> : undefined}>
                <div>{u.text || <span className="muted">–</span>}</div>
                {u.direction && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{u.direction}</Typography.Text>}
              </Tooltip>
            ),
          },
          {
            title: "Emotion", key: "emo", width: 120,
            render: (_, u) => u.type === "pause" ? null : <Tag color={EMOTION_COLOR[u.emotion_tag] ?? "default"}>{u.emotion_tag} <span className="num">{u.emotional_intensity}</span></Tag>,
          },
          { title: "Tags", dataIndex: "audio_tags", width: 150, render: (t: string[]) => <Flex gap={2} wrap>{t.map((x) => <Tag key={x} style={{ marginInlineEnd: 0 }}>{x}</Tag>)}</Flex> },
          { title: "Pause", dataIndex: "pause_after_ms", width: 72, align: "right", render: (v: number) => <Num>{v} ms</Num> },
          {
            title: "Engine / voice", key: "engine", width: 170,
            render: (_, u) => (
              <Tooltip title={`${u.provider} / ${u.model_id} / ${u.voice_id}`}>
                <div style={{ fontSize: 12 }}><div>{u.provider}</div><div className="muted mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}>{u.voice_id}</div></div>
              </Tooltip>
            ),
          },
        ]}
      />
      <Typography.Title level={5} style={{ margin: 0 }}>Render plan</Typography.Title>
      <Table<RenderUnit>
        size="small"
        rowKey="id"
        dataSource={dir.render_plan}
        pagination={false}
        scroll={{ x: 820 }}
        columns={[
          { title: "Render unit", dataIndex: "id", render: (v: string) => <span className="mono" style={{ fontSize: 12 }}>{v}</span> },
          { title: "Kind", dataIndex: "kind", width: 110, render: (v: string) => <Tag color={v === "conversation" ? "geekblue" : "default"}>{v}</Tag> },
          { title: "Scene", dataIndex: "scene_id", width: 70 },
          { title: "Units", dataIndex: "unit_ids", width: 70, align: "right", render: (v: string[]) => <Num>{v.length}</Num> },
          { title: "Speakers", dataIndex: "speakers", render: (v: string[]) => v.join(", ") },
          { title: "Engine", key: "e", render: (_, r) => <span style={{ fontSize: 12 }}>{r.provider} / {r.model_id}</span> },
          { title: "Attempt", dataIndex: "attempt", width: 80, align: "right", render: (v: number) => <Num>{v}</Num> },
        ]}
      />
      {(dir.cliffhanger || dir.director_notes) && (
        <Descriptions size="small" bordered column={1} items={[
          { key: "c", label: "Cliffhanger", children: dir.cliffhanger || "–" },
          { key: "n", label: "Director notes", children: dir.director_notes || "–" },
        ]} />
      )}
    </Flex>
  );
}

function checkOk(c: Record<string, unknown>): boolean | null {
  for (const k of ["ok", "passed", "pass"]) if (typeof c[k] === "boolean") return c[k] as boolean;
  return null;
}

export function QaReportView({ qa, onSeek }: { qa: QAReport | null; onSeek?: (ms: number) => void }) {
  if (!qa) return <EmptyState description="No QA report yet" />;
  return (
    <Flex vertical gap={16}>
      <Space wrap>
        <StatusTag status={qa.status} />
        <Tag><span className="num">score {Math.round(qa.score)}</span></Tag>
        <Tag><span className="num">attempt {qa.attempt}</span></Tag>
        <span className="muted" style={{ fontSize: 12 }}>{fmtTime(qa.generated_at)}</span>
      </Space>
      <div>
        <Typography.Title level={5}>Issues</Typography.Title>
        <QaIssues issues={qa.error_logs} onSeek={onSeek} />
      </div>
      {qa.retry_instructions.length > 0 && (
        <div>
          <Typography.Title level={5}>Retry instructions</Typography.Title>
          {qa.retry_instructions.map((r, i) => (
            <div key={i} style={{ marginBottom: 6 }}>
              <Tag color="processing">{r.action}</Tag> <span className="muted">{r.step}</span> · {r.reason}
              {r.unit_ids.length > 0 && <div className="mono muted" style={{ fontSize: 11 }}>{r.unit_ids.join(", ")}</div>}
            </div>
          ))}
        </div>
      )}
      {qa.review_lines.length > 0 && (
        <div>
          <Typography.Title level={5}>Lines to listen to</Typography.Title>
          <Flex gap={4} wrap>{qa.review_lines.map((l) => <Tag key={l} className="mono">{l}</Tag>)}</Flex>
        </div>
      )}
      <div>
        <Typography.Title level={5}>Checks</Typography.Title>
        <Collapse
          size="small"
          items={Object.entries(qa.checks).map(([name, c]) => {
            const ok = checkOk(c);
            return {
              key: name,
              label: <Space>{name.replace(/_/g, " ")}{ok != null && <Tag color={ok ? "success" : "warning"}>{ok ? "ok" : "check"}</Tag>}</Space>,
              children: <ObjectDescriptions data={c} />,
            };
          })}
        />
      </div>
      {qa.human && (
        <Alert
          type={qa.human.verdict === "approved" ? "success" : "error"}
          showIcon
          title={`Human verdict: ${qa.human.verdict}${qa.human.reviewer ? ` by ${qa.human.reviewer}` : ""}`}
          description={qa.human.notes || undefined}
        />
      )}
    </Flex>
  );
}

export function ReleaseView({ rel }: { rel: ReleasePackage | null }) {
  if (!rel) return <EmptyState description="Not at the approval gate yet" />;
  const m = rel.metadata;
  return (
    <Flex vertical gap={16}>
      <Space wrap>
        <StatusTag status={rel.state} />
        <StatusTag status={rel.qa_status}>{rel.qa_status} {Math.round(rel.qa_score)}</StatusTag>
        <Tag>{rel.qa_attempts} QA attempt{rel.qa_attempts === 1 ? "" : "s"}</Tag>
        <Tag>{fmtClock(rel.duration_ms)}</Tag>
      </Space>
      {rel.reason && <Alert type="info" showIcon title="Gate reason" description={rel.reason} />}
      {rel.decision && (
        <Alert
          type={rel.decision.decision === "approved" ? "success" : "error"}
          showIcon
          title={`${rel.decision.decision} by ${rel.decision.reviewer} · ${fmtTime(rel.decision.at)}${rel.decision.override_flagged ? " (overrode QA)" : ""}`}
          description={rel.decision.notes || undefined}
        />
      )}
      <Descriptions
        size="small"
        bordered
        column={1}
        title="Publish metadata"
        items={[
          { key: "t", label: "Title", children: m.title },
          { key: "d", label: "Description", children: <span style={{ whiteSpace: "pre-wrap" }}>{m.description}</span> },
          { key: "tags", label: "Tags", children: <Flex gap={4} wrap>{m.tags.map((t) => <Tag key={t} style={{ marginInlineEnd: 0 }}>{t}</Tag>)}</Flex> },
          { key: "h", label: "Hashtags", children: m.hashtags.join(" ") },
          { key: "p", label: "Playlist", children: m.playlist_title },
          { key: "th", label: "Thumbnail text", children: m.thumbnail_text },
          { key: "flags", label: "Flags", children: <Space wrap size={4}><Tag>{m.language}</Tag><Tag>{m.category}</Tag>{m.contains_synthetic_media && <Tag color="purple">synthetic media</Tag>}{m.made_for_kids && <Tag>made for kids</Tag>}<Tag>by {m.generated_by}</Tag></Space> },
        ]}
      />
      <div>
        <Typography.Title level={5}>Exported files</Typography.Title>
        {rel.exported.length ? (
          <Table
            size="small"
            rowKey="path"
            pagination={false}
            dataSource={rel.exported}
            scroll={{ x: 480 }}
            columns={[
              { title: "Kind", dataIndex: "kind", width: 90, render: (v: string) => <Tag>{v}</Tag> },
              { title: "Path", dataIndex: "path", render: (v: string) => <Typography.Text className="mono" style={{ fontSize: 12 }} copyable>{v}</Typography.Text> },
              { title: "Size", dataIndex: "bytes", width: 90, align: "right", render: (v: number) => <Num>{fmtBytes(v)}</Num> },
            ]}
          />
        ) : <Typography.Text type="secondary">Nothing exported yet. Files are exported when the episode is approved.</Typography.Text>}
      </div>
      {rel.publish?.status && (
        <Descriptions size="small" bordered column={1} items={[
          { key: "pl", label: "Platform", children: rel.publish.platform ?? "–" },
          { key: "st", label: "Status", children: rel.publish.status },
          { key: "n", label: "Note", children: rel.publish.note ?? "–" },
        ]} />
      )}
    </Flex>
  );
}

export function EpisodeDrawer({ seriesId, episode, onClose }: { seriesId: string; episode: number | null; onClose: () => void }) {
  const open = episode != null;
  const { data, error, loading, refresh } = usePoll(() => api.episode(seriesId, episode!), 0, [seriesId, episode], open);
  const audioRef = useRef<HTMLAudioElement>(null);
  const d = data && data.number === episode ? data : null;
  const src = d?.master_url ?? null;
  const seek = (ms: number) => seekAudio(audioRef.current, ms);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      size="min(920px, 100vw)"
      destroyOnHidden
      title={episode != null ? `${ep(episode)}${d?.plan?.title ? ` · ${d.plan.title}` : ""}` : ""}
    >
      <ErrorAlert error={error} onRetry={refresh} />
      {!d && loading && <Loading card={false} />}
      {!d && !loading && !error && <Empty />}
      {d && (
        <Flex vertical gap={12}>
          {src ? (
            <div>
              <AudioPlayer src={src} wide audioRef={audioRef} />
              {d.timeline_ms != null && <div className="muted" style={{ fontSize: 12 }}>Timeline length {fmtClock(d.timeline_ms)}</div>}
            </div>
          ) : <Typography.Text type="secondary">No master yet.</Typography.Text>}
          <Tabs
            items={[
              { key: "script", label: "Script", children: <ScriptTab d={d} /> },
              { key: "directed", label: `Directed units${d.directed ? ` (${d.directed.units.length})` : ""}`, children: <DirectedTab d={d} /> },
              { key: "qa", label: d.qa ? <Space size={4}>QA report <StatusTag status={d.qa.status} /></Space> : "QA report", children: <QaReportView qa={d.qa} onSeek={seek} /> },
              { key: "release", label: "Release", children: <ReleaseView rel={d.release} /> },
            ]}
          />
        </Flex>
      )}
    </Drawer>
  );
}
