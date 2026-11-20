"""Prove the triage rules on made-up findings, without the target running.

Builds verified findings directly in a scratch database (the shapes Phase 7 produces), runs the
real triage stage, and checks: duplicates merged, each severity rule, owners, false positives
kept out of the ranking, earlier scans matched, nothing sent, and the human review API.

Run from the project root:
    scanner/.venv/bin/python scanner/scripts/check_triage.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="triage-check-")
os.environ["SCANNER_DATABASE_URL"] = f"sqlite:///{TMP}/check.db"
os.environ.pop("TARGET_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from service.db import ApiEndpoint, AuditLog, ScanRun, SessionLocal, TestCase, Vulnerability, init_db  # noqa: E402
from service.main import app  # noqa: E402
from service.triage import run_triage  # noqa: E402
from service.triage.rules import score  # noqa: E402

READBACK_REFUND = [{"name": "repeat on fresh data", "passed": True, "detail": "booking #5001: second refund returned HTTP 200"},
                   {"name": "booking read back", "passed": True,
                    "detail": "booking #5001 now shows ₹50,000 refunded against ₹25,000 paid"}]
READ = [{"name": "repeat on fresh data", "passed": True, "detail": "B-admin asked for a fresh booking: HTTP 200"},
        {"name": "matches the owner's copy", "passed": True, "detail": "identical to what the owner sees"},
        {"name": "made-up ID refused", "passed": True, "detail": "ID 987654321 returned HTTP 404"}]

# (method, path, purpose, classification, inventory owner guess, test_type, verdict, checks)
FINDINGS = [
    ("GET", "/api/bookings/{id}", "booking", "active", "Bookings team", "cross_agency_access", "verified", READ),
    ("GET", "/api/v1/bookings/{id}", "booking", "zombie", "Bookings team", "zombie_ownership_check", "verified", READ),
    ("POST", "/api/refunds", "refund", "active", "Payments team", "duplicate_refund", "verified", READBACK_REFUND),
    ("POST", "/api/payments", "payment", "active", "Payments team", "amount_validation", "verified", READBACK_REFUND),
    ("GET", "/api/internal/partner-details", "partner", "shadow", "Partner integrations", "missing_auth", "verified", READ),
    ("GET", "/api/users/{id}", "user", "active", "Identity team", "cross_agency_access", "false_positive", READ),
    ("POST", "/api/bookings", "booking", "active", "Bookings team", "cross_agency_access", "unverified", []),
]


def make_scan() -> int:
    init_db()
    with SessionLocal() as db:
        run = ScanRun(status="running")
        db.add(run)
        db.flush()
        for m, p, purpose, cls, owner, tt, status, checks in FINDINGS:
            ep = ApiEndpoint(scan_id=run.id, method=m, path=p, business_area=purpose, classification=cls, owner=owner)
            db.add(ep)
            db.flush()
            tc = TestCase(scan_id=run.id, endpoint_id=ep.id, test_type=tt, status="cleared",
                          exec_status="ran", raw_result="suspicious")
            db.add(tc)
            db.flush()
            db.add(Vulnerability(scan_id=run.id, endpoint_id=ep.id, test_case_id=tc.id, title=f"{tt} on {m} {p}",
                                 status=status, checks_json=json.dumps(checks)))
        db.commit()
        return run.id


def findings(scan_id: int) -> dict[str, Vulnerability]:
    with SessionLocal() as db:
        rows = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id)).all()
        eps = {e.id: e for e in db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id))}
        db.expunge_all()
        return {f"{eps[v.endpoint_id].method} {eps[v.endpoint_id].path}": v for v in rows}


results: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    results.append((ok, what))
    print(f"{'PASS' if ok else 'FAIL'}  {what}")


quiet = lambda *a, **k: None  # noqa: E731

# ---- scan 1 ----
s1 = make_scan()
counts = run_triage(s1, quiet)
f = findings(s1)
idor, v1 = f["GET /api/bookings/{id}"], f["GET /api/v1/bookings/{id}"]
refund, pay, shadow = f["POST /api/refunds"], f["POST /api/payments"], f["GET /api/internal/partner-details"]
fp, unv = f["GET /api/users/{id}"], f["POST /api/bookings"]

check(counts["findings"] == 4 and counts["merged"] == 1, f"5 verified -> 4 ranked findings, 1 merged (got {counts['findings']}, {counts['merged']})")
check(v1.duplicate_of == idor.id and v1.rank is None, "zombie v1 leak merged into the current booking leak")
check("/api/v1/bookings/{id} (zombie)" in (idor.business_impact or ""), "booking leak lists the v1 copy under 'also reachable through'")
check(refund.severity == "critical" and pay.severity == "critical", f"money bugs are critical (refund {refund.severity}, payment {pay.severity})")
check(idor.severity == "high" and "zombie" in idor.severity_reason, f"booking leak is high, raised by the zombie copy ({idor.severity_score})")
check(shadow.severity == "high", f"shadow no-login partner data is high ({shadow.severity_reason})")
check(sorted(v.rank for v in (idor, refund, pay, shadow)) == [1, 2, 3, 4] and {refund.rank, pay.rank} == {1, 2},
      "ranked 1-4 with the critical money bugs first")
check(idor.owner == "Bookings team" and idor.owner_source == "ownership data", "booking leak owned by Bookings team (ownership data)")
check(refund.owner == "Payments team", "refund owned by Payments team")
check(shadow.owner == "Partner integrations" and shadow.owner_source == "guessed", "unlisted shadow route falls back to a guessed owner")
check("₹50,000 refunded against ₹25,000 paid" in (refund.business_impact or ""), "impact line carries the test's real numbers")
check(fp.rank is None and fp.severity is None and unv.rank is None and unv.severity is None,
      "false positive and unverified stay out of the ranking")
check(counts["awaiting_review"] == 4 and refund.review_status == "awaiting_review", "critical and high findings await human review")
check(all(v.first_seen_scan_id == s1 for v in (idor, refund, pay, shadow)), "first scan: everything is new")
with SessionLocal() as db:
    n = db.query(AuditLog).filter(AuditLog.scan_id == s1).count()
check(n == 0, f"triage sent nothing to the target (audit rows: {n})")

# ---- severity rules on their own ----
check(score("authorization", "POST", "/api/refunds", "refund", [])[1] == "high", "sub-agent refund (money, lower role) = high")
check(score("missing_auth", "GET", "/api/v1/bookings/{id}", "booking", ["zombie"])[1] == "critical",
      "no-login customer data on a zombie route = critical")
check(score("missing_auth", "GET", "/api/status", "unknown", [])[1] == "medium", "no-login internal info = medium")
check(score("authorization", "GET", "/api/status", "unknown", [])[1] == "low", "lower role reading internal info = low")

# ---- scan 2: the same flaws again ----
s2 = make_scan()
run_triage(s2, quiet)
f2 = findings(s2)
check(f2["POST /api/refunds"].first_seen_scan_id == s1 and f2["GET /api/bookings/{id}"].first_seen_scan_id == s1,
      "second scan: same flaws show 'first seen in scan 1'")

# ---- human review API ----
api = TestClient(app)
url = lambda v: f"/scans/{s1}/findings/{v.id}/review"  # noqa: E731
r = api.post(url(refund), json={"action": "confirm"})
check(r.status_code == 200 and r.json()["review_status"] == "confirmed", f"confirm a critical finding ({r.status_code})")
check(api.post(url(refund), json={"action": "confirm"}).status_code == 409, "a finding can't be reviewed twice")
check(api.post(url(shadow), json={"action": "change", "severity": "medium"}).status_code == 422,
      "changing severity needs a reason")
r = api.post(url(shadow), json={"action": "change", "severity": "medium", "note": "partner list is public on the website"})
check(r.status_code == 200 and r.json()["severity"] == "medium", "change severity with a reason")
r = api.post(url(pay), json={"action": "change", "severity": "low", "note": "test only"})
check(r.status_code == 200 and findings(s1)["POST /api/payments"].rank == 4, "a downgraded finding moves down the ranking")
check(api.post(url(fp), json={"action": "confirm"}).status_code == 409, "false positives can't be reviewed")
check(api.post(url(v1), json={"action": "confirm"}).status_code == 409, "merged duplicates can't be reviewed")
with SessionLocal() as db:
    rows = db.query(AuditLog).filter(AuditLog.scan_id == s1).all()
check(len(rows) == 3 and all(a.stage == "triage" and not a.sent for a in rows),
      f"each review written to the audit log, nothing sent ({len(rows)} rows)")

ok = all(r[0] for r in results)
print(f"\n{sum(r[0] for r in results)}/{len(results)} checks passed")
sys.exit(0 if ok else 1)
