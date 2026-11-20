"""A stand-in "failing target" for demonstrating the health monitor.

It sits between the scanner and the portal and forwards every request
(port 3099 -> http://localhost:3000). Its mode can be switched while it runs:

  ok    forward normally
  slow  wait 4 s before answering (latency problem)
  fail  answer 503 without forwarding (error problem)

It also counts every request it receives, so you can compare that number with
"Sent to target" in the dashboard's Safety panel (they should match: nothing
reaches the target without passing the gateway).

Run the proxy (from the project root):
    scanner/.venv/bin/python scanner/scripts/flaky_proxy.py
Switch mode from another terminal:
    scanner/.venv/bin/python scanner/scripts/flaky_proxy.py slow
    scanner/.venv/bin/python scanner/scripts/flaky_proxy.py ok
Point the scanner at it by starting the scanner API with TARGET_URL=http://localhost:3099
"""
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

LISTEN_PORT = 3099
UPSTREAM = "http://localhost:3000"
SLOW_SECONDS = 4.0
MODE_FILE = Path(__file__).resolve().parent.parent / "data" / "flaky_mode"
_SKIP = {"host", "content-length", "transfer-encoding", "connection", "content-encoding", "keep-alive"}

_count = 0
_count_lock = threading.Lock()
_client = httpx.Client(timeout=30, follow_redirects=False)


def mode() -> str:
    try:
        return MODE_FILE.read_text().strip() or "ok"
    except FileNotFoundError:
        return "ok"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self):
        global _count
        with _count_lock:
            _count += 1
            n = _count
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else None
        m = mode()
        if m == "slow":
            time.sleep(SLOW_SECONDS)
        if m == "fail":
            status, headers, content = 503, {"content-type": "text/plain"}, b"simulated outage (flaky_proxy fail mode)"
        else:
            headers_in = {k: v for k, v in self.headers.items() if k.lower() not in _SKIP}
            try:
                r = _client.request(self.command, UPSTREAM + self.path, headers=headers_in, content=body)
                status, content = r.status_code, r.content
                headers = {k: v for k, v in r.headers.items() if k.lower() not in _SKIP}
            except httpx.HTTPError as exc:
                status, headers, content = 502, {"content-type": "text/plain"}, str(exc).encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)
        print(f"#{n:<5} [{m:<4}] {self.command} {self.path} -> {status}", flush=True)

    do_GET = do_POST = do_HEAD = do_OPTIONS = do_PUT = do_PATCH = do_DELETE = _handle

    def log_message(self, *args):
        pass


def main():
    if len(sys.argv) > 1:
        m = sys.argv[1].lower()
        if m not in ("ok", "slow", "fail"):
            sys.exit("mode must be ok, slow or fail")
        MODE_FILE.parent.mkdir(exist_ok=True)
        MODE_FILE.write_text(m)
        print(f"flaky proxy mode set to: {m}")
        return
    print(f"flaky proxy on http://localhost:{LISTEN_PORT} -> {UPSTREAM} (mode: {mode()}); Ctrl+C to stop")
    srv = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print(f"\nrequests received in total: {_count}")


if __name__ == "__main__":
    main()
