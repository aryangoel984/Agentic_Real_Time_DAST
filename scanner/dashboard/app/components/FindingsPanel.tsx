"use client";

import { useState } from "react";
import { Finding, ScanDetail } from "../lib/api";
import { Evidence } from "./ExecutionPanel";

export const FINDING_STYLES: Record<string, { label: string; chip: string }> = {
  verified: { label: "verified", chip: "bg-red-50 text-red-700 ring-red-200" },
  unverified: { label: "unverified", chip: "bg-amber-50 text-amber-800 ring-amber-200" },
  false_positive: { label: "false positive", chip: "bg-slate-100 text-slate-500 ring-slate-200" },
};

const ORDER: Record<string, number> = { verified: 0, unverified: 1, false_positive: 2 };

export function FindingsHeader({ findings }: { findings: Finding[] }) {
  if (!findings.length) return null;
  const n = (s: string) => findings.filter((f) => f.status === s).length;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
      <span className={n("verified") ? "text-red-700" : "text-slate-400"}>{n("verified")} verified</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">{n("false_positive")} false positive{n("false_positive") === 1 ? "" : "s"}</span>
      <span className="text-slate-300">·</span>
      <span className={n("unverified") ? "text-amber-800" : "text-slate-400"}>{n("unverified")} unverified</span>
    </div>
  );
}

function Row({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  const style = FINDING_STYLES[f.status] ?? FINDING_STYLES.unverified;
  return (
    <li className="px-5 py-3">
      <button onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-2 text-left">
        <span className="text-sm font-medium text-slate-800">{f.title}</span>
        <span className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-slate-400">severity: set in triage</span>
          <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${style.chip}`}>
            {style.label}
          </span>
          {f.evidence.length > 0 && <span className="text-[11px] text-slate-400">{open ? "▾" : "▸"} evidence</span>}
        </span>
      </button>
      <ul className="mt-1.5 space-y-0.5">
        {f.checks.map((c) => (
          <li key={c.name} className="flex gap-2 text-sm">
            <span className={c.passed ? "text-emerald-600" : c.passed === false ? "text-red-600" : "text-amber-600"}>
              {c.passed ? "✓" : c.passed === false ? "✗" : "?"}
            </span>
            <span className="text-slate-600"><span className="font-medium text-slate-700">{c.name}:</span> {c.detail}</span>
          </li>
        ))}
      </ul>
      {f.status !== "verified" && f.verification_reason && (
        <p className="mt-1 text-xs text-slate-500">{f.verification_reason}</p>
      )}
      {open && <Evidence items={f.evidence} />}
    </li>
  );
}

export default function FindingsPanel({ scan, stageStatus }: { scan: ScanDetail; stageStatus?: string }) {
  const findings = scan.findings;
  if (findings.length === 0) {
    const msg = stageStatus === "running" ? "Re-proving each suspicious result…"
      : stageStatus === "done" ? "Nothing to verify: execution found no suspicious results."
      : "Verification hasn't run yet. It re-checks every suspicious result from execution.";
    return <p className="px-5 py-10 text-center text-sm text-slate-500">{msg}</p>;
  }
  const rows = [...findings].sort((a, b) => (ORDER[a.status] ?? 3) - (ORDER[b.status] ?? 3) || a.id - b.id);
  return (
    <ul className="divide-y divide-slate-100">
      {rows.map((f) => <Row key={f.id} f={f} />)}
    </ul>
  );
}
