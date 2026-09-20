"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "auto" | "light" | "dark";
const Ctx = createContext<{ theme: Theme; setTheme: (t: Theme) => void; cycle: () => void }>({ theme: "auto", setTheme: () => {}, cycle: () => {} });
const ORDER: Theme[] = ["auto", "light", "dark"];

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("auto");
  useEffect(() => {
    try {
      const q = new URLSearchParams(location.search).get("theme") as Theme | null;
      const stored = localStorage.getItem("theme") as Theme | null;
      const t = (q && ORDER.includes(q) ? q : stored && ORDER.includes(stored) ? stored : "auto");
      setThemeState(t);
    } catch { /* ignore */ }
  }, []);
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("theme", t); } catch { /* ignore */ }
  }, []);
  const cycle = useCallback(() => setTheme(ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length]), [theme, setTheme]);
  return <Ctx.Provider value={{ theme, setTheme, cycle }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
