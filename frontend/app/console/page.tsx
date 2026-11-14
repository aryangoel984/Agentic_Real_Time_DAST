"use client";

import { useState } from "react";
import RequireLogin from "../components/RequireLogin";
import ResponseBox from "../components/ResponseBox";
import { apiRequest, ApiResult } from "../lib/api";

// Free-form request tool. Deliberately has NO pre-filled routes: anything
// hard-coded here would show up in the website's code and be visible to
// the scanner, which would spoil the zombie/shadow test.
export default function ConsolePage() {
  return (
    <RequireLogin>
      <Console />
    </RequireLogin>
  );
}

function Console() {
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("/api/");
  const [body, setBody] = useState("");
  const [withToken, setWithToken] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApiResult | null>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!path.startsWith("/api/")) {
      setError("Path must start with /api/ (only API calls are forwarded to the backend).");
      return;
    }
    let parsed: unknown = undefined;
    if (method !== "GET" && body.trim()) {
      try {
        parsed = JSON.parse(body);
      } catch {
        setError("Body is not valid JSON.");
        return;
      }
    }
    setResult(await apiRequest(method, path, parsed, { withToken }));
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Request console</h1>
        <p className="mt-1 text-sm text-slate-500">
          Send any request to the backend. Your login token is attached unless you untick it.
        </p>
      </div>
      <section className="card">
        <form onSubmit={send} className="space-y-4">
          <div className="flex gap-3">
            <select className="input max-w-28 font-mono" value={method} onChange={(e) => setMethod(e.target.value)}>
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}
            </select>
            <input className="input font-mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/api/..." />
            <button className="btn shrink-0">Send</button>
          </div>
          {method !== "GET" && (
            <div>
              <label className="label">JSON body</label>
              <textarea className="input min-h-28 font-mono" value={body} onChange={(e) => setBody(e.target.value)} placeholder='{"key": "value"}' />
            </div>
          )}
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={withToken} onChange={(e) => setWithToken(e.target.checked)} />
            Send my login token
            <span className="text-slate-400">(untick to test as an anonymous visitor)</span>
          </label>
        </form>
        {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
        <ResponseBox result={result} defaultOpen />
      </section>
    </div>
  );
}
