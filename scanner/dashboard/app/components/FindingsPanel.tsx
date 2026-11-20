"use client";

import { useState } from "react";
import { Finding, formatDateTime, postJson, ScanDetail } from "../lib/api";
import { Evidence } from "./ExecutionPanel";

export const FINDING_STYLES: Record<string, { label: string; chip: string }> = {
  verified: { label: "verified", chip: "bg-red-50 text-red-700 ring-red-200" },
  unverified: { label: "unverified", chip: "bg-amber-50 text-amber-800 ring-amber-200" },
  false_positive: { label: "false positive", chip: "bg-slate-100 text-slate-500 ring-slate-200" },
};

const SEVERITY: Record<string, string> = {
  critical: "bg-red-600 text-white ring-red-600",
  high: "bg-red-50 text-red-700 ring-red-200",
  medium: "bg-amber-50 text-amber-800 ring-amber-200",
  low: "bg-slate-100 text-slate-600 ring-slate-200",
};
const SEVERITIES = ["critical", "high", "medium", "low"];
const ORDER: Record<string, number> = { verified: 0, unverified: 1, false_positive: 2 };

const ranked = (fs: Finding[]) => fs.filter((f) => f.rank != null).sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
const openRanked = (fs: Finding[]) => ranked(fs).filter((f) => f.status !== "fixed");

const RETEST: Record<string, { label: string; cls: string }> = {
  fixed: { label: "fixed", cls: "text-emerald-700" },
  still_vulnerable: { label: "still vulnerable", cls: "text-red-700" },
  partly_fixed: { label: "partly fixed", cls: "text-amber-800" },
  inconclusive: { label: "inconclusive", cls: "text-amber-800" },
  not_retested: { label: "not retested", cls: "text-slate-500" },
  still_present: { label: "still present", cls: "text-red-700" },
  stopped: { label: "stopped", cls: "text-slate-500" },
};

export function FindingsHeader({ findings }: { findings: Finding[] }) {
  if (!findings.length) return null;
  const n = (s: string) => findings.filter((f) => f.status === s).length;
  const top = ranked(findings);
  const sep = <span className="text-slate-300">·</span>;
  if (!top.length) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
        <span className={n("verified") ? "text-red-700" : "text-slate-400"}>{n("verified")} verified</span>{sep}
        <span className="text-slate-500">{n("false_positive")} false positive{n("false_positive") === 1 ? "" : "s"}</span>{sep}
        <span className={n("unverified") ? "text-amber-800" : "text-slate-400"}>{n("unverified")} unverified</span>
      </div>
    );
  }
  const open = openRanked(findings);
  const fixed = top.length - open.length;
  const sev = (s: string) => open.filter((f) => f.severity === s).length;
  const merged = findings.filter((f) => f.duplicate_of != null).length;
  const waiting = open.filter((f) => f.review_status === "awaiting_review").length;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
      <span className="text-slate-800">{open.length} open finding{open.length === 1 ? "" : "s"}</span>
      {SEVERITIES.filter(sev).map((s) => (<span key={s} className="contents">{sep}
        <span className={s === "critical" || s === "high" ? "text-red-700" : s === "medium" ? "text-amber-800" : "text-slate-500"}>{sev(s)} {s}</span></span>))}
      {merged > 0 && (<>{sep}<span className="text-slate-500">{merged} duplicate{merged === 1 ? "" : "s"} merged</span></>)}
      {sep}<span className={waiting ? "text-amber-800" : "text-emerald-700"}>{waiting ? `${waiting} awaiting review` : "all reviewed"}</span>
      {fixed > 0 && (<>{sep}<span className="text-emerald-700">{fixed} fixed</span></>)}
    </div>
  );
}

function Checks({ f }: { f: Finding }) {
  return (
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
  );
}

function Review({ scanId, f }: { scanId: number; f: Finding }) {
  const [mode, setMode] = useState<"idle" | "change">("idle");
  const [severity, setSeverity] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (f.review_status === "confirmed" || f.review_status === "changed") {
    return (
      <p className="mt-2 text-xs text-emerald-700">
        ✓ {f.review_status === "confirmed" ? `Severity ${f.severity} confirmed by a reviewer` : `Severity changed to ${f.severity} by a reviewer`}
        {f.review_note ? `: ${f.review_note}` : ""}
      </p>
    );
  }
  if (f.review_status !== "awaiting_review") return null;

  const send = async (body: object) => {
    setBusy(true); setError(null);
    try { await postJson(`/scans/${scanId}/findings/${f.id}/review`, body); setMode("idle"); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const btn = "rounded-md px-2.5 py-1 text-xs font-medium ring-1 disabled:opacity-50";
  return (
    <div className="mt-2 rounded-md bg-amber-50/60 p-2.5 ring-1 ring-amber-200">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-amber-800">Awaiting human review before escalation</span>
        <span className="ml-auto flex gap-2">
          <button disabled={busy} onClick={() => send({ action: "confirm" })}
            className={`${btn} bg-white text-slate-800 ring-slate-300 hover:bg-slate-50`}>Confirm {f.severity}</button>
          <button disabled={busy} onClick={() => setMode(mode === "change" ? "idle" : "change")}
            className={`${btn} bg-white text-slate-600 ring-slate-300 hover:bg-slate-50`}>Change severity</button>
        </span>
      </div>
      {mode === "change" && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs">
            <option value="">new severity…</option>
            {SEVERITIES.filter((s) => s !== f.severity).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="reason (required)"
            className="min-w-[12rem] flex-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs" />
          <button disabled={busy || !severity || !note.trim()} onClick={() => send({ action: "change", severity, note })}
            className={`${btn} bg-slate-800 text-white ring-slate-800`}>Save</button>
        </div>
      )}
      {error && <p className="mt-1.5 text-xs text-red-700">{error}</p>}
    </div>
  );
}

function RetestBox({ scan, f }: { scan: ScanDetail; f: Finding }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const money = scan.test_cases.find((t) => t.id === f.test_case_id)?.requires_approval;
  const last = f.retests[0];
  const canRetest = f.status === "verified" && !f.retest_running && !["queued", "running"].includes(scan.status) && !scan.halt_reason;

  const start = async () => {
    if (money && !window.confirm("This retest re-runs a money test: it creates synthetic bookings, payments and refunds on the target, through the safety gateway. Continue?")) return;
    setBusy(true); setError(null);
    try { await postJson(`/scans/${scan.id}/findings/${f.id}/retest`); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  if (f.status !== "verified" && f.status !== "fixed") return null;
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {f.status === "fixed" ? (
          <span className="font-medium text-emerald-700">✓ Fixed: retest passed{f.fixed_at ? ` (${formatDateTime(f.fixed_at)})` : ""}</span>
        ) : f.retest_running ? (
          <span className="text-slate-600">Retest running through the safety gateway…</span>
        ) : last ? (
          <span className="text-slate-600">Last retest: <span className={`font-medium ${RETEST[last.result]?.cls ?? ""}`}>{RETEST[last.result]?.label ?? last.result}</span>
            <span className="text-slate-400"> ({last.triggered_by}, {formatDateTime(last.at)})</span>: {last.reason}</span>
        ) : (
          <span className="text-slate-400">Not retested yet. After the fix is deployed, retest to close it.</span>
        )}
        <span className="ml-auto flex gap-2">
          {f.retests.length > 0 && (
            <button onClick={() => setOpen(!open)} className="text-[11px] text-slate-400 hover:text-slate-600">
              {open ? "▾" : "▸"} retest history ({f.retests.length})
            </button>
          )}
          {f.status === "verified" && (
            <button disabled={!canRetest || busy} onClick={start}
              className="rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50">
              {f.retest_running || busy ? "Retesting…" : "Retest"}
            </button>
          )}
        </span>
      </div>
      {error && <p className="mt-1 text-xs text-red-700">{error}</p>}
      {open && (
        <ul className="mt-2 space-y-2">
          {f.retests.map((h, i) => (
            <li key={i} className="rounded-md bg-slate-50 p-2.5 text-xs ring-1 ring-slate-200">
              <p><span className={`font-medium ${RETEST[h.result]?.cls ?? ""}`}>{RETEST[h.result]?.label ?? h.result}</span>
                <span className="text-slate-400"> · {h.triggered_by} · {formatDateTime(h.at)}</span></p>
              <p className="mt-0.5 text-slate-600">{h.reason}</p>
              {(h.checks ?? []).map((c, j) => (
                <p key={j} className="mt-0.5 text-slate-600">
                  <span className={c.passed ? "text-emerald-600" : c.passed === false ? "text-red-600" : "text-amber-600"}>{c.passed ? "✓" : c.passed === false ? "✗" : "?"}</span>{" "}
                  <span className="font-mono text-[11px] text-slate-400">{c.where}</span> <span className="font-medium">{c.name}:</span> {c.detail}
                </p>
              ))}
              {(h.evidence ?? []).length > 0 && <Evidence items={h.evidence ?? []} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RankedRow({ scan, f, dupes }: { scan: ScanDetail; f: Finding; dupes: Finding[] }) {
  const [open, setOpen] = useState(false);
  const ep = (id: number | null) => scan.endpoints.find((e) => e.id === id);
  const evidence = [...f.evidence, ...dupes.flatMap((d) => d.evidence)];
  const seen = f.first_seen_scan_id == null || f.first_seen_scan_id === scan.id ? "new in this scan" : `first seen in scan ${f.first_seen_scan_id}`;
  return (
    <li className="px-5 py-3.5">
      <button onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-2 text-left">
        <span className="w-5 font-mono text-xs text-slate-400">{f.rank}</span>
        <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${SEVERITY[f.severity ?? "low"]}`}>
          {f.severity}
        </span>
        {f.status === "fixed" && (
          <span className="whitespace-nowrap rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 ring-1 ring-emerald-200">fixed</span>
        )}
        <span className="text-sm font-medium text-slate-800">{f.title}</span>
        <span className="ml-auto flex items-center gap-3 text-[11px] text-slate-500">
          <span>owner: <span className="font-medium text-slate-700">{f.owner ?? "unknown"}</span>{f.owner_source === "guessed" ? " (guessed)" : ""}</span>
          <span className="text-slate-400">{seen}</span>
          {evidence.length > 0 && <span className="text-slate-400">{open ? "▾" : "▸"} evidence</span>}
        </span>
      </button>
      <div className="pl-7">
        {f.business_impact && <p className="mt-1 text-sm text-slate-700">{f.business_impact}</p>}
        {f.severity_reason && <p className="mt-1 text-xs text-slate-500">Why {f.severity}: {f.severity_reason}</p>}
        {dupes.length > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            Also affects (merged duplicate{dupes.length > 1 ? "s" : ""}):{" "}
            {dupes.map((d) => { const e = ep(d.endpoint_id); return e ? `${e.method} ${e.path} (${e.classification ?? "?"}, finding #${d.id})` : `#${d.id}`; }).join(", ")}
          </p>
        )}
        <Checks f={f} />
        {f.status !== "fixed" && <Review scanId={scan.id} f={f} />}
        <RetestBox scan={scan} f={f} />
        {open && <Evidence items={evidence} />}
      </div>
    </li>
  );
}

function PlainRow({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  const style = FINDING_STYLES[f.status] ?? FINDING_STYLES.unverified;
  return (
    <li className="px-5 py-3">
      <button onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-2 text-left">
        <span className="text-sm font-medium text-slate-800">{f.title}</span>
        <span className="ml-auto flex items-center gap-2">
          {f.status === "verified" && <span className="text-[11px] text-slate-400">severity: set in triage</span>}
          <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${style.chip}`}>
            {style.label}
          </span>
          {f.evidence.length > 0 && <span className="text-[11px] text-slate-400">{open ? "▾" : "▸"} evidence</span>}
        </span>
      </button>
      <Checks f={f} />
      {f.status !== "verified" && f.verification_reason && <p className="mt-1 text-xs text-slate-500">{f.verification_reason}</p>}
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
  const top = openRanked(findings);
  const fixedRows = ranked(findings).filter((f) => f.status === "fixed");
  const rest = findings.filter((f) => f.rank == null && f.duplicate_of == null)
    .sort((a, b) => (ORDER[a.status] ?? 3) - (ORDER[b.status] ?? 3) || a.id - b.id);
  return (
    <div>
      {top.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {top.map((f) => <RankedRow key={f.id} scan={scan} f={f} dupes={findings.filter((d) => d.duplicate_of === f.id)} />)}
        </ul>
      )}
      {fixedRows.length > 0 && (
        <>
          <p className="border-y border-slate-100 bg-slate-50 px-5 py-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Fixed: retest passed
          </p>
          <ul className="divide-y divide-slate-100">
            {fixedRows.map((f) => <RankedRow key={f.id} scan={scan} f={f} dupes={findings.filter((d) => d.duplicate_of === f.id)} />)}
          </ul>
        </>
      )}
      {rest.length > 0 && (
        <>
          {top.length > 0 && (
            <p className="border-y border-slate-100 bg-slate-50 px-5 py-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Not ranked: rejected or not proven
            </p>
          )}
          <ul className="divide-y divide-slate-100">{rest.map((f) => <PlainRow key={f.id} f={f} />)}</ul>
        </>
      )}
    </div>
  );
}
