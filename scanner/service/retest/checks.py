"""The retest proof for one place a finding lives (one endpoint + test type).

Two checks, like verification:
  1. the attack no longer works on fresh data: the same executor as in execution runs again
     (new synthetic booking) and must come back clean;
  2. the rightful use still works: the legitimate version of the same action succeeds, so a
     "fix" that simply breaks the endpoint for everyone is not counted as fixed.

Per place: fixed / still_vulnerable / inconclusive. A retired zombie route (410/404 for everyone)
counts as fixed: turning it off is the recommended fix.
"""
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from ..executor.context import FIXTURE_PRICE, CouldNotRun, Ctx, Exchange, NotApplicable
from ..executor.tests import EXECUTORS

RETIRED = (404, 410)


@dataclass
class PlaceResult:
    method: str
    path: str
    result: str                                  # fixed / still_vulnerable / inconclusive / not_retested
    checks: list[dict] = field(default_factory=list)
    evidence: list[tuple[Exchange, str]] = field(default_factory=list)

    def check(self, name: str, passed: bool | None, detail: str):
        self.checks.append({"name": name, "passed": passed, "detail": detail, "where": f"{self.method} {self.path}"})


def _fill(path: str, value) -> str:
    return re.sub(r"\{[^}]+\}", str(value), path)


def _ok(ex: Exchange) -> bool:
    return 200 <= ex.status < 300


def _own_record(ctx: Ctx, tag, ep, pr: PlaceResult) -> tuple[bool | None, str]:
    """The owner reads their own record through the same endpoint."""
    v = ctx.victim
    if "user" in ep["path"]:
        ex = ctx.call(tag, "GET", _fill(ep["path"], v.user_id), who=v)
        what = f"{v.label} reading their own user record"
    else:
        bid = ctx.new_booking(tag, v)
        ex = ctx.call(tag, "GET", _fill(ep["path"], bid), who=v)
        what = f"{v.label} reading their own booking #{bid}"
    pr.evidence.append((ex, "rightful use: owner's own read"))
    mine = _ok(ex) and isinstance(ex.data, dict) and ex.data.get("agency_id", v.agency_id) == v.agency_id
    return mine, f"{what}: HTTP {ex.status}"


def rightful_use(ctx: Ctx, tag, tt: str, ep: dict, pr: PlaceResult, attack_ev) -> tuple[bool | None, str]:
    v = ctx.victim
    m, purpose = ep["method"], ep.get("purpose")
    if tt == "zombie_ownership_check":
        ok, detail = _own_record(ctx, tag, ep, pr)
        if not ok and pr.evidence[-1][0].status in RETIRED:
            return True, f"{detail}: the old route is retired for everyone (the recommended fix)"
        return ok, detail
    if tt == "cross_agency_access" and m == "GET":
        ok, detail = _own_record(ctx, tag, ep, pr)
        if not ok and ep.get("classification") == "zombie" and pr.evidence[-1][0].status in RETIRED:
            return True, f"{detail}: the old route is retired for everyone (the recommended fix)"
        return ok, detail
    if tt == "missing_auth":
        path = ep["path"] if "{" not in ep["path"] else _fill(ep["path"], ctx.new_booking(tag, v))
        ex = ctx.call(tag, m, path, who=v, body=ctx.body_for(ep) if m == "POST" else None)
        pr.evidence.append((ex, "rightful use: logged-in request"))
        return _ok(ex) and bool(ex.data), f"the same request with {v.label}'s login: HTTP {ex.status}"
    if tt == "duplicate_refund":
        first = next((ex for ex, note in attack_ev if "first refund" in note), None)
        if first is None:
            return None, "the first (legitimate) refund was not recorded"
        return _ok(first), f"the first, legitimate refund of the booking: HTTP {first.status}"
    if purpose == "payment" and m == "POST":     # price tampering, or cross-agency payment
        bid = ctx.new_booking(tag, v)
        ex = ctx.call(tag, "POST", ep["path"], who=v, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE))
        pr.evidence.append((ex, "rightful use: owner pays the full price"))
        return _ok(ex), f"{v.label} paying booking #{bid} in full (₹{FIXTURE_PRICE:,}): HTTP {ex.status}"
    if purpose == "refund" and m == "POST":      # over-refund, or sub-agent refund
        bid = ctx.new_booking(tag, v, paid=True)
        ex = ctx.call(tag, "POST", ep["path"], who=v, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE))
        pr.evidence.append((ex, "rightful use: admin refunds what was paid"))
        return _ok(ex), f"{v.label} refunding booking #{bid} for what was paid (₹{FIXTURE_PRICE:,}): HTTP {ex.status}"
    if purpose == "booking" and m == "POST":
        ex = ctx.call(tag, "POST", ep["path"], who=v, body=ctx.body_for(
            ep, agency_id=v.agency_id, user_id=v.user_id, amount=FIXTURE_PRICE))
        pr.evidence.append((ex, "rightful use: owner creates their own booking"))
        return _ok(ex), f"{v.label} creating a booking for their own agency: HTTP {ex.status}"
    if tt == "weak_auth":
        return bool(ctx.victim.token), "the real test-account passwords still sign in"
    return None, "no rightful-use check known for this endpoint"


def retest_place(ctx: Ctx, tag, tt: str, ep: dict) -> PlaceResult:
    """Run the two checks for one place. `tag` is the test id every request is filed under at the gateway."""
    pr = PlaceResult(ep["method"], ep["path"], "inconclusive")
    fn = EXECUTORS.get(tt)
    if fn is None:
        pr.check("attack no longer works", None, "no executor for this test type")
        return pr
    try:
        out = fn(ctx, SimpleNamespace(id=tag, test_type=tt), ep)
    except (NotApplicable, CouldNotRun) as exc:
        pr.check("attack no longer works", None, f"could not run the attack: {exc}")
        return pr
    pr.evidence += out.evidence
    if out.raw_result == "suspicious":
        pr.check("attack no longer works", False, f"the attack worked again: {out.summary}")
        pr.result = "still_vulnerable"
        return pr
    pr.check("attack no longer works", True, out.summary)
    try:
        ok, detail = rightful_use(ctx, tag, tt, ep, pr, out.evidence)
    except CouldNotRun as exc:
        ok, detail = None, f"could not run: {exc}"
    pr.check("rightful use still works", ok, detail)
    pr.result = "fixed" if ok else "inconclusive"
    return pr


def overall(places: list[PlaceResult]) -> tuple[str, str]:
    """Combine the places of one (possibly merged) finding into one result and a plain reason."""
    res = [p.result for p in places]
    where = lambda r: ", ".join(f"{p.method} {p.path}" for p in places if p.result == r)  # noqa: E731
    if all(r == "fixed" for r in res):
        return "fixed", "the attack is refused everywhere it was found, and the rightful use still works"
    if "still_vulnerable" in res:
        if "fixed" in res:
            return "partly_fixed", f"fixed on {where('fixed')}, still vulnerable on {where('still_vulnerable')}"
        return "still_vulnerable", f"the attack still works on {where('still_vulnerable')}"
    if all(r == "not_retested" for r in res):
        return "not_retested", "the matching test was not cleared or approved in this scan, so nothing was sent"
    bad = [c["detail"] for p in places for c in p.checks if c["passed"] is not True]
    return "inconclusive", "a check could not confirm the fix: " + "; ".join(bad[:2])
