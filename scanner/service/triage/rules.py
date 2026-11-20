"""Triage rules: root-cause keys, business severity, impact lines and owners.

Plain, fixed rules (no LLM) so every severity can be explained and is the same on every run.

Severity score = what's at stake + who can do it + exposure:
  at stake : money paid out or lost 5 · customer personal data 3 · account takeover 3
             · partner/supplier data 2 · internal information 1
  who      : anyone, no login 3 · any agency user 2 · only a lower role 1
  exposure : +1 if the flaw is reachable through a zombie or shadow endpoint (nobody watches it)
  score >= 7 critical · >= 5 high · >= 3 medium · otherwise low
"""
import re

from ..config import TARGET_PROFILE
from ..inventory.classifier import OWNER_GUESS
from ..recon.inventory import infer_purpose

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
NEEDS_REVIEW = {"critical", "high"}

MONEY_TESTS = {"duplicate_refund", "amount_validation"}
MONEY_PATHS = ("payment", "refund")

_VERSION = re.compile(r"/v\d+(?=/)")


def strip_version(path: str) -> str:
    """/api/v1/bookings/{id} -> /api/bookings/{id}: old versions share the current route's root cause."""
    return _VERSION.sub("", path)


def root_cause_key(test_type: str, method: str, path: str) -> str:
    """Same flaw on the same resource = same key. The zombie ownership check is a cross-agency read."""
    family = "cross_agency_access" if test_type == "zombie_ownership_check" else test_type
    return f"{family}:{method} {strip_version(path)}"


def severity_label(score: int) -> str:
    return "critical" if score >= 7 else "high" if score >= 5 else "medium" if score >= 3 else "low"


def _stake(test_type: str, method: str, path: str, purpose: str | None) -> tuple[int, str]:
    if test_type in MONEY_TESTS or (method == "POST" and any(w in path for w in MONEY_PATHS)):
        return 5, "money paid out or lost"
    if test_type == "weak_auth":
        return 3, "account takeover"
    if purpose in ("booking", "user") or any(w in path for w in ("booking", "user")):
        return 3, "customer personal data"
    if purpose == "partner" or "partner" in path or "supplier" in path:
        return 2, "partner and supplier data"
    return 1, "internal information"


def _who(test_type: str) -> tuple[int, str]:
    if test_type in ("missing_auth", "weak_auth"):
        return 3, "anyone, with no login"
    if test_type == "authorization":
        return 1, "a lower role (sub-agent)"
    if test_type in MONEY_TESTS:
        return 2, "any agency user, on their own bookings"
    return 2, "any user of another agency"


def score(test_type: str, method: str, path: str, purpose: str | None, exposed_via: list[str]) -> tuple[int, str, str]:
    """-> (score, severity, reason line)."""
    s1, at_stake = _stake(test_type, method, path, purpose)
    s2, who = _who(test_type)
    s3 = 1 if exposed_via else 0
    total = s1 + s2 + s3
    parts = [f"at stake: {at_stake} (+{s1})", f"who can do it: {who} (+{s2})"]
    if s3:
        parts.append(f"reachable through an unmonitored {' and '.join(sorted(set(exposed_via)))} endpoint (+1)")
    sev = severity_label(total)
    return total, sev, " · ".join(parts) + f" → score {total} = {sev}"


def owner_for(path: str, purpose: str | None, guessed: str | None) -> tuple[str | None, str | None]:
    """-> (team, source). Ownership data first, then the inventory's guess from the endpoint's purpose."""
    bare = strip_version(path)
    for row in TARGET_PROFILE.get("ownership", {}).get("paths", []):
        if bare.startswith(row["prefix"]):
            return row["team"], "ownership data"
    team = guessed or OWNER_GUESS.get(purpose or infer_purpose(path))
    return (team, "guessed") if team else (None, None)


def _proof(checks: list[dict]) -> str:
    """The check that shows the effect best: the money read-back, else the reproduced attack itself."""
    passing = {c["name"]: c for c in checks if c.get("passed")}
    for name in ("booking read back", "repeat on fresh data", "same data as a logged-in request"):
        if name in passing:
            return f" In the test: {passing[name]['detail']}."
    return ""


def impact(test_type: str, method: str, path: str, checks: list[dict], also: list[tuple[str, str]]) -> str:
    """One plain sentence on what this means for the business, with the test's real numbers."""
    bare = strip_version(path)
    noun = "booking" if "booking" in bare else "user record" if "user" in bare else "record"
    if test_type in ("cross_agency_access", "zombie_ownership_check") and method == "GET":
        line = (f"Any agency can read another agency's {noun}s, including customer details and amounts, "
                f"just by changing the ID in {method} {bare}.")
    elif test_type == "cross_agency_access":
        line = f"An agency can act on another agency's bookings through {method} {bare}."
    elif test_type == "missing_auth":
        line = f"Anyone on the internet, without logging in, can call {method} {path} and get the same data a logged-in user gets."
    elif test_type == "duplicate_refund":
        line = "An agency can refund the same booking more than once and be paid out more than it ever paid."
    elif test_type == "amount_validation" and "payment" in path:
        line = "An agency can get a booking marked as paid while paying almost nothing: the server trusts the amount sent by the client."
    elif test_type == "amount_validation":
        line = "An agency can refund more than was paid for a booking: the server trusts the amount sent by the client."
    elif test_type == "authorization":
        line = "A sub-agent can issue refunds that only an admin should be able to make."
    elif test_type == "weak_auth":
        line = "Test accounts accept a common password, so an attacker could take over an agency account by guessing."
    else:
        line = f"Verified flaw on {method} {path}."
    if also:
        where = ", ".join(f"{m} {p} ({c})" for m, p, c in also)
        line += f" The same flaw is also reachable through {where}."
    return line + _proof(checks)
