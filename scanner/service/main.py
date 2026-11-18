"""Scanner API (port 9000).

- POST /events/deploy  : receive a "something changed" event, start a scan
- GET  /scans          : list scan runs
- GET  /scans/{id}     : one scan with its event, stages, logs, API inventory, attack plan and findings

This service is independent of the target platform. It has its own database
and never imports the target's code or opens the target's database.
"""
import json

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .config import STAGES
from .db import (AgentLog, ApiEndpoint, DeploymentEvent, ScanRun, ScanStage, SessionLocal, TestCase,
                 Vulnerability, init_db, now)
from .orchestrator.graph import run_scan

app = FastAPI(title="Agentic DAST Scanner", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    init_db()
    # Scans can't resume after a restart yet: mark any unfinished ones as interrupted.
    with SessionLocal() as db:
        for run in db.scalars(select(ScanRun).where(ScanRun.status.in_(["queued", "running"]))):
            run.status = "interrupted"
            run.finished_at = now()
            for st in db.scalars(select(ScanStage).where(ScanStage.scan_id == run.id,
                                                         ScanStage.status == "running")):
                st.status = "interrupted"
            db.add(AgentLog(scan_id=run.id, level="warn",
                            message="scanner restarted while this scan was running; marked interrupted"))
        db.commit()


class DeployEventIn(BaseModel):
    event: str = Field(min_length=1, examples=["API_DEPLOYED"])
    endpoint: str | None = Field(default=None, examples=["/api/refunds"])
    method: str | None = Field(default=None, examples=["POST"])
    version: str | None = Field(default=None, examples=["v2"])
    timestamp: str | None = Field(default=None, examples=["2026-11-15T10:30:00Z"])


@app.get("/health")
def health():
    return {"service": "scanner", "status": "ok"}


@app.post("/events/deploy", status_code=202)
def receive_deploy_event(body: DeployEventIn, background: BackgroundTasks):
    payload = body.model_dump()
    with SessionLocal() as db:
        run = ScanRun(status="queued")
        db.add(run)
        db.flush()
        ev = DeploymentEvent(scan_id=run.id, event_type=body.event, endpoint=body.endpoint,
                             method=body.method.upper() if body.method else None,
                             version=body.version, event_timestamp=body.timestamp,
                             raw_json=json.dumps(payload))
        db.add(ev)
        for i, stage in enumerate(STAGES):
            db.add(ScanStage(scan_id=run.id, stage=stage, position=i))
        db.add(AgentLog(scan_id=run.id, message=f"deploy event received: {body.event}"))
        db.commit()
        scan_id, event_id = run.id, ev.id
    background.add_task(run_scan, scan_id, payload)
    return {"scan_id": scan_id, "event_id": event_id, "status": "queued"}


def _iso(dt):
    return dt.isoformat() + ("Z" if dt and dt.tzinfo is None else "") if dt else None


def _event_dict(ev: DeploymentEvent | None):
    if ev is None:
        return None
    return {"id": ev.id, "event": ev.event_type, "endpoint": ev.endpoint, "method": ev.method,
            "version": ev.version, "timestamp": ev.event_timestamp, "received_at": _iso(ev.received_at)}


def _run_dict(run: ScanRun, ev: DeploymentEvent | None, done: int):
    return {"id": run.id, "status": run.status, "current_stage": run.current_stage,
            "created_at": _iso(run.created_at), "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at), "error": run.error,
            "stages_done": done, "stages_total": len(STAGES), "trigger": _event_dict(ev)}


@app.get("/scans")
def list_scans(limit: int = 50):
    with SessionLocal() as db:
        runs = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(limit)).all()
        out = []
        for run in runs:
            ev = db.scalar(select(DeploymentEvent).where(DeploymentEvent.scan_id == run.id))
            done = db.scalar(select(func.count()).select_from(ScanStage)
                             .where(ScanStage.scan_id == run.id, ScanStage.status == "done"))
            out.append(_run_dict(run, ev, done))
        return out


@app.get("/scans/{scan_id}")
def get_scan(scan_id: int):
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        ev = db.scalar(select(DeploymentEvent).where(DeploymentEvent.scan_id == scan_id))
        stages = db.scalars(select(ScanStage).where(ScanStage.scan_id == scan_id)
                            .order_by(ScanStage.position)).all()
        logs = db.scalars(select(AgentLog).where(AgentLog.scan_id == scan_id)
                          .order_by(AgentLog.id)).all()
        vulns = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id)).all()
        tests = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id).order_by(TestCase.id)).all()
        endpoints = db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id)
                               .order_by(ApiEndpoint.path, ApiEndpoint.method)).all()
        done = sum(1 for s in stages if s.status == "done")
        return {
            **_run_dict(run, ev, done),
            "state": json.loads(run.state_json) if run.state_json else None,
            "stages": [{"stage": s.stage, "position": s.position, "status": s.status, "runs": s.runs,
                        "started_at": _iso(s.started_at), "finished_at": _iso(s.finished_at)}
                       for s in stages],
            "logs": [{"id": l.id, "stage": l.stage, "level": l.level, "message": l.message,
                      "created_at": _iso(l.created_at)} for l in logs],
            "endpoints": [{"id": e.id, "method": e.method, "path": e.path,
                           "params": json.loads(e.params_json) if e.params_json else None,
                           "auth_required": e.auth_required, "auth_basis": e.auth_basis,
                           "roles": json.loads(e.roles_json) if e.roles_json else [],
                           "purpose": e.business_area,
                           "discovered_via": e.discovered_via.split(",") if e.discovered_via else [],
                           "classification": e.classification,
                           "last_traffic_at": e.last_traffic_at,
                           "traffic": json.loads(e.traffic_json) if e.traffic_json else None,
                           "recommendation": e.recommendation,
                           "owner": e.owner}
                          for e in endpoints],
            "test_cases": [{"id": t.id, "endpoint_id": t.endpoint_id, "test_type": t.test_type,
                            "name": t.description, "reason": t.reason, "risk_level": t.risk_level,
                            "requires_approval": t.requires_approval, "planned_by": t.planned_by,
                            "status": t.status} for t in tests],
            "findings": [{"id": v.id, "title": v.title, "severity": v.severity, "status": v.status}
                         for v in vulns],
        }
