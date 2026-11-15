"""Send a sample "something changed" event to the scanner, to trigger a scan by hand.

Examples (from the project root):
  scanner/.venv/bin/python scanner/scripts/fire_event.py
  scanner/.venv/bin/python scanner/scripts/fire_event.py --endpoint /api/payments --method POST --version v3

Uses only the Python standard library, so it runs with any Python 3.
"""
import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


def main() -> None:
    p = argparse.ArgumentParser(description="Fire a deploy event at the scanner.")
    p.add_argument("--scanner", default="http://localhost:9000", help="scanner base URL")
    p.add_argument("--event", default="API_DEPLOYED")
    p.add_argument("--endpoint", default="/api/refunds")
    p.add_argument("--method", default="POST")
    p.add_argument("--version", default="v2")
    args = p.parse_args()

    payload = {
        "event": args.event,
        "endpoint": args.endpoint,
        "method": args.method,
        "version": args.version,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    req = urllib.request.Request(f"{args.scanner}/events/deploy", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            body = json.loads(res.read())
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach the scanner at {args.scanner}: {exc}. Is it running?")
    print("Sent:", json.dumps(payload))
    print(f"Scan #{body['scan_id']} created (status: {body['status']}). Watch it at http://localhost:3001/?scan={body['scan_id']}")


if __name__ == "__main__":
    main()
