"use client";

import { CheckOutlined, CloseOutlined, DollarOutlined, RedoOutlined } from "@ant-design/icons";
import { App, Button, Card, Flex, Input, InputNumber, Select, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useState } from "react";
import { AudioPlayer, Num, QaIssues, StatusTag } from "@/components/common";
import { api, type DecisionAnswer, type DecisionItem } from "@/lib/api";
import { ep, fmtAgo, fmtUsd } from "@/lib/format";

/** One thing a paused run is waiting for: a scene to approve or send back, or a budget to raise. Answering continues the run. */
export function DecisionCard({ item, reviewer, onDone }: { item: DecisionItem; reviewer: string; onDone: () => void }) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState<"yes" | "no" | null>(null);
  const [notes, setNotes] = useState("");
  const [units, setUnits] = useState<string[]>([]);
  const [cap, setCap] = useState<number | null>(item.data.budget_usd != null ? Math.max(1, Math.ceil(item.data.budget_usd * 2)) : null);

  const answer = async (approved: boolean) => {
    if (!reviewer.trim()) { message.warning("Enter your reviewer name first"); return; }
    setBusy(approved ? "yes" : "no");
    const body: DecisionAnswer = { id: item.id, approved, reviewer: reviewer.trim(), notes };
    if (item.kind === "scene_approval" && !approved) body.unit_ids = units;
    if (item.kind === "budget" && approved) body.max_cost_usd = cap;
    try { await api.decide(item.run_id, [body]); message.success("Decision sent; the run continues"); onDone(); }
    catch (e) { message.error((e as Error).message); }
    finally { setBusy(null); }
  };

  const head = (
    <Space wrap size={6}>
      <Link href={`/pipeline/?id=${encodeURIComponent(item.run_id)}`}>{item.series_title}</Link>
      {item.episode != null && <Tag style={{ marginInlineEnd: 0 }}>{ep(item.episode)}</Tag>}
      {item.scene_id && <Tag style={{ marginInlineEnd: 0 }}>{item.scene_id}</Tag>}
      {item.kind === "scene_approval" && <StatusTag status={item.data.qa_status}>{`QA ${item.data.qa_status} ${item.data.score ?? ""}`.trim()}</StatusTag>}
      {(item.data.attempt ?? 0) > 0 && <Tag color="orange" style={{ marginInlineEnd: 0 }}>attempt {item.data.attempt! + 1}</Tag>}
    </Space>
  );

  if (item.kind === "budget") {
    return (
      <Card size="small" title={<Space><DollarOutlined />Budget reached{head}</Space>} extra={<span className="muted" style={{ fontSize: 12 }}>{fmtAgo(item.asked_at)}</span>}>
        <Flex vertical gap={12}>
          <Typography.Text>
            This run has spent <Num>{fmtUsd(item.data.spent_usd ?? 0)}</Num> of its <Num>{fmtUsd(item.data.budget_usd ?? 0)}</Num> budget
            {item.episode != null ? <> and stopped before {ep(item.episode)}</> : null}. Raise the budget to continue, or stop the run here.
          </Typography.Text>
          <Flex gap={8} wrap align="center" justify="flex-end">
            <span className="muted">New budget (USD)</span>
            <InputNumber min={0.01} step={1} value={cap} onChange={setCap} style={{ width: 120 }} aria-label="New budget in USD" />
            <Button danger icon={<CloseOutlined />} loading={busy === "no"} onClick={() => answer(false)}>Stop the run</Button>
            <Button type="primary" icon={<CheckOutlined />} loading={busy === "yes"} disabled={!cap} onClick={() => answer(true)}>Raise and continue</Button>
          </Flex>
        </Flex>
      </Card>
    );
  }

  const scene = item.scene;
  const unitOptions = (item.data.units ?? []).map((u) => ({ value: u, label: u }));
  return (
    <Card size="small" title={head} extra={<span className="muted" style={{ fontSize: 12 }}>{fmtAgo(item.asked_at)}</span>}>
      <Flex vertical gap={12}>
        {scene?.lines.length ? (
          <div style={{ maxHeight: 220, overflowY: "auto" }}>
            {scene.lines.map((l) => (
              <div key={l.unit_id} style={{ fontSize: 13, padding: "2px 0" }}>
                <span className="mono muted" style={{ fontSize: 11 }}>{l.unit_id.split("_").pop()}</span>{" "}
                <b>{l.speaker_id}</b>{l.emotion ? <span className="muted"> ({l.emotion}{l.intensity != null ? ` ${l.intensity}` : ""})</span> : null}: {l.text}
              </div>
            ))}
          </div>
        ) : null}
        {scene?.stems.length ? (
          <Flex vertical gap={4}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>Listen (the episode is mastered after every scene is approved)</Typography.Text>
            {scene.stems.map((s) => (
              <Flex key={s.name} gap={8} align="center" wrap>
                <span className="mono" style={{ fontSize: 12, width: 120 }}>{s.unit_id.replace(/^ep\d+_/, "")}</span>
                <AudioPlayer src={s.url} />
              </Flex>
            ))}
          </Flex>
        ) : null}
        {scene?.qa?.error_logs.length ? <QaIssues issues={scene.qa.error_logs} /> : null}
        <Flex gap={8} wrap align="center">
          <Select mode="multiple" allowClear value={units} onChange={setUnits} options={unitOptions} placeholder="Reject: units to render again (default: the whole scene)"
            style={{ minWidth: 300, flex: 1 }} aria-label="Units to render again" />
          <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (optional)" style={{ minWidth: 200, flex: 1 }} aria-label="Notes" />
        </Flex>
        <Flex gap={8} justify="flex-end" wrap>
          <Button danger icon={<RedoOutlined />} loading={busy === "no"} onClick={() => answer(false)}>Reject and render again</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={busy === "yes"} onClick={() => answer(true)}>
            {item.data.qa_status === "FLAGGED" ? "Approve scene (override QA)" : "Approve scene"}
          </Button>
        </Flex>
      </Flex>
    </Card>
  );
}
