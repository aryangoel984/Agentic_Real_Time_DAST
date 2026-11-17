"""Discovery method A: sign in to the portal as each test user and use it like a person would.

A headless Chromium browser (Playwright) clicks through the real flows. Every
request the browser makes is intercepted and sent through the shared
TargetClient instead of going out directly, so browser traffic passes the same
choke point (scope check + audit log) as everything else. Requests to any other
host are aborted.

Safe values: Pay is submitted for a booking that is already paid (the server
refuses with 409) and Refund asks for more than was paid (refused with 400), so
no money moves. Create booking is done for real for the user's own agency; it
adds one unpaid booking (reset with backend `python seed.py`).
"""
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from ..config import CRAWL_HEADED

_SKIP_REQUEST_HEADERS = {"host", "content-length", "accept-encoding", "connection"}
_SKIP_RESPONSE_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection",
                          "keep-alive"}
TIMEOUT_MS = 30_000
OVER_REFUND_AMOUNT = "99999999"


@dataclass
class ApiCall:
    method: str
    path: str
    query_keys: list[str]
    body_keys: list[str]
    sent_token: bool
    status: int

    @property
    def reached(self) -> bool:
        return self.status not in (401, 403)


@dataclass
class RoleResult:
    label: str
    calls: list[ApiCall] = field(default_factory=list)
    token: str | None = None          # kept in memory only, for later GET checks
    user_id: int | None = None
    notes: list[str] = field(default_factory=list)


def _body_keys(raw: bytes | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return sorted(data.keys()) if isinstance(data, dict) else []
    except ValueError:
        return []


def _is_api(url: str, method: str | None = None):
    def pred(resp) -> bool:
        p = urlsplit(resp.url).path
        return re.match(url, p) is not None and (method is None or resp.request.method == method)
    return pred


class CrawlError(RuntimeError):
    pass


def _crawl_role(browser, client, acct: dict) -> RoleResult:
    result = RoleResult(label=acct["label"])
    ctx = browser.new_context()

    @contextmanager
    def step(name: str):
        """Name the step in any error, plus the last API call the browser made."""
        try:
            yield
        except CrawlError:
            raise
        except Exception as exc:
            last = result.calls[-1] if result.calls else None
            hint = f"; last API call: {last.method} {last.path.split('?')[0]} -> {last.status}" if last else ""
            first_line = str(exc).splitlines()[0]
            raise CrawlError(f"crawl {acct['label']}, step '{name}': {first_line}{hint}") from exc

    def handle(route):
        req = route.request
        if not client.in_scope(req.url):
            route.abort()
            return
        headers = {k: v for k, v in req.all_headers().items()
                   if not k.startswith(":") and k.lower() not in _SKIP_REQUEST_HEADERS}
        body = req.post_data_buffer
        try:
            resp = client.send(req.method, req.url, headers=headers, content=body)
        except Exception:
            route.abort()
            return
        parts = urlsplit(req.url)
        if parts.path.startswith("/api/"):
            auth = headers.get("authorization")
            if auth:
                result.token = auth
            result.calls.append(ApiCall(
                method=req.method, path=parts.path + (f"?{parts.query}" if parts.query else ""),
                query_keys=sorted(parse_qs(parts.query).keys()), body_keys=_body_keys(body),
                sent_token=bool(auth), status=resp.status_code))
        route.fulfill(status=resp.status_code, body=resp.content,
                      headers={k: v for k, v in resp.headers.items()
                               if k.lower() not in _SKIP_RESPONSE_HEADERS})

    ctx.route("**/*", handle)
    # The dev server's live-reload websocket isn't part of the app; keep it off the wire.
    ctx.route_web_socket(re.compile(r".*"), lambda ws: None)

    page = ctx.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    base = client.base
    try:
        with step("sign in"):
            page.goto(base + "/login")
            page.fill("#username", acct["username"])
            page.fill("#password", acct["password"])
            with page.expect_response(_is_api(r"^/api/login$", "POST")) as login:
                page.get_by_role("button", name="Sign in").click()
            if login.value.status != 200:
                raise CrawlError(f"crawl {acct['label']}, step 'sign in': POST /api/login returned "
                                 f"HTTP {login.value.status}")
            page.wait_for_url("**/bookings")
            me = json.loads(page.evaluate("localStorage.getItem('travelhub_user') || '{}'"))
            result.user_id = me.get("id")

        booking_id = str(acct["sample_booking_id"])
        with step("look up booking"):
            lookup = page.locator("section", has_text="Look up a booking")
            lookup.locator("input").fill(booking_id)
            with page.expect_response(_is_api(r"^/api/bookings/\d+$")):
                lookup.get_by_role("button", name="Look up").click()

        with step("pay (already-paid booking, refused)"):
            pay = page.locator("section", has_text="Pay for a booking")
            pay.locator("input").first.fill(booking_id)
            with page.expect_response(_is_api(r"^/api/payments$", "POST")):
                pay.get_by_role("button", name="Pay", exact=True).click()

        with step("refund (over the paid amount, refused)"):
            refund = page.locator("section", has_text="Refund a booking")
            if refund.locator("form").count():
                refund.locator("input").nth(0).fill(booking_id)
                refund.locator("input").nth(1).fill(OVER_REFUND_AMOUNT)
                with page.expect_response(_is_api(r"^/api/refunds$", "POST")):
                    refund.get_by_role("button", name="Refund", exact=True).click()
            else:
                result.notes.append("refund form not offered to this role")

        with step("create booking"):
            create = page.locator("section", has_text="Create a booking")
            with page.expect_response(_is_api(r"^/api/bookings$", "POST")):
                create.get_by_role("button", name="Create booking").click()

        with step("search"):
            page.get_by_role("link", name="Search", exact=True).click()
            page.wait_for_url("**/search")
            with page.expect_response(_is_api(r"^/api/search$")):
                page.locator("form").get_by_role("button", name="Search").click()

        with step("look up own user"):
            page.get_by_role("link", name="Users", exact=True).click()
            page.wait_for_url("**/users")
            if result.user_id:
                page.locator("form input").fill(str(result.user_id))
            with page.expect_response(_is_api(r"^/api/users/\d+$")):
                page.locator("form").get_by_role("button", name="Look up").click()
    finally:
        ctx.close()
    return result


def crawl(client, accounts: list[dict], on_role_done) -> list[RoleResult]:
    """Crawl once per account; call on_role_done(result) after each so progress is saved."""
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not CRAWL_HEADED)
        try:
            for acct in accounts:
                res = _crawl_role(browser, client, acct)
                results.append(res)
                on_role_done(res)
        finally:
            browser.close()
    return results
