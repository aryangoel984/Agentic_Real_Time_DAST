"""The execution stage: run every cleared or approved test through the safety gateway.

Records a RAW result per test (suspicious / clean) with minimal evidence. It does not
confirm vulnerabilities or compute severity; verification and triage do that later.
Denied (or never-approved) high-risk tests are skipped and none of their requests are sent.
"""
import json

from sqlalchemy import select

from ..db import ApiEndpoint, Evidence, SessionLocal, TestCase, now
from ..gateway import GatewayBlocked, halted_reason
from ..target_client import TargetClient
from .context import CouldNotRun, Ctx, NotApplicable
from .tests import EXECUTORS

STAGE = "execution"


def _endpoints(scan_id: int) -> dict[int, dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id)).all()
        return {r.id: {"id": r.id, "method": r.method, "path": r.path, "purpose": r.business_area,
                       "params": json.loads(r.params_json) if r.params_json else None,
                       "classification": r.classification} for r in rows}


def _save(tc_id: int, exec_status: str, raw: str | None, summary: str, evidence=()) -> None:
    with SessionLocal() as db:
        tc = db.get(TestCase, tc_id)
        tc.exec_status, tc.raw_result, tc.result_summary, tc.executed_at = exec_status, raw, summary, now()
        for ex, note in evidence:
            db.add(Evidence(test_case_id=tc_id, request_json=json.dumps(ex.record["request"]),
                            response_json=json.dumps(ex.record["response"], default=str), notes=note))
        db.commit()


def run_execution(scan_id: int, log) -> dict:
    eps = _endpoints(scan_id)
    with SessionLocal() as db:
        tests = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id).order_by(TestCase.id)).all()
        db.expunge_all()

    with TargetClient(scan_id, STAGE) as client:
        ctx = Ctx(scan_id, client, list(eps.values()), log=log)
        runnable = [t for t in tests if t.status in ("cleared", "approved")]
        if runnable:
            ctx.login_all()
        for tc in tests:
            ep = eps.get(tc.endpoint_id)
            label = f"#{tc.id} {tc.test_type} on {ep['method']} {ep['path']}" if ep else f"#{tc.id} {tc.test_type}"
            if tc.status == "denied":
                _save(tc.id, "skipped", None, "Denied at the safety gateway: not run, no request sent.")
                log(f"{label}: skipped (denied)")
                continue
            if tc.status not in ("cleared", "approved"):
                _save(tc.id, "skipped", None, f"Not cleared to run (status {tc.status}): no request sent.")
                log(f"{label}: skipped (status {tc.status})")
                continue
            fn = EXECUTORS.get(tc.test_type)
            try:
                if fn is None or ep is None:
                    raise NotApplicable("no executor for this test type")
                out = fn(ctx, tc, ep)
                _save(tc.id, "ran", out.raw_result, out.summary, out.evidence)
                log(f"{label}: {out.raw_result.upper()}: {out.summary}", "warn" if out.raw_result == "suspicious" else "info")
            except NotApplicable as exc:
                _save(tc.id, "skipped", None, f"Not applicable: {exc}. No request sent for the test itself.")
                log(f"{label}: skipped ({exc})")
            except GatewayBlocked as exc:
                if halted_reason(scan_id):
                    _save(tc.id, "could_not_run", None, f"Stopped: {exc.reason}")
                    raise
                _save(tc.id, "could_not_run", None, f"Blocked by the safety gateway: {exc.reason}")
                log(f"{label}: blocked by the gateway ({exc.reason})", "warn")
            except CouldNotRun as exc:
                _save(tc.id, "could_not_run", None, f"Could not run: {exc}")
                log(f"{label}: could not run ({exc})", "warn")

    with SessionLocal() as db:
        rows = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id)).all()
        counts = {"suspicious": sum(1 for t in rows if t.raw_result == "suspicious"),
                  "clean": sum(1 for t in rows if t.raw_result == "clean"),
                  "skipped": sum(1 for t in rows if t.exec_status == "skipped"),
                  "could_not_run": sum(1 for t in rows if t.exec_status == "could_not_run")}
    log(f"execution done: {counts['suspicious']} suspicious, {counts['clean']} clean, {counts['skipped']} skipped, "
        f"{counts['could_not_run']} could not run. These are raw results, not confirmed findings")
    return counts
