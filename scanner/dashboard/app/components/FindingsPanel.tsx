import { Finding } from "../lib/api";

export default function FindingsPanel({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return (
      <div className="px-5 py-10 text-center">
        <p className="text-sm font-medium text-slate-600">No findings</p>
        <p className="mt-1 text-xs text-slate-400">Pipeline stages are stubs in this phase. Real testing arrives in later phases.</p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-slate-100">
      {findings.map((f) => (
        <li key={f.id} className="flex items-center justify-between px-5 py-3 text-sm">
          <span>{f.title}</span>
          <span className="text-xs text-slate-500">{f.severity} · {f.status}</span>
        </li>
      ))}
    </ul>
  );
}
