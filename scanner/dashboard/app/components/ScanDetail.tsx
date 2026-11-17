import { duration, formatDateTime, ScanDetail as Detail } from "../lib/api";
import AgentLog from "./AgentLog";
import FindingsPanel from "./FindingsPanel";
import InventoryTable from "./InventoryTable";
import StageTimeline from "./StageTimeline";
import StatusPill from "./StatusPill";

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export default function ScanDetail({ scan }: { scan: Detail }) {
  const t = scan.trigger;
  const recon = scan.stages.find((s) => s.stage === "recon");
  const endpoints = scan.endpoints ?? [];
  return (
    <div className="space-y-6">
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold tracking-tight">Scan #{scan.id}</h2>
          <StatusPill status={scan.status} />
          <span className="ml-auto text-sm tabular-nums text-slate-500">
            {scan.stages_done}/{scan.stages_total} stages
            {scan.started_at && <> · {duration(scan.started_at, scan.finished_at)}</>}
          </span>
        </div>
        {scan.error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{scan.error}</p>}
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-slate-100 pt-5 md:grid-cols-5">
          <Meta label="Trigger">{t?.event ?? "—"}</Meta>
          <Meta label="Changed endpoint">
            <span className="font-mono text-xs">{t?.method} {t?.endpoint ?? "—"}</span>
          </Meta>
          <Meta label="Version">{t?.version ?? "—"}</Meta>
          <Meta label="Event received">{formatDateTime(t?.received_at ?? null)}</Meta>
          <Meta label="Finished">{formatDateTime(scan.finished_at)}</Meta>
        </dl>
      </div>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <div>
            <h3 className="card-title">API inventory</h3>
            <p className="mt-0.5 text-xs text-slate-400">Discovered from outside: portal crawl, app.js, version probing</p>
          </div>
          <span className="text-xs text-slate-400">
            {recon?.status === "running" && <span className="mr-2 text-blue-600">discovering…</span>}
            {endpoints.length} endpoint{endpoints.length === 1 ? "" : "s"}
          </span>
        </div>
        <InventoryTable endpoints={endpoints} reconStatus={recon?.status} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <section className="card p-5">
          <h3 className="card-title mb-5">Pipeline</h3>
          <StageTimeline stages={scan.stages} />
        </section>

        <div className="space-y-6">
          <section className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
              <h3 className="card-title">Findings</h3>
              <span className="text-xs text-slate-400">{scan.findings.length}</span>
            </div>
            <FindingsPanel findings={scan.findings} />
          </section>

          <section className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
              <h3 className="card-title">Agent log</h3>
              <span className="text-xs text-slate-400">{scan.logs.length} lines</span>
            </div>
            <AgentLog logs={scan.logs} />
          </section>
        </div>
      </div>
    </div>
  );
}
