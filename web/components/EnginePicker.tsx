"use client";

import { WarningOutlined } from "@ant-design/icons";
import { Alert, AutoComplete, Flex, Segmented, Select, Tooltip } from "antd";
import type { Batching, Config, Provider, ProviderInfo } from "@/lib/api";

/** Providers the operator may pick: "mock" only when the backend enables it. */
export function visibleProviders(config: Config): ProviderInfo[] {
  return config.catalog.providers.filter((p) => p.id !== "mock" || config.mock_enabled);
}

export function providerHasKey(config: Config, p: Provider): boolean {
  if (p === "mock") return true;
  return !!config.keys[p as keyof Config["keys"]];
}

export interface EngineValue { provider: Provider; model: string | null; batching: Batching }

export function ProviderSegmented({ config, value, onChange }: { config: Config; value: Provider; onChange: (p: Provider) => void }) {
  return (
    <Segmented<Provider>
      value={value}
      onChange={onChange}
      options={visibleProviders(config).map((p) => ({
        value: p.id,
        label: (
          <Tooltip title={providerHasKey(config, p.id) ? p.billing : `${p.key_env} is not set`}>
            <span>{p.label}{!providerHasKey(config, p.id) && <WarningOutlined style={{ marginLeft: 6, color: "#faad14" }} aria-label="key missing" />}</span>
          </Tooltip>
        ),
      }))}
    />
  );
}

export function ModelSelect({ provider, value, onChange, allowFree, style }: {
  provider: ProviderInfo | undefined; value: string | null; onChange: (m: string | null) => void; allowFree?: boolean; style?: React.CSSProperties;
}) {
  const placeholder = provider?.default_model ? `Default: ${provider.default_model}` : "Default model";
  if (allowFree) {
    // Free text allowed (e.g. a WaveSpeed model path); catalog models are suggestions.
    return (
      <AutoComplete
        style={{ width: 320, maxWidth: "100%", ...style }}
        value={value ?? ""}
        onChange={(v: string) => onChange(v ? v : null)}
        placeholder={placeholder}
        allowClear
        options={(provider?.models ?? []).map((m) => ({ value: m.id, label: <span>{m.label} <span className="muted mono" style={{ fontSize: 11 }}>{m.id}</span></span> }))}
        showSearch={{ filterOption: (input, opt) => String(opt?.value ?? "").toLowerCase().includes(input.toLowerCase()) }}
        aria-label="Model"
      />
    );
  }
  return (
    <Select
      style={{ width: 320, maxWidth: "100%", ...style }}
      value={value ?? undefined}
      placeholder={placeholder}
      allowClear
      onChange={(v) => onChange(v ?? null)}
      showSearch={{ optionFilterProp: "search" }}
      aria-label="Model"
      options={(provider?.models ?? []).map((m) => ({
        value: m.id,
        search: `${m.label} ${m.id}`,
        label: (
          <Tooltip title={m.note || undefined} placement="right">
            <span>{m.label}{m.tags && <span className="muted" style={{ fontSize: 11 }}> · audio tags</span>}{m.id === provider?.default_model && <span className="muted" style={{ fontSize: 11 }}> · default</span>}</span>
          </Tooltip>
        ),
      }))}
    />
  );
}

export function BatchingSegmented({ value, onChange }: { value: Batching; onChange: (b: Batching) => void }) {
  return (
    <Segmented<Batching>
      value={value}
      onChange={onChange}
      options={[
        { value: "auto", label: <Tooltip title="Engine default (scene batching where supported)">Auto</Tooltip> },
        { value: "scene", label: <Tooltip title="One multi-speaker request per scene chunk: 1-3 requests per episode">Scene</Tooltip> },
        { value: "line", label: <Tooltip title="One request per line: more control, many more requests">Line</Tooltip> },
      ]}
    />
  );
}

/** Engine + model + batching, used by New production and Continue producing. */
export function EnginePicker({ config, value, onChange }: { config: Config; value: EngineValue; onChange: (v: EngineValue) => void }) {
  const prov = config.catalog.providers.find((p) => p.id === value.provider);
  return (
    <Flex vertical gap={10}>
      <div style={{ overflowX: "auto", maxWidth: "100%" }}>
        <ProviderSegmented config={config} value={value.provider} onChange={(p) => onChange({ ...value, provider: p, model: null })} />
      </div>
      <Flex gap={10} wrap align="center">
        <ModelSelect provider={prov} value={value.model} onChange={(m) => onChange({ ...value, model: m })} />
        {prov?.scene_batching && <BatchingSegmented value={value.batching} onChange={(b) => onChange({ ...value, batching: b })} />}
      </Flex>
      {!providerHasKey(config, value.provider) && (
        <Alert type="warning" showIcon title={`${prov?.label ?? value.provider} key is missing`} description={`Set ${prov?.key_env ?? "the API key"} in .env and restart the engine, or pick another engine.`} />
      )}
      {prov?.billing && <div className="muted" style={{ fontSize: 12 }}>{prov.billing}</div>}
    </Flex>
  );
}
