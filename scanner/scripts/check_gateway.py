"""Prove the safety gateway works, without the target running.

Uses a throwaway database and a fake in-memory target (httpx MockTransport), so
nothing is sent anywhere. Prints PASS/FAIL for each check.

Run from the project root:
    scanner/.venv/bin/python scanner/scripts/check_gateway.py
"""
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="gateway-check-")
os.environ["SCANNER_DATABASE_URL"] = f"sqlite:///{TMP}/check.db"
os.environ["HEALTH_PROBE_SECONDS"] = "0.5"
os.environ["HEALTH_MAX_PAUSE_SECONDS"] = "8"
os.environ.pop("TARGET_URL", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from service import gateway  # noqa: E402
from service.config import GATEWAY_MAX_RPS, TARGET_BASE_URL  # noqa: E402
from service.db import AuditLog, ScanRun, SessionLocal, TestCase, init_db  # noqa: E402
from service.gateway import GatewayBlocked  # noqa: E402
from service.target_client import TargetClient  # noqa: E402

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def blocked(client, *args, **kw) -> str | None:
    try:
        client.send(*args, **kw)
    except GatewayBlocked as exc:
        return exc.reason
    return None


# ---------- 1. no bypass path (static) ----------
src = ROOT / "service"
net_libs = re.compile(r"^\s*(import|from)\s+(httpx|requests|urllib\.request|urllib3|aiohttp|socket|http\.client)\b", re.M)
importers = sorted(str(p.relative_to(ROOT)) for p in src.rglob("*.py") if net_libs.search(p.read_text()))
check("only target_client.py imports an HTTP library", importers == ["service/target_client.py"], ", ".join(importers))
pw = sorted(str(p.relative_to(ROOT)) for p in src.rglob("*.py") if "playwright" in p.read_text() and "import" in p.read_text()
            and re.search(r"^\s*from playwright", p.read_text(), re.M))
crawler = (src / "recon" / "crawler.py").read_text()
check("the browser is used only by the crawler, and every browser request is routed into the gateway",
      pw == ["service/recon/crawler.py"] and 'ctx.route("**/*", handle)' in crawler
      and "client.send(" in crawler and "route_web_socket" in crawler)
tc = (src / "target_client.py").read_text()
check("the target client transmits in exactly one place", tc.count("self._http.request(") == 1)

# ---------- setup: throwaway scan, fake target ----------
init_db()
with SessionLocal() as db:
    run = ScanRun(status="running")
    db.add(run)
    db.flush()
    risky = TestCase(scan_id=run.id, test_type="duplicate_refund", risk_level="high", requires_approval=True,
                     status="pending_approval")
    db.add(risky)
    db.commit()
    SCAN, RISKY = run.id, risky.id

target = {"mode": "ok", "hits": 0}


def fake_target(request: httpx.Request) -> httpx.Response:
    target["hits"] += 1
    if target["mode"] == "error":
        return httpx.Response(500, text="broken")
    if target["mode"] == "down":
        return httpx.Response(503, text="unavailable")
    if request.url.path == "/api/login":
        return httpx.Response(200, json={"token": "tok-a-admin", "user_id": 1})
    return httpx.Response(200, json={"ok": True})


client = TargetClient(SCAN, "check", transport=httpx.MockTransport(fake_target))

# ---------- 2. scope ----------
r = blocked(client, "GET", "http://example.com/")
check("off-scope host is blocked", bool(r and r.startswith("out of scope")), r or "")
r = blocked(client, "DELETE", "/api/bookings/1001")
check("DELETE is blocked", bool(r and "not allowed" in r), r or "")
r = blocked(client, "GET", "/api/admin/users")
check("excluded path is blocked", bool(r and "excluded" in r), r or "")

# ---------- 3. credentials ----------
r = blocked(client, "POST", "/api/login", json_body={"username": "intruder", "password": "x"})
check("login with an unlisted account is blocked", bool(r and "not one of the provided" in r), r or "")
r = blocked(client, "GET", "/api/bookings/1001", headers={"authorization": "Bearer forged"})
check("forged token is blocked", bool(r and "unknown token" in r), r or "")
resp = client.send("POST", "/api/login", json_body={"username": "a_admin", "password": "DelhiAdmin@123"})
check("login with a provided test account is allowed", resp.status_code == 200)
resp = client.send("GET", "/api/bookings/1003", headers={"authorization": "Bearer tok-a-admin"})
with SessionLocal() as db:
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
check("token issued to that account is allowed and attributed", resp.status_code == 200 and last.account == "A-admin",
      f"account={last.account}")

# ---------- 4. high-risk approval ----------
r = blocked(client, "POST", "/api/refunds", json_body={"booking_id": 1, "amount": 1}, test_case_id=RISKY)
check("unapproved high-risk test is blocked", bool(r and "not approved" in r), r or "")
with SessionLocal() as db:
    db.get(TestCase, RISKY).status = "approved"
    db.commit()
resp = client.send("POST", "/api/refunds", json_body={"booking_id": 1, "amount": 1}, test_case_id=RISKY)
check("the same test is allowed once approved", resp.status_code == 200)

# ---------- 5. rate limit ----------
gateway.reset(SCAN)
with SessionLocal() as db:
    marker = db.query(AuditLog).order_by(AuditLog.id.desc()).first().id
t0 = time.monotonic()
for _ in range(20):
    client.send("GET", "/")
elapsed = time.monotonic() - t0
expected = 19 / GATEWAY_MAX_RPS
check(f"20 requests take at least {expected:.1f} s at a cap of {GATEWAY_MAX_RPS:g}/s", elapsed >= expected - 0.05,
      f"took {elapsed:.2f} s, {20 / elapsed:.1f} req/s")
with SessionLocal() as db:
    times = [a.sent_at for a in db.query(AuditLog).filter(AuditLog.scan_id == SCAN, AuditLog.sent.is_(True),
                                                          AuditLog.id > marker).order_by(AuditLog.sent_at)]
best, j = 0, 0
for i in range(len(times)):
    while (times[i] - times[j]).total_seconds() >= 1:
        j += 1
    best = max(best, i - j + 1)
check(f"never more than {GATEWAY_MAX_RPS:g} requests in any 1 s", best <= GATEWAY_MAX_RPS, f"highest {best}")

# ---------- 6. health monitor ----------
target["mode"] = "error"
for _ in range(3):   # POSTs: a failed read (GET) would itself be held and retried after recovery
    client.send("POST", "/api/search", json_body={})
check("3 errors in a row pause the scan", gateway.paused_reason(SCAN) is not None, gateway.paused_reason(SCAN) or "")
hits_before = target["hits"]
done = {}


def held_request():
    done["resp"] = client.send("GET", "/api/search")


t = threading.Thread(target=held_request)
t.start()
time.sleep(1.5)
check("while paused, a new request is held (not sent)", t.is_alive())
target["mode"] = "ok"
t.join(timeout=5)
check("after the target recovers, the scan resumes and the held request goes out",
      not t.is_alive() and gateway.paused_reason(SCAN) is None and done.get("resp") is not None
      and done["resp"].status_code == 200)
target["mode"] = "down"
done.clear()


def write_during_outage():
    done["resp"] = client.send("POST", "/api/bookings", json_body={"x": 1})


t = threading.Thread(target=write_during_outage)
t.start()
time.sleep(1.5)
check("a 503 pauses the scan at once and the request waits to be re-sent",
      t.is_alive() and (gateway.paused_reason(SCAN) or "").startswith("target unavailable"),
      gateway.paused_reason(SCAN) or "")
target["mode"] = "ok"
t.join(timeout=5)
check("after recovery that request is sent again and succeeds", done.get("resp") is not None
      and done["resp"].status_code == 200 and gateway.paused_reason(SCAN) is None)
with SessionLocal() as db:
    holds = db.query(AuditLog).filter(AuditLog.scan_id == SCAN, AuditLog.decision == "hold").count()
check("the hold is in the audit log", holds >= 1, f"{holds} hold row(s)")

# ---------- 7. kill switch ----------
gateway.halt(SCAN, "human", "kill switch pressed (check script)")
hits = target["hits"]
r = blocked(client, "GET", "/")
check("after the kill switch, requests are blocked and nothing is sent", bool(r and r.startswith("kill switch"))
      and target["hits"] == hits, r or "")

# ---------- 8. audit masking ----------
with SessionLocal() as db:
    rows = db.query(AuditLog).filter(AuditLog.scan_id == SCAN).all()
text = " ".join(f"{a.request_headers_json} {a.request_body}" for a in rows)
leaks = [s for s in ("DelhiAdmin@123", "tok-a-admin", "forged") if s in text]
check("passwords and tokens are masked in the audit log", not leaks, f"leaked: {leaks}" if leaks else
      f"{len(rows)} rows checked")
decisions = {a.decision for a in rows}
check("allow, block and hold decisions are all recorded", {"allow", "block", "hold"} <= decisions, ", ".join(sorted(decisions)))

client.close()
print(f"\n{sum(results)}/{len(results)} checks passed" + ("" if all(results) else "  <-- FAILURES"))
print(f"(target address checked against: {TARGET_BASE_URL}; scratch data in {TMP})")
sys.exit(0 if all(results) else 1)
