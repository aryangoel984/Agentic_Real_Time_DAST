"""Discovery method B: read the portal's JavaScript bundle and pull out its API routes.

Comments are stripped first. A real production bundle is minified and has no
comments; the mock app.js has a developer comment that names routes the UI does
not call, and those must not count as "referenced by the code".
"""
import re

from .inventory import Inventory

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(^|\s)//[^\n]*")
_ROUTE_PAIR = re.compile(
    r"""method\s*:\s*["'](GET|POST|PUT|PATCH|DELETE)["']\s*,\s*path\s*:\s*["'](/api/[^"']*)["']""")
_API_STRING = re.compile(r"""["'`](/api/[^"'`\s]*)["'`]""")


def strip_comments(code: str) -> str:
    return _LINE_COMMENT.sub(r"\1", _BLOCK_COMMENT.sub("", code))


def discover(client, inv: Inventory, bundle_path: str, log) -> int:
    resp = client.send("GET", bundle_path)
    if resp.status_code != 200:
        log(f"app.js: could not fetch {bundle_path} (HTTP {resp.status_code})", "warn")
        return 0
    code = strip_comments(resp.text)
    pairs = _ROUTE_PAIR.findall(code)
    for method, path in pairs:
        inv.add(method, path, "app.js")
    loose = {p for p in _API_STRING.findall(code)} - {p for _, p in pairs}
    log(f"app.js: fetched {len(resp.text)} bytes, found {len(pairs)} routes in code: "
        + ", ".join(f"{m} {p}" for m, p in pairs))
    if loose:
        log(f"app.js: {len(loose)} other /api strings without a method (not added): {', '.join(sorted(loose))}")
    return len(pairs)
