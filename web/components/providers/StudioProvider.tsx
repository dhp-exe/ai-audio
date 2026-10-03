"use client";

import { createContext, useContext, useMemo } from "react";
import { api, type Config } from "@/lib/api";
import { usePoll } from "@/lib/hooks";

/* Studio-wide data every page needs: the engine config (catalog, actors, keys, active run) and the human-gate count. */
interface StudioCtx {
  config: Config | null;
  configError: string | null;
  configLoading: boolean;
  refreshConfig: () => Promise<void>;
  gateCount: number;
  refreshGate: () => Promise<void>;
}

const Ctx = createContext<StudioCtx>({
  config: null, configError: null, configLoading: true, refreshConfig: async () => {}, gateCount: 0, refreshGate: async () => {},
});
export const useStudio = () => useContext(Ctx);

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const cfg = usePoll(() => api.config(), 10000);
  const gate = usePoll(() => api.approvals(), 20000);
  const gateCount = useMemo(
    () => (gate.data?.items ?? []).filter((i) => i.state === "awaiting_approval" || i.state === "needs_review").length,
    [gate.data],
  );
  const value = useMemo<StudioCtx>(() => ({
    config: cfg.data, configError: cfg.error, configLoading: cfg.loading, refreshConfig: cfg.refresh, gateCount, refreshGate: gate.refresh,
  }), [cfg.data, cfg.error, cfg.loading, cfg.refresh, gateCount, gate.refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
