"""Prove the report is complete, correct and safe, without the target running.

Builds a scan's records directly in a scratch database (endpoints, tests, verified findings with
masked evidence, audit rows), runs the real triage and report code, and checks every section the
brief asks for, the Markdown and ticket downloads, Draft -> Ready after a review, and that no
password or token appears anywhere.

Run from the project root:
    scanner/.venv/bin/python scanner/scripts/check_report.py
"""
import json
import os
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="report-check-")
os.environ["SCANNER_DATABASE_URL"] = f"sqlite:///{TMP}/check.db"
os.environ.pop("TARGET_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from service.config import TARGET_PROFILE  # noqa: E402
from service.db import (ApiEndpoint, AuditLog, DeploymentEvent, Evidence, ScanRun, SessionLocal, TestCase,  # noqa: E402
                        Vulnerability, init_db, now)
from service.main import app  # noqa: E402
from service.reporting import build_report  # noqa: E402
from service.triage import run_triage  # noqa: E402

PASSWORDS = [a["password"] for a in TARGET_PROFILE["accounts"]]
BOOKING = {"id": 1020, "agency_id": 1, "customer_name": "DAST Synthetic Customer", "amount": 25000.0}


def ex(who, method, path, status, fields, body=None, note=""):
    hdr = {"authorization": "Bearer ***"} if who != "no login" else {}
    return ({"as": who, "method": method, "path": path, "headers": hdr, "body": body},
            {"status": status, "key_fields": fields}, note)


READ_CHECKS = [{"name": "repeat on fresh data", "passed": True, "detail": "B-admin asked for #1020: HTTP 200 with agency_id 1"},
               {"name": "matches the owner's copy", "passed": True, "detail": "identical to what the owner sees"},
               {"name": "made-up ID refused", "passed": True, "detail": "ID 987654321 returned HTTP 404"}]
REFUND_CHECKS = [{"name": "repeat on fresh data", "passed": True, "detail": "second refund returned HTTP 200"},
                 {"name": "booking read back", "passed": True, "detail": "booking #1022 now shows ₹50,000 refunded against ₹25,000 paid"}]
SHADOW_CHECKS = [{"name": "repeat without a login", "passed": True, "detail": "no-login request returned HTTP 200"},
                 {"name": "same data as a logged-in request", "passed": True, "detail": "same fields (agencies, note, suppliers)"}]

# method, path, purpose, class, owner guess, auth_required, last traffic, traffic
ENDPOINTS = {
    "read": ("GET", "/api/bookings/{id}", "booking", "active", "Bookings team", True, "2026-11-13T13:44:18+00:00", 303),
    "v1": ("GET", "/api/v1/bookings/{id}", "booking", "zombie", "Bookings team", True, None, 0),
    "refund": ("POST", "/api/refunds", "refund", "active", "Payments team", True, "2026-11-12T11:08:39+00:00", 30),
    "shadow": ("GET", "/api/internal/partner-details", "partner", "shadow", "Partner integrations", None,
               "2026-11-11T20:04:00+00:00", 10),
    "users": ("GET", "/api/users/{id}", "user", "active", "Identity team", True, "2026-11-13T10:43:08+00:00", 69),
}
# endpoint, test type, raw result, verdict (None = clean), checks, verification evidence
TESTS = [
    ("read", "cross_agency_access", "suspicious", "verified", READ_CHECKS,
     [ex("B-admin", "GET", "/api/bookings/1020", 200, BOOKING, note="repeat as the other agency"),
      ex("A-admin", "GET", "/api/bookings/1020", 200, BOOKING, note="owner's own read"),
      ex("B-admin", "GET", "/api/bookings/987654321", 404, {"detail": "Booking not found"}, note="made-up ID")]),
    ("v1", "zombie_ownership_check", "suspicious", "verified", READ_CHECKS,
     [ex("B-admin", "GET", "/api/v1/bookings/1023", 200, {**BOOKING, "id": 1023}, note="repeat as the other agency")]),
    ("refund", "duplicate_refund", "suspicious", "verified", REFUND_CHECKS,
     [ex("A-admin", "POST", "/api/refunds", 200, {"total_refunded": 50000.0}, body={"amount": 25000, "booking_id": 1022},
         note="second refund (repeat)"),
      ex("A-admin", "GET", "/api/bookings/1022", 200, {"payment_status": "paid", "total_refunded": 50000.0},
         note="owner reads the booking back")]),
    ("shadow", "missing_auth", "suspicious", "verified", SHADOW_CHECKS,
     [ex("no login", "GET", "/api/internal/partner-details", 200, {"note": "internal use only", "agencies": "[2 item(s)]"},
         note="repeat with no token")]),
    ("users", "cross_agency_access", "suspicious", "false_positive",
     [{"name": "repeat on fresh data", "passed": False, "detail": "HTTP 404 on the repeat"}], []),
    ("refund", "authorization", "clean", None, [], []),
]


def build() -> int:
    init_db()
    with SessionLocal() as db:
        start = now()
        run = ScanRun(status="completed", started_at=start, finished_at=start + timedelta(seconds=55))
        db.add(run)
        db.flush()
        db.add(DeploymentEvent(scan_id=run.id, event_type="API_DEPLOYED", endpoint="/api/refunds", method="POST",
                               version="v2", raw_json="{}", received_at=start))
        ids = {}
        for k, (m, p, purpose, cls, owner, auth, last, hits) in ENDPOINTS.items():
            e = ApiEndpoint(scan_id=run.id, method=m, path=p, business_area=purpose, classification=cls, owner=owner,
                            auth_required=auth, auth_basis="verified: 401 without a token" if auth else "not tested",
                            last_traffic_at=last, recommendation=f"recommendation for {cls}",
                            traffic_json=json.dumps({"hits_in_window": hits, "callers": [{"caller": "10.0.4.17", "hits": hits}] if hits else []}))
            db.add(e)
            db.flush()
            ids[k] = e.id
        for i, (k, tt, raw, verdict, checks, evs) in enumerate(TESTS):
            tc = TestCase(scan_id=run.id, endpoint_id=ids[k], test_type=tt, status="cleared", exec_status="ran",
                          raw_result=raw, result_summary=f"{tt}: {'refused with HTTP 403 (as expected)' if raw == 'clean' else 'leaked'}")
            db.add(tc)
            db.flush()
            if verdict:
                v = Vulnerability(scan_id=run.id, endpoint_id=ids[k], test_case_id=tc.id, title=f"{tt} on {ENDPOINTS[k][1]}",
                                  status=verdict, checks_json=json.dumps(checks), verification_reason="checked",
                                  last_seen_at=start + timedelta(seconds=40 + i))
                db.add(v)
                db.flush()
                for req, resp, note in evs:
                    db.add(Evidence(vulnerability_id=v.id, test_case_id=tc.id, request_json=json.dumps(req),
                                    response_json=json.dumps(resp), notes=note))
        for reason in ("out of scope: only http://localhost:3000 may be contacted, not http://example.com",
                       "method DELETE is not allowed", "login as 'selftest_intruder' refused",
                       "unknown token", "high-risk test #3 is not approved"):
            db.add(AuditLog(scan_id=run.id, stage="safety_gateway", method="GET", url="-", decision="block",
                            reason=reason, sent=False, sent_at=start))
        db.add(AuditLog(scan_id=run.id, stage="safety_gateway", method="POST", url="/api/refunds", decision="allow",
                        reason="high-risk test #3 (duplicate_refund) approved by a human on the dashboard", sent=False,
                        sent_at=start))
        db.add(AuditLog(scan_id=run.id, stage="execution", method="GET", url="/api/admin/users", decision="block",
                        reason="path /api/admin/ is excluded from scope", sent=False, sent_at=start))
        for j in range(12):   # 12 sent requests, 4 per second
            db.add(AuditLog(scan_id=run.id, stage="recon" if j < 8 else "verification", method="GET", url="/",
                            decision="allow", sent=True, sent_at=start + timedelta(milliseconds=250 * j),
                            request_headers_json=json.dumps({"authorization": "Bearer ***"})))
        db.commit()
        return run.id


results: list[bool] = []


def check(ok: bool, what: str) -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {what}")


sid = build()
run_triage(sid, lambda *a, **k: None)
with SessionLocal() as db:
    audit_before = db.query(AuditLog).filter(AuditLog.scan_id == sid).count()

api = TestClient(app)
r = api.get(f"/scans/{sid}/report").json()
s, tickets = r["summary"], r["tickets"]

# summary
check(r["trigger"]["event"] == "API_DEPLOYED" and r["speed"]["change_to_first_verified_s"] == 40.0,
      f"summary: what changed + 40s from change to first verified finding (got {r['speed']['change_to_first_verified_s']})")
check(s["tickets"] == 3 and s["merged_duplicates"] == 1 and s["false_positives"] == 1,
      "summary: 3 tickets, 1 duplicate merged, 1 false positive rejected")
check(len(s["top_risks"]) == 3 and s["top_risks"][0].startswith(f"DAST-{sid}-01 CRITICAL"), "summary: top risks, critical first")

# tickets
check([t["key"] for t in tickets] == [f"DAST-{sid}-0{i}" for i in (1, 2, 3)], "tickets keyed DAST-<scan>-<rank> in rank order")
need = ("severity", "severity_reason", "owner", "business_impact", "steps", "expected", "actual", "checks", "evidence", "fix")
check(all(all(t[k] for k in need) for t in tickets), "every ticket has severity, owner, impact, steps, expected/actual, checks, evidence, fix")
read = next(t for t in tickets if t["test_type"] == "cross_agency_access")
check(len(read["affected"]) == 2 and read["affected"][1]["classification"] == "zombie", "booking ticket lists the zombie copy")
check(len(read["steps"]) == 4 and "As B-admin, send GET /api/bookings/1020" in read["steps"][1],
      "steps to reproduce: setup + each verification request as the right account")
check(all(t["escalation"] == "draft" for t in tickets), "unreviewed critical/high tickets are drafts")

# zombie and shadow
inv = {e["classification"]: e for e in r["inventory"]}
z, sh = inv.get("zombie"), inv.get("shadow")
six = ("last_traffic_at", "reachable_without_login", "data_exposed", "compared_with_current", "owner", "recommendation")
check(z is not None and sh is not None and all(k in z and k in sh for k in six), "zombie and shadow rows have all six items the brief asks for")
check(z["reachable_without_login"] == "no" and z["compared_with_current"].startswith("Same flaw as the current version"),
      "zombie: needs a login, same flaw as the current version")
check(sh["reachable_without_login"] == "yes" and "agencies" in sh["data_exposed"], "shadow: open without login, exposes partner data")
check(z["last_traffic_at"] is None and sh["last_traffic_at"].startswith("2026-11-11"), "last real traffic from the log")

# coverage and safety
check(len(r["coverage"]["clean"]) == 1 and len(r["coverage"]["false_positives"]) == 1, "clean tests and rejected false positives listed")
sf = r["safety"]
check(sf["sent"] == 12 and sf["max_per_second"] == 4 and sf["by_stage"] == {"recon": 8, "verification": 4},
      "safety: sent count, peak rate and per-stage split match the audit log")
check(sf["self_test_blocked"] == 5 and sf["blocked"] == 1, "safety: self-test blocks kept apart from real blocks")
check(len(sf["human_decisions"]) == 1, "safety: human approval listed")

# downloads
md = api.get(f"/scans/{sid}/report.md")
tj = api.get(f"/scans/{sid}/tickets.json")
check(md.status_code == 200 and "attachment" in md.headers["content-disposition"] and md.text.count("### DAST-") == 3,
      "Markdown download: attachment with the same 3 tickets")
tk = tj.json()
check(tj.status_code == 200 and len(tk) == 3 and all(set(t) >= {"summary", "priority", "component", "labels", "description"} for t in tk)
      and tk[0]["priority"] == "Highest", "tickets.json: tracker fields, critical = Highest priority")

# no secrets anywhere
blob = json.dumps(r) + md.text + tj.text
leaks = [p for p in PASSWORDS if p in blob] + re.findall(r"Bearer (?!\*\*\*)\S+", blob)
check(not leaks, f"no password or unmasked token in the report or downloads ({leaks or 'none'})")

# Draft -> Ready after review
api.post(f"/scans/{sid}/findings/{tickets[0]['finding_id']}/review", json={"action": "confirm"})
r2 = api.get(f"/scans/{sid}/report").json()
check(r2["tickets"][0]["escalation"] == "ready" and r2["summary"]["ready"] == 1, "a confirmed ticket becomes Ready to raise")
check("confirmed" in api.get(f"/scans/{sid}/report.md").text.split("### DAST-")[1], "the Markdown reflects the review at once")

with SessionLocal() as db:
    audit_after = db.query(AuditLog).filter(AuditLog.scan_id == sid).count()
check(audit_after == audit_before + 1, "building the report sent nothing (only the review added an audit row)")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
