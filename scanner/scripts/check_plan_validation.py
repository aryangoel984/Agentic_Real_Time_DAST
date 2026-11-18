"""Prove the catalogue guard works, without any API key or network.

Feeds the validator a fake LLM answer that mixes approved tests with things the
scanner must never accept, and prints what is kept and what is dropped.

Run from the project root:
    scanner/.venv/bin/python scanner/scripts/check_plan_validation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from service.planner import validate  # noqa: E402

ENDPOINTS = {
    1: {"id": 1, "method": "POST", "path": "/api/refunds"},
    2: {"id": 2, "method": "GET", "path": "/api/bookings/{id}"},
}

FAKE_LLM_REPLY = {"plans": [
    {"endpoint_id": 1, "tests": [
        {"test_type": "duplicate_refund", "reason": "Refund the same booking twice."},
        {"test_type": "amount_validation", "reason": "Ask for more than was paid."},
        {"test_type": "rate_limit_test", "reason": "Send many refunds quickly."},           # not in catalogue
        {"test_type": "delete_all_bookings", "reason": "Wipe the table."},                  # not in catalogue
        {"test_type": "duplicate_refund", "reason": "Same test again."},                    # duplicate
    ]},
    {"endpoint_id": 2, "tests": [
        {"test_type": "cross_agency_access", "reason": "Read another agency's booking by ID."},
        {"test_type": "duplicate_refund", "reason": "Refund via the lookup."},             # wrong method (GET)
        {"test_type": "missing_auth", "reason": ""},                                        # no reason
    ]},
    {"endpoint_id": 99, "tests": [{"test_type": "missing_auth", "reason": "Unknown endpoint."}]},  # not in scan
]}

plans, dropped = validate(FAKE_LLM_REPLY, ENDPOINTS, "groq")
print("KEPT")
for eid, p in plans.items():
    for t in p["tests"]:
        print(f"  {ENDPOINTS[eid]['method']} {ENDPOINTS[eid]['path']}: {t['test_type']}")
print("DROPPED")
for d in dropped:
    print(f"  {d}")
