"use client";

import { useEffect, useState } from "react";

/* One shared <audio> element for every preview button on the page, so two clips never overlap. */
let player: HTMLAudioElement | null = null;
let currentUrl: string | null = null;
const listeners = new Set<() => void>();

function notify() { listeners.forEach((l) => l()); }

function getPlayer() {
  if (!player) {
    player = new Audio();
    player.onended = () => { currentUrl = null; notify(); };
    player.onpause = () => { if (player && player.ended) return; };
  }
  return player;
}

export function stopAudio() {
  if (player) player.pause();
  currentUrl = null;
  notify();
}

export function toggleAudio(url: string) {
  if (currentUrl === url) { stopAudio(); return; }
  const p = getPlayer();
  p.src = url;
  currentUrl = url;
  notify();
  p.play().catch(() => { currentUrl = null; notify(); });
}

/** Re-render when the playing url changes. */
export function usePlaying(url: string | null | undefined) {
  const [, force] = useState(0);
  useEffect(() => { const l = () => force((x) => x + 1); listeners.add(l); return () => { listeners.delete(l); }; }, []);
  return !!url && currentUrl === url;
}
