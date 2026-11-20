"""Prove the retest loop closes only what is really fixed, without the target running.

A small fake platform held in memory (httpx MockTransport, nothing sent anywhere) has the five
planted flaws, each with a switch that fixes it, plus a "broken" switch where booking reads fail
for everyone. The real retest code runs against it through the real safety gateway.

Run from the project root:
    scanner/.venv/bin/python scanner/scripts/check_retest.py
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="retest-check-")
os.environ["SCANNER_DATABASE_URL"] = f"sqlite:///{TMP}/check.db"
os.environ["GATEWAY_MAX_RPS"] = "500"
os.environ.pop("TARGET_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from service import gateway  # noqa: E402
from service.db import (ApiEndpoint, AuditLog, RetestHistory, ScanRun, SessionLocal, TestCase, Vulnerability,  # noqa: E402
                        init_db)
from service.retest import can_retest, manual_retest, run_retest_stage  # noqa: E402
from service.triage import run_triage  # noqa: E402

USERS = {"a_admin": (1, 1, "admin"), "a_subagent": (2, 1, "subagent"),
         "b_admin": (3, 2, "admin"), "b_subagent": (4, 2, "subagent")}


class Platform:
    def __init__(self, fixes=(), halt_after=None, scan_for_halt=None):
        self.fixes, self.bookings, self.tokens, self.next_id, self.calls = set(fixes), {}, {}, 5000, 0
        self.halt_after, self.scan_for_halt = halt_after, scan_for_halt

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.halt_after and self.calls == self.halt_after:
            gateway.halt(self.scan_for_halt, "human", "kill switch pressed during a retest (test)")
        path, body = req.url.path, json.loads(req.content) if req.content else {}
        user = self.tokens.get(req.headers.get("authorization", "").removeprefix("Bearer "))
        if path == "/api/login":
            if body.get("username") not in USERS or "@" not in body.get("password", ""):
                return httpx.Response(401, json={"detail": "Invalid username or password"})
            uid, agency, role = USERS[body["username"]]
            tok = f"tok{len(self.tokens)}"
            self.tokens[tok] = (uid, agency, role)
            return httpx.Response(200, json={"token": tok, "user_id": uid, "agency_id": agency, "role": role})
        if path == "/api/internal/partner-details":
            if "shadow" in self.fixes and not user:
                return httpx.Response(401, json={"detail": "Not authenticated"})
            return httpx.Response(200, json={"note": "internal use only", "agencies": [1, 2], "suppliers": [1]})
        if not user:
            return httpx.Response(401, json={"detail": "Not authenticated"})
        uid, agency, role = user
        if path == "/api/bookings" and req.method == "POST":
            self.next_id += 1
            b = {"id": self.next_id, "agency_id": body["agency_id"], "amount": body["amount"], "customer_name": "x",
                 "payment_status": "unpaid", "total_paid": 0, "total_refunded": 0, "refund_status": "none"}
            self.bookings[b["id"]] = b
            return httpx.Response(201, json=b)
        m = re.match(r"^/api(/v1)?/bookings/(\d+)$", path)
        if m:
            old, b = bool(m.group(1)), self.bookings.get(int(m.group(2)))
            if old and "zombie" in self.fixes:
                return httpx.Response(410, json={"detail": "API v1 has been retired"})
            if not old and "broken" in self.fixes:
                return httpx.Response(404, json={"detail": "Booking not found"})
            if b is None or (not old and "idor" in self.fixes and b["agency_id"] != agency):
                return httpx.Response(404, json={"detail": "Booking not found"})
            return httpx.Response(200, json=b)
        if path == "/api/payments":
            b = self.bookings.get(body["booking_id"])
            if b is None or b["agency_id"] != agency:
                return httpx.Response(404, json={"detail": "Booking not found"})
            if "price" in self.fixes and body["amount"] != b["amount"]:
                return httpx.Response(400, json={"detail": "amount must equal the price"})
            b["payment_status"], b["total_paid"] = "paid", b["total_paid"] + body["amount"]
            return httpx.Response(200, json={"payment_status": "paid", "amount_charged": body["amount"]})
        if path == "/api/refunds":
            b = self.bookings.get(body["booking_id"])
            if role != "admin":
                return httpx.Response(403, json={"detail": "admins only"})
            if "refund" in self.fixes and b["refund_status"] == "refunded":
                return httpx.Response(409, json={"detail": "already refunded"})
            if body["amount"] > b["total_paid"]:
                return httpx.Response(400, json={"detail": "more than paid"})
            b["total_refunded"] += body["amount"]
            b["refund_status"] = "refunded"
            return httpx.Response(200, json={"refund_status": "refunded", "total_refunded": b["total_refunded"]})
        return httpx.Response(404, json={"detail": "Not Found"})


ENDPOINTS = [   # method, path, purpose, class, body fields
    ("POST", "/api/login", "auth", "active", ["password", "username"]),
    ("POST", "/api/bookings", "booking", "active", ["agency_id", "amount", "customer_name", "user_id"]),
    ("GET", "/api/bookings/{id}", "booking", "active", []),
    ("GET", "/api/v1/bookings/{id}", "booking", "zombie", []),
    ("POST", "/api/payments", "payment", "active", ["amount", "booking_id"]),
    ("POST", "/api/refunds", "refund", "active", ["amount", "booking_id"]),
    ("GET", "/api/internal/partner-details", "partner", "shadow", []),
]
FINDINGS = [   # (method, path, test type, high risk) - all verified in the "scan"
    ("GET", "/api/bookings/{id}", "cross_agency_access", False),
    ("GET", "/api/v1/bookings/{id}", "zombie_ownership_check", False),
    ("POST", "/api/refunds", "duplicate_refund", True),
    ("POST", "/api/payments", "amount_validation", True),
    ("GET", "/api/internal/partner-details", "missing_auth", False),
]


def make_scan(status="completed", verified=FINDINGS, denied=()) -> int:
    """A finished scan with its inventory, tests (approved/cleared) and verified findings, triaged."""
    init_db()
    with SessionLocal() as db:
        run = ScanRun(status=status)
        db.add(run)
        db.flush()
        ids = {}
        for m, p, purpose, cls, body in ENDPOINTS:
            e = ApiEndpoint(scan_id=run.id, method=m, path=p, business_area=purpose, classification=cls,
                            params_json=json.dumps({"path": [], "query": [], "body": body}))
            db.add(e)
            db.flush()
            ids[(m, p)] = e.id
        for m, p, tt, risky in FINDINGS:
            st = "denied" if tt in denied else "approved" if risky else "cleared"
            tc = TestCase(scan_id=run.id, endpoint_id=ids[(m, p)], test_type=tt, requires_approval=risky, status=st,
                          exec_status="ran", raw_result="suspicious" if (m, p, tt, risky) in verified else "clean")
            db.add(tc)
            db.flush()
            if (m, p, tt, risky) in verified:
                db.add(Vulnerability(scan_id=run.id, endpoint_id=tc.endpoint_id, test_case_id=tc.id,
                                     title=f"{tt} on {m} {p}", status="verified", checks_json="[]"))
        db.commit()
        sid = run.id
    run_triage(sid, lambda *a, **k: None)
    return sid


def finding(sid: int, path: str) -> Vulnerability:
    with SessionLocal() as db:
        ep = db.query(ApiEndpoint).filter_by(scan_id=sid, path=path).first()
        v = db.query(Vulnerability).filter_by(scan_id=sid, endpoint_id=ep.id).first()
        db.expunge(v)
        return v


def last_retest(v_id: int) -> RetestHistory:
    with SessionLocal() as db:
        h = db.query(RetestHistory).filter_by(vulnerability_id=v_id).order_by(RetestHistory.id.desc()).first()
        db.expunge(h)
        return h


def retest(sid: int, path: str, platform: Platform) -> tuple[str, Vulnerability, RetestHistory]:
    v = finding(sid, path)
    manual_retest(sid, v.id, transport=httpx.MockTransport(platform))
    return last_retest(v.id).result, finding(sid, path), last_retest(v.id)


results: list[bool] = []


def check(ok: bool, what: str) -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {what}")


# ---- manual retests ----
s = make_scan()
r, v, h = retest(s, "/api/bookings/{id}", Platform())
check(r == "still_vulnerable" and v.status == "verified", f"nothing fixed: booking leak still vulnerable ({r})")
r, v, h = retest(s, "/api/refunds", Platform())
check(r == "still_vulnerable", f"nothing fixed: double refund still vulnerable ({r})")

r, v, h = retest(s, "/api/bookings/{id}", Platform({"idor"}))
check(r == "partly_fixed" and v.status == "verified" and "/api/v1/bookings/{id}" in h.notes,
      f"main route fixed, v1 copy still leaks: partly fixed, stays open ({h.notes})")

r, v, h = retest(s, "/api/bookings/{id}", Platform({"broken", "zombie"}))
check(r == "inconclusive" and v.status == "verified", f"a 'fix' that breaks reads for everyone: inconclusive, stays open ({r})")

r, v, h = retest(s, "/api/bookings/{id}", Platform({"idor", "zombie"}))
checks = json.loads(h.checks_json)
check(r == "fixed" and v.status == "fixed" and v.fixed_at is not None, f"main route fixed and v1 retired (410): fixed, closed ({r})")
check(any("retired" in c["detail"] for c in checks), "retired zombie accepted as the recommended fix")
check(sum(1 for c in checks if c["passed"]) == 4, "two checks passed on each of the two places")

r, v, h = retest(s, "/api/refunds", Platform({"refund"}))
check(r == "fixed" and any("first, legitimate refund" in c["detail"] for c in json.loads(h.checks_json)),
      "double refund fixed: second refund refused, first refund still works")
r, v, h = retest(s, "/api/payments", Platform({"price"}))
check(r == "fixed" and any("in full" in c["detail"] for c in json.loads(h.checks_json)),
      "price tampering fixed: ₹1 refused, full payment still works")
r, v, h = retest(s, "/api/internal/partner-details", Platform({"shadow"}))
check(r == "fixed", f"shadow route now needs a login, and still works with one: fixed ({r})")

ev = json.loads(h.evidence_json)
check(ev and all(e["request"]["headers"].get("authorization", "Bearer ***") == "Bearer ***" for e in ev),
      "retest evidence is masked")
with SessionLocal() as db:
    rows = db.query(AuditLog).filter(AuditLog.scan_id == s, AuditLog.stage == "retest").all()
check(rows and all(r.decision == "allow" for r in rows if r.sent), f"every retest request went through the gateway ({len(rows)} audit rows)")

check(can_retest(s, finding(s, "/api/refunds")) is not None, "a fixed finding can't be retested again")
s_running = make_scan(status="running")
check("still running" in (can_retest(s_running, finding(s_running, "/api/refunds")) or ""), "no manual retest while its scan runs")

# kill switch during a retest
s_kill = make_scan()
r, v, h = retest(s_kill, "/api/bookings/{id}", Platform({"idor", "zombie"}, halt_after=6, scan_for_halt=s_kill))
check(r == "stopped" and v.status == "verified", f"kill switch during a retest stops it; the finding stays open ({r})")
check(can_retest(s_kill, finding(s_kill, "/api/bookings/{id}")) is not None, "a killed scan's findings can't be retested")

# ---- automatic: the retest stage of a later scan ----
a = make_scan()                                              # scan A: all five verified
b = make_scan(verified=[FINDINGS[0], FINDINGS[1]], denied=("amount_validation",))
# scan B found the booking leak again; refund test approved; price test denied
plat = Platform({"refund", "shadow"})
counts = run_retest_stage(b, lambda *a, **k: None, transport=httpx.MockTransport(plat))
check(last_retest(finding(a, "/api/bookings/{id}").id).result == "still_present", "found again in the new scan: still present")
check(finding(a, "/api/refunds").status == "fixed", "refund fixed: closed by the new scan's retest stage")
check(last_retest(finding(a, "/api/payments").id).result == "not_retested" and finding(a, "/api/payments").status == "verified",
      "price test denied in the new scan: not retested, stays open")
check(finding(a, "/api/internal/partner-details").status == "fixed", "shadow route fixed: closed automatically")
with SessionLocal() as db:
    denied_tc = db.query(TestCase).filter_by(scan_id=b, test_type="amount_validation").first().id
    tagged = db.query(AuditLog).filter(AuditLog.scan_id == b, AuditLog.test_case_id == denied_tc, AuditLog.sent.is_(True)).count()
    booking_tc = db.query(TestCase).filter_by(scan_id=b, test_type="cross_agency_access").first().id
    booking_sent = db.query(AuditLog).filter(AuditLog.scan_id == b, AuditLog.stage == "retest",
                                             AuditLog.test_case_id == booking_tc).count()
check(tagged == 0, "nothing sent for the denied test")
check(booking_sent == 0, "nothing sent for the flaw the scan already found again")
check(counts == {"still_present": 1, "fixed": 2, "not_retested": 1}, f"stage counts {counts}")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
