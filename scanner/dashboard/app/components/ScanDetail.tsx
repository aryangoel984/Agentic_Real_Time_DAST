import { duration, formatDateTime, ScanDetail as Detail } from "../lib/api";
import AgentLog from "./AgentLog";
import AttackPlan, { PlanHeader } from "./AttackPlan";
import FindingsPanel, { FindingsHeader } from "./FindingsPanel";
import InventoryTable, { CLASS_STYLES } from "./InventoryTable";
import ExecutionPanel, { ExecutionHeader } from "./ExecutionPanel";
import SafetyPanel from "./SafetyPanel";
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
  const planning = scan.stages.find((s) => s.stage === "attack_planning");
  const execution = scan.stages.find((s) => s.stage === "execution");
  const verificationStage = scan.stages.find((s) => s.stage === "verification");
  const plan = scan.state?.plan;
  const tests = scan.test_cases ?? [];
  const endpoints = scan.endpoints ?? [];
  const classified = endpoints.some((e) => e.classification);
  const count = (c: string) => endpoints.filter((e) => e.classification === c).length;
  return (
    <div className="space-y-6">
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold tracking-tight">Scan #{scan.id}</h2>
          <StatusPill status={scan.status} />
          {scan.paused_reason && <StatusPill status="paused" />}
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
            <p className="mt-0.5 text-xs text-slate-400">Discovered from outside (portal crawl, app.js, version probing), then classified against provided traffic logs</p>
          </div>
          <div className="flex items-center gap-4 text-xs">
            {recon?.status === "running" && <span className="text-blue-600">discovering…</span>}
            {classified && (
              <span className="flex items-center gap-1.5 font-medium">
                {(["active", "zombie", "shadow"] as const).map((c, i) => (
                  <span key={c} className="flex items-center gap-1.5">
                    {i > 0 && <span className="text-slate-300">·</span>}
                    <span className={CLASS_STYLES[c].text}>
                      {CLASS_STYLES[c].label} {count(c)}
                    </span>
                  </span>
                ))}
              </span>
            )}
            <span className="text-slate-400">
              {endpoints.length} endpoint{endpoints.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>
        <InventoryTable endpoints={endpoints} reconStatus={recon?.status} />
      </section>

      <section className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
          <div>
            <h3 className="card-title">Attack plan</h3>
            <p className="mt-0.5 text-xs text-slate-400">Tests chosen per endpoint from the approved catalogue, with reasons. Not executed.</p>
          </div>
          <PlanHeader plan={plan} count={tests.length} />
        </div>
        <AttackPlan endpoints={endpoints} tests={tests} plan={plan} stageStatus={planning?.status} />
      </section>

      <SafetyPanel scan={scan} />

      <section className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
          <div>
            <h3 className="card-title">Execution</h3>
            <p className="mt-0.5 text-xs text-slate-400">Each cleared or approved test run against the target. Raw results only, not confirmed findings.</p>
          </div>
          <ExecutionHeader tests={tests} />
        </div>
        <ExecutionPanel scan={scan} stageStatus={execution?.status} />
      </section>

      <section className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
          <div>
            <h3 className="card-title">Findings</h3>
            <p className="mt-0.5 text-xs text-slate-400">Each suspicious result re-proved on fresh data plus an independent check. Severity is assigned in triage.</p>
          </div>
          <FindingsHeader findings={scan.findings} />
        </div>
        <FindingsPanel scan={scan} stageStatus={verificationStage?.status} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <section className="card p-5">
          <h3 className="card-title mb-5">Pipeline</h3>
          <StageTimeline stages={scan.stages} />
        </section>

        <div className="space-y-6">
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
