"""The verification stage: re-prove every suspicious raw result before it counts.

For each test execution marked suspicious, run its verifier (service/verifier/checks.py)
through the safety gateway and record a vulnerability row as verified, false_positive
or unverified, with its checks and evidence. Clean results are not re-run (true negatives).
Severity, owner and de-duplication are left for triage.
"""
import json

from sqlalchemy import select

from ..db import Evidence, SessionLocal, TestCase, Vulnerability
from ..gateway import GatewayBlocked, halted_reason
from ..target_client import TargetClient
from ..executor import _endpoints
from ..executor.context import CouldNotRun, Ctx, NotApplicable
from .checks import TITLES, Verdict, verify

STAGE = "verification"


def _save(scan_id: int, tc: TestCase, ep: dict, v: Verdict) -> None:
    with SessionLocal() as db:
        vuln = Vulnerability(scan_id=scan_id, endpoint_id=tc.endpoint_id, test_case_id=tc.id,
                             title=f"{TITLES.get(tc.test_type, tc.test_type)} on {ep['method']} {ep['path']}",
                             vuln_class=tc.vuln_class, status=v.status, verification_reason=v.reason,
                             checks_json=json.dumps(v.checks))
        db.add(vuln)
        db.flush()
        for ex, note in v.evidence:
            db.add(Evidence(vulnerability_id=vuln.id, test_case_id=tc.id,
                            request_json=json.dumps(ex.record["request"]),
                            response_json=json.dumps(ex.record["response"], default=str), notes=note))
        db.commit()


def run_verification(scan_id: int, log, transport=None) -> dict:
    eps = _endpoints(scan_id)
    with SessionLocal() as db:
        done = set(db.scalars(select(Vulnerability.test_case_id).where(Vulnerability.scan_id == scan_id)))
        tests = [t for t in db.scalars(select(TestCase).where(TestCase.scan_id == scan_id,
                                                              TestCase.raw_result == "suspicious")
                                       .order_by(TestCase.id)) if t.id not in done]
        db.expunge_all()
    if not tests:
        log("nothing to verify: no suspicious raw results")
        return {"verified": 0, "false_positive": 0, "unverified": 0}

    log(f"verifying {len(tests)} suspicious result(s): each must reproduce on fresh data and pass an "
        "independent control check")
    with TargetClient(scan_id, STAGE, transport=transport) as client:
        ctx = Ctx(scan_id, client, list(eps.values()), log=log)
        ctx.login_all()
        for tc in tests:
            ep = eps[tc.endpoint_id]
            label = f"#{tc.id} {tc.test_type} on {ep['method']} {ep['path']}"
            try:
                v = verify(ctx, tc, ep)
            except NotApplicable as exc:
                v = Verdict("unverified", f"no verifier: {exc}")
            except CouldNotRun as exc:
                v = Verdict("unverified", f"a check could not be carried out: {exc}")
            except GatewayBlocked as exc:
                if halted_reason(scan_id):
                    raise
                v = Verdict("unverified", f"blocked by the safety gateway: {exc.reason}")
            _save(scan_id, tc, ep, v)
            marks = "; ".join(f"{'✓' if c['passed'] else '✗' if c['passed'] is False else '?'} {c['name']}"
                              for c in v.checks)
            log(f"{label}: {v.status.upper().replace('_', ' ')}: {v.reason} [{marks}]",
                "warn" if v.status == "verified" else "info")

    with SessionLocal() as db:
        rows = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id)).all()
        counts = {s: sum(1 for r in rows if r.status == s) for s in ("verified", "false_positive", "unverified")}
    log(f"verification done: {counts['verified']} verified, {counts['false_positive']} false positive(s), "
        f"{counts['unverified']} unverified. Severity is assigned in triage")
    return counts
