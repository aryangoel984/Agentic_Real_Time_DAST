"""The ten pipeline stages.

Phase 1: every stage is a stub. Phase 2: recon is real (see service/recon). The shared wrapper (`run_stage`) does the
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
    return {}


def attack_planning(state: ScanState) -> dict:
    return {}


def safety_gateway(state: ScanState) -> dict:
    return {}


def execution(state: ScanState) -> dict:
    return {}


def verification(state: ScanState) -> dict:
    return {}


def triage(state: ScanState) -> dict:
    return {}


def reporting(state: ScanState) -> dict:
    return {}


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
        _set_stage(scan_id, stage, "running")
        log(scan_id, stage, f"entered {stage}")
        try:
            if STUB_STAGE_DELAY_SECONDS:
                time.sleep(STUB_STAGE_DELAY_SECONDS)
            update = body(state)
        except Exception as exc:  # mark the stage failed, then let the runner fail the scan
            _set_stage(scan_id, stage, "failed")
            log(scan_id, stage, f"{stage} failed: {exc}", level="error")
            raise
        update = {**update, "stage_history": [stage]}
        _set_stage(scan_id, stage, "done")
        merged = {**state, **{k: v for k, v in update.items() if k != "stage_history"},
                  "stage_history": state.get("stage_history", []) + [stage]}
        _save_state(scan_id, merged)
        return update

    return node
