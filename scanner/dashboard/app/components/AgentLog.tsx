"use client";

import { useEffect, useRef } from "react";
import { formatTime, LogLine } from "../lib/api";

const LEVEL: Record<string, string> = {
  info: "text-slate-700",
  warn: "text-amber-700",
  error: "text-red-700",
};

export default function AgentLog({ logs }: { logs: LogLine[] }) {
  const box = useRef<HTMLDivElement>(null);
  // Keep the newest line in view inside the box (without scrolling the page).
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [logs.length]);

  return (
    <div ref={box} className="max-h-80 overflow-y-auto bg-slate-50 px-4 py-3 font-mono text-xs leading-6">
      {logs.length === 0 && <p className="text-slate-400">No log lines yet.</p>}
      {logs.map((l) => (
        <div key={l.id} className="flex gap-3">
          <span className="shrink-0 tabular-nums text-slate-400">{formatTime(l.created_at)}</span>
          <span className="w-32 shrink-0 truncate text-slate-500">{l.stage ?? "orchestrator"}</span>
          <span className={LEVEL[l.level] ?? LEVEL.info}>{l.message}</span>
        </div>
      ))}
    </div>
  );
}
