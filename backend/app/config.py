"""Fix switches for the five planted vulnerabilities.

Every switch defaults to OFF, which means the bug is LIVE. Turning a switch
on (e.g. `FIX_IDOR=true uvicorn app.main:app --port 8000`) closes that one
bug without touching any code. This is what makes the later
"fix -> retest" demo possible.
"""
import os


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


FIX_IDOR = _flag("FIX_IDOR")                    # Bug 1: cross-agency booking read
FIX_DOUBLE_REFUND = _flag("FIX_DOUBLE_REFUND")  # Bug 2: same booking refunded twice
FIX_PRICE_TAMPER = _flag("FIX_PRICE_TAMPER")    # Bug 3: client-chosen payment amount
FIX_ZOMBIE = _flag("FIX_ZOMBIE")                # Bug 4: old /api/v1/ route still live
FIX_SHADOW_AUTH = _flag("FIX_SHADOW_AUTH")      # Bug 5: internal route with no login


def active_fixes() -> dict:
    return {
        "FIX_IDOR": FIX_IDOR,
        "FIX_DOUBLE_REFUND": FIX_DOUBLE_REFUND,
        "FIX_PRICE_TAMPER": FIX_PRICE_TAMPER,
        "FIX_ZOMBIE": FIX_ZOMBIE,
        "FIX_SHADOW_AUTH": FIX_SHADOW_AUTH,
    }
