"""Shared setup for the executors: test-account sessions, synthetic bookings, evidence capture.

Every request goes through the shared TargetClient (the safety gateway). Requests made
for a test, including its setup, carry that test's id, so the gateway re-checks the
test's approval on every one of them.
"""
import json
from dataclasses import dataclass, field

from ..config import TARGET_PROFILE
from ..gateway import LOGIN_PATH, TOKEN_FIELD
from ..target_client import TargetClient, _redact_body, _redact_headers

# Synthetic values for any booking the scanner creates. No real or seeded customer data.
SYNTHETIC = {
    "customer_name": "DAST Synthetic Customer",
    "customer_email": "dast+synthetic@example.test",
    "customer_phone": "+91-00000-00000",
    "item": "DAST synthetic test item",
    "travel_date": "2027-01-15",
}
FIXTURE_PRICE = 25000

# Only these response fields are kept as evidence (no bulk data, no contact details).
KEY_FIELDS = ["id", "agency_id", "agency_name", "booked_by_user_id", "customer_name", "amount",
              "payment_status", "refund_status", "booking_price", "amount_charged", "refunded_now",
              "total_refunded", "amount_paid", "username", "role", "user_id", "note", "detail"]


class NotApplicable(Exception):
    """No executor recipe fits this endpoint: the test is skipped, not forced."""


class CouldNotRun(Exception):
    """Setup failed or the answer was unexpected: no verdict is guessed."""


@dataclass
class Session:
    label: str
    username: str
    token: str | None = None
    user_id: int | None = None
    agency_id: int | None = None
    role: str | None = None


@dataclass
class Exchange:
    status: int
    data: object          # parsed JSON body, or None
    record: dict          # masked request + key response fields, for evidence


def key_part(data) -> dict | str | None:
    """The few response fields that prove the result. Lists become counts."""
    if isinstance(data, dict):
        out = {}
        for k in KEY_FIELDS:
            if k in data:
                out[k] = data[k]
        for k, v in data.items():
            if k not in out and isinstance(v, list):
                out[k] = f"[{len(v)} item(s)]"
        return out or {"keys": sorted(data.keys())[:10]}
    if isinstance(data, list):
        return f"[{len(data)} item(s)]"
    return None if data is None else str(data)[:200]


@dataclass
class Ctx:
    scan_id: int
    client: TargetClient
    endpoints: list[dict]
    sessions: dict[str, Session] = field(default_factory=dict)
    log: object = None

    # ---------- accounts ----------
    def login_all(self) -> None:
        for acct in TARGET_PROFILE["accounts"]:
            s = Session(acct["label"], acct["username"])
            ex = self.call(None, "POST", LOGIN_PATH, body={"username": acct["username"],
                                                           "password": acct["password"]})
            if ex.status == 200 and isinstance(ex.data, dict):
                s.token = ex.data.get(TOKEN_FIELD)
                s.user_id, s.agency_id, s.role = ex.data.get("user_id"), ex.data.get("agency_id"), ex.data.get("role")
                self.log(f"signed in as {s.label} (agency {s.agency_id}, {s.role})")
            else:
                self.log(f"could not sign in as {s.label}: HTTP {ex.status}", "warn")
            self.sessions[s.label] = s

    def _pick(self, *, admin: bool, other_agency_than: int | None = None, agency: int | None = None) -> Session:
        for s in self.sessions.values():
            if not s.token or (s.role == "admin") != admin:
                continue
            if other_agency_than is not None and s.agency_id == other_agency_than:
                continue
            if agency is not None and s.agency_id != agency:
                continue
            return s
        raise CouldNotRun("no suitable signed-in test account")

    @property
    def victim(self) -> Session:        # owner of the synthetic data (first admin, e.g. A-admin)
        return self._pick(admin=True)

    @property
    def attacker(self) -> Session:      # an admin from a different agency (e.g. B-admin)
        return self._pick(admin=True, other_agency_than=self.victim.agency_id)

    @property
    def victim_subagent(self) -> Session:   # non-admin in the victim's agency (e.g. A-subagent)
        return self._pick(admin=False, agency=self.victim.agency_id)

    # ---------- endpoints ----------
    def find(self, purpose: str, method: str, with_id: bool | None = None) -> dict:
        for e in self.endpoints:
            if e.get("purpose") == purpose and e["method"] == method and \
                    (with_id is None or ("{" in e["path"]) == with_id):
                return e
        raise CouldNotRun(f"no {method} {purpose} endpoint in the inventory")

    @staticmethod
    def body_for(ep: dict, **values) -> dict:
        """Fill the endpoint's known body fields with synthetic values plus the given ones."""
        keys = (ep.get("params") or {}).get("body") or list(values)
        body = {}
        for k in keys:
            if k in values:
                body[k] = values[k]
            elif k in SYNTHETIC:
                body[k] = SYNTHETIC[k]
        for k, v in values.items():
            body.setdefault(k, v)
        return body

    # ---------- sending ----------
    def call(self, tc_id, method, path, *, who: Session | None = None, body=None) -> Exchange:
        headers = {"authorization": f"Bearer {who.token}"} if who and who.token else {}
        resp = self.client.send(method, path, headers=headers, json_body=body, test_case_id=tc_id)
        try:
            data = resp.json()
        except ValueError:
            data = None
        sent_headers = dict(headers)
        if body is not None:
            sent_headers["content-type"] = "application/json"
        record = {"request": {"as": who.label if who else "no login", "method": method, "path": path,
                              "headers": _redact_headers(sent_headers),
                              "body": json.loads(_redact_body(json.dumps(body).encode())) if body is not None else None},
                  "response": {"status": resp.status_code, "key_fields": key_part(data)}}
        return Exchange(resp.status_code, data, record)

    # ---------- synthetic bookings ----------
    def new_booking(self, tc_id, owner: Session, *, paid: bool = False) -> int:
        create = self.find("booking", "POST", with_id=False)
        ex = self.call(tc_id, "POST", create["path"], who=owner, body=self.body_for(
            create, agency_id=owner.agency_id, user_id=owner.user_id, amount=FIXTURE_PRICE))
        if ex.status not in (200, 201) or not isinstance(ex.data, dict) or "id" not in ex.data:
            raise CouldNotRun(f"setup: creating a synthetic booking returned HTTP {ex.status}")
        bid = ex.data["id"]
        if paid:
            pay = self.find("payment", "POST")
            ex = self.call(tc_id, "POST", pay["path"], who=owner,
                           body=self.body_for(pay, booking_id=bid, amount=FIXTURE_PRICE))
            if ex.status != 200:
                raise CouldNotRun(f"setup: paying synthetic booking #{bid} in full returned HTTP {ex.status}")
        return bid
