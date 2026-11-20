"""The safety gateway: the rules every request to the target must pass.

`TargetClient.send` (service/target_client.py) is the only code that talks to the
target, and it calls this module before and after every request:

  before:  1. kill switch      halted scan -> block
           2. scope            host, method, excluded paths -> block
           3. credentials      only the provided test accounts / tokens issued to them -> block
           4. high-risk test   a request for an unapproved high-risk test -> block
           5. health pause     target unhealthy -> hold until healthy (or stop safely)
           6. rate limit       wait for a slot under GATEWAY_MAX_RPS
  after:   observe status + latency (health monitor); remember tokens issued at login

Every decision is written to `audit_logs` by the client.
"""
import json
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ..config import (GATEWAY_MAX_RPS, HEALTH_MAX_CONSECUTIVE_ERRORS, HEALTH_MAX_ERROR_RATE, HEALTH_MAX_LATENCY_MS,
                      HEALTH_MAX_PAUSE_SECONDS, HEALTH_MIN_SAMPLES, HEALTH_PROBE_SECONDS,
                      HEALTH_WINDOW, TARGET_BASE_URL, TARGET_PROFILE)
from ..db import AgentLog, ScanRun, SessionLocal, TestCase, now

_SCOPE = TARGET_PROFILE.get("scope", {})
SCOPE_HOST = urlsplit(TARGET_BASE_URL).netloc
SCOPE_SCHEME = urlsplit(TARGET_BASE_URL).scheme
ALLOWED_METHODS = {m.upper() for m in _SCOPE.get("allowed_methods", ["GET", "POST", "HEAD", "OPTIONS"])}
EXCLUDED_PATHS = list(_SCOPE.get("excluded_paths", []))
LOGIN_PATH = _SCOPE.get("login_path", "/api/login")
TOKEN_FIELD = _SCOPE.get("token_field", "token")
ACCOUNTS = {a["username"]: a["label"] for a in TARGET_PROFILE["accounts"]}


class GatewayBlocked(Exception):
    """The gateway refused the request. Nothing was sent."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Decision:
    decision: str                 # allow / block
    reason: str | None = None
    account: str | None = None    # which test account the request uses, if any


@dataclass
class _ScanState:
    tokens: dict[str, str] = field(default_factory=dict)          # token -> account label
    window: deque = field(default_factory=lambda: deque(maxlen=HEALTH_WINDOW))  # (is_error, latency_ms)
    paused_reason: str | None = None
    paused_at: float | None = None
    last_probe: float = 0.0
    halted: str | None = None
    next_slot: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    probe_lock: threading.Lock = field(default_factory=threading.Lock)


_states: dict[int | None, _ScanState] = {}
_states_lock = threading.Lock()


def _state(scan_id) -> _ScanState:
    with _states_lock:
        return _states.setdefault(scan_id, _ScanState())


def _agent_log(scan_id, message: str, level: str = "info") -> None:
    if scan_id is None:
        return
    with SessionLocal() as db:   # file it under the stage that was running when it happened
        run = db.get(ScanRun, scan_id)
        stage = (run.current_stage if run else None) or "safety_gateway"
        db.add(AgentLog(scan_id=scan_id, stage=stage, level=level, message=f"[gateway] {message}"))
        db.commit()


# ---------------- kill switch ----------------

def halt(scan_id: int, by: str, reason: str) -> bool:
    """Stop all outgoing requests for a scan, at once. Returns False if already halted."""
    st = _state(scan_id)
    if st.halted:
        return False
    st.halted = reason
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run is not None:
            run.halted_at, run.halted_by, run.halt_reason = now(), by, reason
            run.paused_reason = None
            db.commit()
    _agent_log(scan_id, f"HALTED: {reason}. Every further request to the target is blocked.", "error")
    return True


def halted_reason(scan_id) -> str | None:
    st = _state(scan_id)
    if st.halted is None and scan_id is not None:
        with SessionLocal() as db:   # also honour a halt recorded before a restart
            run = db.get(ScanRun, scan_id)
            if run is not None and run.halted_at is not None:
                st.halted = run.halt_reason or "scan halted"
    return st.halted


def halted_now(scan_id) -> str | None:
    """In-memory kill-switch check (no database read)."""
    return _state(scan_id).halted


# ---------------- checks 1-4 ----------------

def _bearer(headers: dict) -> str | None:
    for k, v in headers.items():
        if k.lower() == "authorization" and v:
            return v.split(" ", 1)[1].strip() if v.lower().startswith("bearer ") else v.strip()
    return None


def check(scan_id, method: str, url: str, headers: dict, body: bytes | None,
          test_case_id: int | None) -> Decision:
    # 1. kill switch
    h = halted_reason(scan_id)
    if h:
        return Decision("block", f"kill switch: {h}")

    # 2. scope
    parts = urlsplit(url)
    if parts.netloc != SCOPE_HOST or parts.scheme != SCOPE_SCHEME:
        return Decision("block", f"out of scope: only {SCOPE_SCHEME}://{SCOPE_HOST} may be contacted, "
                                 f"not {parts.scheme}://{parts.netloc}")
    if method not in ALLOWED_METHODS:
        return Decision("block", f"method {method} is not allowed (allowed: {', '.join(sorted(ALLOWED_METHODS))})")
    for p in EXCLUDED_PATHS:
        if parts.path.startswith(p):
            return Decision("block", f"path {parts.path} is excluded from scope ({p})")

    # 3. credentials
    account = None
    if method == "POST" and parts.path == LOGIN_PATH:
        try:
            username = json.loads(body or b"{}").get("username")
        except (ValueError, AttributeError):
            username = None
        if username not in ACCOUNTS:
            return Decision("block", f"login as {username!r} refused: not one of the provided test accounts")
        account = ACCOUNTS[username]
    token = _bearer(headers)
    if token:
        label = _state(scan_id).tokens.get(token)
        if label is None:
            return Decision("block", "unknown token: it was not issued to a provided test account in this scan")
        account = label

    # 4. high-risk test approval
    if test_case_id is not None:
        with SessionLocal() as db:
            tc = db.get(TestCase, test_case_id)
            if tc is None or tc.scan_id != scan_id:
                return Decision("block", f"test case #{test_case_id} is not part of this scan")
            if tc.requires_approval and tc.status != "approved":
                return Decision("block", f"high-risk test #{tc.id} ({tc.test_type}) is not approved "
                                         f"(status: {tc.status})")
    return Decision("allow", None, account)


# ---------------- check 5: health monitor ----------------

def _judge(st: _ScanState) -> str | None:
    recent = list(st.window)[-HEALTH_MAX_CONSECUTIVE_ERRORS:]
    if len(recent) == HEALTH_MAX_CONSECUTIVE_ERRORS and all(e for e, _ in recent):
        return f"target unhealthy: the last {len(recent)} responses in a row were errors"
    if len(st.window) < HEALTH_MIN_SAMPLES:
        return None
    errors = sum(1 for e, _ in st.window if e)
    rate = errors / len(st.window)
    median = statistics.median(l for _, l in st.window)
    if rate >= HEALTH_MAX_ERROR_RATE:
        return f"target unhealthy: {errors} of the last {len(st.window)} responses were errors"
    if median >= HEALTH_MAX_LATENCY_MS:
        return f"target unhealthy: median latency {median / 1000:.1f} s over the last {len(st.window)} responses"
    return None


def _set_paused(scan_id, reason: str | None) -> None:
    if scan_id is None:
        return
    with SessionLocal() as db:
        run = db.get(ScanRun, scan_id)
        if run is not None:
            run.paused_reason = reason
            db.commit()


def observe(scan_id, status: int | None, latency_ms: int, unavailable: bool = False) -> None:
    """Record one response (status None = connection error). May pause the scan.
    `unavailable` (503 or connection refused) means the target is down right now: pause at once."""
    st = _state(scan_id)
    with st.lock:
        st.window.append((status is None or status >= 500, latency_ms))
        if st.paused_reason:
            return
        reason = (f"target unavailable ({'HTTP 503' if status == 503 else 'connection refused'})"
                  if unavailable else _judge(st))
        if reason:
            st.paused_reason, st.paused_at, st.last_probe = reason, time.monotonic(), time.monotonic()
    if reason:
        _set_paused(scan_id, reason)
        _agent_log(scan_id, f"PAUSED: {reason}. Requests are held; checking health every "
                            f"{HEALTH_PROBE_SECONDS:g} s", "warn")


def paused_reason(scan_id) -> str | None:
    return _state(scan_id).paused_reason


def hold_while_paused(scan_id, probe) -> float:
    """Block the caller while the scan is paused. `probe()` -> (status|None, latency_ms)
    sends one health check. Returns seconds waited. Raises GatewayBlocked on halt/timeout."""
    st = _state(scan_id)
    if not st.paused_reason:
        return 0.0
    start = time.monotonic()
    while st.paused_reason:
        h = halted_reason(scan_id)
        if h:
            raise GatewayBlocked(f"kill switch: {h}")
        if time.monotonic() - (st.paused_at or start) > HEALTH_MAX_PAUSE_SECONDS:
            halt(scan_id, "health_monitor", f"target stayed unhealthy for over "
                                            f"{HEALTH_MAX_PAUSE_SECONDS:g} s; scan stopped safely")
            raise GatewayBlocked(f"kill switch: {st.halted}")
        if st.probe_lock.acquire(blocking=False):      # one health check at a time
            try:
                if st.paused_reason and time.monotonic() - st.last_probe >= HEALTH_PROBE_SECONDS:
                    st.last_probe = time.monotonic()
                    status, latency = probe()
                    healthy = status is not None and status < 500 and latency < HEALTH_MAX_LATENCY_MS
                    if healthy:
                        with st.lock:
                            st.window.clear()
                            st.paused_reason, st.paused_at = None, None
                        _set_paused(scan_id, None)
                        _agent_log(scan_id, f"RESUMED: health check answered {status} in {latency} ms")
            finally:
                st.probe_lock.release()
        time.sleep(0.25)
    return time.monotonic() - start


# ---------------- check 6: rate limit ----------------

def rate_wait(scan_id) -> float:
    """Reserve the next send slot (at most GATEWAY_MAX_RPS per second) and wait for it."""
    st = _state(scan_id)
    interval = 1.0 / GATEWAY_MAX_RPS
    with st.lock:
        t = time.monotonic()
        slot = max(t, st.next_slot)
        st.next_slot = slot + interval
    wait = slot - t
    if wait > 0:
        time.sleep(wait)
    with st.lock:   # space the next send from when this one really goes out
        st.next_slot = max(st.next_slot, time.monotonic() + interval)
    return wait


# ---------------- after a login ----------------

def remember_token(scan_id, account: str | None, response_body: bytes) -> None:
    """A provided test account just signed in: its token becomes usable in this scan."""
    if not account:
        return
    try:
        token = json.loads(response_body).get(TOKEN_FIELD)
    except (ValueError, AttributeError):
        return
    if token:
        _state(scan_id).tokens[str(token)] = account


def reset(scan_id) -> None:
    """Forget in-memory gateway state for a scan (used by the check script)."""
    with _states_lock:
        _states.pop(scan_id, None)
