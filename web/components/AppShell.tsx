"use client";

import {
  AppstoreOutlined, AuditOutlined, CustomerServiceOutlined, DashboardOutlined, DesktopOutlined, DollarOutlined, MenuOutlined,
  MoonOutlined, NodeIndexOutlined, PlusCircleOutlined, RiseOutlined, SettingOutlined, SunOutlined,
} from "@ant-design/icons";
import { Badge, Breadcrumb, Button, Drawer, Grid, Layout, Menu, Segmented, Space, Tag, Tooltip, type MenuProps } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useStoredState } from "@/lib/hooks";
import { ErrorAlert } from "./common";
import { useStudio } from "./providers/StudioProvider";
import { useThemeMode, type ThemeMode } from "./providers/ThemeProvider";

interface NavItem { key: string; href: string; label: string; icon: React.ReactNode }

export const NAV: NavItem[] = [
  { key: "dashboard", href: "/", label: "Dashboard", icon: <DashboardOutlined /> },
  { key: "productions", href: "/productions/", label: "Productions", icon: <AppstoreOutlined /> },
  { key: "new", href: "/new/", label: "New production", icon: <PlusCircleOutlined /> },
  { key: "pipeline", href: "/pipeline/", label: "Pipeline", icon: <NodeIndexOutlined /> },
  { key: "approvals", href: "/approvals/", label: "Approvals", icon: <AuditOutlined /> },
  { key: "voices", href: "/voices/", label: "Voice IPs", icon: <CustomerServiceOutlined /> },
  { key: "research", href: "/research/", label: "Market research", icon: <RiseOutlined /> },
  { key: "costs", href: "/costs/", label: "Costs", icon: <DollarOutlined /> },
  { key: "settings", href: "/settings/", label: "Settings", icon: <SettingOutlined /> },
];

function sectionOf(pathname: string) {
  const seg = pathname.split("/").filter(Boolean)[0] ?? "";
  return NAV.find((n) => n.key === seg) ?? NAV[0];
}

function Brand({ collapsed, dark }: { collapsed: boolean; dark: boolean }) {
  return (
    <Link href="/" className="ev-brand" aria-label="Emvoox Studio home" style={collapsed ? { justifyContent: "center", padding: 0 } : undefined}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={dark ? "/brand/emvoox-mark-light.png" : "/brand/emvoox-mark.png"} alt="" width={30} height={30} style={{ objectFit: "contain" }} />
      {!collapsed && <span className="name">Emvoox<small>Studio</small></span>}
    </Link>
  );
}

function ThemeSwitch() {
  const { mode, setMode } = useThemeMode();
  return (
    <Segmented<ThemeMode>
      size="small"
      value={mode}
      onChange={setMode}
      aria-label="Colour theme"
      options={[
        { value: "light", icon: <Tooltip title="Light"><SunOutlined aria-label="Light theme" /></Tooltip> },
        { value: "dark", icon: <Tooltip title="Dark"><MoonOutlined aria-label="Dark theme" /></Tooltip> },
        { value: "system", icon: <Tooltip title="System"><DesktopOutlined aria-label="System theme" /></Tooltip> },
      ]}
    />
  );
}

const KEY_LABELS: [keyof NonNullable<ReturnType<typeof useStudio>["config"]>["keys"], string][] = [
  ["gemini", "Gemini"], ["elevenlabs", "ElevenLabs"], ["wavespeed", "WaveSpeed"],
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const section = sectionOf(pathname);
  const { config, configError, refreshConfig, gateCount } = useStudio();
  const { resolved } = useThemeMode();
  const screens = Grid.useBreakpoint();
  const mobile = screens.lg === false;
  const [collapsed, setCollapsed] = useStoredState("emvoox-sider-collapsed", false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => { setDrawerOpen(false); }, [pathname]);
  useEffect(() => { document.title = `${section.label} · Emvoox Studio`; }, [section.label]);

  const menuItems: MenuProps["items"] = useMemo(() => NAV.map((n) => ({
    key: n.key,
    icon: n.icon,
    label: (
      <Link href={n.href}>
        {n.key === "approvals" && gateCount > 0 ? (
          <Space size={8}>{n.label}<Badge count={gateCount} size="small" /></Space>
        ) : n.label}
      </Link>
    ),
  })), [gateCount]);

  const menu = <Menu mode="inline" selectedKeys={[section.key]} items={menuItems} style={{ borderInlineEnd: 0 }} />;
  const isDetail = pathname.startsWith("/productions/detail");
  const crumbs = [
    { title: <Link href={section.href}>{section.label}</Link> },
    ...(isDetail ? [{ title: "Production" }] : []),
  ];
  const activeRun = config?.active_run;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      {!mobile && (
        <Layout.Sider
          collapsible
          collapsed={collapsed}
          onCollapse={(c) => setCollapsed(c)}
          width={232}
          collapsedWidth={72}
          theme="light"
          style={{ position: "sticky", top: 0, height: "100vh", overflow: "auto", borderInlineEnd: "1px solid var(--ev-border)" }}
        >
          <Brand collapsed={collapsed} dark={resolved === "dark"} />
          {menu}
        </Layout.Sider>
      )}
      {mobile && (
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          placement="left"
          size={260}
          closable={false}
          styles={{ body: { padding: 0 } }}
          title={null}
        >
          <Brand collapsed={false} dark={resolved === "dark"} />
          {menu}
        </Drawer>
      )}
      <Layout style={{ minWidth: 0 }}>
        <Layout.Header className="ev-header" style={{ height: 56, lineHeight: "normal" }}>
          {mobile && (
            <Button type="text" icon={<MenuOutlined />} aria-label="Open navigation" onClick={() => setDrawerOpen(true)} />
          )}
          <div className="grow">
            <Breadcrumb items={screens.sm === false ? crumbs : [{ title: "Emvoox Studio" }, ...crumbs]} />
          </div>
          {activeRun && (
            <Tooltip title={`Run ${activeRun} is in progress`}>
              <Link href={`/pipeline/?id=${encodeURIComponent(activeRun)}`} className="ev-run-pill">
                <span className="pulse-dot" />
                <span className="ev-hide-xs">Live run</span>
              </Link>
            </Tooltip>
          )}
          {config && (
            <Space size={4} className="ev-hide-md">
              {KEY_LABELS.map(([k, label]) => (
                <Tooltip key={k} title={config.keys[k] ? `${label} key present` : `${label} key missing in .env`}>
                  <Tag color={config.keys[k] ? "success" : "default"} style={{ marginInlineEnd: 0 }}>{label}</Tag>
                </Tooltip>
              ))}
            </Space>
          )}
          <ThemeSwitch />
        </Layout.Header>
        <Layout.Content>
          {/* no engine config = no engine (down, or a different backend on the port): one message instead of every page failing */}
          <div className="ev-content">{!config && configError ? <ErrorAlert error={configError} onRetry={refreshConfig} /> : children}</div>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
