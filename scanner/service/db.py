"""The scanner's own datastore (scanner/data/scanner.db).

`scan_runs` is the hub. Everything a scan produces hangs off it:
  scan_run ─┬─ deployment_events   (what triggered it)
            ├─ scan_stages         (one row per pipeline stage: pending/running/done)
            ├─ agent_logs          (what each stage did)
            ├─ api_endpoints       (endpoints discovered)
            ├─ test_cases          (tests planned per endpoint)
            ├─ vulnerabilities ─┬─ evidence        (request/response proof)
            │                   └─ retest_history  (each re-check after a fix)
            └─ audit_logs          (every request sent to the target)

Phase 1 fills scan_runs, deployment_events, scan_stages and agent_logs.
Phase 2 (recon) fills api_endpoints and audit_logs.
Phase 3 (inventory) adds classification, traffic and recommendation to api_endpoints.
Phase 4 (attack planning) fills test_cases with planned (not executed) tests.
The rest exist now so later phases grow into a fixed shape.
"""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}
                       if DATABASE_URL.startswith("sqlite") else {})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        # WAL lets the dashboard read while a scan is writing.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------- hub ----------------

class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")   # queued/running/completed/failed/interrupted
    current_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # last saved orchestrator state
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Safety gateway (Phase 5)
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)     # set while the health monitor holds traffic
    halted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # kill switch / safe stop
    halted_by: Mapped[str | None] = mapped_column(String(20), nullable=True)   # human / health_monitor
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))                  # e.g. API_DEPLOYED
    endpoint: Mapped[str | None] = mapped_column(String(300), nullable=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_timestamp: Mapped[str | None] = mapped_column(String(50), nullable=True)  # as sent by the source
    raw_json: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ScanStage(Base):
    __tablename__ = "scan_stages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")   # pending/running/done/failed/interrupted
    runs: Mapped[int] = mapped_column(Integer, default=0)                # >1 when the retest loop re-enters it
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="info")       # info/warn/error
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ---------------- grown into in later phases ----------------

class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    discovered_via: Mapped[str | None] = mapped_column(String(100), nullable=True)  # comma list: crawl,app.js,version_probe
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)           # {"path": [], "query": [], "body": []}
    auth_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    auth_basis: Mapped[str | None] = mapped_column(String(200), nullable=True)     # how auth_required was decided
    roles_json: Mapped[str | None] = mapped_column(Text, nullable=True)            # roles whose calls got through
    classification: Mapped[str | None] = mapped_column(String(20), nullable=True)  # active/zombie/shadow
    last_traffic_at: Mapped[str | None] = mapped_column(String(50), nullable=True)  # ISO time, None = never
    traffic_json: Mapped[str | None] = mapped_column(Text, nullable=True)          # {"hits", "hits_in_window", "callers"}
    business_area: Mapped[str | None] = mapped_column(String(50), nullable=True)   # bookings/payments/PII...
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class TestCase(Base):
    __tablename__ = "test_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    endpoint_id: Mapped[int | None] = mapped_column(ForeignKey("api_endpoints.id"), nullable=True)
    test_type: Mapped[str | None] = mapped_column(String(50), nullable=True)      # id from the approved catalogue
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)              # planner's plain-English reason
    planned_by: Mapped[str | None] = mapped_column(String(20), nullable=True)    # groq / rules
    vuln_class: Mapped[str | None] = mapped_column(String(50), nullable=True)      # access_control/business_logic/...
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="planned")            # planned/cleared/pending_approval/approved/denied/...
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # when a human approved/denied it
    # Execution (Phase 6): raw outcome only; confirmation and severity come later
    exec_status: Mapped[str | None] = mapped_column(String(20), nullable=True)   # ran / skipped / could_not_run
    raw_result: Mapped[str | None] = mapped_column(String(20), nullable=True)    # suspicious / clean
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)      # one plain-English line
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    endpoint_id: Mapped[int | None] = mapped_column(ForeignKey("api_endpoints.id"), nullable=True)
    test_case_id: Mapped[int | None] = mapped_column(ForeignKey("test_cases.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    vuln_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)        # critical/high/medium/low
    business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="suspected")           # verified/false_positive/unverified/fixed
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)   # why verified / rejected (Phase 7)
    checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)           # [{name, passed, detail}]
    # triage (Phase 8)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("vulnerabilities.id"), nullable=True)  # merged into
    severity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity_reason: Mapped[str | None] = mapped_column(Text, nullable=True)       # the factors behind the severity
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)               # 1 = fix first
    owner_source: Mapped[str | None] = mapped_column(String(30), nullable=True)    # ownership data / guessed
    first_seen_scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True) # earliest scan with this flaw
    review_status: Mapped[str | None] = mapped_column(String(20), nullable=True)   # awaiting_review/confirmed/changed/not_needed
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # retest (Phase 10)
    retest_status: Mapped[str | None] = mapped_column(String(20), nullable=True)   # latest retest result
    last_retested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vulnerability_id: Mapped[int | None] = mapped_column(ForeignKey("vulnerabilities.id"), nullable=True, index=True)
    test_case_id: Mapped[int | None] = mapped_column(ForeignKey("test_cases.id"), nullable=True, index=True)
    request_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RetestHistory(Base):
    __tablename__ = "retest_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vulnerability_id: Mapped[int] = mapped_column(ForeignKey("vulnerabilities.id"), index=True)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(20))   # fixed/still_vulnerable/partly_fixed/inconclusive/not_retested/still_present/stopped
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)                 # the plain reason
    triggered_by: Mapped[str | None] = mapped_column(String(30), nullable=True)    # manual / scan N
    checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)           # [{name, passed, detail, where}]
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)         # masked exchanges
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"), nullable=True, index=True)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    method: Mapped[str] = mapped_column(String(10))
    url: Mapped[str] = mapped_column(String(500))
    request_headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(10), default="allow")            # allow / block / hold
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)                    # did a request actually go out
    account: Mapped[str | None] = mapped_column(String(50), nullable=True)        # test account label used
    test_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waited_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)         # rate-limit / pause wait
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def init_db() -> None:
    Base.metadata.create_all(engine)
