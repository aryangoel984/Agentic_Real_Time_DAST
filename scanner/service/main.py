"""Scanner API (port 9000).

- POST /events/deploy  : receive a "something changed" event, start a scan
- GET  /scans          : list scan runs
- GET  /scans/{id}     : one scan with its event, stages, logs, API inventory, attack plan and findings
- GET  /scans/{id}/audit : safety gateway decisions (audit log, masked) and a safety summary
- POST /scans/{id}/tests/{tid}/approve | deny : human decision on a high-risk test
- POST /scans/{id}/kill : kill switch, halts every outgoing request for the scan
- POST /scans/{id}/findings/{fid}/review : human review of a critical/high finding (confirm or change severity)
- GET  /scans/{id}/report | report.md | tickets.json : the scan report (JSON, Markdown) and tracker-ready tickets

This service is independent of the target platform. It has its own database
and never imports the target's code or opens the target's database.
"""
import json

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import gateway
from .config import GATEWAY_MAX_RPS, STAGES
from .db import (AgentLog, ApiEndpoint, AuditLog, DeploymentEvent, Evidence, ScanRun, ScanStage, SessionLocal,
                 TestCase, Vulnerability, init_db, now)
from .orchestrator.graph import run_scan
from .reporting import build_report, max_per_second, tickets_export
from .reporting.markdown import report_markdown

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
            "paused_reason": run.paused_reason, "halted_by": run.halted_by, "halt_reason": run.halt_reason,
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
        vulns = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id)
                           .order_by(Vulnerability.id)).all()
        tests = db.scalars(select(TestCase).where(TestCase.scan_id == scan_id).order_by(TestCase.id)).all()
        evidence: dict[int, list] = {}
        vuln_evidence: dict[int, list] = {}
        if tests:
            for item in db.scalars(select(Evidence).where(Evidence.test_case_id.in_([t.id for t in tests]))
                                   .order_by(Evidence.id)):
                if item.vulnerability_id is None:      # execution evidence
                    evidence.setdefault(item.test_case_id, []).append(item)
                else:                                  # verification evidence
                    vuln_evidence.setdefault(item.vulnerability_id, []).append(item)
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
                            "status": t.status, "exec_status": t.exec_status, "raw_result": t.raw_result,
                            "result_summary": t.result_summary, "executed_at": _iso(t.executed_at),
                            "evidence": [{"request": json.loads(x.request_json) if x.request_json else None,
                                          "response": json.loads(x.response_json) if x.response_json else None,
                                          "note": x.notes} for x in evidence.get(t.id, [])]}
                           for t in tests],
            "findings": [{"id": v.id, "title": v.title, "severity": v.severity, "status": v.status,
                          "test_case_id": v.test_case_id, "endpoint_id": v.endpoint_id, "vuln_class": v.vuln_class,
                          "verification_reason": v.verification_reason,
                          "duplicate_of": v.duplicate_of, "rank": v.rank, "severity_score": v.severity_score,
                          "severity_reason": v.severity_reason, "business_impact": v.business_impact,
                          "owner": v.owner, "owner_source": v.owner_source,
                          "first_seen_scan_id": v.first_seen_scan_id, "review_status": v.review_status,
                          "review_note": v.review_note, "reviewed_at": _iso(v.reviewed_at),
                          "checks": json.loads(v.checks_json) if v.checks_json else [],
                          "evidence": [{"request": json.loads(x.request_json) if x.request_json else None,
                                        "response": json.loads(x.response_json) if x.response_json else None,
                                        "note": x.notes} for x in vuln_evidence.get(v.id, [])]}
                         for v in vulns],
        }


# ---------------- safety gateway (Phase 5) ----------------

@app.get("/scans/{scan_id}/audit")
def get_audit(scan_id: int, limit: int = 400):
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        counts = dict(db.execute(select(AuditLog.decision, func.count()).where(AuditLog.scan_id == scan_id)
                                 .group_by(AuditLog.decision)).all())
        sent_times = db.scalars(select(AuditLog.sent_at).where(AuditLog.scan_id == scan_id, AuditLog.sent.is_(True))
                                .order_by(AuditLog.sent_at)).all()
        rows = db.scalars(select(AuditLog).where(AuditLog.scan_id == scan_id)
                          .order_by(AuditLog.id.desc()).limit(limit)).all()
        return {
            "summary": {"allowed": counts.get("allow", 0), "held": counts.get("hold", 0),
                        "blocked": counts.get("block", 0), "sent": len(sent_times),
                        "rate_cap": GATEWAY_MAX_RPS, "max_per_second": max_per_second(sent_times),
                        "paused_reason": run.paused_reason, "halted_by": run.halted_by,
                        "halt_reason": run.halt_reason, "status": run.status},
            "rows": [{"id": a.id, "at": _iso(a.sent_at), "stage": a.stage, "method": a.method, "url": a.url,
                      "decision": a.decision, "reason": a.reason, "status": a.response_status, "sent": a.sent,
                      "account": a.account, "test_case_id": a.test_case_id, "latency_ms": a.latency_ms,
                      "waited_ms": a.waited_ms,
                      "request_headers": json.loads(a.request_headers_json) if a.request_headers_json else {},
                      "request_body": a.request_body} for a in rows],
        }


def _decide(scan_id: int, test_id: int, approve: bool):
    with SessionLocal() as db:
        t = db.get(TestCase, test_id)
        if t is None or t.scan_id != scan_id:
            raise HTTPException(status_code=404, detail="Test not found in this scan")
        run = db.get(ScanRun, scan_id)
        if run.status not in ("queued", "running") or run.halted_at is not None:
            raise HTTPException(status_code=409, detail=f"Scan is {run.status}; decisions are closed")
        if t.status != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Test is {t.status}, not waiting for approval")
        ep = db.get(ApiEndpoint, t.endpoint_id)
        t.status, t.decided_at = ("approved" if approve else "denied"), now()
        verb = "approved" if approve else "denied"
        db.add(AuditLog(scan_id=scan_id, stage="safety_gateway", method=ep.method if ep else "-",
                        url=ep.path if ep else "-", decision="allow" if approve else "block",
                        test_case_id=t.id, sent=False, sent_at=now(),
                        reason=f"high-risk test #{t.id} ({t.test_type}) {verb} by a human on the dashboard"
                               + ("; may run in execution (nothing sent now)" if approve else "; dropped, will never run")))
        db.add(AgentLog(scan_id=scan_id, stage="safety_gateway", level="info" if approve else "warn",
                        message=f"test #{t.id} {t.test_type} {verb} by a human on the dashboard"))
        db.commit()
        return {"id": t.id, "status": t.status}


@app.post("/scans/{scan_id}/tests/{test_id}/approve")
def approve_test(scan_id: int, test_id: int):
    return _decide(scan_id, test_id, True)


@app.post("/scans/{scan_id}/tests/{test_id}/deny")
def deny_test(scan_id: int, test_id: int):
    return _decide(scan_id, test_id, False)


# ---------------- triage review (Phase 8) ----------------

class ReviewIn(BaseModel):
    action: str = Field(pattern="^(confirm|change)$")
    severity: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    note: str | None = Field(default=None, max_length=500)


@app.post("/scans/{scan_id}/findings/{finding_id}/review")
def review_finding(scan_id: int, finding_id: int, body: ReviewIn):
    with SessionLocal() as db:
        v = db.get(Vulnerability, finding_id)
        if v is None or v.scan_id != scan_id:
            raise HTTPException(status_code=404, detail="Finding not found in this scan")
        if v.status != "verified" or v.duplicate_of is not None:
            raise HTTPException(status_code=409, detail="Only verified, ranked findings can be reviewed")
        if v.review_status != "awaiting_review":
            raise HTTPException(status_code=409, detail=f"Finding is {v.review_status or 'not triaged'}, not awaiting review")
        note = (body.note or "").strip()
        if body.action == "change":
            if not body.severity or body.severity == v.severity:
                raise HTTPException(status_code=422, detail="Pick a different severity")
            if not note:
                raise HTTPException(status_code=422, detail="Give a reason for changing the severity")
            what = f"severity changed from {v.severity} to {body.severity}"
            v.severity_reason = f"{v.severity_reason} · reviewer changed it to {body.severity}: {note}"
            v.severity, v.review_status = body.severity, "changed"
            ranked = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id,
                                                            Vulnerability.rank.is_not(None))).all()
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            for i, r in enumerate(sorted(ranked, key=lambda r: (order[r.severity], -(r.severity_score or 0), r.id)), 1):
                r.rank = i     # re-rank so a downgraded finding moves down the list
        else:
            what = f"severity {v.severity} confirmed"
            v.review_status = "confirmed"
        v.review_note, v.reviewed_at = note or None, now()
        ep = db.get(ApiEndpoint, v.endpoint_id) if v.endpoint_id else None
        db.add(AuditLog(scan_id=scan_id, stage="triage", method=ep.method if ep else "-", url=ep.path if ep else "-",
                        decision="allow", test_case_id=v.test_case_id, sent=False, sent_at=now(),
                        reason=f"finding #{v.id} reviewed by a human on the dashboard: {what}"
                               + (f" ({note})" if note else "") + "; nothing sent"))
        db.add(AgentLog(scan_id=scan_id, stage="triage", level="info",
                        message=f"finding #{v.id} {v.title}: {what} by a human reviewer"))
        db.commit()
        return {"id": v.id, "severity": v.severity, "review_status": v.review_status}


# ---------------- report (Phase 9) ----------------

def _report_or_404(scan_id: int) -> dict:
    r = build_report(scan_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return r


@app.get("/scans/{scan_id}/report")
def get_report(scan_id: int):
    return _report_or_404(scan_id)


@app.get("/scans/{scan_id}/report.md", response_class=PlainTextResponse)
def get_report_md(scan_id: int):
    return PlainTextResponse(report_markdown(_report_or_404(scan_id)), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="dast-scan-{scan_id}-report.md"'})


@app.get("/scans/{scan_id}/tickets.json")
def get_tickets(scan_id: int):
    return JSONResponse(tickets_export(_report_or_404(scan_id)),
                        headers={"Content-Disposition": f'attachment; filename="dast-scan-{scan_id}-tickets.json"'})


@app.post("/scans/{scan_id}/kill")
def kill_scan(scan_id: int):
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        if run.status not in ("queued", "running"):
            raise HTTPException(status_code=409, detail=f"Scan is {run.status}; nothing to stop")
    gateway.halt(scan_id, "human", "kill switch pressed on the dashboard")
    return {"scan_id": scan_id, "halted": True}
