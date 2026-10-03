"use client";

import { ApiOutlined, CheckCircleFilled, CloseCircleFilled, QuestionCircleFilled, ThunderboltOutlined } from "@ant-design/icons";
import { App, Button, Card, Col, Descriptions, Flex, Row, Steps, Table, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";
import { EmptyState, ErrorAlert, Loading, Num, PageHead } from "@/components/common";
import { useStudio } from "@/components/providers/StudioProvider";
import { api, type AgentInfo, type Config, type DoctorCheck } from "@/lib/api";
import { usePoll } from "@/lib/hooks";

const LLM_KEY_ENV: Record<string, string> = { openai: "OPENAI_API_KEY", anthropic: "ANTHROPIC_API_KEY", gemini: "GEMINI_API_KEY", wavespeed: "WAVESPEED_API_KEY", elevenlabs: "ELEVENLABS_API_KEY" };

function keyRows(config: Config) {
  return (Object.keys(config.keys) as (keyof Config["keys"])[]).map((k) => {
    const prov = config.catalog.providers.find((p) => p.id === k);
    const uses = [prov ? "TTS" : null, config.llm.providers.includes(k as never) ? "LLM" : null].filter(Boolean).join(" + ");
    return { provider: prov?.label ?? k, id: k, env: prov?.key_env ?? LLM_KEY_ENV[k] ?? `${k.toUpperCase()}_API_KEY`, present: config.keys[k], uses };
  });
}

const CheckIcon = ({ ok }: { ok: boolean | null }) =>
  ok === true ? <CheckCircleFilled style={{ color: "#52c41a" }} aria-label="ok" />
    : ok === false ? <CloseCircleFilled style={{ color: "#ff4d4f" }} aria-label="failed" />
      : <QuestionCircleFilled className="muted" aria-label="not checked" />;

function Doctor() {
  const { message } = App.useApp();
  const { data, error, loading, refresh, setData } = usePoll(() => api.doctor(false), 0);
  const [live, setLive] = useState(false);
  const runLive = async () => {
    setLive(true);
    try { setData(await api.doctor(true)); message.success("Live checks finished"); }
    catch (e) { message.error((e as Error).message); }
    finally { setLive(false); }
  };
  return (
    <Card
      title="Health checks"
      size="small"
      extra={<Button icon={<ThunderboltOutlined />} loading={live} onClick={runLive}>Run live checks</Button>}
    >
      <ErrorAlert error={error} onRetry={refresh} />
      {loading && !data ? <Loading card={false} rows={4} /> : (
        <Table<DoctorCheck>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={data?.checks ?? []}
          scroll={{ x: 520 }}
          locale={{ emptyText: <EmptyState description="No checks reported" /> }}
          columns={[
            { title: "", dataIndex: "ok", width: 40, render: (v: boolean | null) => <CheckIcon ok={v} /> },
            { title: "Check", dataIndex: "label", width: 220 },
            { title: "Detail", dataIndex: "detail", render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12, wordBreak: "break-word" }}>{v}</Typography.Text> },
          ]}
        />
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>Live checks call each configured vendor once (a tiny request) to verify keys and quotas.</Typography.Text>
    </Card>
  );
}

function Fleet() {
  const { data, error, loading, refresh } = usePoll(() => api.agents(), 0);
  return (
    <Card title="Agent fleet" size="small">
      <ErrorAlert error={error} onRetry={refresh} />
      {loading && !data ? <Loading card={false} rows={6} /> : (
        <Table<AgentInfo>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={data?.agents ?? []}
          scroll={{ x: 900 }}
          columns={[
            { title: "#", key: "i", width: 40, render: (_, __, i) => <Num>{i + 1}</Num> },
            { title: "Agent", key: "a", width: 260, render: (_, a) => <div><Typography.Text strong>{a.title}</Typography.Text><div className="muted" style={{ fontSize: 12 }}>{a.description}</div></div> },
            {
              title: "Contract", key: "c", width: 280,
              render: (_, a) => (
                <Flex vertical gap={2} style={{ fontSize: 12 }}>
                  <span><span className="muted">in </span><span className="mono">{a.consumes}</span></span>
                  <span><span className="muted">out </span><span className="mono">{a.produces ?? "–"}</span></span>
                </Flex>
              ),
            },
            {
              title: "Skills", dataIndex: "skills",
              render: (skills: AgentInfo["skills"]) => (
                <Flex gap={4} wrap>
                  {skills.map((s) => <Tooltip key={s.id} title={s.description}><Tag style={{ marginInlineEnd: 0 }}>{s.name}</Tag></Tooltip>)}
                </Flex>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}

export default function SettingsPage() {
  const { config, configError, refreshConfig } = useStudio();
  return (
    <>
      <PageHead title="Settings" sub="Engine health, keys, defaults and the agent fleet. Change values in .env on the engine host, then restart it." />
      <ErrorAlert error={configError} onRetry={refreshConfig} />
      <Flex vertical gap={16}>
        <Doctor />
        {!config ? <Loading rows={6} /> : (
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={12}>
              <Card title="API keys" size="small" style={{ height: "100%" }}>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={false}
                  dataSource={keyRows(config)}
                  scroll={{ x: 420 }}
                  columns={[
                    { title: "Provider", dataIndex: "provider" },
                    { title: "Used for", dataIndex: "uses", render: (v: string) => <span className="muted" style={{ fontSize: 12 }}>{v || "–"}</span> },
                    { title: "Env var", dataIndex: "env", render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
                    { title: "Present", dataIndex: "present", width: 90, render: (v: boolean) => <Tag color={v ? "success" : "default"} style={{ marginInlineEnd: 0 }}>{v ? "set" : "missing"}</Tag> },
                  ]}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>Keys are read from .env by the engine; the browser never sees their values.</Typography.Text>
              </Card>
            </Col>
            <Col xs={24} xl={12}>
              <Card title="Defaults" size="small" style={{ height: "100%" }}>
                <Descriptions
                  size="small"
                  bordered
                  column={1}
                  items={[
                    { key: "v", label: "Engine version", children: <span className="mono">{config.version}</span> },
                    { key: "llm", label: "LLM", children: <span>{config.llm.provider} · <span className="mono">{config.llm.model}</span></span> },
                    { key: "tts", label: "TTS", children: <span>{config.tts.provider} · <span className="mono">{config.tts.model}</span> · {config.tts.batching}</span> },
                    { key: "st", label: "Storage", children: <span>{config.storage.backend} · <span className="mono" style={{ wordBreak: "break-all" }}>{config.storage.root}</span></span> },
                    { key: "fmt", label: "Episodes", children: <Num>{config.defaults.episodes} planned, {config.defaults.produce} produced per run, {config.defaults.min_sec}-{config.defaults.max_sec}s</Num> },
                    { key: "qa", label: "QA", children: `${config.defaults.max_retries} retries · ${config.defaults.auto_approve ? "auto-approve PASS" : "human approval"} · ${config.defaults.halt_on_qa_fail ? "halt on fail" : "continue on fail"} · transcribe ${config.defaults.qa_transcribe ? "on" : "off"}` },
                    { key: "mix", label: "Mix", children: <Num>{config.defaults.loudness_lufs} LUFS · {config.defaults.true_peak_dbtp} dBTP · BGM {config.defaults.enable_bgm ? "on" : "off"} · SFX {config.defaults.enable_sfx ? "on" : "off"}</Num> },
                    { key: "rb", label: "Research browser", children: config.defaults.research_use_browser ? "on (Playwright)" : "off" },
                    { key: "mock", label: "Mock engine", children: config.mock_enabled ? "enabled" : "hidden" },
                  ]}
                />
              </Card>
            </Col>
          </Row>
        )}
        <Fleet />
        <Card title={<Flex gap={8} align="center"><ApiOutlined />Plugging in WaveSpeed</Flex>} size="small">
          <Steps
            orientation="vertical"
            size="small"
            current={-1}
            items={[
              { title: "Add the key", content: <span>Put <Typography.Text code>WAVESPEED_API_KEY=…</Typography.Text> in the engine&apos;s <Typography.Text code>.env</Typography.Text>.</span>, status: config?.keys.wavespeed ? "finish" : "wait" },
              { title: "Restart the engine", content: <Typography.Text code>python -m emvoox serve</Typography.Text>, status: "wait" },
              { title: "Run live checks", content: "Use the button above: the WaveSpeed check should turn green and the Costs page shows the balance.", status: "wait" },
              { title: "Pick it in New production", content: "Choose WaveSpeed as the LLM provider and/or the TTS engine in step 3, or plug a WaveSpeed voice into a Voice IP.", status: "wait" },
            ]}
          />
        </Card>
      </Flex>
    </>
  );
}
