"use client";

import { useState } from "react";
import { EvidenceItem, ScanDetail, TestCase } from "../lib/api";
import { FINDING_STYLES } from "./FindingsPanel";

const RESULT: Record<string, { label: string; chip: string }> = {
  suspicious: { label: "suspicious", chip: "bg-amber-50 text-amber-800 ring-amber-200" },
  clean: { label: "clean", chip: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  skipped: { label: "skipped", chip: "bg-slate-100 text-slate-500 ring-slate-200" },
  could_not_run: { label: "could not run", chip: "bg-slate-100 text-slate-600 ring-slate-300" },
};

const ORDER: Record<string, number> = { suspicious: 0, clean: 1, could_not_run: 2, skipped: 3 };

function outcome(t: TestCase): string {
  return t.raw_result ?? t.exec_status ?? "pending";
}

export function Evidence({ items }: { items: EvidenceItem[] }) {
  return (
    <div className="mt-2 space-y-2">
      {items.map((e, i) => (
        <div key={i} className="rounded-md bg-slate-50 p-2.5 ring-1 ring-slate-200">
          {e.note && <p className="mb-1 text-[11px] font-medium text-slate-500">{e.note}</p>}
          <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-slate-700">
{`${e.request?.method} ${e.request?.path}   (as ${e.request?.as})
${Object.entries(e.request?.headers ?? {}).map(([k, v]) => `${k}: ${v}`).join("\n")}${e.request?.body ? `\n${JSON.stringify(e.request.body)}` : ""}

→ HTTP ${e.response?.status}
${JSON.stringify(e.response?.key_fields, null, 1)}`}
          </pre>
        </div>
      ))}
    </div>
  );
}

function Row({ t, endpoint, verdict }: { t: TestCase; endpoint: string; verdict?: string }) {
  const [open, setOpen] = useState(false);
  const o = outcome(t);
  const style = RESULT[o];
  const ran = t.exec_status === "ran";
  return (
    <li className="px-5 py-3">
      <button onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-2 text-left">
        <span className="font-mono text-xs text-slate-400">#{t.id}</span>
        <span className="text-sm font-medium text-slate-800">{t.name}</span>
        <span className="font-mono text-xs text-slate-600">{endpoint}</span>
        <span className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-slate-400">{ran ? "ran" : t.exec_status === "skipped" ? "not run" : ""}</span>
          {style ? (
            <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${style.chip}`}>
              {style.label}
            </span>
          ) : (
            <span className="text-[11px] text-slate-400">waiting</span>
          )}
          {verdict && (
            <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ${FINDING_STYLES[verdict]?.chip ?? ""}`}>
              {FINDING_STYLES[verdict]?.label ?? verdict}
            </span>
          )}
          {t.evidence.length > 0 && <span className="text-[11px] text-slate-400">{open ? "▾" : "▸"} evidence</span>}
        </span>
      </button>
      {t.result_summary && <p className="mt-1 text-sm text-slate-600">{t.result_summary}</p>}
      {open && t.evidence.length > 0 && <Evidence items={t.evidence} />}
    </li>
  );
}

export function ExecutionHeader({ tests }: { tests: TestCase[] }) {
  const n = (o: string) => tests.filter((t) => outcome(t) === o).length;
  if (!tests.some((t) => t.exec_status)) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
      <span className={n("suspicious") ? "text-amber-800" : "text-slate-400"}>{n("suspicious")} suspicious</span>
      <span className="text-slate-300">·</span>
      <span className="text-emerald-700">{n("clean")} clean</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">{n("skipped")} skipped</span>
      {n("could_not_run") > 0 && (<><span className="text-slate-300">·</span><span className="text-slate-600">{n("could_not_run")} could not run</span></>)}
    </div>
  );
}

export default function ExecutionPanel({ scan, stageStatus }: { scan: ScanDetail; stageStatus?: string }) {
  const tests = scan.test_cases ?? [];
  const started = tests.some((t) => t.exec_status);
  if (!started) {
    const msg = stageStatus === "running" ? "Running tests through the safety gateway…" : stageStatus === "failed" || stageStatus === "halted"
      ? "Execution stopped. See the agent log." : "Execution hasn't run yet. It starts after the safety gateway clears or approves the tests.";
    return <p className="px-5 py-10 text-center text-sm text-slate-500">{msg}</p>;
  }
  const ep = (id: number) => {
    const e = scan.endpoints.find((x) => x.id === id);
    return e ? `${e.method} ${e.path}` : "";
  };
  const rows = [...tests].sort((a, b) => (ORDER[outcome(a)] ?? 4) - (ORDER[outcome(b)] ?? 4) || a.id - b.id);
  return (
    <div>
      <ul className="divide-y divide-slate-100">
        {rows.map((t) => <Row key={t.id} t={t} endpoint={ep(t.endpoint_id)}
          verdict={scan.findings.find((f) => f.test_case_id === t.id)?.status} />)}
      </ul>
      <p className="border-t border-slate-100 px-5 py-2.5 text-[11px] text-slate-400">
        Raw results compared against the synthetic bookings the scanner created. Not confirmed findings and no severity yet:
        verification and triage come next. Every request went through the safety gateway (see its audit log).
      </p>
    </div>
  );
}
