"use client";

import {
  CheckOutlined, CloseOutlined, DeleteOutlined, LoadingOutlined, PlusOutlined, RobotOutlined, SendOutlined, ToolOutlined, UserOutlined,
} from "@ant-design/icons";
import { Alert, App, Button, Card, Col, Collapse, Flex, Input, Popconfirm, Progress, Row, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AudioPlayer, EmptyState, ErrorAlert, Loading, Num, PageHead, StatusTag } from "@/components/common";
import { DecisionCard } from "@/components/DecisionCard";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type ApprovalItem, type ChatItem, type ChatRun, type ChatThread, type ChatView } from "@/lib/api";
import { ep, fmtAgo, fmtUsd } from "@/lib/format";
import { useMemoryState, usePoll, useStoredState } from "@/lib/hooks";
import { isLive } from "@/lib/status";

const EXAMPLES = [
  "Làm một series 10 tập thể loại trọng sinh cho khán giả nữ 25-34",
  "Tìm 3 thể loại phim ngắn đang hot nhất rồi đề xuất một series cho kênh Mặc Khải",
  "Tôi đã có truyện, hãy sản xuất tập đầu để nghe thử",
];
const TOOL_LABEL: Record<string, string> = {
  spawn_subagent: "Handed to a specialist agent", ask_user: "Question", production_start: "Start production", production_continue: "Continue production",
  library_list_briefs: "Read trend briefs", library_list_series: "Read productions", library_get_series: "Read a production",
  library_list_voice_ips: "Read Voice IPs", library_run_status: "Checked the run",
};

type ToolItem = Extract<ChatItem, { kind: "tool" }>;

function short(v: unknown, max = 90): string {
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

/** A tool call that ran (or failed): one quiet line, expandable. */
function ToolLine({ item }: { item: ToolItem }) {
  const args = Object.entries(item.args ?? {}).map(([k, v]) => `${k}: ${short(v, 60)}`).join(" · ");
  return (
    <Collapse
      size="small"
      ghost
      items={[{
        key: "t",
        label: (
          <Space size={6} wrap>
            <ToolOutlined className="muted" />
            <span style={{ fontSize: 13 }}>{TOOL_LABEL[item.tool] ?? item.tool}</span>
            <Tag color={item.status === "failed" ? "error" : item.status === "running" ? "processing" : "default"} style={{ marginInlineEnd: 0 }}
              icon={item.status === "running" ? <LoadingOutlined /> : undefined}>{item.status}</Tag>
            {args && <span className="muted" style={{ fontSize: 12 }}>{short(args, 110)}</span>}
          </Space>
        ),
        children: <pre className="ev-pre" style={{ maxHeight: 240, fontSize: 11.5 }}>{JSON.stringify({ tool: item.tool, args: item.args, result: item.result }, null, 2)}</pre>,
      }]}
    />
  );
}

/** The agent is waiting for the person: a question to answer, or a tool call (money) to approve. */
function PendingCard({ item, busy, onAnswer }: { item: ToolItem; busy: boolean; onAnswer: (a: { answer?: string; approved?: boolean; notes?: string }) => void }) {
  const p = item.pending!;
  const [text, setText] = useState("");
  if (p.kind === "question") {
    return (
      <Card size="small" style={{ borderColor: "var(--ev-navy)" }} title={<Space><RobotOutlined />The Producer asks</Space>}>
        <Flex vertical gap={12}>
          <Typography.Text strong>{p.message}</Typography.Text>
          {p.options.length > 0 && (
            <Flex gap={8} wrap>
              {p.options.map((o) => <Button key={o} onClick={() => onAnswer({ answer: o })} disabled={busy}>{o}</Button>)}
            </Flex>
          )}
          <Space.Compact style={{ width: "100%" }}>
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={p.options.length ? "Or type another answer" : "Your answer"}
              onPressEnter={() => text.trim() && onAnswer({ answer: text.trim() })} disabled={busy} aria-label="Answer" />
            <Button type="primary" icon={<SendOutlined />} disabled={!text.trim() || busy} onClick={() => onAnswer({ answer: text.trim() })}>Answer</Button>
          </Space.Compact>
        </Flex>
      </Card>
    );
  }
  const a = item.args as Record<string, unknown>;
  const rows: [string, React.ReactNode][] = item.tool === "production_start" ? [
    ["Source", a.source === "brief" ? `trend brief ${a.brief_id ?? ""}${a.genre_index != null ? ` · genre #${Number(a.genre_index) + 1}` : ""}` : `own story “${a.title ?? ""}”`],
    ["Episodes", `${a.produce ?? 1} now, of ${a.episodes ?? 10} planned`],
    ["Scene approval", a.scene_approval ? "every scene waits for you" : "off"],
    ["Budget", a.max_cost_usd ? fmtUsd(Number(a.max_cost_usd)) : "no cap"],
  ] : Object.entries(a).map(([k, v]) => [k, short(v, 120)]);
  return (
    <Card size="small" style={{ borderColor: "#fa8c16" }} title={<Space><ToolOutlined />Approval needed: {TOOL_LABEL[item.tool] ?? item.tool}</Space>}>
      <Flex vertical gap={12}>
        <Typography.Text type="secondary">This step spends vendor credits, so the Producer waits for you. Nothing is published without a further approval.</Typography.Text>
        <div>
          {rows.map(([k, v]) => <Flex key={k} gap={8}><span className="muted" style={{ width: 130, flex: "none" }}>{k}</span><span>{v}</span></Flex>)}
        </div>
        <Flex gap={8} wrap justify="flex-end">
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Why not, or what to change (optional)" style={{ flex: 1, minWidth: 200 }} aria-label="Notes" />
          <Button danger icon={<CloseOutlined />} disabled={busy} onClick={() => onAnswer({ approved: false, notes: text })}>Decline</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={busy} onClick={() => onAnswer({ approved: true })}>Approve and start</Button>
        </Flex>
      </Flex>
    </Card>
  );
}

function EpisodeGate({ item, reviewer, onChanged }: { item: ApprovalItem; reviewer: string; onChanged: () => void }) {
  const { message } = App.useApp();
  const { refreshGate } = useStudio();
  const [busy, setBusy] = useState(false);
  const pending = item.state === "awaiting_approval" || item.state === "needs_review";
  const approve = async () => {
    if (!reviewer.trim()) { message.warning("Enter your reviewer name first"); return; }
    setBusy(true);
    try { await api.approve(item.series_id, item.episode_number, { reviewer: reviewer.trim() }); message.success(`${ep(item.episode_number)} approved and exported`); refreshGate(); onChanged(); }
    catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <Flex gap={12} align="center" wrap style={{ padding: "8px 0", borderTop: "1px solid var(--ev-border)" }}>
      <Tag style={{ marginInlineEnd: 0 }}>{ep(item.episode_number)}</Tag>
      <StatusTag status={item.state} />
      <StatusTag status={item.qa_status}>{`QA ${item.qa_status} ${item.qa_score ?? ""}`.trim()}</StatusTag>
      <div style={{ flex: 1, minWidth: 220 }}><AudioPlayer src={item.master_url} /></div>
      {pending && <Button type="primary" size="small" icon={<CheckOutlined />} loading={busy} onClick={approve}>{item.qa_status === "FLAGGED" ? "Approve (override QA)" : "Approve"}</Button>}
      <Link href="/approvals/">{pending ? "Reject or edit metadata" : "Open"}</Link>
    </Flex>
  );
}

function RunCard({ run, reviewer, onChanged }: { run: ChatRun; reviewer: string; onChanged: () => void }) {
  const pct = run.progress.total ? Math.round((run.progress.done / run.progress.total) * 100) : 0;
  return (
    <Card size="small" title={<Space wrap><Link href={`/pipeline/?id=${encodeURIComponent(run.run_id)}`}>{run.title}</Link><StatusTag status={run.status} /></Space>}
      extra={<span className="muted num" style={{ fontSize: 12 }}>{fmtUsd(run.cost_usd)}{run.budget_usd != null ? ` / ${fmtUsd(run.budget_usd)}` : ""}</span>}>
      <Flex vertical gap={10}>
        <Flex gap={12} align="center">
          <Progress percent={pct} size="small" style={{ flex: 1, margin: 0 }} status={run.status === "failed" ? "exception" : isLive(run.status) ? "active" : undefined} />
          {run.current && <span className="muted" style={{ fontSize: 12 }}>{run.current}</span>}
        </Flex>
        {run.error && <Alert type={run.status === "failed" ? "error" : "warning"} showIcon title={run.error} />}
        {run.decisions.map((d) => <DecisionCard key={d.id} item={d} reviewer={reviewer} onDone={onChanged} />)}
        {run.episodes.map((e) => <EpisodeGate key={e.episode_number} item={e} reviewer={reviewer} onChanged={onChanged} />)}
      </Flex>
    </Card>
  );
}

function Bubble({ who, children }: { who: "user" | "assistant"; children: React.ReactNode }) {
  const mine = who === "user";
  return (
    <Flex justify={mine ? "flex-end" : "flex-start"}>
      <div style={{
        maxWidth: "82%", padding: "8px 12px", borderRadius: 12, whiteSpace: "pre-wrap", wordBreak: "break-word",
        background: mine ? "var(--ev-navy)" : "var(--ev-sunken)", color: mine ? "#fff" : undefined, border: mine ? undefined : "1px solid var(--ev-border)",
      }}>{children}</div>
    </Flex>
  );
}

function Conversation({ view, reviewer, refresh }: { view: ChatView; reviewer: string; refresh: () => void }) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [view.items.length, view.thread.status, view.runs.length]);
  const answer = async (id: string, a: { answer?: string; approved?: boolean; notes?: string }) => {
    setBusy(true);
    try { await api.chatAnswer(view.thread.id, [{ id, ...a, reviewer }]); refresh(); }
    catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <Flex vertical gap={10}>
      {view.items.map((it, i) => {
        if (it.kind !== "tool") return <Bubble key={i} who={it.kind}>{it.text}</Bubble>;
        if (it.pending) return <PendingCard key={it.id} item={it} busy={busy} onAnswer={(a) => answer(it.pending!.id, a)} />;
        if (it.tool === "ask_user") return null; // answered: the question and its answer read as the next lines of the conversation
        return <ToolLine key={it.id} item={it} />;
      })}
      {view.thread.status === "running" && <Flex gap={8} align="center" className="muted"><LoadingOutlined /> The Producer is working…</Flex>}
      {view.thread.status === "failed" && <Alert type="error" showIcon title="The Producer could not finish this turn" description={view.thread.error} />}
      {view.thread.status === "idle" && view.thread.error && <Alert type="warning" showIcon title={view.thread.error} />}
      {view.runs.map((r) => <RunCard key={r.run_id} run={r} reviewer={reviewer} onChanged={refresh} />)}
      <div ref={end} />
    </Flex>
  );
}

export default function ChatPage() {
  const { message } = App.useApp();
  const threads = usePoll(() => api.chatThreads(), 8000);
  const [selected, setSelected] = useMemoryState<string | null>("chat.thread", null);
  const [draft, setDraft] = useMemoryState("chat.draft", "");
  const [reviewer, setReviewer] = useStoredState("emvoox-reviewer", "");
  const [sending, setSending] = useState(false);
  const [view, setView] = useState<ChatView | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Follow the open thread: quickly while the Producer or one of its runs is working, slowly otherwise.
  const busy = view?.thread.status === "running" || (view?.runs ?? []).some((r) => isLive(r.status));
  useEffect(() => {
    if (!selected) { setView(null); return; }
    let alive = true;
    const load = async () => {
      try { const v = await api.chatThread(selected); if (alive) { setView(v); setError(null); } }
      catch (e) { if (alive) setError((e as Error).message); }
    };
    load();
    const id = setInterval(load, busy ? 1500 : 10000);
    return () => { alive = false; clearInterval(id); };
  }, [selected, busy]);
  const refresh = async () => { if (selected) { try { setView(await api.chatThread(selected)); } catch { /* next poll */ } } threads.refresh(); };

  const send = async (text: string) => {
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      const v = selected && view ? await api.chatSend(selected, text.trim()) : await api.chatStart(text.trim(), reviewer);
      setView(v); setSelected(v.thread.id); setDraft(""); threads.refresh();
    } catch (e) { message.error((e as Error).message); }
    finally { setSending(false); }
  };
  const remove = async (t: ChatThread) => {
    try { await api.chatDelete(t.id); if (selected === t.id) { setSelected(null); setView(null); } threads.refresh(); }
    catch (e) { message.error((e as Error).message); }
  };
  const working = view?.thread.status === "running";
  const waiting = view?.thread.status === "waiting";

  return (
    <>
      <PageHead
        title="Producer chat"
        sub="Describe what you want to make. The Producer researches, plans and produces, and stops only where the decision is yours."
        extra={<Input prefix={<UserOutlined />} placeholder="Your name (for approvals)" value={reviewer} onChange={(e) => setReviewer(e.target.value)}
          style={{ width: 230 }} aria-label="Reviewer name" status={!reviewer.trim() ? "warning" : undefined} />}
      />
      <ErrorAlert error={threads.error ?? error} onRetry={refresh} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={7} xl={6}>
          <Card size="small" title="Conversations" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => { setSelected(null); setView(null); }}>New</Button>}
            styles={{ body: { padding: 8 } }}>
            {threads.loading && !threads.data ? <Loading card={false} rows={3} /> : (threads.data?.threads.length ? (
              <Flex vertical gap={2} style={{ maxHeight: "62vh", overflowY: "auto" }}>
                {threads.data.threads.map((t) => (
                  <Flex key={t.id} align="center" gap={4} className="ev-issue seekable"
                    style={{ paddingLeft: 10, background: t.id === selected ? "var(--ev-sunken)" : undefined, boxShadow: t.id === selected ? "inset 3px 0 0 var(--ev-navy)" : undefined }}>
                    <div role="button" tabIndex={0} style={{ flex: 1, minWidth: 0 }} onClick={() => setSelected(t.id)} onKeyDown={(e) => { if (e.key === "Enter") setSelected(t.id); }}>
                      <Typography.Text strong ellipsis style={{ display: "block" }}>{t.title}</Typography.Text>
                      <Space size={6}>
                        {t.status !== "idle" && <StatusTag status={t.status} />}
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{fmtAgo(t.updated_at)}</Typography.Text>
                      </Space>
                    </div>
                    <Popconfirm title="Delete this conversation?" description="Productions it started are kept." okText="Delete" okButtonProps={{ danger: true }} onConfirm={() => remove(t)}>
                      <Button type="text" size="small" icon={<DeleteOutlined />} aria-label="Delete conversation" />
                    </Popconfirm>
                  </Flex>
                ))}
              </Flex>
            ) : <EmptyState description="No conversations yet." />)}
          </Card>
        </Col>
        <Col xs={24} lg={17} xl={18}>
          <Card size="small" styles={{ body: { display: "flex", flexDirection: "column", gap: 12, minHeight: "62vh" } }}>
            <div style={{ flex: 1, overflowY: "auto", maxHeight: "58vh", paddingRight: 4 }}>
              {view ? <Conversation view={view} reviewer={reviewer} refresh={refresh} /> : selected ? <Loading card={false} rows={6} /> : (
                <Flex vertical gap={12} align="center" justify="center" style={{ minHeight: "40vh", textAlign: "center" }}>
                  <RobotOutlined style={{ fontSize: 34, color: "var(--ev-navy)" }} />
                  <Typography.Title level={4} style={{ margin: 0 }}>What do you want to make?</Typography.Title>
                  <Typography.Text type="secondary">One message is enough. You will be asked to choose a genre, to approve the spend, and to approve each finished episode.</Typography.Text>
                  <Flex gap={8} wrap justify="center">
                    {EXAMPLES.map((e) => <Button key={e} onClick={() => setDraft(e)} style={{ whiteSpace: "normal", height: "auto", textAlign: "left" }}>{e}</Button>)}
                  </Flex>
                </Flex>
              )}
            </div>
            <Space.Compact style={{ width: "100%" }}>
              <Input.TextArea value={draft} onChange={(e) => setDraft(e.target.value)} autoSize={{ minRows: 1, maxRows: 6 }} disabled={working}
                placeholder={working ? "The Producer is working…" : waiting ? "Answer above, or type your reply here" : "Describe your idea, paste a story, or ask about a production"}
                onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(draft); } }} aria-label="Message" />
              <Button type="primary" icon={<SendOutlined />} loading={sending} disabled={!draft.trim() || working} onClick={() => send(draft)} style={{ height: "auto" }}>Send</Button>
            </Space.Compact>
            {view && <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              This conversation: <Num>{view.usage.steps}</Num> model turns · <Num>{fmtUsd(view.usage.cost_usd)}</Num>
            </Typography.Text>}
          </Card>
        </Col>
      </Row>
    </>
  );
}
