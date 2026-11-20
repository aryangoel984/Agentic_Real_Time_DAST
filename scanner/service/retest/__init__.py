"""Retest: re-run the proof after a fix and close the finding once it is resolved.

Two ways in:
  * manual: the Retest button on an open finding (after a fix is deployed). Runs in the
    background under the finding's own scan, tagged with its own (already approved) tests.
  * automatic: the retest stage at the end of every scan looks at open findings from earlier
    scans. If this scan found the same flaw again, the finding stays open (no extra requests).
    Otherwise it is retested, tagged with this scan's matching test, and only if that test was
    cleared or approved here; a denied money test means "not retested".

Every place a (merged) finding lives is checked: the attack must fail on fresh data and the
rightful use must still work (retest/checks.py). All requests go through the safety gateway.
Each attempt is kept in retest_history with its checks and masked evidence.
"""
import json
import threading

from sqlalchemy import select

from ..db import AgentLog, ApiEndpoint, RetestHistory, ScanRun, SessionLocal, TestCase, Vulnerability, now
from ..executor import _endpoints
from ..executor.context import Ctx
from ..gateway import GatewayBlocked, halted_reason
from ..target_client import TargetClient
from .checks import PlaceResult, overall, retest_place

STAGE = "retest"
RUNNING: set[int] = set()          # finding ids with a manual retest in progress
RUNNING_SCANS: dict[int, int] = {}  # scan id -> manual retests running under it (lets the kill switch act)
_lock = threading.Lock()


def _places(db, v: Vulnerability) -> list[tuple[Vulnerability, TestCase, ApiEndpoint]]:
    """The finding itself plus every duplicate merged into it."""
    rows = [v] + db.scalars(select(Vulnerability).where(Vulnerability.duplicate_of == v.id)
                            .order_by(Vulnerability.id)).all()
    return [(r, db.get(TestCase, r.test_case_id), db.get(ApiEndpoint, r.endpoint_id)) for r in rows]


def _run(scan_id: int, items: list[tuple[str, dict, int | None]], log, transport=None) -> list[PlaceResult]:
    """items: (test_type, endpoint dict, gateway tag or None). None = not cleared here, nothing sent."""
    out = [PlaceResult(ep["method"], ep["path"], "not_retested") for tt, ep, tag in items if tag is None]
    todo = [(tt, ep, tag) for tt, ep, tag in items if tag is not None]
    if not todo:
        return out
    with TargetClient(scan_id, STAGE, transport=transport) as client:
        ctx = Ctx(scan_id, client, list(_endpoints(scan_id).values()), log=log)
        ctx.login_all()
        for tt, ep, tag in todo:
            try:
                out.append(retest_place(ctx, tag, tt, ep))
            except GatewayBlocked as exc:
                if halted_reason(scan_id):
                    raise
                pr = PlaceResult(ep["method"], ep["path"], "inconclusive")
                pr.check("attack no longer works", None, f"blocked by the safety gateway: {exc.reason}")
                out.append(pr)
    return out


def _record(v_id: int, scan_id: int, trigger: str, result: str, reason: str, places=(), log=None) -> None:
    with SessionLocal() as db:
        v = db.get(Vulnerability, v_id)
        db.add(RetestHistory(
            vulnerability_id=v_id, scan_id=scan_id, result=result, notes=reason, triggered_by=trigger,
            checks_json=json.dumps([c for p in places for c in p.checks]),
            evidence_json=json.dumps([{**ex.record, "note": note, "where": f"{p.method} {p.path}"}
                                      for p in places for ex, note in p.evidence], default=str)))
        v.retest_status, v.last_retested_at = result, now()
        closed = 0
        if result == "fixed":     # the same flaw is one issue across scans: close every open copy
            for c in db.scalars(select(Vulnerability).where(Vulnerability.dedupe_key == v.dedupe_key,
                                                            Vulnerability.status == "verified",
                                                            Vulnerability.duplicate_of.is_(None))):
                c.status, c.fixed_at = "fixed", now()
                closed += 1
        msg = (f"retest of finding #{v.id} {v.title} ({trigger}): {result.upper().replace('_', ' ')}: {reason}"
               + (f"; closed {closed} open cop{'y' if closed == 1 else 'ies'} of this flaw" if closed else ""))
        if log is None:   # the stage's own log writes the line otherwise
            db.add(AgentLog(scan_id=scan_id, stage=STAGE, level="info" if result == "fixed" else "warn", message=msg))
        db.commit()
    if log:
        log(msg, "info" if result == "fixed" else "warn")


# ---------------- manual: the Retest button ----------------

def can_retest(scan_id: int, v: Vulnerability) -> str | None:
    """Why a manual retest is refused, or None if it may start."""
    if v.status != "verified" or v.duplicate_of is not None:
        return "only open (verified, ranked) findings can be retested"
    if v.id in RUNNING:
        return "a retest of this finding is already running"
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run.status in ("queued", "running"):
            return "the scan is still running; retest after it finishes"
        if run.halted_at is not None:
            return f"the scan was stopped ({run.halt_reason}); its approvals no longer apply"
    return None


def manual_retest(scan_id: int, v_id: int, transport=None) -> None:
    """Background job for the Retest button. Uses the finding's own scan and its own approved tests."""
    with _lock:
        RUNNING.add(v_id)
        RUNNING_SCANS[scan_id] = RUNNING_SCANS.get(scan_id, 0) + 1
    log = lambda msg, level="info": _agent_log(scan_id, msg, level)  # noqa: E731
    try:
        with SessionLocal() as db:
            v = db.get(Vulnerability, v_id)
            eps = _endpoints(scan_id)
            items = [(tc.test_type, eps[ep.id], tc.id) for _, tc, ep in _places(db, v)]
        log(f"manual retest of finding #{v_id} started: {len(items)} place(s) to re-check")
        try:
            places = _run(scan_id, items, log, transport)
            result, reason = overall(places)
        except GatewayBlocked as exc:
            places, result, reason = [], "stopped", f"stopped by the safety gateway: {exc.reason}"
        _record(v_id, scan_id, "manual", result, reason, places)
    finally:
        with _lock:
            RUNNING.discard(v_id)
            RUNNING_SCANS[scan_id] -= 1
            if not RUNNING_SCANS[scan_id]:
                RUNNING_SCANS.pop(scan_id)


def _agent_log(scan_id: int, message: str, level: str = "info") -> None:
    with SessionLocal() as db:
        db.add(AgentLog(scan_id=scan_id, stage=STAGE, level=level, message=message))
        db.commit()


# ---------------- automatic: the retest stage of every scan ----------------

def run_retest_stage(scan_id: int, log, transport=None) -> dict:
    counts: dict[str, int] = {}
    with SessionLocal() as db:
        here = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id,
                                                      Vulnerability.status == "verified",
                                                      Vulnerability.duplicate_of.is_(None))).all()
        found_again = {v.dedupe_key for v in here}
        older = db.scalars(select(Vulnerability).where(Vulnerability.scan_id < scan_id,
                                                       Vulnerability.status == "verified",
                                                       Vulnerability.duplicate_of.is_(None),
                                                       Vulnerability.dedupe_key.is_not(None))
                           .order_by(Vulnerability.scan_id.desc(), Vulnerability.id)).all()
        latest: dict[str, Vulnerability] = {}
        for v in older:
            latest.setdefault(v.dedupe_key, v)     # newest open copy of each flaw
        my_eps = {(e["method"], e["path"]): e for e in _endpoints(scan_id).values()}
        my_tests = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id)).all()
        jobs = []
        for key, v in latest.items():
            if key in found_again:
                jobs.append((v.id, None, f"found again in scan {scan_id}, so it is still open"))
                continue
            items = []
            for _, tc, ep in _places(db, v):
                mine = my_eps.get((ep.method, ep.path))
                match = next((t for t in my_tests if mine and t.endpoint_id == mine["id"]
                              and t.test_type == tc.test_type), None)
                tag = match.id if match and match.status in ("cleared", "approved") else None
                items.append((tc.test_type, mine or {"method": ep.method, "path": ep.path, "id": None}, tag))
            jobs.append((v.id, items, None))

    if not jobs:
        log("no open findings from earlier scans to retest")
        return counts
    log(f"{len(jobs)} open finding(s) from earlier scans: checking whether each is fixed")
    for v_id, items, note in jobs:
        if items is None:
            _record(v_id, scan_id, f"scan {scan_id}", "still_present", note, log=log)
            counts["still_present"] = counts.get("still_present", 0) + 1
            continue
        places = _run(scan_id, items, log, transport)
        result, reason = overall(places)
        _record(v_id, scan_id, f"scan {scan_id}", result, reason, places, log=log)
        counts[result] = counts.get(result, 0) + 1
    log("retest done: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items()))
    return counts
