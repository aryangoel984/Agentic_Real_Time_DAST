"use client";

import { useState } from "react";
import RequireLogin from "../components/RequireLogin";
import ResponseBox from "../components/ResponseBox";
import { apiRequest, ApiResult, inr } from "../lib/api";

type Row = Record<string, string | number>;

export default function SearchPage() {
  return (
    <RequireLogin>
      <Search />
    </RequireLogin>
  );
}

function Search() {
  const [type, setType] = useState("flight");
  const [origin, setOrigin] = useState("DEL");
  const [destination, setDestination] = useState("BOM");
  const [result, setResult] = useState<ApiResult | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const q = new URLSearchParams({ type, origin, destination });
    setResult(await apiRequest("GET", `/api/search?${q}`));
  }

  const rows = result?.ok ? ((result.data as { results: Row[] }).results ?? []) : [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <p className="mt-1 text-sm text-slate-500">Find flights and hotels.</p>
      </div>
      <section className="card">
        <form onSubmit={run} className="grid gap-4 sm:grid-cols-4">
          <div>
            <label className="label">Type</label>
            <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="flight">Flight</option>
              <option value="hotel">Hotel</option>
            </select>
          </div>
          {type === "flight" && (
            <div>
              <label className="label">From</label>
              <input className="input font-mono uppercase" value={origin} onChange={(e) => setOrigin(e.target.value)} />
            </div>
          )}
          <div>
            <label className="label">{type === "flight" ? "To" : "City"}</label>
            <input className="input font-mono uppercase" value={destination} onChange={(e) => setDestination(e.target.value)} />
          </div>
          <div className="flex items-end">
            <button className="btn w-full">Search</button>
          </div>
        </form>

        {rows.length > 0 && (
          <table className="mt-6 w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left">
                {Object.keys(rows[0]).map((k) => (
                  <th key={k} className="label py-2">{k.replace("_", " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  {Object.entries(r).map(([k, v]) => (
                    <td key={k} className="py-3">
                      {k === "fare" || k === "per_night" ? inr(Number(v)) : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <ResponseBox result={result} />
      </section>
    </div>
  );
}
