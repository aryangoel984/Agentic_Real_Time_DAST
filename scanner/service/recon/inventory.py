"""The scan's API inventory: merges what the three discovery methods see.

Endpoints are keyed by (method, path template). A concrete path such as
/api/bookings/1003 becomes the template /api/bookings/{id}, so the same
endpoint found by the crawl and by app.js lands in one row.
"""
import json
import re

from sqlalchemy import select

from ..db import ApiEndpoint, SessionLocal, now

_NUMERIC = re.compile(r"^\d+$")
_COLON_PARAM = re.compile(r"^:(\w+)$")

# Keyword rules for a short business purpose, checked in order.
_PURPOSE_RULES = [
    ("refund", "refund"),
    ("payment", "payment"),
    ("login", "auth"), ("logout", "auth"), ("token", "auth"), ("auth", "auth"),
    ("booking", "booking"),
    ("user", "user"),
    ("search", "search"),
    ("partner", "partner"),
]


def to_template(path: str) -> str:
    """'/api/bookings/1003' -> '/api/bookings/{id}', '/api/users/:id' -> '/api/users/{id}'."""
    path = path.split("?", 1)[0]
    out = []
    for seg in path.split("/"):
        m = _COLON_PARAM.match(seg)
        if m:
            out.append("{" + m.group(1) + "}")
        elif _NUMERIC.match(seg):
            out.append("{id}")
        else:
            out.append(seg)
    return "/".join(out)


def infer_purpose(path: str) -> str:
    low = path.lower()
    for keyword, purpose in _PURPOSE_RULES:
        if keyword in low:
            return purpose
    return "unknown"


class Inventory:
    def __init__(self, scan_id: int):
        self.scan_id = scan_id
        self.items: dict[tuple[str, str], dict] = {}

    def add(self, method: str, path: str, source: str, *, query=(), body=(), role: str | None = None,
            reached: bool = False, example: str | None = None, sent_token: bool | None = None) -> dict:
        method = method.upper()
        tpl = to_template(path)
        item = self.items.setdefault((method, tpl), {
            "method": method, "path": tpl, "sources": [], "query": set(), "body": set(),
            "roles": [], "example": None, "token_seen": False, "no_token_seen": False,
            "auth_required": None, "auth_basis": None,
        })
        if source not in item["sources"]:
            item["sources"].append(source)
        item["query"].update(query)
        item["body"].update(body)
        if role and reached and role not in item["roles"]:
            item["roles"].append(role)
        if example and item["example"] is None:
            item["example"] = example
        if sent_token is True:
            item["token_seen"] = True
        elif sent_token is False and reached:
            item["no_token_seen"] = True
        return item

    def settle_auth_from_observation(self) -> None:
        """For endpoints not verified by a replay, decide auth from what the portal did."""
        for item in self.items.values():
            if item["auth_basis"]:
                continue
            if item["no_token_seen"]:
                item["auth_required"] = False
                item["auth_basis"] = "portal called it without a token and it succeeded"
            elif item["token_seen"]:
                item["auth_required"] = True
                item["auth_basis"] = "portal always sent a token (writes are not replayed until the safety gateway exists)"
            else:
                item["auth_basis"] = "not observed being called"

    def save(self) -> None:
        with SessionLocal() as db:
            existing = {(r.method, r.path): r for r in db.scalars(
                select(ApiEndpoint).where(ApiEndpoint.scan_id == self.scan_id))}
            for key, it in self.items.items():
                row = existing.get(key) or ApiEndpoint(scan_id=self.scan_id, method=it["method"],
                                                        path=it["path"])
                row.discovered_via = ",".join(it["sources"])
                row.params_json = json.dumps({
                    "path": re.findall(r"\{(\w+)\}", it["path"]),
                    "query": sorted(it["query"]),
                    "body": sorted(it["body"]),
                })
                row.auth_required = it["auth_required"]
                row.auth_basis = it["auth_basis"]
                row.roles_json = json.dumps(it["roles"])
                row.business_area = infer_purpose(it["path"])
                row.updated_at = now()
                db.add(row)
            db.commit()
