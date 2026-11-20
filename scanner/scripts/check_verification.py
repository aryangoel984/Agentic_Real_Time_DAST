"""Prove the verifiers reject false positives, without the target running.

Runs the real verification stage against a small fake platform held in memory
(httpx MockTransport, nothing is sent anywhere). Five scenarios:

  1. truly vulnerable                       -> must be VERIFIED
  2. leaks once, then refuses on the repeat -> must be FALSE POSITIVE
  3. answers 200 for every ID (even made-up) -> must be FALSE POSITIVE
  4. no-login answer is only a placeholder   -> must be FALSE POSITIVE
  5. payment says "paid" but nothing changed -> must be FALSE POSITIVE

Run from the project root:
    scanner/.venv/bin/python scanner/scripts/check_verification.py
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="verify-check-")
os.environ["SCANNER_DATABASE_URL"] = f"sqlite:///{TMP}/check.db"
os.environ["GATEWAY_MAX_RPS"] = "200"          # no need to be gentle with a fake target
os.environ.pop("TARGET_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from service.db import ApiEndpoint, ScanRun, SessionLocal, TestCase, Vulnerability, init_db  # noqa: E402
from service.verifier import run_verification  # noqa: E402

USERS = {"a_admin": (1, 1, "admin"), "a_subagent": (2, 1, "subagent"),
         "b_admin": (3, 2, "admin"), "b_subagent": (4, 2, "subagent")}


class FakePlatform:
    """A tiny stand-in for the travel platform with switchable misbehaviour."""

    def __init__(self, mode: str):
        self.mode, self.bookings, self.tokens, self.next_id = mode, {}, {}, 5000
        # "flaky": the one leak already happened during execution; every later foreign read is refused
        self.reads = 1 if mode == "flaky" else 0

    def view(self, b):
        return {k: b[k] for k in ("id", "agency_id", "customer_name", "amount", "payment_status",
                                  "total_paid", "total_refunded")}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, body = req.url.path, json.loads(req.content) if req.content else {}
        auth = req.headers.get("authorization", "")
        user = self.tokens.get(auth.removeprefix("Bearer "))
        if path == "/api/login":
            if body.get("username") not in USERS or "@" not in body.get("password", ""):
                return httpx.Response(401, json={"detail": "Invalid username or password"})
            uid, agency, role = USERS[body["username"]]
            tok = f"tok{len(self.tokens)}"
            self.tokens[tok] = (uid, agency, role)
            return httpx.Response(200, json={"token": tok, "user_id": uid, "agency_id": agency, "role": role})
        if path == "/api/internal/partner-details":
            real = {"note": "internal use only", "agencies": [1, 2], "suppliers": [1, 2]}
            if self.mode == "placeholder" and not user:
                return httpx.Response(200, json={"status": "ok", "message": "sign in to see partner data"})
            return httpx.Response(200, json=real)
        if not user:
            return httpx.Response(401, json={"detail": "Not authenticated"})
        uid, agency, role = user
        if path == "/api/bookings" and req.method == "POST":
            self.next_id += 1
            b = {"id": self.next_id, "agency_id": body["agency_id"], "customer_name": body.get("customer_name"),
                 "amount": body["amount"], "payment_status": "unpaid", "total_paid": 0, "total_refunded": 0}
            self.bookings[b["id"]] = b
            return httpx.Response(201, json=self.view(b))
        m = re.match(r"^/api(/v1)?/bookings/(\d+)$", path)
        if m:
            bid = int(m.group(2))
            if self.mode == "soft200":     # same canned record for any id, even ones that don't exist
                return httpx.Response(200, json={"id": 1, "agency_id": 1, "customer_name": "Sample", "amount": 1})
            b = self.bookings.get(bid)
            if b is None:
                return httpx.Response(404, json={"detail": "Booking not found"})
            if b["agency_id"] != agency:
                self.reads += 1
                if self.mode == "flaky" and self.reads > 1:
                    return httpx.Response(404, json={"detail": "Booking not found"})
            return httpx.Response(200, json=self.view(b))
        if path == "/api/payments":
            b = self.bookings[body["booking_id"]]
            if self.mode != "fake_paid":
                b["payment_status"], b["total_paid"] = "paid", b["total_paid"] + body["amount"]
            return httpx.Response(200, json={"booking_id": b["id"], "payment_status": "paid",
                                             "amount_charged": body["amount"]})
        if path == "/api/refunds":
            b = self.bookings[body["booking_id"]]
            b["total_refunded"] += body["amount"]
            return httpx.Response(200, json={"booking_id": b["id"], "total_refunded": b["total_refunded"]})
        return httpx.Response(404, json={"detail": "Not Found"})


ENDPOINTS = [
    ("POST", "/api/login", "auth", "active", ["password", "username"]),
    ("POST", "/api/bookings", "booking", "active", ["agency_id", "amount", "customer_name", "user_id"]),
    ("GET", "/api/bookings/{id}", "booking", "active", []),
    ("GET", "/api/v1/bookings/{id}", "booking", "zombie", []),
    ("POST", "/api/payments", "payment", "active", ["amount", "booking_id"]),
    ("POST", "/api/refunds", "refund", "active", ["amount", "booking_id"]),
    ("GET", "/api/internal/partner-details", "partner", "shadow", []),
]


def run(mode: str, test_type: str, method: str, path: str, *, high_risk=False) -> Vulnerability:
    init_db()
    with SessionLocal() as db:
        run_ = ScanRun(status="running")
        db.add(run_)
        db.flush()
        ids = {}
        for m, p, purpose, cls, body in ENDPOINTS:
            e = ApiEndpoint(scan_id=run_.id, method=m, path=p, business_area=purpose, classification=cls,
                            params_json=json.dumps({"path": [], "query": [], "body": body}))
            db.add(e)
            db.flush()
            ids[(m, p)] = e.id
        tc = TestCase(scan_id=run_.id, endpoint_id=ids[(method, path)], test_type=test_type,
                      requires_approval=high_risk, status="approved" if high_risk else "cleared",
                      exec_status="ran", raw_result="suspicious")
        db.add(tc)
        db.commit()
        scan_id = run_.id
    run_verification(scan_id, lambda *a, **k: None, transport=httpx.MockTransport(FakePlatform(mode)))
    with SessionLocal() as db:
        v = db.query(Vulnerability).filter(Vulnerability.scan_id == scan_id).one()
        db.expunge(v)
        return v


SCENARIOS = [
    ("truly vulnerable: cross-agency read", "vulnerable", "cross_agency_access", "GET", "/api/bookings/{id}", False, "verified"),
    ("truly vulnerable: double refund", "vulnerable", "duplicate_refund", "POST", "/api/refunds", True, "verified"),
    ("truly vulnerable: shadow missing auth", "vulnerable", "missing_auth", "GET", "/api/internal/partner-details", False, "verified"),
    ("leaks once, then refuses on the repeat", "flaky", "cross_agency_access", "GET", "/api/bookings/{id}", False, "false_positive"),
    ("answers 200 for every ID, even made-up ones", "soft200", "zombie_ownership_check", "GET", "/api/v1/bookings/{id}", False, "false_positive"),
    ("no-login answer is only a placeholder", "placeholder", "missing_auth", "GET", "/api/internal/partner-details", False, "false_positive"),
    ("payment says paid but nothing changed", "fake_paid", "amount_validation", "POST", "/api/payments", True, "false_positive"),
]

ok_all = True
for name, mode, tt, m, p, risky, expected in SCENARIOS:
    v = run(mode, tt, m, p, high_risk=risky)
    ok = v.status == expected
    ok_all &= ok
    marks = ", ".join(f"{'✓' if c['passed'] else '✗' if c['passed'] is False else '?'} {c['name']}"
                      for c in json.loads(v.checks_json or "[]"))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {v.status.upper()} (expected {expected.upper()})")
    print(f"      {marks}")
    if v.status != "verified":
        print(f"      reason: {v.verification_reason}")
print(f"\n{'all scenarios behaved as expected' if ok_all else 'SOME SCENARIOS FAILED'}")
sys.exit(0 if ok_all else 1)
