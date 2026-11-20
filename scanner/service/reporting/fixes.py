"""Per test type: suggested fix, expected vs actual behaviour, and the setup step for reproducing.

Fixed text written for this kind of platform (agencies, bookings, payments, refunds). The
actual requests in "steps to reproduce" come from the masked verification evidence.
"""

FIXES = {
    "cross_agency_access": (
        "On every request that reads or changes a record by ID, load the record and check that its agency_id "
        "equals the caller's agency (from the token, never from the request). Return 404 when it doesn't, so "
        "other agencies can't even learn the ID exists. Put the check in one shared function used by every "
        "route and every API version, and add a test that agency B gets 404 for agency A's records."),
    "zombie_ownership_check": (
        "Turn the old version off: remove the route or block it at the gateway (410 Gone). If a client still "
        "needs it, route it through the same ownership check as the current version. Nothing called it in the "
        "traffic window, so turning it off should not break any user."),
    "missing_auth": (
        "Require a valid login on this route, like every other /api route, and return 401 without one. If it "
        "is meant for a partner system, give it its own credential (an API key or mutual TLS) and limit it to "
        "that caller. Add the route to the API inventory so it is documented, owned and tested."),
    "duplicate_refund": (
        "Make refunds idempotent: inside one database transaction, lock the booking, refuse with 409 if it is "
        "already refunded, and refuse any refund that would make total refunded exceed total paid. Accept an "
        "idempotency key so a retried request can't pay out twice."),
    "amount_validation": (
        "Never trust an amount sent by the client. Work out the price from the booking on the server; for a "
        "payment, refuse with 400 unless the amount equals the outstanding balance; for a refund, refuse any "
        "amount above what was paid minus what was already refunded."),
    "authorization": (
        "Check the caller's role on the server for every sensitive action: refunds need the admin role. Read "
        "the role from the token, not the request, and return 403 for any other role."),
    "weak_auth": (
        "Reject common and breached passwords when accounts are created or changed, and slow down or lock "
        "an account after repeated failed logins."),
}

EXPECTED = {
    "cross_agency_access": ("The other agency's request is refused (403 or 404) and no data comes back.",
                            "The record of another agency came back in full (HTTP 200)."),
    "zombie_ownership_check": ("The old version is gone (410) or refuses other agencies like the current one.",
                               "The old version returned another agency's booking (HTTP 200)."),
    "missing_auth": ("Without a login the request is refused with 401.",
                     "Without any login the endpoint returned the same data a logged-in user gets (HTTP 200)."),
    "duplicate_refund": ("The second refund is refused (409 already refunded).",
                         "The second refund was accepted and the booking shows more refunded than paid."),
    "amount_validation": ("A payment that doesn't match the price, or a refund above what was paid, is refused (400).",
                          "The server accepted the client's amount and recorded it."),
    "authorization": ("A sub-agent's refund is refused (403).", "The sub-agent's refund was accepted."),
    "weak_auth": ("Common passwords are refused.", "A common password was accepted."),
}

SETUP = {
    "cross_agency_access": "Log in as an admin of agency A and create a booking (the scanner used a synthetic booking), then log in as an admin of agency B.",
    "zombie_ownership_check": "Log in as an admin of agency A and create a booking (synthetic), then log in as an admin of agency B.",
    "missing_auth": "No login is needed. Send the request without any Authorization header.",
    "duplicate_refund": "Log in as an admin of agency A, create a booking priced ₹25,000 (synthetic) and pay it in full.",
    "amount_validation": "Log in as an admin of agency A and create a booking priced ₹25,000 (synthetic).",
    "authorization": "Log in as an admin of agency A, create and pay a booking (synthetic), then log in as a sub-agent of agency A.",
    "weak_auth": "Use the login form with each test account's username.",
}


def fix_for(test_type: str) -> str:
    return FIXES.get(test_type, "Review the evidence with the owning team and add a server-side check.")


def expected_actual(test_type: str) -> tuple[str, str]:
    return EXPECTED.get(test_type, ("The request is refused.", "The request was accepted."))


def steps(test_type: str, evidence: list[dict]) -> list[str]:
    """Numbered steps: the setup, then each verification request (masked) with what came back."""
    out = [SETUP.get(test_type, "Log in with a test account.")]
    for e in evidence:
        req, resp = e.get("request") or {}, e.get("response") or {}
        body = f" with body {_compact(req['body'])}" if req.get("body") else ""
        kf = resp.get("key_fields")
        got = f": {_compact(kf)}" if kf else ""
        who = req.get("as") or "no login"
        label = f" ({e['note']})" if e.get("note") else ""
        out.append(f"As {who}, send {req.get('method')} {req.get('path')}{body}{label} → HTTP {resp.get('status')}{got}")
    return out


def _compact(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {v[k]}" for k in v) + "}"
    return str(v)
