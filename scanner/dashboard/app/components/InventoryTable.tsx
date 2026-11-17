import { Fragment } from "react";
import { Endpoint } from "../lib/api";

const SOURCE_LABELS: Record<string, string> = {
  crawl: "crawl",
  "app.js": "app.js",
  version_probe: "version probe",
  traffic_log: "traffic log",
};

export const CLASS_STYLES: Record<string, { label: string; badge: string; text: string; row: string }> = {
  active: { label: "Active", badge: "bg-emerald-50 text-emerald-700 ring-emerald-200", text: "text-emerald-700", row: "" },
  zombie: { label: "Zombie", badge: "bg-amber-50 text-amber-800 ring-amber-200", text: "text-amber-700", row: "bg-amber-50/40" },
  shadow: { label: "Shadow", badge: "bg-red-50 text-red-700 ring-red-200", text: "text-red-700", row: "bg-red-50/40" },
};

// Endpoints needing attention first.
const ORDER: Record<string, number> = { shadow: 0, zombie: 1, active: 2 };

function Chip({ children, mono = false }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 ${mono ? "font-mono" : ""}`}>
      {children}
    </span>
  );
}

function Classification({ c }: { c: Endpoint["classification"] }) {
  if (!c) return <span className="text-xs text-slate-400">pending</span>;
  const s = CLASS_STYLES[c];
  return <span className={`rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${s.badge}`}>{s.label}</span>;
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

function lastSeen(iso: string | null): string {
  if (!iso) return "never";
  // Traffic logs are in UTC; show UTC so the date matches the log and the agent log.
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) + " (UTC)";
}

function Detail({ e }: { e: Endpoint }) {
  const s = CLASS_STYLES[e.classification!];
  const t = e.traffic;
  const callers = t?.callers.map((c) => `${c.caller} ×${c.hits}`).join(", ");
  return (
    <tr className={`border-b border-slate-100 ${s.row}`}>
      <td />
      <td colSpan={7} className="px-3 pb-3 pt-0">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-600">
          <span>
            <span className="text-slate-400">Last seen in traffic: </span>
            <span className={`font-medium ${s.text}`}>{lastSeen(e.last_traffic_at)}</span>
          </span>
          {t && t.hits > 0 && (
            <span>
              <span className="text-slate-400">Traffic: </span>
              {t.hits} hits{callers && <> from <span className="font-mono">{callers}</span></>}
            </span>
          )}
          {e.owner && (
            <span>
              <span className="text-slate-400">Likely owner: </span>
              {e.owner} <span className="text-slate-400">(guess)</span>
            </span>
          )}
        </div>
        <p className="mt-1 text-xs">
          <span className="text-slate-400">Recommended: </span>
          <span className="font-medium text-slate-800">{e.recommendation}</span>
        </p>
      </td>
    </tr>
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
  const rows = [...endpoints].sort(
    (a, b) => (ORDER[a.classification ?? ""] ?? 3) - (ORDER[b.classification ?? ""] ?? 3) || a.path.localeCompare(b.path),
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            <th className="px-5 py-2.5 font-medium">Method</th>
            <th className="px-3 py-2.5 font-medium">Path</th>
            <th className="px-3 py-2.5 font-medium">Class</th>
            <th className="px-3 py-2.5 font-medium">Params</th>
            <th className="px-3 py-2.5 font-medium">Auth</th>
            <th className="px-3 py-2.5 font-medium">Roles reached</th>
            <th className="px-3 py-2.5 font-medium">Purpose</th>
            <th className="px-5 py-2.5 font-medium">Found by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const flagged = e.classification === "zombie" || e.classification === "shadow";
            const tint = flagged ? CLASS_STYLES[e.classification!].row : "";
            return (
              <Fragment key={e.id}>
                <tr className={`align-top ${tint} ${flagged ? "" : "border-b border-slate-100"}`}>
                  <td className="px-5 py-3">
                    <span className="font-mono text-xs font-semibold text-slate-700">{e.method}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 font-mono text-xs text-slate-900">{e.path}</td>
                  <td className="px-3 py-3"><Classification c={e.classification} /></td>
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
                {flagged && <Detail e={e} />}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
