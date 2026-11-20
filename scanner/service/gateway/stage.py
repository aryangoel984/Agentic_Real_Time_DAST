"""The safety_gateway pipeline stage.

1. Self-test: push deliberately bad requests through the real gate in dry-run mode
   (they are never transmitted, even if the gate were broken). All must be blocked,
   otherwise the scan stops before any test can run (fail closed).
2. Approval queue: high-risk tests wait for a human on the dashboard. Approve ->
   "approved" (may run in execution). Deny -> "denied" (dropped). Undecided after
   APPROVAL_TIMEOUT_SECONDS -> denied. Low/medium tests are "cleared".
"""
import time

from sqlalchemy import select

from ..config import APPROVAL_TIMEOUT_SECONDS
from ..db import ApiEndpoint, AuditLog, SessionLocal, TestCase, now
from ..target_client import SelfTestLeak, TargetClient
from . import GatewayBlocked, halted_reason

STAGE = "safety_gateway"


class ScanHalted(RuntimeError):
    pass


def _self_test(scan_id: int, log) -> None:
    with SessionLocal() as db:
        risky = db.scalar(select(TestCase).where(TestCase.scan_id == scan_id,
                                                 TestCase.requires_approval.is_(True)))
        risky_id = risky.id if risky else None
    cases = [
        ("off-scope host", dict(method="GET", path_or_url="http://example.com/")),
        ("forbidden method", dict(method="DELETE", path_or_url="/api/bookings/1001")),
        ("unlisted account", dict(method="POST", path_or_url="/api/login",
                                  json_body={"username": "selftest_intruder", "password": "not-a-test-account"})),
        ("forged token", dict(method="GET", path_or_url="/api/bookings/1001",
                              headers={"authorization": "Bearer forged-selftest-token"})),
    ]
    if risky_id:
        cases.append(("unapproved high-risk test", dict(method="POST", path_or_url="/api/refunds",
                                                         json_body={"booking_id": 0, "amount": 0},
                                                         test_case_id=risky_id)))
    log(f"gateway self-test: {len(cases)} deliberately bad requests in dry-run mode "
        "(the real gate decides; nothing is ever transmitted)")
    with TargetClient(scan_id, STAGE) as client:
        for name, kw in cases:
            try:
                client.send(**kw, dry_run=True)
            except GatewayBlocked as exc:
                log(f"self-test {name}: blocked ({exc.reason})")
            except SelfTestLeak as exc:
                log(f"self-test {name}: NOT blocked ({exc}); stopping the scan", "error")
                raise RuntimeError(f"gateway self-test failed: {name} was not blocked") from exc
    log("gateway self-test passed: every bad request was blocked")


def _hold_rows(scan_id: int, tests: list[TestCase]) -> None:
    """One audit 'hold' row per high-risk test waiting for a human (no request sent)."""
    with SessionLocal() as db:
        for t in tests:
            ep = db.get(ApiEndpoint, t.endpoint_id)
            db.add(AuditLog(scan_id=scan_id, stage=STAGE, method=ep.method if ep else "-",
                            url=ep.path if ep else "-", decision="hold", test_case_id=t.id,
                            reason=f"high-risk test #{t.id} ({t.test_type}) waits for human approval; "
                                   "nothing sent", sent=False, sent_at=now()))
        db.commit()


def run_safety(scan_id: int, log) -> dict:
    _self_test(scan_id, log)

    with SessionLocal() as db:
        tests = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id)).all()
        risky = [t for t in tests if t.requires_approval]
        for t in tests:
            t.status = "pending_approval" if t.requires_approval else "cleared"
        db.commit()
        for t in risky:
            db.refresh(t)
    log(f"{len(tests) - len(risky)} low/medium-risk test(s) cleared; {len(risky)} high-risk test(s) "
        "held for human approval on the dashboard")
    for t in risky:
        log(f"waiting for approval: test #{t.id} {t.test_type} ({t.risk_level} risk)")
    _hold_rows(scan_id, risky)

    deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS
    ids = [t.id for t in risky]
    while ids:
        h = halted_reason(scan_id)
        if h:
            raise ScanHalted(h)
        with SessionLocal() as db:
            pending = db.scalars(select(TestCase).where(TestCase.id.in_(ids),
                                                        TestCase.status == "pending_approval")).all()
            if not pending:
                break
            if time.monotonic() > deadline:
                for t in pending:
                    t.status, t.decided_at = "denied", now()
                    db.add(AuditLog(scan_id=scan_id, stage=STAGE, method="-", url="-", decision="block",
                                    test_case_id=t.id, sent=False, sent_at=now(),
                                    reason=f"high-risk test #{t.id} denied automatically: no decision within "
                                           f"{APPROVAL_TIMEOUT_SECONDS:g} s"))
                    log(f"test #{t.id} {t.test_type} denied automatically (no decision in time)", "warn")
                db.commit()
                break
        time.sleep(1)

    with SessionLocal() as db:
        rows = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id)).all()
        counts = {s: sum(1 for t in rows if t.status == s) for s in ("cleared", "approved", "denied")}
    log(f"safety gateway done: {counts['cleared']} cleared, {counts['approved']} approved, "
        f"{counts['denied']} denied (denied tests are dropped and will never run)")
    return counts
