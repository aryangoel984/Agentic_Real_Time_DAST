"""LLM planner on Groq: reasons about endpoints and returns a JSON test plan. It never acts.

What the model is given: endpoint descriptions (method, path template, parameter
names, roles that reached it, auth result, classification, purpose) and the
approved catalogue. What it is NOT given: the target's address, credentials,
tokens, booking data, response bodies, or any tool. It can only return text.

Its reply is untrusted: the caller validates every item against the catalogue.
"""
import json

from groq import BadRequestError, Groq

from ..config import (PLANNER_MODEL, PLANNER_REASONING_EFFORT, PLANNER_TEMPERATURE,
                      PLANNER_TIMEOUT_SECONDS)
from .catalogue import describe_for_llm

SYSTEM_PROMPT = """You are the attack planner inside an authorised security scanner for a B2B travel
booking platform (agencies book flights and hotels, take payments and issue refunds).
Your only job is to PLAN tests. You cannot send requests and nothing you write is executed directly.

For every endpoint you are given, choose which test types from the approved catalogue are worth
running, and give a one-sentence reason in plain English a non-expert can follow, tied to the
endpoint's facts (its purpose, which roles reached it, its classification, its parameters).
Plan only tests the facts justify; precision matters more than coverage. Do not re-test something
discovery already proved: if auth_basis starts with "verified" and auth_required is true, login is
already enforced, so do not plan missing_auth for it. Plan missing_auth only where auth is unknown
or was not required. Only plan duplicate_refund and amount_validation where money moves.
If no catalogue test fits an endpoint, give an empty test list and a short skip_reason.
If you believe a test outside the catalogue would be valuable, you may list it with your own
test_type name; such tests are reviewed separately and never run automatically.

Reply with JSON only, in exactly this shape:
{"plans": [{"endpoint_id": <int>, "tests": [{"test_type": "<id>", "reason": "<one sentence>"}],
            "skip_reason": <string or null>}]}"""


def _endpoint_for_llm(e: dict) -> dict:
    return {k: e.get(k) for k in ("id", "method", "path", "params", "auth_required", "auth_basis", "roles",
                                  "classification", "purpose", "discovered_via", "last_traffic_at")}


def plan(endpoints: list[dict]) -> tuple[dict, str]:
    """Return (raw parsed JSON from the model, model name). Raises on any failure."""
    client = Groq(timeout=PLANNER_TIMEOUT_SECONDS, max_retries=1)  # reads GROQ_API_KEY
    user = json.dumps({
        "approved_catalogue": describe_for_llm(),
        "roles_available": ["A-admin", "A-subagent", "B-admin", "B-subagent"],
        "endpoints": [_endpoint_for_llm(e) for e in endpoints],
    }, indent=1)
    kwargs = dict(
        model=PLANNER_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        temperature=PLANNER_TEMPERATURE,
        max_completion_tokens=8192,
        reasoning_effort=PLANNER_REASONING_EFFORT,
        stream=False,
    )
    try:
        resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    except BadRequestError as exc:
        # Some models don't accept JSON mode; ask again relying on the prompt alone.
        if "response_format" not in str(exc):
            raise
        resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("model reply contained no JSON object")
    return json.loads(text[start:end + 1]), PLANNER_MODEL
