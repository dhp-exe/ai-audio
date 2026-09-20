"use client";

import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useStoredState } from "@/lib/hooks";

/**
 * A left-docked panel that behaves like an editor side panel: drag its right edge to resize,
 * collapse it to a rail, expand it back, or close it. Width and collapsed state persist per key.
 */
export function SidePanel({ storageKey, title, subtitle, onClose, children, defaultWidth = 480, minWidth = 340, maxWidth = 760 }: {
  storageKey: string; title: React.ReactNode; subtitle?: React.ReactNode; onClose?: () => void; children: React.ReactNode;
  defaultWidth?: number; minWidth?: number; maxWidth?: number;
}) {
  const [width, setWidth] = useStoredState<number>(`panel:${storageKey}:width`, defaultWidth);
  const [collapsed, setCollapsed] = useStoredState<boolean>(`panel:${storageKey}:collapsed`, false);
  const [dragging, setDragging] = useState(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    startX.current = e.clientX; startW.current = width; setDragging(true);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [width]);
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => setWidth(Math.min(maxWidth, Math.max(minWidth, startW.current + e.clientX - startX.current)));
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [dragging, maxWidth, minWidth, setWidth]);

  if (collapsed) {
    return (
      <aside className="relative flex w-11 flex-none flex-col items-center border-r border-line bg-panel py-2">
        <button className="btn-icon" title="Expand panel" onClick={() => setCollapsed(false)}><ChevronRight size={16} /></button>
        <div className="mt-3 select-none text-[12px] font-medium text-muted [writing-mode:vertical-rl]">{title}</div>
      </aside>
    );
  }
  return (
    <aside
      className="relative flex flex-none flex-col border-r border-line bg-panel"
      style={{ width, transition: dragging ? "none" : "width .16s ease" }}
    >
      <div className="flex h-11 items-center gap-2 border-b border-line px-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold">{title}</div>
          {subtitle && <div className="truncate text-[11px] text-muted">{subtitle}</div>}
        </div>
        <button className="btn-icon" title="Collapse panel" onClick={() => setCollapsed(true)}><ChevronLeft size={16} /></button>
        {onClose && <button className="btn-icon" title="Close panel" onClick={onClose}><X size={16} /></button>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
      <div
        role="separator" aria-orientation="vertical" title="Drag to resize"
        onPointerDown={onPointerDown}
        className={`absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-accent/40 ${dragging ? "bg-accent/60" : ""}`}
      />
    </aside>
  );
}
