"""The orchestrator: a LangGraph state graph with one node per pipeline stage.

  change_detection → recon → inventory → attack_planning → safety_gateway
  → execution → verification → triage → reporting → retest → END

The retest stage re-proves open findings from earlier scans inside itself (service/retest),
so there is no loop back to verification.
"""
import json

from langgraph.graph import END, START, StateGraph

from ..config import STAGES
from ..db import ScanRun, SessionLocal, now
from ..gateway import halted_reason
from .stages import log, run_stage
from .state import ScanState


def build_graph():
    g = StateGraph(ScanState)
    for stage in STAGES:
        g.add_node(stage, run_stage(stage))
    g.add_edge(START, STAGES[0])
    for a, b in zip(STAGES[:-1], STAGES[1:]):   # one straight line of stages
        g.add_edge(a, b)
    g.add_edge(STAGES[-1], END)
    return g.compile()


GRAPH = build_graph()


def run_scan(scan_id: int, event: dict) -> None:
    """Run one scan through the whole pipeline. Called in the background."""
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        run.status = "running"
        run.started_at = now()
        db.commit()
    log(scan_id, None, "scan started")

    initial: ScanState = {"scan_id": scan_id, "event": event, "stage_history": []}
    try:
        final = GRAPH.invoke(initial)
        status, error = "completed", None
    except Exception as exc:
        final, status, error = None, "failed", str(exc)
        if halted_reason(scan_id):   # stopped by the kill switch or the health monitor
            with SessionLocal() as db:
                by = db.get(ScanRun, scan_id).halted_by
            status, error = ("killed" if by == "human" else "stopped"), halted_reason(scan_id)

    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        run.paused_reason = None
        run.status = status
        run.error = error
        run.finished_at = now()
        if status in ("completed", "killed", "stopped"):
            run.current_stage = None
        if final is not None:
            run.state_json = json.dumps(final, default=str)
        db.commit()
    log(scan_id, None, f"scan {status}" + (f": {error}" if error else ""),
        level="info" if status == "completed" else "error")
