"use client";

import { useEffect, useState } from "react";
import { fetchJson, Report, REPORT_BASE, ScanDetail, seconds } from "../lib/api";

export default function ReportCard({ scan, stageStatus }: { scan: ScanDetail; stageStatus?: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const reviews = scan.findings.map((f) => f.review_status).join(",");

  useEffect(() => {
    if (stageStatus !== "done") return;
    fetchJson<Report>(`/scans/${scan.id}/report`).then(setReport).catch(() => setReport(null));
  }, [scan.id, stageStatus, reviews]);

  if (stageStatus !== "done" || !report) {
    const msg = stageStatus === "running" ? "Writing the report…"
      : stageStatus === "failed" || stageStatus === "halted" ? "The scan stopped before the report was written."
      : "The report is written after triage. It turns the findings into tickets with steps to reproduce and a fix.";
    return <p className="px-5 py-8 text-center text-sm text-slate-500">{msg}</p>;
  }
  const s = report.summary;
  const btn = "rounded-md px-3 py-1.5 text-xs font-medium ring-1";
  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-4 px-5 py-4">
      <dl className="flex flex-wrap gap-x-8 gap-y-3">
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wider text-slate-400">Change → first verified finding</dt>
          <dd className="mt-0.5 text-sm font-medium tabular-nums text-slate-800">{seconds(report.speed.change_to_first_verified_s)}</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wider text-slate-400">Tickets</dt>
          <dd className="mt-0.5 text-sm text-slate-800">
            <span className="font-medium">{s.tickets}</span>
            <span className="text-slate-400"> · </span>
            <span className={s.ready ? "text-emerald-700" : "text-slate-500"}>{s.ready} ready to raise</span>
            <span className="text-slate-400"> · </span>
            <span className={s.draft ? "text-amber-800" : "text-slate-500"}>{s.draft} draft (awaiting review)</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wider text-slate-400">Zombie / shadow described</dt>
          <dd className="mt-0.5 text-sm text-slate-800">{report.inventory.length}</dd>
        </div>
      </dl>
      <div className="ml-auto flex flex-wrap gap-2">
        <a href={`/report?scan=${scan.id}`} target="_blank" rel="noreferrer"
          className={`${btn} bg-slate-800 text-white ring-slate-800 hover:bg-slate-700`}>Open report</a>
        <a href={`${REPORT_BASE}/scans/${scan.id}/report.md`} download
          className={`${btn} bg-white text-slate-700 ring-slate-300 hover:bg-slate-50`}>Download Markdown</a>
        <a href={`${REPORT_BASE}/scans/${scan.id}/tickets.json`} download
          className={`${btn} bg-white text-slate-700 ring-slate-300 hover:bg-slate-50`}>Download tickets (JSON)</a>
      </div>
    </div>
  );
}
