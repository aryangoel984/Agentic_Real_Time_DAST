"""The ten pipeline stages.

Phase 1: every stage is a stub. Phase 2: recon is real (see service/recon).
Phase 3: inventory is real (see service/inventory).
Phase 4: attack_planning is real (see service/planner); it plans, never executes.
Phase 5: safety_gateway is real (see service/gateway/stage.py): gate self-test + approval queue.
Phase 6: execution is real (see service/executor): runs cleared/approved tests, records raw results.
Phase 7: verification is real (see service/verifier): re-proves each suspicious result.
Phase 8: triage is real (see service/triage): merges duplicates, scores severity, maps owners.
Phase 9: reporting is real (see service/reporting): builds the report and tickets from the database.
The gate itself runs inside the shared HTTP client for every stage. The shared wrapper (`run_stage`) does the
bookkeeping: mark the stage running, log "entered <stage>", wait briefly so
a human can watch, mark it done, and save the scan's state. The per-stage
functions return only what that stage changes; for now that is nothing,
except retest, which counts its rounds.

Later phases replace each stub body with real work.
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
    pending = state.get("findings_to_retest", [])
    log(state["scan_id"], "retest",
        f"{len(pending)} finding(s) awaiting retest" + ("" if pending else "; nothing to loop back for"))
    return {"retest_round": state.get("retest_round", 0) + (1 if pending else 0)}


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
