"""The single choke point for every request the scanner sends to the target.

Nothing else in the scanner talks to the target directly. Direct calls (app.js
fetch, auth checks, version probes) use `TargetClient.send`, and the crawler's
browser hands each of its requests to the same method. So there is exactly one
place that decides whether a request may go out (`send` -> the safety gateway) and one place that
records it (the `audit_logs` table).

Phase 5: `send` runs the safety gateway (service/gateway) on every request:
kill switch, scope, credentials, high-risk approval, health pause, rate limit,
and writes one audit row per decision (allow / block / hold).
"""
import json
from urllib.parse import urljoin, urlsplit

import time

import httpx

from . import gateway
from .config import HTTP_TIMEOUT_SECONDS, TARGET_BASE_URL
from .db import AuditLog, SessionLocal, now
from .gateway import GatewayBlocked

_SECRET_HEADERS = {"authorization", "cookie", "set-cookie"}
_SECRET_FIELDS = {"password", "token"}
_MAX_BODY_CHARS = 2000


# Kept as a name for callers that catch it; every refusal is a GatewayBlocked.
OutOfScope = GatewayBlocked


def _redact_headers(headers: dict) -> dict:
    out = {}
    for k, v in (headers or {}).items():
        if k.lower() in _SECRET_HEADERS:
            out[k] = v.split(" ")[0] + " ***" if k.lower() == "authorization" else "***"
        else:
            out[k] = v
    return out


def _redact_body(body: bytes | None) -> str | None:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = {k: ("***" if k.lower() in _SECRET_FIELDS else v) for k, v in data.items()}
        text = json.dumps(data)
    except ValueError:
        pass
    return text[:_MAX_BODY_CHARS]


class SelfTestLeak(Exception):
    """A dry-run request passed the gate when it should have been blocked."""


class TargetClient:
    def __init__(self, scan_id: int | None, stage: str | None, transport: httpx.BaseTransport | None = None):
        self.scan_id = scan_id
        self.stage = stage
        self.base = TARGET_BASE_URL
        self._scope = urlsplit(self.base).netloc
        # follow_redirects=False: a redirect can never bounce us off the target.
        self._http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def url(self, path_or_url: str) -> str:
        return urljoin(self.base + "/", path_or_url)

    def in_scope(self, url: str) -> bool:
        return urlsplit(url).netloc == self._scope

    def _audit(self, method, url, headers, content, decision, reason=None, *, stage=None, status=None,
               sent=False, account=None, test_case_id=None, latency_ms=None, waited_ms=None, sent_at=None):
        with SessionLocal() as db:
            db.add(AuditLog(scan_id=self.scan_id, stage=stage or self.stage, method=method, url=url[:500],
                            request_headers_json=json.dumps(_redact_headers(headers)),
                            request_body=_redact_body(content), response_status=status,
                            decision=decision, reason=reason, sent=sent, account=account,
                            test_case_id=test_case_id, latency_ms=latency_ms, waited_ms=waited_ms,
                            sent_at=sent_at or now()))
            db.commit()

    def _transmit(self, method, url, headers, content):
        """The one line that puts bytes on the wire. Returns (response|None, latency_ms, error)."""
        t0 = time.monotonic()
        try:
            resp = self._http.request(method, url, headers=headers, content=content)
            return resp, int((time.monotonic() - t0) * 1000), None
        except httpx.HTTPError as exc:
            return None, int((time.monotonic() - t0) * 1000), exc

    def _probe(self):
        """Health check used while paused: GET / through the rate limit, audited."""
        url = self.url("/")
        gateway.rate_wait(self.scan_id)
        sent_at = now()
        resp, latency, err = self._transmit("GET", url, {}, None)
        status = resp.status_code if resp is not None else None
        self._audit("GET", url, {}, None, "allow", "health check while paused" + (f" ({err})" if err else ""),
                    stage="health_probe", status=status, sent=True, latency_ms=latency, sent_at=sent_at)
        return status, latency

    def send(self, method: str, path_or_url: str, *, headers: dict | None = None,
             json_body=None, content: bytes | None = None, test_case_id: int | None = None,
             dry_run: bool = False, _retry: bool = True) -> httpx.Response:
        url = self.url(path_or_url)
        method = method.upper()
        headers = dict(headers or {})
        if json_body is not None:
            content = json.dumps(json_body).encode()
            headers.setdefault("content-type", "application/json")
        audit = dict(test_case_id=test_case_id)

        # checks 1-4: kill switch, scope, credentials, high-risk approval
        d = gateway.check(self.scan_id, method, url, headers, content, test_case_id)
        if d.decision == "block":
            self._audit(method, url, headers, content, "block", d.reason, **audit)
            raise GatewayBlocked(d.reason)
        if dry_run:   # self-test: the gate path ran; never transmit
            self._audit(method, url, headers, content, "allow", "self-test request passed the gate (NOT sent)",
                        account=d.account, **audit)
            raise SelfTestLeak(f"{method} {url} was not blocked")

        # check 5: hold while the target is unhealthy
        waited = 0.0
        if gateway.paused_reason(self.scan_id):
            self._audit(method, url, headers, content, "hold", gateway.paused_reason(self.scan_id),
                        account=d.account, **audit)
            try:
                waited += gateway.hold_while_paused(self.scan_id, self._probe)
            except GatewayBlocked as exc:
                self._audit(method, url, headers, content, "block", exc.reason, account=d.account, **audit)
                raise
        # a last kill-switch look, then check 6: the rate-limit slot, taken right before sending
        h = gateway.halted_reason(self.scan_id)
        if not h:
            waited += gateway.rate_wait(self.scan_id)
            h = gateway.halted_now(self.scan_id)      # in-memory only: no delay after the slot
        if h:
            self._audit(method, url, headers, content, "block", f"kill switch: {h}", account=d.account, **audit)
            raise GatewayBlocked(f"kill switch: {h}")

        sent_at = now()
        resp, latency, err = self._transmit(method, url, headers, content)
        status = resp.status_code if resp is not None else None
        # 503 / connection refused: the target did not process the request, so it is safe to
        # hold it and send it again once the target is back (for any method).
        unavailable = status == 503 or isinstance(err, httpx.ConnectError)
        gateway.observe(self.scan_id, status, latency, unavailable)
        self._audit(method, url, headers, content, "allow", f"connection error: {err}" if err else None,
                    status=status, sent=True, account=d.account, latency_ms=latency,
                    waited_ms=int(waited * 1000), sent_at=sent_at, **audit)
        if resp is not None and status == 200 and method == "POST" and urlsplit(url).path == gateway.LOGIN_PATH:
            gateway.remember_token(self.scan_id, d.account, resp.content)

        # Retried once, after the target recovers: anything the target did not process (503 /
        # refused), and reads (GET/HEAD) that failed while it was struggling. Other failed
        # writes are returned as they are, never repeated.
        failed = status is None or status >= 500
        retryable = unavailable or (failed and method in ("GET", "HEAD"))
        if retryable and _retry and gateway.paused_reason(self.scan_id):
            return self.send(method, path_or_url, headers=headers, content=content,
                             test_case_id=test_case_id, _retry=False)
        if err:
            raise err
        return resp
