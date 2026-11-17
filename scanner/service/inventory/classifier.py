"""The inventory classifier: label each endpoint active, zombie or shadow.

It compares two lists:
  - what recon could see from outside (this scan's api_endpoints rows)
  - what real traffic hit (the provided gateway access log)

  active : in the inventory AND used within the window
  zombie : in the inventory but NOT used within the window (still switched on, forgotten)
  shadow : used in traffic but NOT in the inventory (nobody tracks it) -> added as a new row

The traffic log is a provided input file (scanner/inputs/ by default), the way a
client hands over gateway logs. This stage sends no requests to the target and
never touches the target's database or code.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select

from ..config import TRAFFIC_LOG_PATH, TRAFFIC_WINDOW_DAYS
from ..db import ApiEndpoint, SessionLocal, now
from ..recon.inventory import infer_purpose, to_template

RECOMMENDATIONS = {
    "active": "Keep monitoring; include in regular testing.",
    "zombie": "Decommission, or restrict and block it at the gateway; it is still live but unused.",
    "shadow": "Investigate ownership, then bring it under controls: auth, documentation and testing.",
}

# Likely owning team, guessed from the endpoint's purpose (a guess, not a service catalogue).
OWNER_GUESS = {
    "booking": "Bookings team",
    "payment": "Payments team",
    "refund": "Payments team",
    "auth": "Identity team",
    "user": "Identity team",
    "search": "Search team",
    "partner": "Partner integrations",
}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_traffic(path=TRAFFIC_LOG_PATH) -> dict:
    """Read the log and reduce it to one summary per (method, path template)."""
    data = json.loads(path.read_text())
    entries = data["entries"] if isinstance(data, dict) else data
    meta = data if isinstance(data, dict) else {}
    times = [_ts(e["ts"]) for e in entries]
    log_end = _ts(meta["window_end"]) if meta.get("window_end") else max(times)
    log_start = _ts(meta["window_start"]) if meta.get("window_start") else min(times)
    window_start = log_end - timedelta(days=TRAFFIC_WINDOW_DAYS)

    routes: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"hits": 0, "hits_in_window": 0, "last": None, "callers": Counter()})
    for e, t in zip(entries, times):
        r = routes[(e["method"].upper(), to_template(e["path"]))]
        r["hits"] += 1
        if t >= window_start:
            r["hits_in_window"] += 1
        if r["last"] is None or t > r["last"]:
            r["last"] = t
        r["callers"][f"{e.get('client_ip', '?')} ({e.get('user_agent', '?').split(' ')[0]})"] += 1
    return {"routes": routes, "entry_count": len(entries), "log_start": log_start,
            "log_end": log_end, "window_start": window_start}


def _traffic_json(r: dict | None) -> str:
    if r is None:
        return json.dumps({"hits": 0, "hits_in_window": 0, "callers": []})
    return json.dumps({"hits": r["hits"], "hits_in_window": r["hits_in_window"],
                       "callers": [{"caller": c, "hits": n} for c, n in r["callers"].most_common(3)]})


def classify(scan_id: int, log) -> dict:
    log(f"traffic log source: {TRAFFIC_LOG_PATH} (provided input file; the target's database "
        f"and code are not accessed, and this stage sends no requests to the target)")
    t = load_traffic()
    log(f"traffic log: {t['entry_count']} requests from {t['log_start']:%d %b %Y} to {t['log_end']:%d %b %Y}, "
        f"{len(t['routes'])} distinct routes; window = last {TRAFFIC_WINDOW_DAYS} days of the log "
        f"({t['window_start']:%d %b} to {t['log_end']:%d %b %Y})")
    routes = t["routes"]
    counts = Counter()

    with SessionLocal() as db:
        rows = db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id)).all()
        known = set()
        for row in rows:
            key = (row.method, row.path)
            known.add(key)
            r = routes.get(key)
            label = "active" if r and r["hits_in_window"] > 0 else "zombie"
            row.classification = label
            row.last_traffic_at = r["last"].isoformat() if r else None
            row.traffic_json = _traffic_json(r)
            row.recommendation = RECOMMENDATIONS[label]
            row.owner = OWNER_GUESS.get(row.business_area or infer_purpose(row.path))
            row.updated_at = now()
            counts[label] += 1
            seen = f"last seen {r['last']:%d %b %Y}, {r['hits_in_window']} hits in window" if r else "never seen in traffic"
            log(f"{label:<6} {row.method} {row.path}: {seen}")

        for key, r in sorted(routes.items()):
            if key in known:
                continue
            method, path = key
            purpose = infer_purpose(path)
            db.add(ApiEndpoint(
                scan_id=scan_id, method=method, path=path, discovered_via="traffic_log",
                params_json=json.dumps({"path": [p.strip("{}") for p in path.split("/") if p.startswith("{")],
                                        "query": [], "body": []}),
                auth_required=None, auth_basis="not tested: only seen in traffic, recon could not reach it",
                roles_json="[]", business_area=purpose, classification="shadow",
                last_traffic_at=r["last"].isoformat(), traffic_json=_traffic_json(r),
                recommendation=RECOMMENDATIONS["shadow"], owner=OWNER_GUESS.get(purpose)))
            counts["shadow"] += 1
            callers = ", ".join(f"{c} x{n}" for c, n in r["callers"].most_common(3))
            log(f"shadow {method} {path}: in traffic but not discovered by recon; {r['hits']} hits, "
                f"last seen {r['last']:%d %b %Y}, callers: {callers}", "warn")
        db.commit()

    summary = {k: counts.get(k, 0) for k in ("active", "zombie", "shadow")}
    log(f"classification: active {summary['active']} · zombie {summary['zombie']} · shadow {summary['shadow']}")
    return summary
