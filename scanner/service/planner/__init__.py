"""The attack planner: decide which approved tests each endpoint needs. Nothing is executed.

1. Pick a planner: Groq (LLM) if configured, otherwise the rule-based planner.
   When the LLM plans, the rule-based plan is a guaranteed minimum: core tests it misses are added.
2. Validate every proposed test against the approved catalogue (code, not the LLM,
   has the final say). Out-of-catalogue or not-applicable proposals are dropped and logged.
3. Save the kept tests to test_cases with status "planned".
"""
import json
import os

from sqlalchemy import func, select

from ..config import PLANNER_MODEL, PLANNER_PROVIDER
from ..db import ApiEndpoint, AuditLog, SessionLocal, TestCase
from . import rules
from .catalogue import CATALOGUE

STAGE = "attack_planning"


def _endpoints(scan_id: int) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id)).all()
        return [{"id": r.id, "method": r.method, "path": r.path,
                 "params": json.loads(r.params_json) if r.params_json else None,
                 "auth_required": r.auth_required, "auth_basis": r.auth_basis,
                 "roles": json.loads(r.roles_json or "[]"),
                 "classification": r.classification, "purpose": r.business_area,
                 "discovered_via": r.discovered_via, "last_traffic_at": r.last_traffic_at}
                for r in rows]


def _choose() -> tuple[str, str]:
    has_key = bool(os.getenv("GROQ_API_KEY"))
    if PLANNER_PROVIDER == "rules":
        return "rules", "PLANNER_PROVIDER=rules"
    if PLANNER_PROVIDER == "groq" and not has_key:
        return "rules", "PLANNER_PROVIDER=groq but no GROQ_API_KEY set"
    if has_key:
        return "groq", "GROQ_API_KEY is set"
    return "rules", "no GROQ_API_KEY set"


def validate(raw, endpoints: dict[int, dict], source: str):
    """Keep only well-formed, catalogue-approved, applicable tests. Returns (plans, dropped)."""
    plans: dict[int, dict] = {}
    dropped: list[str] = []
    items = raw.get("plans") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("plan has no 'plans' list")
    for item in items:
        if not isinstance(item, dict):
            dropped.append(f"malformed plan entry {str(item)[:60]!r}")
            continue
        eid = item.get("endpoint_id")
        ep = endpoints.get(eid) if isinstance(eid, int) else None
        if ep is None:
            dropped.append(f"plan for unknown endpoint_id {eid!r}")
            continue
        label = f"{ep['method']} {ep['path']}"
        kept = plans.setdefault(eid, {"tests": [], "skip_reason": None})
        for t in item.get("tests") or []:
            tt = t.get("test_type") if isinstance(t, dict) else None
            reason = (t.get("reason") or "").strip() if isinstance(t, dict) else ""
            if not isinstance(tt, str) or tt not in CATALOGUE:
                dropped.append(f'"{tt}" on {label}: not in the approved catalogue')
            elif ep["method"] not in CATALOGUE[tt].methods:
                dropped.append(f'"{tt}" on {label}: does not apply to {ep["method"]}')
            elif not reason:
                dropped.append(f'"{tt}" on {label}: no reason given')
            elif any(k["test_type"] == tt for k in kept["tests"]):
                continue  # duplicate
            else:
                kept["tests"].append({"test_type": tt, "reason": reason[:500], "planned_by": source})
        skip = item.get("skip_reason")
        if not kept["tests"] and isinstance(skip, str) and skip.strip():
            kept["skip_reason"] = skip.strip()[:300]
    return plans, dropped


def run_planning(scan_id: int, log) -> dict:
    endpoints = _endpoints(scan_id)
    by_id = {e["id"]: e for e in endpoints}
    planner, why = _choose()
    model = None
    plans, dropped = {}, []

    if planner == "groq":
        log(f"planner: Groq LLM ({PLANNER_MODEL}), because {why}. It returns a JSON plan only; "
            f"it has no tools and is not given the target's address or any credentials")
        try:
            from . import groq_planner
            raw, model = groq_planner.plan(endpoints)
            plans, dropped = validate(raw, by_id, "groq")
        except Exception as exc:  # any failure -> deterministic fallback, never a failed scan
            log(f"Groq planner failed ({type(exc).__name__}: {str(exc)[:200]}); falling back to the rule-based planner", "warn")
            planner, why, model, plans, dropped = "rules", f"Groq call failed ({type(exc).__name__})", None, {}, []
    if planner == "rules":
        log(f"planner: rule-based (deterministic), because {why}")
        raw = {"plans": [{"endpoint_id": eid, **p} for eid, p in rules.plan(endpoints).items()]}
        plans, dropped = validate(raw, by_id, "rules")

    missing = [e for e in endpoints if e["id"] not in plans]
    for e in missing:
        log(f"LLM gave no plan for {e['method']} {e['path']}; using the rule-based plan for it", "warn")
        p = rules.plan_endpoint(e)
        plans[e["id"]] = {"tests": [{**t, "planned_by": "rules"} for t in p["tests"]],
                          "skip_reason": p["skip_reason"]}

    # Guaranteed minimum: the LLM's choices vary run to run, so when it planned, any core
    # test the rules would plan but the LLM missed is added (marked as planned by rules).
    floor_added = 0
    if planner == "groq":
        for e in endpoints:
            have = {t["test_type"] for t in plans[e["id"]]["tests"]}
            for t in rules.plan_endpoint(e)["tests"]:
                if t["test_type"] not in have:
                    plans[e["id"]]["tests"].append({**t, "planned_by": "rules"})
                    floor_added += 1
                    log(f"rules minimum added {t['test_type']} to {e['method']} {e['path']} (the LLM did not plan it)")

    for d in dropped:
        log(f"dropped: {d}", "warn")

    total = 0
    skips: dict[str, str] = {}
    with SessionLocal() as db:
        for eid, p in plans.items():
            ep = by_id[eid]
            for t in p["tests"]:
                cat = CATALOGUE[t["test_type"]]
                db.add(TestCase(scan_id=scan_id, endpoint_id=eid, test_type=cat.id, reason=t["reason"],
                                planned_by=t["planned_by"], vuln_class=cat.vuln_class, description=cat.name,
                                risk_level=cat.risk, requires_approval=cat.requires_approval,
                                status="planned"))
                total += 1
            names = ", ".join(t["test_type"] for t in p["tests"])
            if p["tests"]:
                log(f"{ep['method']} {ep['path']}: {names}")
            else:
                skips[str(eid)] = p["skip_reason"] or "No approved test fits this endpoint."
                log(f"{ep['method']} {ep['path']}: no tests ({skips[str(eid)]})")
        db.commit()
        sent = db.scalar(select(func.count()).select_from(AuditLog)
                         .where(AuditLog.scan_id == scan_id, AuditLog.stage == STAGE))

    log(f"planned {total} tests across {len(plans) - len(skips)} endpoints; dropped {len(dropped)} "
        f"proposal(s); requests sent to the target during planning: {sent} (nothing is executed)")
    return {"planner": planner, "model": model, "why": why, "tests": total, "floor_added": floor_added,
            "dropped": dropped, "skips": skips, "requests_to_target": sent}
