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

/** US dollars; small amounts keep more precision so free-tier runs do not all read $0.00. */
export function fmtUsd(n: number | null | undefined) {
  if (n == null) return "–";
  if (n === 0) return "$0";
  const abs = Math.abs(n);
  return `$${n.toFixed(abs < 0.01 ? 4 : abs < 1 ? 3 : 2)}`;
}

/** Milliseconds as m:ss. */
export function fmtClock(ms: number | null | undefined) {
  if (ms == null) return "–";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${pad2(s % 60)}`;
}

export function fmtMinutes(min: number | null | undefined) {
  if (min == null) return "–";
  return min < 10 ? `${min.toFixed(1)} min` : `${Math.round(min)} min`;
}

export function fmtBytes(n: number | null | undefined) {
  if (n == null) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtCompact(n: number | null | undefined) {
  if (n == null) return "–";
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function fmtAgo(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return "";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
