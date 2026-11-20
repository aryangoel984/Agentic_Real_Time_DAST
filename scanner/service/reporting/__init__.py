"""The report: one document per scan, built fresh from the scanner's database each time it is asked for.

Contents: a summary (what changed, time to the first verified finding, counts), one ticket per
ranked finding (severity, owner, impact, steps to reproduce, evidence, suggested fix, escalation
status), the zombie and shadow endpoints with what the brief asks for each, what was tested and
found clean, and the safety record. A ticket is "ready" once a human has reviewed it (critical and
high) or it needs no review (medium and low); otherwise it stays a draft and is not escalated.

Reporting reads the scanner's own database only. It sends nothing to the target.
"""
import json
from collections import Counter
from datetime import datetime

from sqlalchemy import select

from ..config import GATEWAY_MAX_RPS
from ..db import (ApiEndpoint, AuditLog, DeploymentEvent, Evidence, RetestHistory, ScanRun, SessionLocal, TestCase,
                  Vulnerability)
from ..planner.catalogue import CATALOGUE
from ..triage.rules import strip_version
from . import fixes

PRIORITY = {"critical": "Highest", "high": "High", "medium": "Medium", "low": "Low"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + ("Z" if dt and dt.tzinfo is None else "") if dt else None


def max_per_second(times: list) -> int:
    """Most requests sent inside any 1-second window [t, t+1)."""
    best, j = 0, 0
    for i in range(len(times)):
        while (times[i] - times[j]).total_seconds() >= 1:
            j += 1
        best = max(best, i - j + 1)
    return best


def _ev(x: Evidence) -> dict:
    return {"request": json.loads(x.request_json) if x.request_json else None,
            "response": json.loads(x.response_json) if x.response_json else None, "note": x.notes}


def _seconds(a: datetime | None, b: datetime | None) -> float | None:
    return round((b - a).total_seconds(), 1) if a and b else None


def build_report(scan_id: int) -> dict | None:
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run is None:
            return None
        event = db.scalar(select(DeploymentEvent).where(DeploymentEvent.scan_id == scan_id))
        eps = {e.id: e for e in db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id))}
        tests = {t.id: t for t in db.scalars(select(TestCase).where(TestCase.scan_id == scan_id))}
        vulns = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id)
                           .order_by(Vulnerability.id)).all()
        evidence = db.scalars(select(Evidence).where(Evidence.test_case_id.in_(list(tests) or [0]))
                              .order_by(Evidence.id)).all()
        audit = db.scalars(select(AuditLog).where(AuditLog.scan_id == scan_id).order_by(AuditLog.id)).all()

        vuln_ev: dict[int, list] = {}
        test_ev: dict[int, list] = {}
        for x in evidence:
            (vuln_ev.setdefault(x.vulnerability_id, []) if x.vulnerability_id else
             test_ev.setdefault(x.test_case_id, [])).append(_ev(x))

        history: dict[int, list] = {}
        for h in db.scalars(select(RetestHistory).where(RetestHistory.vulnerability_id.in_([v.id for v in vulns] or [0]))
                            .order_by(RetestHistory.id)):
            history.setdefault(h.vulnerability_id, []).append(
                {"at": _iso(h.ran_at), "result": h.result, "reason": h.notes, "triggered_by": h.triggered_by})
        ranked = sorted((v for v in vulns if v.rank is not None), key=lambda v: v.rank)
        key_of = {v.id: f"DAST-{scan_id}-{v.rank:02d}" for v in ranked}
        for v in vulns:
            if v.duplicate_of in key_of:
                key_of[v.id] = key_of[v.duplicate_of]
        tickets = [_ticket(v, [d for d in vulns if d.duplicate_of == v.id], eps, tests, vuln_ev, key_of[v.id],
                           history.get(v.id, [])) for v in ranked]

        verified_at = [v.last_seen_at for v in vulns if v.status == "verified"]
        first_verified = min(verified_at) if verified_at else None
        change_at = event.received_at if event else run.created_at

        open_tickets = [t for t in tickets if t["escalation"] != "resolved"]
        sev = Counter(t["severity"] for t in open_tickets)
        report = {
            "scan": {"id": scan_id, "status": run.status, "started_at": _iso(run.started_at),
                     "finished_at": _iso(run.finished_at), "duration_s": _seconds(run.started_at, run.finished_at)},
            "trigger": {"event": event.event_type if event else None, "method": event.method if event else None,
                        "endpoint": event.endpoint if event else None, "version": event.version if event else None,
                        "received_at": _iso(change_at)},
            "speed": {"first_verified_at": _iso(first_verified),
                      "change_to_first_verified_s": _seconds(change_at, first_verified)},
            "summary": {
                "tickets": len(tickets), "open": len(open_tickets), "fixed": len(tickets) - len(open_tickets),
                "by_severity": {s: sev.get(s, 0) for s in PRIORITY},
                "ready": sum(1 for t in tickets if t["escalation"] == "ready"),
                "draft": sum(1 for t in tickets if t["escalation"] == "draft"),
                "merged_duplicates": sum(1 for v in vulns if v.duplicate_of is not None),
                "false_positives": sum(1 for v in vulns if v.status == "false_positive"),
                "unverified": sum(1 for v in vulns if v.status == "unverified"),
                "endpoints": len(eps),
                "inventory": dict(Counter(e.classification or "unclassified" for e in eps.values())),
                "top_risks": [f"{t['key']} {t['severity'].upper()}: {t['business_impact'].split('. ')[0].rstrip('.')}."
                              for t in open_tickets[:3]],
            },
            "tickets": tickets,
            "inventory": [_inventory_row(e, eps, vulns, tests, test_ev, vuln_ev, key_of)
                          for e in sorted(eps.values(), key=lambda e: (e.classification != "zombie", e.path))
                          if e.classification in ("zombie", "shadow")],
            "coverage": _coverage(tests, eps, vulns),
            "safety": _safety(run, audit),
        }
    return report


def _ticket(v, dupes, eps, tests, vuln_ev, key, retests) -> dict:
    ep, tc = eps[v.endpoint_id], tests[v.test_case_id]
    expected, actual = fixes.expected_actual(tc.test_type)
    ev = vuln_ev.get(v.id, [])
    escalation = ("resolved" if v.status == "fixed" else
                  "draft" if v.review_status == "awaiting_review" else "ready")
    review = {"awaiting_review": "Waiting for human review: not escalated yet",
              "confirmed": f"Severity confirmed by a human reviewer{': ' + v.review_note if v.review_note else ''}",
              "changed": f"Severity changed by a human reviewer: {v.review_note or ''}".rstrip(": "),
              "not_needed": "No review needed for this severity"}.get(v.review_status or "", "")
    return {
        "key": key, "rank": v.rank, "finding_id": v.id, "title": v.title, "severity": v.severity,
        "priority": PRIORITY.get(v.severity or "", "Medium"), "severity_reason": v.severity_reason,
        "owner": v.owner, "owner_source": v.owner_source, "first_seen_scan_id": v.first_seen_scan_id,
        "escalation": escalation, "review": review, "reviewed_at": _iso(v.reviewed_at),
        "vuln_class": v.vuln_class, "test_type": tc.test_type, "business_impact": v.business_impact or "",
        "affected": [{"method": e.method, "path": e.path, "classification": e.classification}
                     for e in [ep] + [eps[d.endpoint_id] for d in dupes]],
        "steps": fixes.steps(tc.test_type, ev), "expected": expected, "actual": actual,
        "checks": json.loads(v.checks_json or "[]"), "evidence": ev, "fix": fixes.fix_for(tc.test_type),
        "fixed_at": _iso(v.fixed_at), "retest_status": v.retest_status, "retests": retests,
    }


def _inventory_row(e, eps, vulns, tests, test_ev, vuln_ev, key_of) -> dict:
    mine = [v for v in vulns if v.endpoint_id == e.id and v.status == "verified"]
    no_login = [v for v in mine if tests[v.test_case_id].test_type == "missing_auth"]
    if no_login:
        reach = ("yes", f"verified: answered without a login ({key_of.get(no_login[0].id, '')})")
    elif e.auth_required is True:
        reach = ("no", e.auth_basis or "refused without a token")
    elif e.auth_required is False:
        reach = ("yes", e.auth_basis or "answered without a token")
    else:
        reach = ("unknown", e.auth_basis or "not tested")

    fields: set[str] = set()
    for t in (t for t in tests.values() if t.endpoint_id == e.id):
        for x in test_ev.get(t.id, []) + [y for v in mine for y in vuln_ev.get(v.id, [])]:
            resp = x.get("response") or {}
            if resp.get("status") == 200 and isinstance(resp.get("key_fields"), dict):
                fields |= {k for k in resp["key_fields"] if k not in ("detail", "keys")}

    current = next((c for c in eps.values() if c.id != e.id and c.classification == "active"
                    and c.method == e.method and c.path == strip_version(e.path) != e.path), None)
    def flaw(v):   # the zombie ownership check is the same flaw as a cross-agency read
        tt = tests[v.test_case_id].test_type
        tt = "cross_agency_access" if tt == "zombie_ownership_check" else tt
        return CATALOGUE[tt].name if tt in CATALOGUE else tt
    flaws = sorted({flaw(v) for v in mine})
    if current:
        cur = sorted({flaw(v) for v in vulns if v.endpoint_id == current.id and v.status == "verified"})
        here = ", ".join(flaws) or "no verified flaws"
        if flaws and flaws == cur:
            compared = f"Same flaw as the current version {current.method} {current.path} ({here}): fixing one does not fix the other."
        elif flaws and not cur:
            compared = f"Worse than the current version {current.method} {current.path}, which has no verified flaws. This version: {here}."
        else:
            compared = (f"This version: {here}. Current version {current.method} {current.path}: "
                        f"{', '.join(cur) or 'no verified flaws'}.")
    else:
        compared = "No current version of this route was found: it has no documented counterpart."

    traffic = json.loads(e.traffic_json) if e.traffic_json else {}
    return {"method": e.method, "path": e.path, "classification": e.classification,
            "last_traffic_at": e.last_traffic_at, "hits_in_window": traffic.get("hits_in_window"),
            "callers": [c["caller"] for c in traffic.get("callers", [])],
            "reachable_without_login": reach[0], "reachable_basis": reach[1],
            "data_exposed": sorted(fields), "compared_with_current": compared,
            "vulnerabilities": [f"{key_of.get(v.id, '#' + str(v.id))} {v.title}" for v in mine],
            "owner": e.owner, "recommendation": e.recommendation}


def _coverage(tests, eps, vulns) -> dict:
    def where(t):
        e = eps.get(t.endpoint_id)
        return f"{e.method} {e.path}" if e else ""
    name = lambda t: CATALOGUE[t.test_type].name if t.test_type in CATALOGUE else t.test_type  # noqa: E731
    return {
        "clean": [{"test": name(t), "endpoint": where(t), "result": t.result_summary}
                  for t in tests.values() if t.raw_result == "clean"],
        "false_positives": [{"title": v.title, "reason": v.verification_reason} for v in vulns if v.status == "false_positive"],
        "unverified": [{"title": v.title, "reason": v.verification_reason} for v in vulns if v.status == "unverified"],
        "not_run": [{"test": name(t), "endpoint": where(t), "result": t.result_summary}
                    for t in tests.values() if t.exec_status in ("skipped", "could_not_run")],
    }


def _safety(run, audit) -> dict:
    sent = sorted(a.sent_at for a in audit if a.sent)
    blocks = [a for a in audit if a.decision == "block" and "by a human" not in (a.reason or "")]
    # the safety_gateway stage's blocks are its own self-test: deliberately bad requests in dry-run mode
    blocked = Counter(a.reason for a in blocks if a.stage != "safety_gateway")
    self_test = Counter(a.reason for a in blocks if a.stage == "safety_gateway")
    health_holds = [a for a in audit if a.decision == "hold" and "human approval" not in (a.reason or "")]
    return {
        "sent": len(sent), "blocked": sum(blocked.values()),
        "held_for_approval": sum(1 for a in audit if a.decision == "hold" and "human approval" in (a.reason or "")),
        "held_by_health_monitor": len(health_holds), "rate_cap": GATEWAY_MAX_RPS,
        "max_per_second": max_per_second(sent),
        "blocked_reasons": [{"reason": r, "count": n} for r, n in blocked.items()],
        "self_test_blocked": sum(self_test.values()),
        "self_test_reasons": [{"reason": r, "count": n} for r, n in self_test.items()],
        "human_decisions": [{"at": _iso(a.sent_at), "stage": a.stage, "decision": a.reason}
                            for a in audit if "by a human" in (a.reason or "")],
        "halted_by": run.halted_by, "halt_reason": run.halt_reason,
        "by_stage": dict(Counter(a.stage for a in audit if a.sent)),
    }


def tickets_export(report: dict) -> list[dict]:
    """One entry per ticket, in the shape issue trackers such as Jira import."""
    from .markdown import ticket_markdown
    return [{"key": t["key"], "summary": f"[{t['severity'].upper()}] {t['title']}", "priority": t["priority"],
             "component": t["owner"], "labels": ["dast", t["vuln_class"] or "", t["test_type"]] +
             sorted({a["classification"] for a in t["affected"] if a["classification"] in ("zombie", "shadow")}),
             "status": {"ready": "Ready to raise", "draft": "Draft: awaiting human review",
                        "resolved": "Resolved (fixed, retest passed)"}[t["escalation"]],
             "description": ticket_markdown(t)} for t in report["tickets"]]


def run_reporting(scan_id: int, log) -> dict:
    r = build_report(scan_id)
    s = r["summary"]
    log(f"report ready: {s['tickets']} ticket(s), {s['ready']} ready to raise, {s['draft']} waiting for human review, "
        f"{s['fixed']} resolved; "
        f"{len(r['inventory'])} zombie/shadow endpoint(s) described; {len(r['coverage']['clean'])} clean test(s) listed. "
        f"Open it from the Report card. No requests were sent")
    if r["speed"]["change_to_first_verified_s"] is not None:
        log(f"time from the change to the first verified finding: {r['speed']['change_to_first_verified_s']:.0f}s")
    return {"tickets": s["tickets"], "ready": s["ready"], "draft": s["draft"]}
