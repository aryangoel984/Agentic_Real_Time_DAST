"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import ResponseBox from "../components/ResponseBox";
import type { ApiResult } from "../lib/api";
import { useSession } from "../lib/session";

// Usernames only. Passwords are intentionally NOT in the website code
// (they live in backend/seed.py), so the scanner can't find them here.
const ACCOUNT_HINTS = [
  { username: "a_admin", label: "Delhi Travels · Admin" },
  { username: "a_subagent", label: "Delhi Travels · Sub-agent" },
  { username: "b_admin", label: "Mumbai Holidays · Admin" },
  { username: "b_subagent", label: "Mumbai Holidays · Sub-agent" },
];

export default function LoginPage() {
  const { login } = useSession();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApiResult | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const res = await login(username, password);
    setBusy(false);
    if (res.ok) router.push("/bookings");
    else setResult(res);
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-1 text-sm text-slate-500">Agency portal for booking flights and hotels.</p>

      <form onSubmit={submit} className="card mt-8 space-y-5">
        <div>
          <label className="label" htmlFor="username">Username</label>
          <input id="username" className="input" value={username}
            onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </div>
        <div>
          <label className="label" htmlFor="password">Password</label>
          <input id="password" type="password" className="input" value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </div>
        <button className="btn w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <ResponseBox result={result} />
      </form>

      <div className="mt-8">
        <p className="label">Test accounts: click to fill the username</p>
        <div className="grid grid-cols-2 gap-2">
          {ACCOUNT_HINTS.map((a) => (
            <button key={a.username} type="button" onClick={() => setUsername(a.username)}
              className={`rounded-lg border px-3 py-2.5 text-left text-sm hover:bg-white ${
                username === a.username ? "border-slate-900 bg-white" : "border-slate-200"}`}>
              <div className="font-mono text-xs font-semibold">{a.username}</div>
              <div className="text-xs text-slate-500">{a.label}</div>
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-400">Passwords are in backend/seed.py (dev only).</p>
      </div>
    </div>
  );
}
