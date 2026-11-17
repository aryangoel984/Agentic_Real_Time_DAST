"""Discovery method C: try older/newer version paths of endpoints we already know.

For every known GET endpoint with a real example (e.g. /api/bookings/1003) we
try /api/v0/..., /api/v1/..., /api/v2/... on the same host. Anything that does
not answer 404/405 "responds" and is added to the inventory.

GET only: guessing write paths (POST) waits for the Phase 5 safety gateway.
"""
import re
from urllib.parse import parse_qs, urlsplit

from .inventory import Inventory

VERSIONS = ["v0", "v1", "v2"]
_ALREADY_VERSIONED = re.compile(r"^/api/v\d+/")


def probe(client, inv: Inventory, token: str | None, token_role: str | None, log) -> int:
    candidates = [it for it in list(inv.items.values())
                  if it["method"] == "GET" and it["example"]
                  and not _ALREADY_VERSIONED.match(it["path"])]
    headers = {"authorization": token} if token else {}
    found = 0
    for it in candidates:
        rest = it["example"][len("/api/"):]
        results = []
        for v in VERSIONS:
            probe_path = f"/api/{v}/{rest}"
            resp = client.send("GET", probe_path, headers=headers)
            results.append(f"{v} {resp.status_code}")
            if resp.status_code not in (404, 405):
                parts = urlsplit(probe_path)
                inv.add("GET", parts.path, "version_probe",
                        query=parse_qs(parts.query).keys(), role=token_role,
                        reached=resp.status_code not in (401, 403), example=probe_path,
                        sent_token=bool(token))
                found += 1
                log(f"version probe: GET {probe_path} answered {resp.status_code}, added to inventory")
        log(f"version probe: {it['path']} -> " + ", ".join(results))
    return found
