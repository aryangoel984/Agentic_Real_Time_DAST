"use client";

import { useEffect, useState } from "react";
import { AuditRow, AuditView, fetchJson, postJson, ScanDetail } from "../lib/api";

const POLL_MS = 1500;

const DECISION: Record<string, { label: string; chip: string }> = {
  allow: { label: "allowed", chip: "bg-slate-100 text-slate-600 ring-slate-200" },
  hold: { label: "held", chip: "bg-amber-50 text-amber-800 ring-amber-200" },
  block: { label: "blocked", chip: "bg-red-50 text-red-700 ring-red-200" },
};

const FILTERS = [
  { id: "all", label: "All" },
  { id: "block", label: "Blocked" },
  { id: "hold", label: "Held" },
  { id: "sent", label: "Sent to target" },
] as const;

function clock(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })
    + "." + String(d.getMilliseconds()).padStart(3, "0");
}

// Show only the path for target requests; keep the full URL when the host itself is the point.
function shortUrl(r: AuditRow) {
  if (r.reason?.startsWith("out of scope")) return r.url;
  try {
    const u = new URL(r.url);
    return u.pathname + u.search;
  } catch {
    return r.url;
  }
}

function Row({ r }: { r: AuditRow }) {
  const [open, setOpen] = useState(false);
  const d = DECISION[r.decision] ?? DECISION.allow;
  return (
    <>
      <tr onClick={() => setOpen(!open)} className="cursor-pointer align-top hover:bg-slate-50">
        <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] tabular-nums text-slate-500">{clock(r.at)}</td>
        <td className="px-3 py-2">
          <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${d.chip}`}>{d.label}</span>
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{r.stage}</td>
        <td className="min-w-[14rem] px-3 py-2 font-mono text-xs text-slate-800">
          <span className="font-semibold">{r.method}</span> <span className="break-all">{shortUrl(r)}</span>
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-xs tabular-nums text-slate-600">
          {r.sent ? (r.status ?? "error") : <span className="text-slate-400">not sent</span>}
          {r.latency_ms != null && <span className="text-slate-400"> · {r.latency_ms} ms</span>}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">{r.account ?? "—"}</td>
        <td className="min-w-[18rem] px-3 py-2 text-xs text-slate-600">
          {r.reason}
          {!!r.waited_ms && r.waited_ms > 0 && <span className="text-slate-400">{r.reason ? " · " : ""}waited {r.waited_ms} ms</span>}
        </td>
      </tr>
      {open && (
        <tr className="bg-slate-50">
          <td colSpan={7} className="px-3 pb-3 pt-1">
            <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">Request as recorded (secrets masked)</p>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded bg-white p-2 font-mono text-[11px] text-slate-700 ring-1 ring-slate-200">
{`${r.method} ${r.url}
${Object.entries(r.request_headers).map(([k, v]) => `${k}: ${v}`).join("\n")}${r.request_body ? `\n\n${r.request_body}` : ""}`}
            </pre>
            {r.test_case_id && <p className="mt-1 text-[11px] text-slate-500">Test case #{r.test_case_id}</p>}
          </td>
        </tr>
      )}
    </>
  );
}

export default function SafetyPanel({ scan }: { scan: ScanDetail }) {
  const [audit, setAudit] = useState<AuditView | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const a = await fetchJson<AuditView>(`/scans/${scan.id}/audit`);
        if (alive) setAudit(a);
      } catch { /* keep the last view */ }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [scan.id]);

  const act = async (key: string, path: string) => {
    setBusy(key);
    setError(null);
    try { await postJson(path); } catch (e) { setError(String(e)); } finally { setBusy(null); }
  };

  const kill = () => {
    if (window.confirm(`Stop scan #${scan.id}? Every further request to the target will be blocked.`)) {
      act("kill", `/scans/${scan.id}/kill`);
    }
  };

  const s = audit?.summary;
  const live = scan.status === "running" || scan.status === "queued" || !!scan.retest_running;
  const risky = (scan.test_cases ?? []).filter((t) => t.requires_approval);
  const pending = risky.filter((t) => t.status === "pending_approval");
  const ep = (id: number) => scan.endpoints.find((e) => e.id === id);
  const rows = (audit?.rows ?? []).filter((r) =>
    filter === "all" ? true : filter === "sent" ? r.sent : r.decision === filter);

  let state: { text: string; cls: string };
  if (scan.halt_reason) state = { text: `${scan.halted_by === "human" ? "Killed" : "Stopped"}: ${scan.halt_reason}`, cls: "text-red-700" };
  else if (scan.paused_reason) state = { text: `Paused: ${scan.paused_reason}. Requests are held until it recovers.`, cls: "text-amber-800" };
  else if (pending.length && live) state = { text: `Waiting for your decision on ${pending.length} high-risk test${pending.length > 1 ? "s" : ""}`, cls: "text-amber-800" };
  else if (scan.retest_running && scan.status !== "running") state = { text: "Retest running: every request passes the gateway", cls: "text-slate-700" };
  else if (live) state = { text: "Running: every request passes the gateway", cls: "text-slate-700" };
  else state = { text: `Scan ${scan.status}`, cls: "text-slate-500" };

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
        <div>
          <h3 className="card-title">Safety gateway</h3>
          <p className="mt-0.5 text-xs text-slate-400">Every request to the target passes here: kill switch, scope, test accounts, approvals, health, rate limit</p>
        </div>
        {live && !scan.halt_reason && (
          <button onClick={kill} disabled={busy === "kill"}
            className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-red-700 disabled:opacity-50">
            {busy === "kill" ? "Stopping…" : "Kill switch: stop all requests"}
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-slate-100 px-5 py-3 text-xs">
        <span className={`font-medium ${state.cls}`}>{state.text}</span>
        {s && (
          <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 tabular-nums">
            <span className="text-slate-600">Sent to target <b>{s.sent}</b></span>
            <span className="text-slate-600">Allowed <b>{s.allowed}</b></span>
            <span className={s.held ? "text-amber-800" : "text-slate-400"}>Held <b>{s.held}</b></span>
            <span className={s.blocked ? "text-red-700" : "text-slate-400"}>Blocked <b>{s.blocked}</b></span>
            <span className="text-slate-600">
              Rate: highest <b>{s.max_per_second}</b> in any 1 s <span className="text-slate-400">(cap {s.rate_cap}/s)</span>
            </span>
          </span>
        )}
      </div>
      {error && <p className="bg-red-50 px-5 py-2 text-xs text-red-700">{error}</p>}

      {risky.length > 0 && (
        <div className="border-b border-slate-100 px-5 py-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">High-risk tests (need a human)</p>
          <ul className="mt-2 divide-y divide-slate-100">
            {risky.map((t) => {
              const e = ep(t.endpoint_id);
              return (
                <li key={t.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                  <span className="font-mono text-xs text-slate-500">#{t.id}</span>
                  <span className="font-medium text-slate-800">{t.name}</span>
                  <span className="font-mono text-xs text-slate-600">{e?.method} {e?.path}</span>
                  <span className="hidden min-w-0 flex-1 truncate text-xs text-slate-500 lg:block" title={t.reason}>{t.reason}</span>
                  <span className="ml-auto flex items-center gap-2">
                    {t.status === "pending_approval" && !live ? (
                      <span className="text-xs text-slate-400">not decided · scan ended, will never run</span>
                    ) : t.status === "pending_approval" ? (
                      <>
                        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-800 ring-1 ring-amber-200">waiting</span>
                        <button disabled={!!busy} onClick={() => act(`a${t.id}`, `/scans/${scan.id}/tests/${t.id}/approve`)}
                          className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50">Approve</button>
                        <button disabled={!!busy} onClick={() => act(`d${t.id}`, `/scans/${scan.id}/tests/${t.id}/deny`)}
                          className="rounded-md px-2.5 py-1 text-xs font-medium text-red-700 ring-1 ring-red-200 hover:bg-red-50 disabled:opacity-50">Deny</button>
                      </>
                    ) : t.status === "approved" ? (
                      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-emerald-700 ring-1 ring-emerald-200">approved</span>
                    ) : t.status === "denied" ? (
                      <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-red-700 ring-1 ring-red-200">denied · dropped</span>
                    ) : (
                      <span className="text-xs text-slate-400">reviewed at the safety gateway stage</span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-1 px-5 pt-3">
        {FILTERS.map((f) => (
          <button key={f.id} onClick={() => setFilter(f.id)}
            className={`rounded-md px-2.5 py-1 text-xs ${filter === f.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-slate-400">Audit log, newest first · click a row for the masked request</span>
      </div>
      <div className="mt-2 max-h-[28rem] overflow-auto">
        {rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-400">No gateway decisions{filter !== "all" ? " of this kind" : ""} yet.</p>
        ) : (
          <table className="w-full min-w-[56rem] text-left">
            <thead className="sticky top-0 bg-white text-[11px] uppercase tracking-wider text-slate-400 shadow-[0_1px_0_#e2e8f0]">
              <tr>
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Decision</th>
                <th className="px-3 py-2 font-medium">Stage</th>
                <th className="px-3 py-2 font-medium">Request</th>
                <th className="px-3 py-2 font-medium">Result</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => <Row key={r.id} r={r} />)}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
