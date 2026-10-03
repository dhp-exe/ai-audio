import { networkInterfaces } from "node:os";
import type { NextConfig } from "next";

// Two ways to run the same app:
//  - `npm run export` (STATIC_EXPORT=1): static files in web/out, served by the FastAPI backend at http://127.0.0.1:8765
//    (same origin, so /api/* just works).
//  - `npm run dev` / Vercel: the app proxies /api/* to the backend given by API_BASE (default local backend).
const isExport = process.env.STATIC_EXPORT === "1";
const apiBase = process.env.API_BASE ?? "http://127.0.0.1:8765";

// Next blocks its dev resources (/_next/hmr, dev chunks) for any host other than localhost, so opening the dev server
// via the "Network" URL (http://192.168.x.x:3000) or from a phone fails with "Blocked cross-origin request". Allow this
// machine's own LAN addresses (looked up at start, DHCP changes them) plus extra hosts from DEV_ORIGINS (comma-separated).
const lanHosts = Object.values(networkInterfaces()).flat()
  .filter((i) => i && i.family === "IPv4" && !i.internal)
  .map((i) => i!.address);
const extraHosts = (process.env.DEV_ORIGINS ?? "").split(",").map((h) => h.trim()).filter(Boolean);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", ...lanHosts, ...extraHosts],
  trailingSlash: true,
  images: { unoptimized: true },
  ...(isExport
    ? { output: "export" as const }
    : { async rewrites() { return [{ source: "/api/:path*", destination: `${apiBase}/api/:path*` }]; } }),
};

export default nextConfig;
