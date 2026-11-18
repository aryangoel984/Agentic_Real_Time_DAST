"""The approved test catalogue: the ONLY test types the scanner may ever plan.

Whatever a planner (rules or LLM) proposes is checked against this list in code.
Anything not here, or proposed for a method it doesn't apply to, is dropped.
The risk level is used by the safety gateway (Phase 5): high-risk tests move
money and will need approval before they run.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TestType:
    id: str
    name: str
    description: str
    methods: tuple[str, ...]
    risk: str          # low / medium / high
    vuln_class: str    # access_control / business_logic / authentication

    @property
    def requires_approval(self) -> bool:
        return self.risk == "high"


CATALOGUE: dict[str, TestType] = {t.id: t for t in [
    TestType("cross_agency_access", "Cross-agency access",
             "Can a user of agency A read or act on a record that belongs to agency B (IDOR)?",
             ("GET", "POST"), "medium", "access_control"),
    TestType("duplicate_refund", "Duplicate refund",
             "Can the same booking be refunded twice, paying the money out again?",
             ("POST",), "high", "business_logic"),
    TestType("amount_validation", "Amount validation / price tampering",
             "Does the server trust an amount sent by the client (pay less than the price, refund more than was paid)?",
             ("POST",), "high", "business_logic"),
    TestType("authorization", "Role authorization",
             "Can a lower role (sub-agent) perform an action meant only for a higher role (admin)?",
             ("GET", "POST"), "medium", "access_control"),
    TestType("missing_auth", "Missing authentication",
             "Does the endpoint answer without any login at all?",
             ("GET", "POST"), "low", "authentication"),
    TestType("zombie_ownership_check", "Zombie version ownership check",
             "Does an old, unused API version skip the ownership checks the current version enforces?",
             ("GET",), "medium", "access_control"),
    TestType("weak_auth", "Weak authentication",
             "Does login accept weak or default passwords, or allow unlimited guessing?",
             ("POST",), "medium", "authentication"),
]}


def describe_for_llm() -> list[dict]:
    return [{"test_type": t.id, "description": t.description, "applies_to_methods": list(t.methods)}
            for t in CATALOGUE.values()]
