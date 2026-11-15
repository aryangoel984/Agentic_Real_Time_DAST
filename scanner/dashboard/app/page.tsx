"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import ScanDetailView from "./components/ScanDetail";
import ScanList from "./components/ScanList";
import { fetchJson, ScanDetail, ScanSummary } from "./lib/api";

const POLL_MS = 1500;

export default function Page() {
  return (
    <Suspense>
      <CommandCenter />
    </Suspense>
  );
}

function CommandCenter() {
  const router = useRouter();
  const params = useSearchParams();
  const selectedParam = params.get("scan");
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [detail, setDetail] = useState<ScanDetail | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [notFound, setNotFound] = useState(false);

  // Selected scan lives in the URL (?scan=N), so a refresh reopens it.
  // With no selection, show the newest scan.
  const selected = selectedParam ? Number(selectedParam) : scans[0]?.id ?? null;

  const select = useCallback((id: number) => router.replace(`/?scan=${id}`), [router]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const list = await fetchJson<ScanSummary[]>("/scans");
        if (alive) { setScans(list); setOnline(true); }
      } catch {
        if (alive) setOnline(false);
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    if (selected === null) { setDetail(null); return; }
    let alive = true;
    const load = async () => {
      try {
        const d = await fetchJson<ScanDetail>(`/scans/${selected}`);
        if (alive) { setDetail(d); setNotFound(false); }
      } catch (e) {
        if (alive && String(e).includes("404")) { setDetail(null); setNotFound(true); }
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [selected]);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900 text-white">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3Z" strokeLinejoin="round" />
            </svg>
          </div>
          <div>
            <h1 className="text-base font-semibold leading-tight">Security Command Center</h1>
            <p className="text-xs text-slate-400">Agentic real-time DAST · TravelHub B2B</p>
          </div>
          <div className="ml-auto flex items-center gap-2 text-xs text-slate-300">
            <span className={`h-2 w-2 rounded-full ${online === null ? "bg-slate-500" : online ? "bg-emerald-400" : "bg-red-500"}`} />
            {online === null ? "Connecting…" : online ? "Scanner online" : "Scanner offline (port 9000)"}
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside>
          <ScanList scans={scans} selected={selected} onSelect={select} />
        </aside>
        <section>
          {detail ? (
            <ScanDetailView scan={detail} />
          ) : notFound ? (
            <div className="card p-10 text-center text-sm text-slate-500">Scan #{selectedParam} was not found.</div>
          ) : scans.length === 0 && online !== null ? (
            <div className="card p-10 text-center">
              <p className="text-sm font-medium text-slate-700">No scans yet</p>
              <p className="mt-1 text-sm text-slate-500">Fire a deploy event to start one:</p>
              <code className="mt-4 inline-block rounded-lg bg-slate-100 px-3 py-2 font-mono text-xs text-slate-700">
                scanner/.venv/bin/python scanner/scripts/fire_event.py
              </code>
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}
