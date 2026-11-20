"""One verifier per test type: try to DISPROVE a suspicious raw result.

Every verifier runs two independent checks:
  1. repeat   - the same attack on FRESH synthetic data must give the same suspicious answer
  2. control  - a different kind of proof that the effect is real (owner's copy comparison,
                a made-up ID, a logged-in comparison, or reading the booking back)

Outcome: both pass -> verified; a check contradicts -> false_positive; a check could not be
carried out -> unverified (left for a human, never promoted).
"""
import re
from dataclasses import dataclass, field

from ..executor.context import FIXTURE_PRICE, CouldNotRun, Ctx, Exchange, NotApplicable

BOGUS_ID = 987654321
COMPARE_FIELDS = ["id", "agency_id", "customer_name", "amount", "username"]


@dataclass
class Verdict:
    status: str                                    # verified / false_positive / unverified
    reason: str
    checks: list[dict] = field(default_factory=list)          # {name, passed, detail}
    evidence: list[tuple[Exchange, str]] = field(default_factory=list)


class _Result:
    """Collects checks and turns them into a verdict."""

    def __init__(self):
        self.checks, self.evidence = [], []

    def check(self, name: str, passed: bool | None, detail: str, ex: Exchange | None = None, note: str = ""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if ex is not None:
            self.evidence.append((ex, note or name))
        return passed

    def verdict(self) -> Verdict:
        failed = [c for c in self.checks if c["passed"] is False]
        unknown = [c for c in self.checks if c["passed"] is None]
        if failed:
            c = failed[0]
            return Verdict("false_positive", f"{c['name']} contradicted the raw result: {c['detail']}",
                           self.checks, self.evidence)
        if unknown:
            c = unknown[0]
            return Verdict("unverified", f"{c['name']} could not be carried out: {c['detail']}",
                           self.checks, self.evidence)
        return Verdict("verified", "reproduced on fresh data and confirmed by an independent check",
                       self.checks, self.evidence)


def _fill_id(path: str, value) -> str:
    return re.sub(r"\{[^}]+\}", str(value), path)


def _ok(ex: Exchange) -> bool:
    return 200 <= ex.status < 300


def _readback_endpoint(ctx: Ctx) -> dict:
    """The current (not zombie) 'read a booking by ID' endpoint, used to read state back."""
    for e in ctx.endpoints:
        if e.get("purpose") == "booking" and e["method"] == "GET" and "{" in e["path"] \
                and e.get("classification") != "zombie":
            return e
    raise CouldNotRun("no current booking-lookup endpoint to read the booking back")


def _readback(ctx: Ctx, tc, bid: int) -> Exchange:
    ep = _readback_endpoint(ctx)
    return ctx.call(tc.id, "GET", _fill_id(ep["path"], bid), who=ctx.victim)


def _num(d, k):
    v = d.get(k) if isinstance(d, dict) else None
    return v if isinstance(v, (int, float)) else None


# ---------------- reads: cross-agency by ID, zombie old version ----------------

def foreign_read(ctx: Ctx, tc, ep) -> Verdict:
    r = _Result()
    v, a = ctx.victim, ctx.attacker
    if "user" in ep["path"]:
        rid, what = v.user_id, f"{v.label}'s user record"
    elif "booking" in ep["path"]:
        rid, what = ctx.new_booking(tc.id, v), "a fresh synthetic booking"
    else:
        raise NotApplicable("no verifier for this kind of record")

    rep = ctx.call(tc.id, "GET", _fill_id(ep["path"], rid), who=a)
    leaked = _ok(rep) and isinstance(rep.data, dict) and rep.data.get("agency_id") == v.agency_id
    r.check("repeat on fresh data", leaked,
            f"{a.label} asked for {what} (#{rid}): HTTP {rep.status}"
            + (f" with agency_id {v.agency_id}" if leaked else ", no foreign data"), rep, "repeat as the other agency")
    if not leaked:
        return r.verdict()

    own = ctx.call(tc.id, "GET", _fill_id(ep["path"], rid), who=v)
    if not (_ok(own) and isinstance(own.data, dict)):
        r.check("matches the owner's copy", None, f"the owner's own read returned HTTP {own.status}", own)
    else:
        diff = [k for k in COMPARE_FIELDS if k in own.data and own.data.get(k) != rep.data.get(k)]
        r.check("matches the owner's copy", not diff,
                "identical to what the owner sees (" + ", ".join(k for k in COMPARE_FIELDS if k in own.data) + ")"
                if not diff else f"differs from the owner's copy in {', '.join(diff)}", own, "owner's own read")

    bogus = ctx.call(tc.id, "GET", _fill_id(ep["path"], BOGUS_ID), who=a)
    r.check("made-up ID refused", not _ok(bogus),
            f"ID {BOGUS_ID} (does not exist) returned HTTP {bogus.status}"
            + ("" if not _ok(bogus) else ": the endpoint answers 200 to anything"), bogus, "made-up ID")
    return r.verdict()


# ---------------- missing authentication ----------------

def _real_data(data) -> bool:
    return isinstance(data, dict) and bool(data) and set(data) != {"detail"}


def missing_auth(ctx: Ctx, tc, ep) -> Verdict:
    r = _Result()
    path = ep["path"]
    if "{" in path:
        if "booking" not in path:
            raise NotApplicable("no record id available for this endpoint")
        path = _fill_id(path, ctx.new_booking(tc.id, ctx.victim))
    if ep["method"] != "GET":
        raise NotApplicable("verifier covers read endpoints only")

    anon = ctx.call(tc.id, "GET", path, who=None)
    r.check("repeat without a login", _ok(anon) and _real_data(anon.data),
            f"no-login request returned HTTP {anon.status}", anon, "repeat with no token")
    if not (_ok(anon) and _real_data(anon.data)):
        return r.verdict()

    authed = ctx.call(tc.id, "GET", path, who=ctx.victim)
    if not (_ok(authed) and isinstance(authed.data, dict)):
        r.check("same data as a logged-in request", None, f"logged-in request returned HTTP {authed.status}", authed)
    else:
        same_keys = set(anon.data) == set(authed.data)
        r.check("same data as a logged-in request", same_keys,
                "the no-login answer has the same fields as the logged-in answer ("
                + ", ".join(sorted(authed.data)[:6]) + ")" if same_keys else
                f"the no-login answer differs from the real one (fields {sorted(anon.data)} vs {sorted(authed.data)})",
                authed, "logged-in comparison")
    return r.verdict()


# ---------------- money ----------------

def duplicate_refund(ctx: Ctx, tc, ep) -> Verdict:
    r = _Result()
    v = ctx.victim
    bid = ctx.new_booking(tc.id, v, paid=True)
    body = ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE)
    first = ctx.call(tc.id, "POST", ep["path"], who=v, body=body)
    if first.status != 200:
        r.check("repeat on fresh data", None, f"the first (legitimate) refund returned HTTP {first.status}", first)
        return r.verdict()
    second = ctx.call(tc.id, "POST", ep["path"], who=v, body=body)
    r.check("repeat on fresh data", _ok(second),
            f"booking #{bid}: second refund returned HTTP {second.status}", second, "second refund (repeat)")
    if not _ok(second):
        return r.verdict()
    back = _readback(ctx, tc, bid)
    paid, refunded = _num(back.data, "total_paid"), _num(back.data, "total_refunded")
    if not _ok(back) or paid is None or refunded is None:
        r.check("booking read back", None, f"read-back returned HTTP {back.status} without totals", back)
    else:
        r.check("booking read back", refunded > paid,
                f"booking #{bid} now shows ₹{refunded:,.0f} refunded against ₹{paid:,.0f} paid", back,
                "owner reads the booking back")
    return r.verdict()


def amount_validation(ctx: Ctx, tc, ep) -> Verdict:
    r = _Result()
    v = ctx.victim
    if ep.get("purpose") == "payment":
        bid = ctx.new_booking(tc.id, v)
        ex = ctx.call(tc.id, "POST", ep["path"], who=v, body=ctx.body_for(ep, booking_id=bid, amount=1))
        r.check("repeat on fresh data", _ok(ex), f"paying ₹1 for booking #{bid} returned HTTP {ex.status}",
                ex, "₹1 payment (repeat)")
        if not _ok(ex):
            return r.verdict()
        back = _readback(ctx, tc, bid)
        paid, price = _num(back.data, "total_paid"), _num(back.data, "amount")
        status = back.data.get("payment_status") if isinstance(back.data, dict) else None
        if not _ok(back) or paid is None or price is None:
            r.check("booking read back", None, f"read-back returned HTTP {back.status} without totals", back)
        else:
            r.check("booking read back", status == "paid" and paid < price,
                    f"booking #{bid} shows payment_status {status}, ₹{paid:,.0f} paid of ₹{price:,.0f}", back,
                    "owner reads the booking back")
        return r.verdict()
    if ep.get("purpose") == "refund":
        bid = ctx.new_booking(tc.id, v, paid=True)
        ex = ctx.call(tc.id, "POST", ep["path"], who=v, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE * 2))
        r.check("repeat on fresh data", _ok(ex), f"over-sized refund on booking #{bid} returned HTTP {ex.status}", ex)
        if not _ok(ex):
            return r.verdict()
        back = _readback(ctx, tc, bid)
        paid, refunded = _num(back.data, "total_paid"), _num(back.data, "total_refunded")
        if paid is None or refunded is None:
            r.check("booking read back", None, f"read-back returned HTTP {back.status} without totals", back)
        else:
            r.check("booking read back", refunded > paid, f"₹{refunded:,.0f} refunded against ₹{paid:,.0f} paid", back)
        return r.verdict()
    raise NotApplicable("no verifier for this endpoint")


def authorization(ctx: Ctx, tc, ep) -> Verdict:
    r = _Result()
    v, sub = ctx.victim, ctx.victim_subagent
    bid = ctx.new_booking(tc.id, v, paid=True)
    ex = ctx.call(tc.id, "POST", ep["path"], who=sub, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE))
    r.check("repeat on fresh data", _ok(ex), f"{sub.label} refund on booking #{bid} returned HTTP {ex.status}", ex)
    if not _ok(ex):
        return r.verdict()
    back = _readback(ctx, tc, bid)
    refunded = _num(back.data, "total_refunded")
    r.check("booking read back", None if refunded is None else refunded > 0,
            f"booking #{bid} shows ₹{refunded or 0:,.0f} refunded", back)
    return r.verdict()


def cross_agency_write(ctx: Ctx, tc, ep) -> Verdict:
    r = _Result()
    v, a = ctx.victim, ctx.attacker
    if ep.get("purpose") == "payment":
        bid = ctx.new_booking(tc.id, v)
        ex = ctx.call(tc.id, "POST", ep["path"], who=a, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE))
        r.check("repeat on fresh data", _ok(ex), f"{a.label} paying booking #{bid} returned HTTP {ex.status}", ex)
        if not _ok(ex):
            return r.verdict()
        back = _readback(ctx, tc, bid)
        st = back.data.get("payment_status") if isinstance(back.data, dict) else None
        r.check("booking read back", None if st is None else st == "paid", f"booking #{bid} shows payment_status {st}", back)
        return r.verdict()
    ex = ctx.call(tc.id, "POST", ep["path"], who=a, body=ctx.body_for(
        ep, agency_id=v.agency_id, user_id=v.user_id, amount=FIXTURE_PRICE))
    r.check("repeat on fresh data", _ok(ex), f"{a.label} creating a booking for agency {v.agency_id}: HTTP {ex.status}", ex)
    if not _ok(ex):
        return r.verdict()
    new_id = ex.data.get("id") if isinstance(ex.data, dict) else None
    if new_id is None:
        r.check("booking read back", None, "the response had no booking id", ex)
        return r.verdict()
    back = _readback(ctx, tc, new_id)
    owner = back.data.get("agency_id") if isinstance(back.data, dict) else None
    r.check("booking read back", None if owner is None else owner == v.agency_id,
            f"booking #{new_id} belongs to agency {owner}", back)
    return r.verdict()


def verify(ctx: Ctx, tc, ep) -> Verdict:
    t, m = tc.test_type, ep["method"]
    if t in ("cross_agency_access", "zombie_ownership_check") and m == "GET":
        return foreign_read(ctx, tc, ep)
    if t == "cross_agency_access":
        return cross_agency_write(ctx, tc, ep)
    if t == "missing_auth":
        return missing_auth(ctx, tc, ep)
    if t == "duplicate_refund":
        return duplicate_refund(ctx, tc, ep)
    if t == "amount_validation":
        return amount_validation(ctx, tc, ep)
    if t == "authorization":
        return authorization(ctx, tc, ep)
    raise NotApplicable(f"no verifier for {t}")


TITLES = {
    "cross_agency_access": "Cross-agency access",
    "zombie_ownership_check": "Old API version skips the ownership check",
    "missing_auth": "Missing authentication",
    "duplicate_refund": "Duplicate refund",
    "amount_validation": "Amount not validated (price tampering)",
    "authorization": "Role check missing (sub-agent can act as admin)",
    "weak_auth": "Weak authentication",
}
