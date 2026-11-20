"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { fetchJson, formatDateTime, Report, REPORT_BASE, seconds, Ticket } from "../lib/api";

const SEVERITY: Record<string, string> = {
  critical: "bg-red-600 text-white ring-red-600",
  high: "bg-red-50 text-red-700 ring-red-200",
  medium: "bg-amber-50 text-amber-800 ring-amber-200",
  low: "bg-slate-100 text-slate-600 ring-slate-200",
};

export default function Page() {
  return (
    <Suspense>
      <ReportPage />
    </Suspense>
  );
}

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 mt-10 border-b border-slate-200 pb-2 text-lg font-semibold tracking-tight text-slate-900">{children}</h2>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-1.5 sm:grid-cols-[11rem_1fr]">
      <dt className="text-xs font-medium uppercase tracking-wider text-slate-400">{label}</dt>
      <dd className="text-sm text-slate-700">{children}</dd>
    </div>
  );
}

function TicketView({ t }: { t: Ticket }) {
  return (
    <article className="mt-6 break-inside-avoid-page rounded-xl border border-slate-200 bg-white p-5 print:rounded-none print:border-x-0 print:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-400">{t.key}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${SEVERITY[t.severity]}`}>{t.severity}</span>
        <h3 className="text-base font-semibold text-slate-900">{t.title}</h3>
        <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ${t.escalation === "draft"
          ? "bg-amber-50 text-amber-800 ring-amber-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"}`}>
          {t.escalation === "ready" ? "READY TO RAISE" : t.escalation === "draft" ? "DRAFT · AWAITING REVIEW" : "RESOLVED · RETEST PASSED"}
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-slate-800">{t.business_impact}</p>
      <dl className="mt-3 divide-y divide-slate-100">
        <Field label="Owner">{t.owner ?? "unknown"}{t.owner_source === "guessed" ? " (guessed)" : ""}</Field>
        <Field label={`Why ${t.severity}`}>{t.severity_reason}</Field>
        <Field label="Affected">
          {t.affected.map((a) => (
            <div key={a.path + a.method} className="font-mono text-xs">{a.method} {a.path} <span className="font-sans text-slate-400">({a.classification})</span></div>
          ))}
        </Field>
        <Field label="Steps to reproduce">
          <ol className="list-decimal space-y-1 pl-5">
            {t.steps.map((s, i) => <li key={i} className="break-words">{s}</li>)}
          </ol>
          <p className="mt-1 text-xs text-slate-400">Test accounts and synthetic data only. Tokens masked.</p>
        </Field>
        <Field label="Expected">{t.expected}</Field>
        <Field label="Actual">{t.actual}</Field>
        <Field label="Verified by">
          {t.checks.map((c) => (
            <div key={c.name}>
              <span className={c.passed ? "text-emerald-600" : "text-red-600"}>{c.passed ? "✓" : "✗"}</span>{" "}
              <span className="font-medium">{c.name}:</span> {c.detail}
            </div>
          ))}
        </Field>
        <Field label="Suggested fix">{t.fix}</Field>
        <Field label="Review">{t.review}</Field>
        {t.retests.length > 0 && (
          <Field label="Retest history">
            {t.retests.map((h, i) => (
              <div key={i} className="text-xs">
                <span className="text-slate-400">{formatDateTime(h.at)} · {h.triggered_by} · </span>
                <span className={`font-medium ${h.result === "fixed" ? "text-emerald-700" : h.result === "still_vulnerable" || h.result === "still_present" ? "text-red-700" : "text-amber-800"}`}>
                  {h.result.replace(/_/g, " ")}</span>: {h.reason}
              </div>
            ))}
          </Field>
        )}
        {t.first_seen_scan_id != null && <Field label="First seen">scan {t.first_seen_scan_id}</Field>}
      </dl>
    </article>
  );
}

function ReportPage() {
  const scanId = useSearchParams().get("scan");
  const [r, setR] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!scanId) return;
    fetchJson<Report>(`/scans/${scanId}/report`).then(setR).catch((e) => setError(String(e)));
  }, [scanId]);

  if (!scanId) return <p className="p-10 text-sm text-slate-500">No scan selected.</p>;
  if (error) return <p className="p-10 text-sm text-red-700">Could not load the report ({error}).</p>;
  if (!r) return <p className="p-10 text-sm text-slate-500">Loading report…</p>;

  const s = r.summary, sf = r.safety, trig = r.trigger;
  const change = [trig.event, trig.method, trig.endpoint, trig.version].filter(Boolean).join(" ") || "manual scan";
  return (
    <main className="mx-auto max-w-4xl px-4 py-10 sm:px-8 print:max-w-none print:px-0 print:py-0">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Security scan report</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Scan #{r.scan.id}</h1>
          <p className="mt-1 text-sm text-slate-500">Generated {formatDateTime(new Date().toISOString())} · scan {r.scan.status}</p>
        </div>
        <div className="ml-auto flex gap-2 print:hidden">
          <button onClick={() => window.print()} className="rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-white">Print / save as PDF</button>
          <a href={`${REPORT_BASE}/scans/${r.scan.id}/report.md`} download className="rounded-md bg-white px-3 py-1.5 text-xs font-medium text-slate-700 ring-1 ring-slate-300">Markdown</a>
          <a href={`${REPORT_BASE}/scans/${r.scan.id}/tickets.json`} download className="rounded-md bg-white px-3 py-1.5 text-xs font-medium text-slate-700 ring-1 ring-slate-300">Tickets (JSON)</a>
        </div>
      </div>

      <H2>Summary</H2>
      <dl className="divide-y divide-slate-100">
        <Field label="What changed">{change} <span className="text-slate-400">· received {formatDateTime(trig.received_at)}</span></Field>
        <Field label="Speed">
          <span className="font-medium">{seconds(r.speed.change_to_first_verified_s)}</span> from the change to the first verified finding
          <span className="text-slate-400"> · whole scan {seconds(r.scan.duration_s)}</span>
        </Field>
        <Field label="Findings">
          {s.open} open · {Object.entries(s.by_severity).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ") || "none"}
          <span className="text-slate-400"> · </span>{s.ready} ready to raise · {s.draft} waiting for human review
          <span className="text-slate-400"> · </span><span className={s.fixed ? "text-emerald-700" : ""}>{s.fixed} fixed</span>
        </Field>
        <Field label="Noise removed">
          {s.merged_duplicates} duplicate(s) merged · {s.false_positives} false positive(s) rejected · {s.unverified} unverified
        </Field>
        <Field label="API inventory">
          {s.endpoints} endpoints ({Object.entries(s.inventory).map(([k, n]) => `${n} ${k}`).join(", ")})
        </Field>
      </dl>
      {s.top_risks.length > 0 && (
        <div className="mt-4 rounded-lg bg-slate-50 p-4 ring-1 ring-slate-200">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Top risks</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-800">{s.top_risks.map((x) => <li key={x}>{x}</li>)}</ol>
        </div>
      )}

      <H2>Findings</H2>
      {r.tickets.filter((t) => t.escalation !== "resolved").length === 0 ? <p className="text-sm text-slate-500">No open findings in this scan.</p>
        : r.tickets.filter((t) => t.escalation !== "resolved").map((t) => <TicketView key={t.key} t={t} />)}
      {r.tickets.some((t) => t.escalation === "resolved") && (<>
        <H2>Resolved: fixed and retested</H2>
        {r.tickets.filter((t) => t.escalation === "resolved").map((t) => <TicketView key={t.key} t={t} />)}
      </>)}

      <H2>Zombie and shadow endpoints</H2>
      {r.inventory.length === 0 && <p className="text-sm text-slate-500">None found.</p>}
      {r.inventory.map((e) => (
        <article key={e.method + e.path} className="mt-4 break-inside-avoid-page rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-mono text-sm font-semibold text-slate-900">{e.method} {e.path} <span className="font-sans text-xs font-medium uppercase text-slate-500">· {e.classification}</span></h3>
          <dl className="mt-2 divide-y divide-slate-100">
            <Field label="Last real traffic">
              {e.last_traffic_at ? formatDateTime(e.last_traffic_at) : "none in the log"}
              {e.hits_in_window != null && <> · {e.hits_in_window} call(s) in the window</>}
              {e.callers.length > 0 && <> · callers: {e.callers.join(", ")}</>}
            </Field>
            <Field label="Reachable without login">
              <span className={e.reachable_without_login === "yes" ? "font-medium text-red-700" : ""}>{e.reachable_without_login}</span> ({e.reachable_basis})
            </Field>
            <Field label="Data it exposes">{e.data_exposed.length ? e.data_exposed.join(", ") : "none seen in a successful response"}</Field>
            <Field label="Vs current version">{e.compared_with_current}</Field>
            <Field label="Vulnerabilities">{e.vulnerabilities.length ? e.vulnerabilities.join("; ") : "none verified"}</Field>
            <Field label="Likely owner">{e.owner ?? "unknown"}</Field>
            <Field label="Recommendation">{e.recommendation}</Field>
          </dl>
        </article>
      ))}

      <H2>Tested and found clean</H2>
      <ul className="space-y-1.5 text-sm text-slate-700">
        {r.coverage.clean.map((c, i) => (
          <li key={i}><span className="text-emerald-600">✓</span> {c.test} on <span className="font-mono text-xs">{c.endpoint}</span>: {c.result}</li>
        ))}
        {r.coverage.clean.length === 0 && <li className="text-slate-500">none</li>}
      </ul>
      {r.coverage.false_positives.length > 0 && (<>
        <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Rejected as false positives</p>
        <ul className="mt-1 space-y-1 text-sm text-slate-600">{r.coverage.false_positives.map((x, i) => <li key={i}>{x.title}: {x.reason}</li>)}</ul>
      </>)}
      {r.coverage.unverified.length > 0 && (<>
        <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Not proven (left for a human)</p>
        <ul className="mt-1 space-y-1 text-sm text-slate-600">{r.coverage.unverified.map((x, i) => <li key={i}>{x.title}: {x.reason}</li>)}</ul>
      </>)}
      {r.coverage.not_run.length > 0 && (<>
        <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Not run</p>
        <ul className="mt-1 space-y-1 text-sm text-slate-600">{r.coverage.not_run.map((x, i) => <li key={i}>{x.test} on <span className="font-mono text-xs">{x.endpoint}</span>: {x.result}</li>)}</ul>
      </>)}

      <H2>Safety record</H2>
      <dl className="divide-y divide-slate-100">
        <Field label="Sent to the target">{sf.sent} <span className="text-slate-400">({Object.entries(sf.by_stage).map(([k, n]) => `${k} ${n}`).join(", ")})</span></Field>
        <Field label="Peak rate">{sf.max_per_second} per second (cap {sf.rate_cap})</Field>
        <Field label="Blocked during scan">
          {sf.blocked}{sf.blocked_reasons.map((b) => <div key={b.reason} className="text-xs text-slate-500">{b.reason} ({b.count})</div>)}
        </Field>
        <Field label="Gateway self-test">
          {sf.self_test_blocked} deliberately bad requests, all blocked, none sent
          {sf.self_test_reasons.map((b) => <div key={b.reason} className="text-xs text-slate-500">{b.reason}</div>)}
        </Field>
        <Field label="Held">{sf.held_for_approval} for human approval · {sf.held_by_health_monitor} while the target struggled</Field>
        <Field label="Stopped early">{sf.halted_by ? `yes, by ${sf.halted_by}: ${sf.halt_reason ?? ""}` : "no"}</Field>
        <Field label="Human decisions">
          {sf.human_decisions.length === 0 ? "none" : sf.human_decisions.map((d, i) => (
            <div key={i} className="text-xs"><span className="text-slate-400">{formatDateTime(d.at)}</span> · {d.decision}</div>
          ))}
        </Field>
      </dl>
      <p className="mt-8 text-xs text-slate-400">
        Every request went through the safety gateway and is in the scan&apos;s audit log. Only the provided test accounts
        and synthetic bookings were used; passwords and tokens are masked throughout.
      </p>
    </main>
  );
}
