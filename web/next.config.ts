import type { NextConfig } from "next";

// Two ways to run the same app:
//  - `npm run export` (STATIC_EXPORT=1): static files in web/out, served by the FastAPI backend at http://127.0.0.1:8765
//    (same origin, so /api/* just works).
//  - `npm run dev` / Vercel: the app proxies /api/* to the backend given by API_BASE (default local backend).
const isExport = process.env.STATIC_EXPORT === "1";
const apiBase = process.env.API_BASE ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  trailingSlash: true,
  images: { unoptimized: true },
  ...(isExport
    ? { output: "export" as const }
    : { async rewrites() { return [{ source: "/api/:path*", destination: `${apiBase}/api/:path*` }]; } }),
};

export default nextConfig;
