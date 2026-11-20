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
  paused_reason: string | null;
  halted_by: string | null;
  halt_reason: string | null;
  retest_running?: boolean;
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

export type Finding = {
  id: number;
  title: string;
  severity: string | null;
  status: "verified" | "false_positive" | "unverified" | string;
  test_case_id: number | null;
  endpoint_id: number | null;
  vuln_class: string | null;
  verification_reason: string | null;
  checks: { name: string; passed: boolean | null; detail: string }[];
  evidence: EvidenceItem[];
  duplicate_of: number | null;
  rank: number | null;
  severity_score: number | null;
  severity_reason: string | null;
  business_impact: string | null;
  owner: string | null;
  owner_source: string | null;
  first_seen_scan_id: number | null;
  review_status: "awaiting_review" | "confirmed" | "changed" | "not_needed" | null;
  review_note: string | null;
  reviewed_at: string | null;
  retest_status: string | null;
  last_retested_at: string | null;
  fixed_at: string | null;
  retest_running: boolean;
  retests: RetestAttempt[];
};

export type RetestAttempt = {
  at: string | null;
  result: "fixed" | "still_vulnerable" | "partly_fixed" | "inconclusive" | "not_retested" | "still_present" | "stopped" | string;
  reason: string | null;
  triggered_by: string | null;
  scan_id?: number | null;
  checks?: { name: string; passed: boolean | null; detail: string; where?: string }[];
  evidence?: (EvidenceItem & { where?: string })[];
};

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

export type TestCase = {
  id: number;
  endpoint_id: number;
  test_type: string;
  name: string;
  reason: string;
  risk_level: "low" | "medium" | "high";
  requires_approval: boolean;
  planned_by: string;
  status: string;
  exec_status: "ran" | "skipped" | "could_not_run" | null;
  raw_result: "suspicious" | "clean" | null;
  result_summary: string | null;
  executed_at: string | null;
  evidence: EvidenceItem[];
};

export type EvidenceItem = {
  request: { as: string; method: string; path: string; headers: Record<string, string>; body: unknown } | null;
  response: { status: number; key_fields: unknown } | null;
  note: string | null;
};

export type PlanSummary = {
  planner: "groq" | "rules";
  model: string | null;
  why: string;
  tests: number;
  floor_added?: number;
  dropped: string[];
  skips: Record<string, string>;
  requests_to_target: number;
};

export type ScanDetail = ScanSummary & {
  stages: Stage[];
  logs: LogLine[];
  endpoints: Endpoint[];
  test_cases: TestCase[];
  findings: Finding[];
  state: { plan?: PlanSummary } | null;
};

export type AuditRow = {
  id: number;
  at: string | null;
  stage: string | null;
  method: string;
  url: string;
  decision: "allow" | "block" | "hold";
  reason: string | null;
  status: number | null;
  sent: boolean;
  account: string | null;
  test_case_id: number | null;
  latency_ms: number | null;
  waited_ms: number | null;
  request_headers: Record<string, string>;
  request_body: string | null;
};

export type AuditView = {
  summary: {
    allowed: number; held: number; blocked: number; sent: number;
    rate_cap: number; max_per_second: number;
    paused_reason: string | null; halted_by: string | null; halt_reason: string | null; status: string;
  };
  rows: AuditRow[];
};

const BASE = "/scanner-api";

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, body === undefined ? { method: "POST" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`${res.status}: ${(await res.json().catch(() => ({}))).detail ?? ""}`);
  return res.json() as Promise<T>;
}

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
  retest: "Re-prove open findings from earlier scans; closes the fixed ones",
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

// ---------------- report (Phase 9) ----------------

export type Ticket = {
  key: string;
  rank: number;
  finding_id: number;
  title: string;
  severity: string;
  priority: string;
  severity_reason: string | null;
  owner: string | null;
  owner_source: string | null;
  first_seen_scan_id: number | null;
  escalation: "ready" | "draft" | "resolved";
  fixed_at: string | null;
  retest_status: string | null;
  retests: RetestAttempt[];
  review: string;
  vuln_class: string | null;
  test_type: string;
  business_impact: string;
  affected: { method: string; path: string; classification: string | null }[];
  steps: string[];
  expected: string;
  actual: string;
  checks: { name: string; passed: boolean | null; detail: string }[];
  evidence: EvidenceItem[];
  fix: string;
};

export type InventoryRow = {
  method: string;
  path: string;
  classification: string;
  last_traffic_at: string | null;
  hits_in_window: number | null;
  callers: string[];
  reachable_without_login: "yes" | "no" | "unknown";
  reachable_basis: string;
  data_exposed: string[];
  compared_with_current: string;
  vulnerabilities: string[];
  owner: string | null;
  recommendation: string | null;
};

export type Report = {
  scan: { id: number; status: string; started_at: string | null; finished_at: string | null; duration_s: number | null };
  trigger: { event: string | null; method: string | null; endpoint: string | null; version: string | null; received_at: string | null };
  speed: { first_verified_at: string | null; change_to_first_verified_s: number | null };
  summary: {
    tickets: number; open: number; fixed: number; by_severity: Record<string, number>; ready: number; draft: number;
    merged_duplicates: number; false_positives: number; unverified: number; endpoints: number;
    inventory: Record<string, number>; top_risks: string[];
  };
  tickets: Ticket[];
  inventory: InventoryRow[];
  coverage: {
    clean: { test: string; endpoint: string; result: string | null }[];
    false_positives: { title: string; reason: string | null }[];
    unverified: { title: string; reason: string | null }[];
    not_run: { test: string; endpoint: string; result: string | null }[];
  };
  safety: {
    sent: number; blocked: number; held_for_approval: number; held_by_health_monitor: number;
    rate_cap: number; max_per_second: number; by_stage: Record<string, number>;
    blocked_reasons: { reason: string; count: number }[];
    self_test_blocked: number; self_test_reasons: { reason: string; count: number }[];
    human_decisions: { at: string | null; stage: string | null; decision: string }[];
    halted_by: string | null; halt_reason: string | null;
  };
};

export const REPORT_BASE = BASE;

export function seconds(s: number | null): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`;
}
