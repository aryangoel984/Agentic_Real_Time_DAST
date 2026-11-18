"""Deterministic rule-based planner: endpoint facts -> catalogue test types.

Used when no LLM is configured, or when the LLM call fails. Same output shape
as the LLM planner: {endpoint_id: {"tests": [{test_type, reason}], "skip_reason": str|None}}.
"""


def plan_endpoint(e: dict) -> dict:
    tests: list[dict] = []
    method, path, purpose, cls = e["method"], e["path"], e.get("purpose"), e.get("classification")
    has_id = "{" in path
    roles = e.get("roles") or []
    admin_only = bool(roles) and all("admin" in r.lower() for r in roles)

    def add(test_type: str, reason: str) -> None:
        tests.append({"test_type": test_type, "reason": reason})

    if cls == "shadow":
        add("missing_auth", "This endpoint is used in live traffic but nothing links to it, so nobody has "
                            "checked it. First check whether it answers without any login.")
        if has_id:
            add("cross_agency_access", "It takes a record ID; check one agency cannot read another agency's record.")
    elif cls == "zombie":
        add("zombie_ownership_check", "This is an old version that is still switched on but unused. Old versions "
                                      "often miss checks added later; check it blocks access to another agency's records.")
        if e.get("auth_required") is False:
            add("missing_auth", "It answered without a login during discovery; confirm what it exposes.")
    else:
        if purpose == "refund":
            add("duplicate_refund", "Refunds move money; try refunding the same booking twice to see if it pays out again.")
            add("amount_validation", "The refund amount comes from the client; ask for more than was paid and check it is refused.")
            add("authorization", ("Only admins reached it during discovery; " if admin_only else "")
                + "try it as a sub-agent to confirm the admin-only rule is enforced by the server.")
        elif purpose == "payment":
            add("amount_validation", "The amount comes from the client; try paying less than the booking price "
                                     "(price tampering) and check the server refuses.")
            add("cross_agency_access", "It takes a booking ID in the body; try paying for another agency's booking.")
        elif purpose == "auth" and method == "POST":
            add("weak_auth", "This is the login endpoint; check for weak passwords and unlimited guessing.")
        elif method == "GET" and has_id:
            add("cross_agency_access", f"It returns a {purpose or 'record'} by ID; check an agency cannot read "
                                       "another agency's record by changing the ID.")
        elif purpose == "booking" and method == "POST":
            add("cross_agency_access", "It creates a booking with agency and user IDs in the body; try creating "
                                       "one for another agency.")
        if e.get("auth_required") is False and purpose != "auth":
            add("missing_auth", "It answered without a login during discovery; confirm what it exposes.")

    skip = None
    if not tests:
        skip = ("No approved test fits: it returns shared results with no per-agency record, "
                "and login is already enforced." if e.get("auth_required") else
                "No approved test fits this endpoint.")
    return {"tests": tests, "skip_reason": skip}


def plan(endpoints: list[dict]) -> dict[int, dict]:
    return {e["id"]: plan_endpoint(e) for e in endpoints}
