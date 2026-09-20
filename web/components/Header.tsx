"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Library, Moon, PenLine, Sun, SunMoon, Users } from "lucide-react";
import { useTheme } from "./ThemeProvider";
import { usePoll } from "@/lib/hooks";
import { api } from "@/lib/api";

const NAV = [
  { href: "/", label: "Library", icon: Library, match: (p: string) => p === "/" },
  { href: "/story/", label: "New story", icon: PenLine, match: (p: string) => p.startsWith("/story") || p.startsWith("/run") },
  { href: "/characters/", label: "Characters", icon: Users, match: (p: string) => p.startsWith("/characters") },
  { href: "/usage/", label: "Usage", icon: Activity, match: (p: string) => p.startsWith("/usage") },
];

export function Header() {
  const path = usePathname() ?? "/";
  const { theme, cycle } = useTheme();
  const { data: cfg } = usePoll(api.config, 30_000);
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : SunMoon;
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-5 border-b border-line bg-panel px-5">
      <Link href="/" className="text-[15px] font-semibold tracking-tight">
        Audio AI Studio <span className="font-normal text-muted">· Voice IP micro-drama</span>
      </Link>
      <nav className="flex items-center gap-1">
        {NAV.map(({ href, label, icon: I, match }) => (
          <Link key={href} href={href} className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium ${match(path) ? "bg-sunken text-ink" : "text-muted hover:text-ink"}`}>
            <I size={15} /> {label}
          </Link>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2 text-[12px] text-muted">
        {cfg && (
          <>
            {cfg.active_run && (
              <Link href={`/run/?id=${cfg.active_run}`} className="pill bg-live text-[#111]"><span className="dot running" /> run in progress</Link>
            )}
            <span className="hidden sm:inline">LLM <b className="font-medium text-ink">{cfg.llm_model}</b></span>
            <span className={`pill border ${cfg.keys.gemini ? "border-ok text-ok" : "border-bad text-bad"}`}>Gemini key</span>
            <span className={`pill border ${cfg.keys.elevenlabs ? "border-ok text-ok" : "border-bad text-bad"}`}>ElevenLabs key</span>
          </>
        )}
        <button onClick={cycle} className="btn-ghost h-8 px-2.5" title={`Theme: ${theme}. Click to change.`}>
          <Icon size={15} /> <span className="capitalize">{theme}</span>
        </button>
      </div>
    </header>
  );
}
