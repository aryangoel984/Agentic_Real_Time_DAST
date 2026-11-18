import { Endpoint, PlanSummary, TestCase } from "../lib/api";
import { CLASS_STYLES } from "./InventoryTable";

const RISK: Record<string, string> = {
  high: "bg-red-50 text-red-700 ring-red-200",
  medium: "bg-amber-50 text-amber-800 ring-amber-200",
  low: "bg-slate-100 text-slate-600 ring-slate-200",
};

const ORDER: Record<string, number> = { shadow: 0, zombie: 1, active: 2 };

export function PlanHeader({ plan, count }: { plan?: PlanSummary; count: number }) {
  if (!plan) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <span className="text-slate-600">
        {plan.planner === "groq" ? (
          <>Planned by <span className="font-medium text-slate-900">Groq LLM</span> <span className="font-mono">({plan.model})</span></>
        ) : (
          <>Planned by <span className="font-medium text-slate-900">rule-based fallback</span> <span className="text-slate-400">({plan.why})</span></>
        )}
      </span>
      <span className="text-slate-400">{count} tests</span>
      {plan.dropped.length > 0 && <span className="text-amber-700">{plan.dropped.length} dropped</span>}
    </div>
  );
}

export default function AttackPlan({
  endpoints, tests, plan, stageStatus,
}: { endpoints: Endpoint[]; tests: TestCase[]; plan?: PlanSummary; stageStatus?: string }) {
  if (!plan) {
    const msg = stageStatus === "running" ? "Planning tests…" : stageStatus === "failed"
      ? "Attack planning failed. See the agent log." : "Attack planning hasn't run yet.";
    return <p className="px-5 py-10 text-center text-sm text-slate-500">{msg}</p>;
  }
  const rows = [...endpoints].sort(
    (a, b) => (ORDER[a.classification ?? ""] ?? 3) - (ORDER[b.classification ?? ""] ?? 3) || a.path.localeCompare(b.path),
  );
  return (
    <div>
      <ul className="divide-y divide-slate-100">
        {rows.map((e) => {
          const mine = tests.filter((t) => t.endpoint_id === e.id);
          const cls = e.classification ? CLASS_STYLES[e.classification] : null;
          return (
            <li key={e.id} className="px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-slate-700">{e.method}</span>
                <span className="font-mono text-xs text-slate-900">{e.path}</span>
                {cls && <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ${cls.badge}`}>{cls.label}</span>}
                <span className="ml-auto text-xs text-slate-400">{mine.length ? `${mine.length} test${mine.length > 1 ? "s" : ""}` : "no tests"}</span>
              </div>
              {mine.length > 0 ? (
                <ul className="mt-2.5 space-y-2">
                  {mine.map((t) => (
                    <li key={t.id} className="grid grid-cols-[minmax(0,14rem)_minmax(0,1fr)] gap-3 text-sm">
                      <div className="flex flex-wrap items-start gap-1.5">
                        <span className="font-medium text-slate-800">{t.name}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${RISK[t.risk_level]}`}>
                          {t.risk_level}
                        </span>
                        {t.planned_by !== plan.planner && (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500" title="The LLM did not plan this; added by the rule-based minimum">
                            added by rules
                          </span>
                        )}
                      </div>
                      <p className="text-slate-600">
                        {t.reason}
                        {t.requires_approval && <span className="ml-1.5 text-xs text-red-700">needs approval before running</span>}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-slate-400">{plan.skips[String(e.id)] ?? "No approved test fits this endpoint."}</p>
              )}
            </li>
          );
        })}
      </ul>
      {plan.dropped.length > 0 && (
        <div className="border-t border-amber-200 bg-amber-50/50 px-5 py-3 text-xs text-amber-800">
          <p className="font-medium">Dropped by the catalogue guard (never planned):</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {plan.dropped.map((d) => <li key={d} className="font-mono">{d}</li>)}
          </ul>
        </div>
      )}
      <p className="border-t border-slate-100 px-5 py-2.5 text-[11px] text-slate-400">
        Plan only. Nothing was executed: {plan.requests_to_target} requests were sent to the target during planning.
      </p>
    </div>
  );
}
