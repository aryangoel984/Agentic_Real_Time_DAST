"use client";

import { useState } from "react";
import RequireLogin from "../components/RequireLogin";
import ResponseBox from "../components/ResponseBox";
import { apiRequest, ApiResult } from "../lib/api";
import type { CurrentUser } from "../lib/session";

export default function UsersPage() {
  return (
    <RequireLogin>
      <Users />
    </RequireLogin>
  );
}

function Users() {
  const [id, setId] = useState("1");
  const [result, setResult] = useState<ApiResult | null>(null);
  const u = result?.ok ? (result.data as CurrentUser & { email: string }) : null;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <p className="mt-1 text-sm text-slate-500">Look up a user in your agency. User IDs: 1–4.</p>
      </div>
      <section className="card">
        <form onSubmit={async (e) => { e.preventDefault(); setResult(await apiRequest("GET", `/api/users/${encodeURIComponent(id)}`)); }}
          className="flex gap-3">
          <input className="input max-w-48 font-mono" value={id} onChange={(e) => setId(e.target.value)} placeholder="User ID" />
          <button className="btn">Look up</button>
        </form>
        {u && (
          <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-5 rounded-xl border border-slate-200 p-5 md:grid-cols-3">
            {[["Name", u.full_name], ["Username", u.username], ["Email", u.email],
              ["Role", u.role], ["Agency", u.agency_name], ["User ID", u.id]].map(([k, v]) => (
              <div key={String(k)}>
                <dt className="label">{k}</dt>
                <dd className="text-sm">{String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
        <ResponseBox result={result} />
      </section>
    </div>
  );
}
