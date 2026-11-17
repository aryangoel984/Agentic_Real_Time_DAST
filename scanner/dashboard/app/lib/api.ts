// Types and fetch helpers for the scanner API (forwarded via /scanner-api).

export type Trigger = {
  id: number;
  event: string;
  endpoint: string | null;
  method: string | null;
  version: string | null;
  timestamp: string | null;
  received_at: string | null;
};

export type ScanSummary = {
  id: number;
  status: string;
  current_stage: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  stages_done: number;
  stages_total: number;
  trigger: Trigger | null;
};

export type Stage = {
  stage: string;
  position: number;
  status: string;
  runs: number;
  started_at: string | null;
  finished_at: string | null;
};

export type LogLine = { id: number; stage: string | null; level: string; message: string; created_at: string | null };

export type Finding = { id: number; title: string; severity: string | null; status: string };

export type Endpoint = {
  id: number;
  method: string;
  path: string;
  params: { path: string[]; query: string[]; body: string[] } | null;
  auth_required: boolean | null;
  auth_basis: string | null;
  roles: string[];
  purpose: string | null;
  discovered_via: string[];
  classification: "active" | "zombie" | "shadow" | null;
  last_traffic_at: string | null;
  traffic: { hits: number; hits_in_window: number; callers: { caller: string; hits: number }[] } | null;
  recommendation: string | null;
  owner: string | null;
};

export type ScanDetail = ScanSummary & { stages: Stage[]; logs: LogLine[]; endpoints: Endpoint[]; findings: Finding[] };

const BASE = "/scanner-api";

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<T>;
}

export const STAGE_LABELS: Record<string, string> = {
  change_detection: "Change detection",
  recon: "Recon",
  inventory: "Inventory",
  attack_planning: "Attack planning",
  safety_gateway: "Safety gateway",
  execution: "Execution",
  verification: "Verification",
  triage: "Triage",
  reporting: "Reporting",
  retest: "Retest",
};

export const STAGE_HINTS: Record<string, string> = {
  change_detection: "What changed and what needs testing",
  recon: "Discover endpoints, parameters and roles",
  inventory: "Label endpoints active / zombie / shadow",
  attack_planning: "Choose targeted tests per endpoint",
  safety_gateway: "Scope, rate limits and approvals",
  execution: "Send the planned test requests",
  verification: "Prove each hit with minimal evidence",
  triage: "De-duplicate, score severity, map owner",
  reporting: "Raise ticket-ready findings",
  retest: "Re-check after a fix; loops back to verification",
};

export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function duration(start: string | null, end: string | null): string {
  if (!start) return "";
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime();
  if (ms < 1000) return `${Math.max(ms, 0)} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.max(s, 0)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
