"use client";

import { CheckOutlined, CloseOutlined, DownloadOutlined, SaveOutlined, UserOutlined } from "@ant-design/icons";
import {
  Alert, App, Badge, Button, Card, Col, Flex, Form, Input, Modal, Row, Select, Space, Table, Tabs, Tag, Typography,
} from "antd";
import Link from "next/link";
import { useRef, useState } from "react";
import { AudioPlayer, EmptyState, ErrorAlert, Loading, Num, PageHead, QaIssues, StatusTag, seekAudio } from "@/components/common";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type ApprovalItem, type GateState, type OutputItem, type PublishMetadata, type ReleasePackage } from "@/lib/api";
import { fmtBytes, fmtClock, fmtTime } from "@/lib/format";
import { usePoll, useStoredState } from "@/lib/hooks";

function ExportedFiles({ files }: { files: ReleasePackage["exported"] }) {
  if (!files.length) return <Typography.Text type="secondary">No exported files.</Typography.Text>;
  return (
    <Flex vertical gap={2}>
      {files.map((f) => (
        <Flex key={f.path} gap={8} align="center" wrap>
          <Tag style={{ marginInlineEnd: 0 }}>{f.kind}</Tag>
          <Typography.Text className="mono" style={{ fontSize: 12 }} copyable ellipsis={{ tooltip: f.path }}>{f.path}</Typography.Text>
          <span className="num muted" style={{ fontSize: 12 }}>{fmtBytes(f.bytes)}</span>
        </Flex>
      ))}
    </Flex>
  );
}

function MetadataForm({ item, value, onChange, editable, onSaved }: {
  item: ApprovalItem; value: PublishMetadata; onChange: (m: PublishMetadata) => void; editable: boolean; onSaved: (m: PublishMetadata) => void;
}) {
  const { message } = App.useApp();
  const m = value;
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(m) !== JSON.stringify(item.metadata);
  const set = <K extends keyof PublishMetadata>(k: K, v: PublishMetadata[K]) => onChange({ ...m, [k]: v });
  const save = async () => {
    setSaving(true);
    try { await api.saveMetadata(item.series_id, item.episode_number, m); message.success("Metadata saved"); onSaved(m); }
    catch (e) { message.error((e as Error).message); }
    finally { setSaving(false); }
  };
  return (
    <Form layout="vertical" size="small" disabled={!editable}>
      <Form.Item label="YouTube title" style={{ marginBottom: 8 }}>
        <Input value={m.title} onChange={(e) => set("title", e.target.value)} maxLength={100} showCount />
      </Form.Item>
      <Form.Item label="Description" style={{ marginBottom: 8 }}>
        <Input.TextArea value={m.description} onChange={(e) => set("description", e.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} />
      </Form.Item>
      <Row gutter={8}>
        <Col xs={24} md={12}>
          <Form.Item label="Tags" style={{ marginBottom: 8 }}>
            <Select mode="tags" value={m.tags} onChange={(v) => set("tags", v)} tokenSeparators={[","]} open={false} suffixIcon={null} placeholder="Add tags" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Hashtags" style={{ marginBottom: 8 }}>
            <Select mode="tags" value={m.hashtags} onChange={(v) => set("hashtags", v)} tokenSeparators={[",", " "]} open={false} suffixIcon={null} placeholder="#hashtag" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Playlist" style={{ marginBottom: 8 }}><Input value={m.playlist_title} onChange={(e) => set("playlist_title", e.target.value)} /></Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Thumbnail text" style={{ marginBottom: 8 }}><Input value={m.thumbnail_text} onChange={(e) => set("thumbnail_text", e.target.value)} maxLength={60} /></Form.Item>
        </Col>
      </Row>
      {editable && (
        <Button icon={<SaveOutlined />} onClick={save} loading={saving} disabled={!dirty}>Save metadata</Button>
      )}
    </Form>
  );
}

function RejectModal({ item, open, onClose, onDone, reviewer }: { item: ApprovalItem; open: boolean; onClose: () => void; onDone: () => void; reviewer: string }) {
  const { message } = App.useApp();
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const lineOptions = Array.from(new Set([
    ...(item.qa?.review_lines ?? []),
    ...(item.qa?.error_logs ?? []).map((i) => i.line_id ?? i.unit_id).filter((x): x is string => !!x),
  ])).map((l) => ({ value: l, label: l }));
  const submit = async () => {
    setBusy(true);
    try {
      await api.reject(item.series_id, item.episode_number, { reviewer, notes, lines });
      message.success(`Episode ${item.episode_number} rejected`);
      onDone(); onClose();
    } catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onCancel={onClose} title={`Reject ${item.series_title} · Ep ${item.episode_number}`} okText="Reject" okButtonProps={{ danger: true, loading: busy }} onOk={submit} destroyOnHidden>
      <Form layout="vertical">
        <Form.Item label="Notes for the next pass" extra="What should change? The notes travel with the release package.">
          <Input.TextArea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} autoFocus />
        </Form.Item>
        <Form.Item label="Lines to fix (optional)">
          <Select mode="tags" value={lines} onChange={setLines} options={lineOptions} placeholder="ep01_sc01_l003" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function ApprovalCard({ item, reviewer, onChanged }: { item: ApprovalItem; reviewer: string; onChanged: () => void }) {
  const { message, modal } = App.useApp();
  const { refreshGate } = useStudio();
  const audio = useRef<HTMLAudioElement>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approving, setApproving] = useState(false);
  const [exported, setExported] = useState<ReleasePackage["exported"] | null>(null);
  const [saved, setSaved] = useState<PublishMetadata>(item.metadata);
  const [meta, setMeta] = useState<PublishMetadata>(item.metadata);
  const pending = item.state === "awaiting_approval" || item.state === "needs_review";
  const flagged = item.qa_status === "FLAGGED";

  const doApprove = async () => {
    setApproving(true);
    try {
      const pkg = await api.approve(item.series_id, item.episode_number, { reviewer, metadata: meta });
      setExported(pkg.exported);
      modal.success({
        title: `Episode ${item.episode_number} approved`,
        content: <div><Typography.Paragraph type="secondary">Exported files:</Typography.Paragraph><ExportedFiles files={pkg.exported} /></div>,
        width: 560,
      });
      refreshGate();
      onChanged();
    } catch (e) { message.error((e as Error).message); }
    finally { setApproving(false); }
  };
  const approve = () => {
    if (!reviewer.trim()) { message.warning("Enter your reviewer name at the top of the page first."); return; }
    if (flagged) {
      modal.confirm({
        title: "Approve a FLAGGED episode?",
        content: "QA flagged this episode. Approving overrides the QA verdict and is recorded on the release package.",
        okText: "Approve anyway",
        okButtonProps: { danger: true },
        onOk: doApprove,
      });
    } else doApprove();
  };
  const openReject = () => {
    if (!reviewer.trim()) { message.warning("Enter your reviewer name at the top of the page first."); return; }
    setRejectOpen(true);
  };

  const files = exported ?? item.exported;
  return (
    <Card
      size="small"
      title={
        <div style={{ whiteSpace: "normal" }}>
          <Typography.Text strong>{item.series_title}</Typography.Text>
          <Typography.Text type="secondary"> · Ep {item.episode_number}{item.episode_title ? `: ${item.episode_title}` : ""}</Typography.Text>
        </div>
      }
      extra={<StatusTag status={item.state} />}
    >
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={11}>
          <Flex vertical gap={10}>
            <Space wrap size={6}>
              <StatusTag status={item.qa_status}><span className="num">{item.qa_status} {Math.round(item.qa_score)}</span></StatusTag>
              <Tag style={{ marginInlineEnd: 0 }}><span className="num">{item.qa_attempts === 0 ? "first render" : `${item.qa_attempts} QA retr${item.qa_attempts === 1 ? "y" : "ies"}`}</span></Tag>
              <Tag style={{ marginInlineEnd: 0 }}><span className="num">{fmtClock(item.duration_ms)}</span></Tag>
              <Link href={`/productions/detail/?id=${encodeURIComponent(item.series_id)}`} style={{ fontSize: 12 }}>Production</Link>
            </Space>
            {item.reason && <Alert type={item.state === "needs_review" ? "warning" : "info"} showIcon title={item.reason} />}
            <AudioPlayer src={item.master_url ?? api.masterUrl(item.series_id, item.episode_number)} wide audioRef={audio} />
            <div>
              <Typography.Text strong style={{ fontSize: 13 }}>QA issues</Typography.Text>
              <div style={{ maxHeight: 260, overflowY: "auto", marginTop: 4 }}>
                <QaIssues issues={item.qa?.error_logs ?? []} onSeek={(ms) => seekAudio(audio.current, ms)} />
              </div>
            </div>
            {item.decision && (
              <Alert
                type={item.decision.decision === "approved" ? "success" : "error"}
                showIcon
                title={`${item.decision.decision} by ${item.decision.reviewer} · ${fmtTime(item.decision.at)}${item.decision.override_flagged ? " (overrode QA)" : ""}`}
                description={[item.decision.notes, item.decision.lines.length ? `Lines: ${item.decision.lines.join(", ")}` : ""].filter(Boolean).join(" · ") || undefined}
              />
            )}
          </Flex>
        </Col>
        <Col xs={24} lg={13}>
          <MetadataForm item={{ ...item, metadata: saved }} value={meta} onChange={setMeta} editable={pending} onSaved={setSaved} />
          {(files.length > 0 || item.state === "approved") && (
            <div style={{ marginTop: 12 }}>
              <Typography.Text strong style={{ fontSize: 13 }}>Exported files</Typography.Text>
              <div style={{ marginTop: 4 }}><ExportedFiles files={files} /></div>
            </div>
          )}
        </Col>
      </Row>
      {pending && (
        <Flex gap={8} justify="flex-end" wrap style={{ marginTop: 16, borderTop: "1px solid var(--ev-border)", paddingTop: 12 }}>
          <Button danger icon={<CloseOutlined />} onClick={openReject}>Reject</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={approving} onClick={approve}>{flagged ? "Approve (override QA)" : "Approve"}</Button>
        </Flex>
      )}
      <RejectModal item={item} open={rejectOpen} onClose={() => setRejectOpen(false)} onDone={() => { refreshGate(); onChanged(); }} reviewer={reviewer} />
    </Card>
  );
}

function OutputsTable() {
  const { data, error, loading, refresh } = usePoll(() => api.outputs(), 0);
  if (loading && !data) return <Loading card={false} />;
  return (
    <>
      <ErrorAlert error={error} onRetry={refresh} />
      <Table<OutputItem>
        size="small"
        rowKey="key"
        dataSource={data?.items ?? []}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        scroll={{ x: 900 }}
        locale={{ emptyText: <EmptyState description="Nothing exported yet. Approved episodes are exported here." /> }}
        columns={[
          { title: "Series", key: "s", render: (_, o) => <div>{o.metadata?.series_title ?? o.series_id}<div className="mono muted" style={{ fontSize: 11 }}>{o.series_id}</div></div> },
          { title: "File", dataIndex: "file", render: (v: string) => <span className="mono" style={{ fontSize: 12 }}>{v}</span> },
          { title: "Title", key: "t", render: (_, o) => o.metadata?.title ?? <span className="muted">–</span> },
          { title: "Length", key: "d", width: 80, align: "right", render: (_, o) => <Num>{o.metadata?.duration_seconds != null ? fmtClock(o.metadata.duration_seconds * 1000) : "–"}</Num> },
          { title: "Approved", key: "a", width: 170, render: (_, o) => o.metadata?.approved_by ? <span style={{ fontSize: 12 }}>{o.metadata.approved_by}<div className="muted">{fmtTime(o.metadata.approved_at)}</div></span> : <span className="muted">–</span> },
          { title: "Size", dataIndex: "bytes", width: 90, align: "right", render: (v: number) => <Num>{fmtBytes(v)}</Num> },
          {
            title: "", key: "dl", width: 60,
            render: (_, o) => <a href={o.url} download aria-label={`Download ${o.file}`}><Button type="text" icon={<DownloadOutlined />} aria-label={`Download ${o.file}`} /></a>,
          },
        ]}
      />
    </>
  );
}

const BADGE_COLOR: Record<GateState, string> = { awaiting_approval: "#d4a017", needs_review: "#ff4d4f", approved: "#52c41a", rejected: "#8c8c8c" };

const TABS: { key: GateState; label: string }[] = [
  { key: "awaiting_approval", label: "Waiting for approval" },
  { key: "needs_review", label: "Needs review" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

export default function ApprovalsPage() {
  const { data, error, loading, refresh } = usePoll(() => api.approvals(), 15000);
  const [reviewer, setReviewer] = useStoredState("emvoox-reviewer", "");
  const [tab, setTab] = useStoredState<string>("emvoox-approvals-tab", "awaiting_approval");
  const items = data?.items ?? [];

  return (
    <>
      <PageHead
        title="Approvals"
        sub="The human gate: listen, check QA, polish the publish metadata, then approve or send back."
        extra={
          <Input
            prefix={<UserOutlined />}
            placeholder="Reviewer name"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            style={{ width: 220 }}
            aria-label="Reviewer name"
            status={!reviewer.trim() ? "warning" : undefined}
          />
        }
      />
      <ErrorAlert error={error} onRetry={refresh} />
      {loading && !data ? <Loading rows={8} /> : (
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            ...TABS.map((t) => {
              const list = items.filter((i) => i.state === t.key);
              return {
                key: t.key,
                label: <Space size={6}>{t.label}<Badge count={list.length} showZero={false} color={BADGE_COLOR[t.key]} size="small" /></Space>,
                children: list.length ? (
                  <Flex vertical gap={12}>
                    {list.map((i) => <ApprovalCard key={`${i.series_id}-${i.episode_number}`} item={i} reviewer={reviewer} onChanged={refresh} />)}
                  </Flex>
                ) : (
                  <Card size="small"><EmptyState description={t.key === "awaiting_approval" || t.key === "needs_review" ? "Nothing waiting for you." : `No ${t.label.toLowerCase()} episodes.`} /></Card>
                ),
              };
            }),
            { key: "outputs", label: "Exported files", children: <Card size="small"><OutputsTable key={items.filter((i) => i.state === "approved").length} /></Card> },
          ]}
        />
      )}
    </>
  );
}
