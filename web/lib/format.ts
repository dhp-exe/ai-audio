export const pad2 = (n: number) => String(n).padStart(2, "0");
export const ep = (n: number) => `ep${pad2(n)}`;

export function fmtSeconds(ms: number | null | undefined) {
  if (ms == null) return "";
  return `${(ms / 1000).toFixed(1)}s`;
}

export function fmtDuration(start: string | null, end: string | null) {
  if (!start) return "";
  const s = Math.max(0, ((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000);
  return s < 60 ? `${s.toFixed(0)}s` : `${Math.floor(s / 60)}m${(s % 60).toFixed(0)}s`;
}

export function fmtCountdown(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return "";
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  if (diff <= 0) return "now";
  const h = Math.floor(diff / 3600), m = Math.floor((diff % 3600) / 60), s = diff % 60;
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  if (h) return `${h}h ${pad2(m)}m`;
  if (m) return `${m}m ${pad2(s)}s`;
  return `${s}s`;
}

export function fmtTime(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const fmtInt = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString());

export function wordCount(s: string) { return s.trim() ? s.trim().split(/\s+/).length : 0; }
