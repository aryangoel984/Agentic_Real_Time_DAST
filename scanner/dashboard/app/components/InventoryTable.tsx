import { Endpoint } from "../lib/api";

const SOURCE_LABELS: Record<string, string> = {
  crawl: "crawl",
  "app.js": "app.js",
  version_probe: "version probe",
};

function Chip({ children, mono = false }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 ${mono ? "font-mono" : ""}`}>
      {children}
    </span>
  );
}

function Params({ p }: { p: Endpoint["params"] }) {
  if (!p) return <span className="text-slate-300">—</span>;
  const groups: [string, string[]][] = [["path", p.path], ["query", p.query], ["body", p.body]];
  const shown = groups.filter(([, v]) => v.length > 0);
  if (shown.length === 0) return <span className="text-slate-300">none</span>;
  return (
    <div className="space-y-0.5">
      {shown.map(([k, v]) => (
        <div key={k} className="text-xs leading-5">
          <span className="text-slate-400">{k}: </span>
          <span className="font-mono text-slate-700">{v.join(", ")}</span>
        </div>
      ))}
    </div>
  );
}

function Auth({ e }: { e: Endpoint }) {
  const verified = e.auth_basis?.startsWith("verified") ?? false;
  const badge =
    e.auth_required === true ? (
      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200">Required</span>
    ) : e.auth_required === false ? (
      <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">No auth</span>
    ) : (
      <span className="text-xs text-slate-400">Unknown</span>
    );
  return (
    <div title={e.auth_basis ?? undefined}>
      {badge}
      <div className="mt-1 text-[11px] text-slate-400">{e.auth_required === null ? "" : verified ? "verified" : "observed"}</div>
    </div>
  );
}

export default function InventoryTable({ endpoints, reconStatus }: { endpoints: Endpoint[]; reconStatus?: string }) {
  if (endpoints.length === 0) {
    const msg =
      reconStatus === "running"
        ? "Discovering… endpoints appear here as recon finds them."
        : reconStatus === "failed"
          ? "Recon failed before it found anything. See the agent log."
          : "Recon hasn't run yet.";
    return <p className="px-5 py-10 text-center text-sm text-slate-500">{msg}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            <th className="px-5 py-2.5 font-medium">Method</th>
            <th className="px-3 py-2.5 font-medium">Path</th>
            <th className="px-3 py-2.5 font-medium">Params</th>
            <th className="px-3 py-2.5 font-medium">Auth</th>
            <th className="px-3 py-2.5 font-medium">Roles reached</th>
            <th className="px-3 py-2.5 font-medium">Purpose</th>
            <th className="px-5 py-2.5 font-medium">Found by</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {endpoints.map((e) => (
            <tr key={e.id} className="align-top">
              <td className="px-5 py-3">
                <span className="font-mono text-xs font-semibold text-slate-700">{e.method}</span>
              </td>
              <td className="px-3 py-3 font-mono text-xs text-slate-900">{e.path}</td>
              <td className="px-3 py-3"><Params p={e.params} /></td>
              <td className="px-3 py-3"><Auth e={e} /></td>
              <td className="px-3 py-3">
                {e.roles.length ? (
                  <div className="flex flex-wrap gap-1">{e.roles.map((r) => <Chip key={r}>{r}</Chip>)}</div>
                ) : (
                  <span className="text-xs text-slate-300">none observed</span>
                )}
              </td>
              <td className="px-3 py-3 text-xs capitalize text-slate-700">{e.purpose ?? "—"}</td>
              <td className="px-5 py-3">
                <div className="flex flex-wrap gap-1">
                  {e.discovered_via.map((s) => <Chip key={s} mono>{SOURCE_LABELS[s] ?? s}</Chip>)}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
