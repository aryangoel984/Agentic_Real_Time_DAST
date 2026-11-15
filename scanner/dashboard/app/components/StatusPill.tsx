const STYLES: Record<string, string> = {
  queued: "bg-slate-100 text-slate-600 ring-slate-200",
  pending: "bg-slate-100 text-slate-500 ring-slate-200",
  running: "bg-blue-50 text-blue-700 ring-blue-200",
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  done: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-red-200",
  interrupted: "bg-amber-50 text-amber-800 ring-amber-200",
};

export default function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${STYLES[status] ?? STYLES.pending}`}>
      {status === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />}
      {status}
    </span>
  );
}
