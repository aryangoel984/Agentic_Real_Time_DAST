"""The ten pipeline stages.

Phase 1: every stage is a stub. Phase 2: recon is real (see service/recon).
Phase 3: inventory is real (see service/inventory).
Phase 4: attack_planning is real (see service/planner); it plans, never executes.
Phase 5: safety_gateway is real (see service/gateway/stage.py): gate self-test + approval queue.
Phase 6: execution is real (see service/executor): runs cleared/approved tests, records raw results.
Phase 7: verification is real (see service/verifier): re-proves each suspicious result.
Phase 8: triage is real (see service/triage): merges duplicates, scores severity, maps owners.
Phase 9: reporting is real (see service/reporting): builds the report and tickets from the database.
Phase 10: retest is real (see service/retest): re-proves open findings from earlier scans.
The gate itself runs inside the shared HTTP client for every stage. The shared wrapper (`run_stage`) does the
bookkeeping: mark the stage running, log "entered <stage>", mark it done, and save the scan's state.
Each stage function returns only what that stage adds to the scan's state.
"""
import json
import time
from typing import Callable

from sqlalchemy import select

from ..config import STUB_STAGE_DELAY_SECONDS
from ..db import AgentLog, ScanRun, ScanStage, SessionLocal, now
from ..gateway import halted_reason
from ..gateway.stage import ScanHalted, run_safety
from ..inventory import classify
from ..executor import run_execution
from ..planner import run_planning
from ..verifier import run_verification
from ..triage import run_triage
from ..reporting import run_reporting
from ..retest import run_retest_stage
from ..recon import run_recon
from .state import ScanState


def log(scan_id: int, stage: str | None, message: str, level: str = "info") -> None:
    with SessionLocal() as db:
        db.add(AgentLog(scan_id=scan_id, stage=stage, level=level, message=message))
        db.commit()


def _set_stage(scan_id: int, stage: str, status: str) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(ScanStage).where(ScanStage.scan_id == scan_id, ScanStage.stage == stage))
        row.status = status
        if status == "running":
            row.started_at = now()
            row.finished_at = None
            row.runs += 1
            run = db.get(ScanRun, scan_id)
            run.current_stage = stage
        else:
            row.finished_at = now()
        db.commit()


def _save_state(scan_id: int, state: dict) -> None:
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        run.state_json = json.dumps(state, default=str)
        db.commit()


# ---------- stub bodies (one per stage) ----------

def change_detection(state: ScanState) -> dict:
    ev = state.get("event", {})
    log(state["scan_id"], "change_detection",
        f"change received: {ev.get('event')} {ev.get('method') or ''} {ev.get('endpoint') or ''} "
        f"{ev.get('version') or ''}".strip())
    return {}


def recon(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    count = run_recon(scan_id, lambda msg, level="info": log(scan_id, "recon", msg, level))
    return {"endpoint_count": count}


def inventory(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    summary = classify(scan_id, lambda msg, level="info": log(scan_id, "inventory", msg, level))
    return {"classification": summary}


def attack_planning(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    summary = run_planning(scan_id, lambda msg, level="info": log(scan_id, "attack_planning", msg, level))
    return {"plan": summary}


def safety_gateway(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    counts = run_safety(scan_id, lambda msg, level="info": log(scan_id, "safety_gateway", msg, level))
    return {"safety": counts}


def execution(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    counts = run_execution(scan_id, lambda msg, level="info": log(scan_id, "execution", msg, level))
    return {"execution": counts}


def verification(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    counts = run_verification(scan_id, lambda msg, level="info": log(scan_id, "verification", msg, level))
    return {"verification": counts}


def triage(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    counts = run_triage(scan_id, lambda msg, level="info": log(scan_id, "triage", msg, level))
    return {"triage": counts}


def reporting(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    counts = run_reporting(scan_id, lambda msg, level="info": log(scan_id, "reporting", msg, level))
    return {"report": counts}


def retest(state: ScanState) -> dict:
    scan_id = state["scan_id"]
    counts = run_retest_stage(scan_id, lambda msg, level="info": log(scan_id, "retest", msg, level))
    return {"retest": counts}


STAGE_FUNCS: dict[str, Callable[[ScanState], dict]] = {
    "change_detection": change_detection,
    "recon": recon,
    "inventory": inventory,
    "attack_planning": attack_planning,
    "safety_gateway": safety_gateway,
    "execution": execution,
    "verification": verification,
    "triage": triage,
    "reporting": reporting,
    "retest": retest,
}


def run_stage(stage: str) -> Callable[[ScanState], dict]:
    """Wrap a stage body with status tracking, logging and state persistence."""
    body = STAGE_FUNCS[stage]

    def node(state: ScanState) -> dict:
        scan_id = state["scan_id"]
        h = halted_reason(scan_id)
        if h:   # kill switch: no further stage starts
            raise ScanHalted(h)
        _set_stage(scan_id, stage, "running")
        log(scan_id, stage, f"entered {stage}")
        try:
            if STUB_STAGE_DELAY_SECONDS:
                time.sleep(STUB_STAGE_DELAY_SECONDS)
            update = body(state)
        except Exception as exc:  # mark the stage failed (or halted), then let the runner end the scan
            h = halted_reason(scan_id)
            _set_stage(scan_id, stage, "halted" if h else "failed")
            log(scan_id, stage, f"{stage} halted: {h}" if h else f"{stage} failed: {exc}", level="error")
            if h:
                raise ScanHalted(h) from exc
            raise
        update = {**update, "stage_history": [stage]}
        _set_stage(scan_id, stage, "done")
        merged = {**state, **{k: v for k, v in update.items() if k != "stage_history"},
                  "stage_history": state.get("stage_history", []) + [stage]}
        _save_state(scan_id, merged)
        return update

    return node
