import { duration, Stage, STAGE_HINTS, STAGE_LABELS } from "../lib/api";

function Dot({ status }: { status: string }) {
  if (status === "done")
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white">
        <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
          <path fillRule="evenodd" d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" clipRule="evenodd" />
        </svg>
      </span>
    );
  if (status === "running")
    return (
      <span className="relative flex h-6 w-6 items-center justify-center">
        <span className="absolute h-6 w-6 animate-ping rounded-full bg-blue-400 opacity-40" />
        <span className="h-3 w-3 rounded-full bg-blue-600" />
      </span>
    );
  if (status === "failed")
    return <span className="flex h-6 w-6 items-center justify-center rounded-full bg-red-500 text-xs font-bold text-white">!</span>;
  if (status === "interrupted")
    return <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-400 text-xs font-bold text-white">–</span>;
  return <span className="block h-6 w-6 rounded-full border-2 border-slate-200 bg-white" />;
}

export default function StageTimeline({ stages }: { stages: Stage[] }) {
  return (
    <ol className="relative">
      {stages.map((s, i) => (
        <li key={s.stage} className="relative flex gap-4 pb-5 last:pb-0">
          {i < stages.length - 1 && (
            <span
              className={`absolute top-6 left-[11px] h-[calc(100%-1.5rem)] w-0.5 ${
                s.status === "done" ? "bg-emerald-300" : "bg-slate-200"
              }`}
            />
          )}
          <div className="relative z-10 shrink-0">
            <Dot status={s.status} />
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className={`text-sm font-medium ${s.status === "pending" ? "text-slate-400" : "text-slate-900"}`}>
                {STAGE_LABELS[s.stage] ?? s.stage}
                {s.runs > 1 && <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">×{s.runs}</span>}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-slate-400">
                {s.status === "pending" ? "pending" : duration(s.started_at, s.finished_at)}
              </span>
            </div>
            <p className="text-xs text-slate-500">{STAGE_HINTS[s.stage]}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
