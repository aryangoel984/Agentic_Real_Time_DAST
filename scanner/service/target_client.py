"""The single choke point for every request the scanner sends to the target.

Nothing else in the scanner talks to the target directly. Direct calls (app.js
fetch, auth checks, version probes) use `TargetClient.send`, and the crawler's
browser hands each of its requests to the same method. So there is exactly one
place that decides whether a request may go out (`_gate`) and one place that
records it (the `audit_logs` table).

Phase 2: `_gate` only enforces scope (the target portal's host). Phase 5 puts
the safety gateway in `_gate`.
"""
import json
from urllib.parse import urljoin, urlsplit

import httpx

from .config import HTTP_TIMEOUT_SECONDS, TARGET_BASE_URL
from .db import AuditLog, SessionLocal

_SECRET_HEADERS = {"authorization", "cookie", "set-cookie"}
_SECRET_FIELDS = {"password", "token"}
_MAX_BODY_CHARS = 2000


class OutOfScope(Exception):
    """Raised when a request would leave the target host. Nothing is sent."""


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


class TargetClient:
    def __init__(self, scan_id: int | None, stage: str | None):
        self.scan_id = scan_id
        self.stage = stage
        self.base = TARGET_BASE_URL
        self._scope = urlsplit(self.base).netloc
        # follow_redirects=False: a redirect can never bounce us off the target.
        self._http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False)

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

    def _gate(self, method: str, url: str) -> str | None:
        """Return None to allow the request, or a reason to block it."""
        if not self.in_scope(url):
            return f"out of scope: only {self._scope} may be contacted"
        return None

    def send(self, method: str, path_or_url: str, *, headers: dict | None = None,
             json_body=None, content: bytes | None = None) -> httpx.Response:
        url = self.url(path_or_url)
        method = method.upper()
        headers = dict(headers or {})
        if json_body is not None:
            content = json.dumps(json_body).encode()
            headers.setdefault("content-type", "application/json")

        reason = self._gate(method, url)
        row = AuditLog(scan_id=self.scan_id, stage=self.stage, method=method, url=url[:500],
                       request_headers_json=json.dumps(_redact_headers(headers)),
                       request_body=_redact_body(content), allowed=reason is None,
                       block_reason=reason)
        try:
            if reason:
                raise OutOfScope(reason)
            resp = self._http.request(method, url, headers=headers, content=content)
            row.response_status = resp.status_code
            return resp
        finally:
            with SessionLocal() as db:
                db.add(row)
                db.commit()
