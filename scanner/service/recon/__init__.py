"""The recon (discovery) agent: build an API inventory of the target from the outside.

Order of work, saving the inventory after each step so the dashboard fills in live:
  1. app.js      read the portal's JavaScript bundle for API routes
  2. crawl       sign in as each test user and click through the real flows
  3. probe       try older/newer version paths of known GET endpoints
  4. auth check  replay each GET once without a token to see if auth is enforced

Everything goes through one TargetClient (the choke point). No target code is
imported and the target's database is never touched.
"""
from ..config import TARGET_PROFILE
from ..target_client import TargetClient
from . import app_js, crawler, version_probe
from .inventory import Inventory

STAGE = "recon"


def _check_auth_by_replay(client: TargetClient, inv: Inventory, log) -> None:
    for it in inv.items.values():
        if it["method"] != "GET" or not it["example"]:
            continue
        resp = client.send("GET", it["example"])  # no Authorization header
        if resp.status_code == 401:
            it["auth_required"], it["auth_basis"] = True, "verified: 401 without a token"
        elif resp.status_code < 400:
            it["auth_required"], it["auth_basis"] = False, f"verified: answered {resp.status_code} without a token"
        log(f"auth check: GET {it['example']} without a token -> {resp.status_code}")


def run_recon(scan_id: int, log) -> int:
    """Run discovery; `log(message, level='info')` writes to the agent log. Returns endpoint count."""
    inv = Inventory(scan_id)
    accounts = TARGET_PROFILE["accounts"]
    with TargetClient(scan_id, STAGE) as client:
        log(f"target portal: {client.base} (the only host the scanner may contact)")
        try:
            client.send("GET", "/")
        except Exception as exc:
            raise RuntimeError(f"could not reach the target portal at {client.base}: {exc}") from exc
        # The portal forwards /api/* to the platform's API. A 5xx here means the
        # portal is up but nothing is answering behind it.
        api = client.send("GET", "/api")
        if api.status_code >= 500:
            raise RuntimeError(f"the portal is up but its API is not answering (GET /api -> HTTP "
                               f"{api.status_code}). Is the target API running?")

        # 1. app.js
        app_js.discover(client, inv, TARGET_PROFILE.get("bundle_path", "/app.js"), log)
        inv.save()

        # 2. crawl
        log(f"crawl: signing in as {len(accounts)} test users: " + ", ".join(a["label"] for a in accounts))

        def on_role_done(res: crawler.RoleResult) -> None:
            for c in res.calls:
                inv.add(c.method, c.path, "crawl", query=c.query_keys, body=c.body_keys,
                        role=res.label, reached=c.reached, example=c.path if c.method == "GET" else None,
                        sent_token=c.sent_token)
            inv.save()
            summary = ", ".join(f"{c.method} {c.path.split('?')[0]} {c.status}" for c in res.calls)
            log(f"crawl {res.label}: {len(res.calls)} API calls captured: {summary}")
            for n in res.notes:
                log(f"crawl {res.label}: {n}")

        results = crawler.crawl(client, accounts, on_role_done)

        # 3. version probing, using the first role's session
        first = next((r for r in results if r.token), None)
        version_probe.probe(client, inv, first.token if first else None,
                            first.label if first else None, log)
        inv.save()

        # 4. auth check for GETs, then settle the rest from what the portal did
        _check_auth_by_replay(client, inv, log)
        inv.settle_auth_from_observation()
        inv.save()

    by_source = {s: sum(1 for it in inv.items.values() if s in it["sources"])
                 for s in ("crawl", "app.js", "version_probe")}
    log(f"recon finished: {len(inv.items)} endpoints (crawl {by_source['crawl']}, "
        f"app.js {by_source['app.js']}, version probe {by_source['version_probe']})")
    for it in sorted(inv.items.values(), key=lambda i: (i["path"], i["method"])):
        log(f"inventory: {it['method']:<6} {it['path']}  [{', '.join(it['sources'])}]")
    return len(inv.items)
