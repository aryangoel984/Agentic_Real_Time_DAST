"use client";

import { useState } from "react";
import type { ApiResult } from "../lib/api";

function statusStyle(status: number) {
  if (status >= 200 && status < 300) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (status >= 400 && status < 500) return "bg-amber-50 text-amber-800 ring-amber-200";
  return "bg-red-50 text-red-700 ring-red-200";
}

// Shows what the server answered: status (colour-coded), timing, and the raw JSON.
export default function ResponseBox({ result, defaultOpen = false }: { result: ApiResult | null; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!result) return null;
  const detail =
    result.data && typeof result.data === "object" && "detail" in (result.data as object)
      ? String((result.data as { detail: unknown }).detail)
      : null;
  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm"
      >
        <span className={`rounded-md px-2 py-0.5 font-mono text-xs font-semibold ring-1 ${statusStyle(result.status)}`}>
          {result.status || "ERR"}
        </span>
        <span className="font-mono text-xs text-slate-600">
          {result.method} {result.path}
        </span>
        <span className="ml-auto text-xs text-slate-400">{result.ms} ms · {open ? "hide" : "show"} response</span>
      </button>
      {detail && !open && <p className="px-4 pb-2.5 text-sm text-slate-700">{detail}</p>}
      {open && (
        <pre className="max-h-96 overflow-auto border-t border-slate-200 px-4 py-3 font-mono text-xs leading-relaxed text-slate-800">
          {typeof result.data === "string" ? result.data : JSON.stringify(result.data, null, 2)}
        </pre>
      )}
    </div>
  );
}
