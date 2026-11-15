"use client";

import { ScanSummary, timeAgo } from "../lib/api";
import StatusPill from "./StatusPill";

export default function ScanList({ scans, selected, onSelect }: {
  scans: ScanSummary[];
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="card-title">Scan runs</h2>
        <span className="text-xs text-slate-400">{scans.length}</span>
      </div>
      {scans.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-500">No scans yet.</p>
      ) : (
        <ul className="max-h-[calc(100vh-11rem)] divide-y divide-slate-100 overflow-y-auto">
          {scans.map((s) => {
            const pct = Math.round((s.stages_done / s.stages_total) * 100);
            return (
              <li key={s.id}>
                <button
                  onClick={() => onSelect(s.id)}
                  className={`w-full px-4 py-3 text-left transition-colors ${
                    selected === s.id ? "bg-slate-100" : "hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">Scan #{s.id}</span>
                    <StatusPill status={s.status} />
                  </div>
                  <div className="mt-1 truncate font-mono text-xs text-slate-600">
                    {s.trigger?.method} {s.trigger?.endpoint ?? s.trigger?.event}
                    {s.trigger?.version ? <span className="text-slate-400"> · {s.trigger.version}</span> : null}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="h-1 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className={`h-full rounded-full ${s.status === "failed" ? "bg-red-500" : s.status === "completed" ? "bg-emerald-500" : "bg-blue-500"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-[11px] tabular-nums text-slate-400">
                      {s.stages_done}/{s.stages_total} · {timeAgo(s.created_at)}
                    </span>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
