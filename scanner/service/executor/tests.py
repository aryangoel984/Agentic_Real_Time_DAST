"""One executor per approved test type. Plain code, no LLM.

Each returns an Outcome: raw_result "suspicious" or "clean", a one-line summary that
states what came back and what a secure system must return, and 1-2 evidence exchanges.
Ground truth: the scanner created the synthetic data, so it knows the owner, price and
paid/refunded state, and compares the target's answer against that.
"""
import re
from dataclasses import dataclass, field

from .context import FIXTURE_PRICE, CouldNotRun, Ctx, Exchange, NotApplicable

REFUSED = (400, 401, 403, 404, 409, 410, 422)
COMMON_PASSWORDS = ["password", "123456", "admin123"]


@dataclass
class Outcome:
    raw_result: str                       # suspicious / clean
    summary: str
    evidence: list[tuple[Exchange, str]] = field(default_factory=list)   # (exchange, note)


def _fill_id(path: str, value) -> str:
    return re.sub(r"\{[^}]+\}", str(value), path)


def _secure_refusal(ex: Exchange, ok_codes=REFUSED) -> bool:
    return ex.status in ok_codes


def _unexpected(ex: Exchange, what: str):
    raise CouldNotRun(f"{what} returned HTTP {ex.status}; neither the vulnerable nor the secure answer")


# ---------------- cross-agency access ----------------

def cross_agency_access(ctx: Ctx, tc, ep) -> Outcome:
    v, a = ctx.victim, ctx.attacker
    path, method = ep["path"], ep["method"]

    if method == "GET" and "{" in path:
        if "user" in path:
            ex = ctx.call(tc.id, "GET", _fill_id(path, v.user_id), who=a)
            what = f"{v.label}'s user record #{v.user_id}"
        elif "booking" in path:
            bid = ctx.new_booking(tc.id, v)
            ex = ctx.call(tc.id, "GET", _fill_id(path, bid), who=a)
            what = f"agency {v.agency_id}'s synthetic booking #{bid}"
        else:
            raise NotApplicable("no executor recipe for this kind of record")
        got_theirs = ex.status == 200 and isinstance(ex.data, dict) and ex.data.get("agency_id") == v.agency_id
        if got_theirs:
            return Outcome("suspicious", f"{a.label} read {what}: HTTP 200 with agency_id {v.agency_id} "
                                         f"(secure answer: 403/404)", [(ex, "other agency's record returned")])
        if _secure_refusal(ex) or ex.status == 200:
            return Outcome("clean", f"{a.label} asked for {what}: HTTP {ex.status}, no agency {v.agency_id} data "
                                    "returned (as expected)", [(ex, "refused or no foreign data")])
        _unexpected(ex, "the request")

    if method == "POST" and ep.get("purpose") == "payment":
        bid = ctx.new_booking(tc.id, v)
        ex = ctx.call(tc.id, "POST", path, who=a, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE))
        if 200 <= ex.status < 300:
            return Outcome("suspicious", f"{a.label} paid agency {v.agency_id}'s synthetic booking #{bid}: "
                                         f"HTTP {ex.status} (secure answer: 403/404)", [(ex, "foreign booking paid")])
        if _secure_refusal(ex):
            return Outcome("clean", f"{a.label} tried to pay agency {v.agency_id}'s synthetic booking #{bid}: "
                                    f"refused with HTTP {ex.status} (as expected)", [(ex, "refused")])
        _unexpected(ex, "the payment")

    if method == "POST" and ep.get("purpose") == "booking" and "{" not in path:
        ex = ctx.call(tc.id, "POST", path, who=a, body=ctx.body_for(
            ep, agency_id=v.agency_id, user_id=v.user_id, amount=FIXTURE_PRICE))
        if 200 <= ex.status < 300:
            return Outcome("suspicious", f"{a.label} created a booking for agency {v.agency_id}: HTTP {ex.status} "
                                         "(secure answer: 403)", [(ex, "booking created for another agency")])
        if _secure_refusal(ex):
            return Outcome("clean", f"{a.label} tried to create a booking for agency {v.agency_id}: refused with "
                                    f"HTTP {ex.status} (as expected)", [(ex, "refused")])
        _unexpected(ex, "the booking request")

    raise NotApplicable("no per-agency record to reach on this endpoint")


# ---------------- zombie (old version) ----------------

def zombie_ownership_check(ctx: Ctx, tc, ep) -> Outcome:
    if ep["method"] != "GET" or "{" not in ep["path"] or "booking" not in ep["path"]:
        raise NotApplicable("no executor recipe for this old endpoint")
    v, a = ctx.victim, ctx.attacker
    bid = ctx.new_booking(tc.id, v)
    ex = ctx.call(tc.id, "GET", _fill_id(ep["path"], bid), who=a)
    if ex.status == 200 and isinstance(ex.data, dict) and ex.data.get("agency_id") == v.agency_id:
        return Outcome("suspicious", f"the old version returned agency {v.agency_id}'s synthetic booking #{bid} to "
                                     f"{a.label}: HTTP 200 (secure answer: 403/404, or 410 if retired)",
                       [(ex, "old version skips the ownership check")])
    if _secure_refusal(ex):
        return Outcome("clean", f"the old version refused {a.label} with HTTP {ex.status} (as expected)",
                       [(ex, "refused")])
    _unexpected(ex, "the old version")


# ---------------- missing authentication ----------------

def missing_auth(ctx: Ctx, tc, ep) -> Outcome:
    path = ep["path"]
    if "{" in path:
        if "booking" not in path:
            raise NotApplicable("no record id available for this endpoint")
        path = _fill_id(path, ctx.new_booking(tc.id, ctx.victim))
    body = ctx.body_for(ep) if ep["method"] == "POST" else None
    ex = ctx.call(tc.id, ep["method"], path, who=None, body=body)
    if 200 <= ex.status < 300 and ex.data:
        return Outcome("suspicious", f"{ep['method']} {path} answered HTTP {ex.status} with data and no login "
                                     "(secure answer: 401)", [(ex, "data returned without any token")])
    if ex.status in (401, 403):
        return Outcome("clean", f"{ep['method']} {path} refused a request with no login: HTTP {ex.status} "
                                "(as expected)", [(ex, "login required")])
    _unexpected(ex, "the request without a login")


# ---------------- money: duplicate refund ----------------

def duplicate_refund(ctx: Ctx, tc, ep) -> Outcome:
    if ep.get("purpose") != "refund" or ep["method"] != "POST":
        raise NotApplicable("not a refund endpoint")
    v = ctx.victim
    bid = ctx.new_booking(tc.id, v, paid=True)
    body = ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE)
    first = ctx.call(tc.id, "POST", ep["path"], who=v, body=body)
    if first.status != 200:
        raise CouldNotRun(f"setup: the first (legitimate) refund of synthetic booking #{bid} returned HTTP {first.status}")
    second = ctx.call(tc.id, "POST", ep["path"], who=v, body=body)
    ev = [(first, "first refund (legitimate)"), (second, "second refund of the same booking")]
    if 200 <= second.status < 300:
        total = second.data.get("total_refunded") if isinstance(second.data, dict) else None
        return Outcome("suspicious", f"synthetic booking #{bid} (paid ₹{FIXTURE_PRICE:,}) was refunded twice: the second "
                                     f"refund returned HTTP {second.status}"
                                     + (f", total refunded ₹{total:,.0f}" if isinstance(total, (int, float)) else "")
                                     + " (secure answer: 409 already refunded)", ev)
    if _secure_refusal(second):
        return Outcome("clean", f"the second refund of synthetic booking #{bid} was refused with HTTP {second.status} "
                                "(as expected)", ev)
    _unexpected(second, "the second refund")


# ---------------- money: amount validation / price tampering ----------------

def amount_validation(ctx: Ctx, tc, ep) -> Outcome:
    v = ctx.victim
    if ep.get("purpose") == "payment" and ep["method"] == "POST":
        bid = ctx.new_booking(tc.id, v)
        ex = ctx.call(tc.id, "POST", ep["path"], who=v, body=ctx.body_for(ep, booking_id=bid, amount=1))
        paid = isinstance(ex.data, dict) and ex.data.get("payment_status") == "paid"
        if 200 <= ex.status < 300 and paid:
            return Outcome("suspicious", f"synthetic booking #{bid} priced ₹{FIXTURE_PRICE:,} was marked paid for ₹1: "
                                         f"HTTP {ex.status} (secure answer: 400, amount must equal the price)",
                           [(ex, "paid ₹1 for a ₹25,000 booking")])
        if _secure_refusal(ex):
            return Outcome("clean", f"paying ₹1 for synthetic booking #{bid} (price ₹{FIXTURE_PRICE:,}) was refused "
                                    f"with HTTP {ex.status} (as expected)", [(ex, "refused")])
        _unexpected(ex, "the under-priced payment")
    if ep.get("purpose") == "refund" and ep["method"] == "POST":
        bid = ctx.new_booking(tc.id, v, paid=True)
        ex = ctx.call(tc.id, "POST", ep["path"], who=v, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE * 2))
        if 200 <= ex.status < 300:
            return Outcome("suspicious", f"a refund of ₹{FIXTURE_PRICE * 2:,} on synthetic booking #{bid} (paid "
                                         f"₹{FIXTURE_PRICE:,}) was accepted: HTTP {ex.status} (secure answer: 400)",
                           [(ex, "refund larger than the payment accepted")])
        if _secure_refusal(ex):
            return Outcome("clean", f"a refund of ₹{FIXTURE_PRICE * 2:,} on synthetic booking #{bid} (paid "
                                    f"₹{FIXTURE_PRICE:,}) was refused with HTTP {ex.status} (as expected)",
                           [(ex, "refused")])
        _unexpected(ex, "the over-sized refund")
    raise NotApplicable("no amount to tamper with on this endpoint")


# ---------------- role authorization ----------------

def authorization(ctx: Ctx, tc, ep) -> Outcome:
    if ep.get("purpose") != "refund" or ep["method"] != "POST":
        raise NotApplicable("no admin-only action known for this endpoint")
    v, sub = ctx.victim, ctx.victim_subagent
    bid = ctx.new_booking(tc.id, v, paid=True)
    ex = ctx.call(tc.id, "POST", ep["path"], who=sub, body=ctx.body_for(ep, booking_id=bid, amount=FIXTURE_PRICE))
    if 200 <= ex.status < 300:
        return Outcome("suspicious", f"{sub.label} (not an admin) refunded synthetic booking #{bid}: HTTP {ex.status} "
                                     "(secure answer: 403 admins only)", [(ex, "sub-agent performed an admin action")])
    if ex.status in (401, 403):
        return Outcome("clean", f"{sub.label} (not an admin) was refused with HTTP {ex.status} (as expected)",
                       [(ex, "refused")])
    _unexpected(ex, "the sub-agent refund")


# ---------------- weak authentication ----------------

def weak_auth(ctx: Ctx, tc, ep) -> Outcome:
    if ep["method"] != "POST" or ep.get("purpose") != "auth":
        raise NotApplicable("not a login endpoint")
    hits, last = [], None
    for s in ctx.sessions.values():
        for pw in COMMON_PASSWORDS:
            ex = ctx.call(tc.id, "POST", ep["path"], body={"username": s.username, "password": pw})
            last = ex
            if ex.status == 200:
                hits.append((s, ex))
    tried = len(ctx.sessions) * len(COMMON_PASSWORDS)
    if hits:
        s, ex = hits[0]
        return Outcome("suspicious", f"{s.label} signed in with a common password ({len(hits)} of {tried} guesses "
                                     "worked; secure answer: 401)", [(ex, "common password accepted")])
    note = "no lockout or slow-down was seen after 3 wrong passwords per account (noted, not flagged)"
    return Outcome("clean", f"none of {tried} common-password guesses worked (as expected); {note}",
                   [(last, "wrong password refused")])


EXECUTORS = {
    "cross_agency_access": cross_agency_access,
    "zombie_ownership_check": zombie_ownership_check,
    "missing_auth": missing_auth,
    "duplicate_refund": duplicate_refund,
    "amount_validation": amount_validation,
    "authorization": authorization,
    "weak_auth": weak_auth,
}
