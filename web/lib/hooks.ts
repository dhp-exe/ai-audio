"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Poll `fn` every `intervalMs` (0 = once). Returns data, error and a manual refresh. */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number, deps: unknown[] = [], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const refresh = useCallback(async () => {
    try { setData(await fnRef.current()); setError(null); } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }, []);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const tick = async () => { if (alive) await refresh(); };
    tick();
    if (!intervalMs) return () => { alive = false; };
    const id = setInterval(tick, intervalMs);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, refresh, ...deps]);
  return { data, error, loading, refresh, setData };
}

/** localStorage-backed state; falls back to memory when storage is unavailable. */
export function useStoredState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(initial);
  const loaded = useRef(false);
  useEffect(() => {
    try { const raw = localStorage.getItem(key); if (raw != null) setValue(JSON.parse(raw)); } catch { /* ignore */ }
    loaded.current = true;
  }, [key]);
  const set = useCallback((v: T | ((prev: T) => T)) => {
    setValue((prev) => {
      const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }, [key]);
  return [value, set] as const;
}

/** A clock that ticks every second, for countdowns. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), intervalMs); return () => clearInterval(id); }, [intervalMs]);
  return now;
}
