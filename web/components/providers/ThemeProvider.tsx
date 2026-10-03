"use client";

import { App, ConfigProvider, theme as antdTheme, type ThemeConfig } from "antd";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { THEME_KEY, type ThemeMode } from "@/lib/theme";

export type { ThemeMode };

interface ThemeCtx { mode: ThemeMode; resolved: "light" | "dark"; setMode: (m: ThemeMode) => void }
const Ctx = createContext<ThemeCtx>({ mode: "system", resolved: "light", setMode: () => {} });
export const useThemeMode = () => useContext(Ctx);

export const NAVY = "#284979";
export const NAVY_DARK = "#5b82c4";

function systemDark() {
  try { return window.matchMedia("(prefers-color-scheme: dark)").matches; } catch { return false; }
}

function buildTheme(dark: boolean): ThemeConfig {
  const primary = dark ? NAVY_DARK : NAVY;
  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: primary,
      colorLink: primary,
      borderRadius: 8,
      fontFamily: 'var(--font-sans), "Be Vietnam Pro", system-ui, -apple-system, "Segoe UI", sans-serif',
      fontFamilyCode: 'var(--font-mono), "JetBrains Mono", ui-monospace, Menlo, monospace',
      colorBgLayout: dark ? "#0b111b" : "#f3f5f9",
      colorBgBase: dark ? "#0e1522" : "#ffffff",
      colorBorderSecondary: dark ? "#1d2840" : "#e8ecf2",
      ...(dark ? { colorBgContainer: "#111a2a", colorBgElevated: "#162133" } : {}),
      wireframe: false,
    },
    components: {
      Layout: {
        lightSiderBg: dark ? "#0e1522" : "#ffffff",
        headerBg: dark ? "#0e1522" : "#ffffff",
        bodyBg: dark ? "#0b111b" : "#f3f5f9",
        lightTriggerBg: dark ? "#0e1522" : "#ffffff",  // same as the sider: no strip under the menu
        lightTriggerColor: dark ? "#c9d3e6" : NAVY,
        headerPadding: "0 16px",
      },
      Menu: {
        itemBg: "transparent",
        itemSelectedBg: dark ? "rgba(91,130,196,.18)" : "rgba(40,73,121,.08)",
        itemSelectedColor: primary,
        itemBorderRadius: 8,
        itemMarginInline: 8,
      },
      Card: { headerFontSize: 15 },
      Statistic: { contentFontSize: 24, titleFontSize: 13 },
      Table: { headerBg: dark ? "#121b2b" : "#f7f9fc" },
    },
  };
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // The prerender is light; the real mode is applied after mount (the head script hides the page for dark users meanwhile).
  const [mode, setModeState] = useState<ThemeMode>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let m: ThemeMode = "system";
    try { const s = localStorage.getItem(THEME_KEY); if (s === "light" || s === "dark" || s === "system") m = s; } catch { /* ignore */ }
    setModeState(m);
    setResolved(m === "system" ? (systemDark() ? "dark" : "light") : m);
    setReady(true);
  }, []);

  useEffect(() => {
    if (mode !== "system") return;
    let mq: MediaQueryList | null = null;
    try { mq = window.matchMedia("(prefers-color-scheme: dark)"); } catch { return; }
    const on = () => setResolved(mq!.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq!.removeEventListener("change", on);
  }, [mode]);

  useEffect(() => {
    if (!ready) return;
    const el = document.documentElement;
    el.setAttribute("data-theme", resolved);
    el.classList.remove("theme-pending");
  }, [ready, resolved]);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    setResolved(m === "system" ? (systemDark() ? "dark" : "light") : m);
    try { localStorage.setItem(THEME_KEY, m); } catch { /* ignore */ }
  }, []);

  const themeConfig = useMemo(() => buildTheme(resolved === "dark"), [resolved]);
  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved, setMode]);

  return (
    <Ctx.Provider value={value}>
      <ConfigProvider theme={themeConfig}>
        <App>{children}</App>
      </ConfigProvider>
    </Ctx.Provider>
  );
}
