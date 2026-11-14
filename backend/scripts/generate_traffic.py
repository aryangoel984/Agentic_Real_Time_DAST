"""Generate a synthetic API-gateway traffic log (60 days).

Run from the backend/ folder:   python scripts/generate_traffic.py

What the log deliberately shows:
- The current endpoints get steady, realistic traffic.
- /api/internal/partner-details gets a small amount of traffic from an
  internal sync job -> it IS used, but is not in the frontend route list (SHADOW).
- /api/v1/bookings/{id} gets NO traffic at all -> still live but unused (ZOMBIE).

A fixed random seed and fixed end date make the file identical every run.
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
WINDOW_DAYS = 60
WINDOW_END = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
OUT = Path(__file__).resolve().parent.parent / "data" / "traffic_log.json"

BROWSER_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/132.0",
]
AGENCY_IPS = ["49.36.12.44", "49.36.12.91", "103.21.58.7", "103.21.58.33"]  # A: 49.x, B: 103.x
BOOKING_IDS = list(range(1001, 1009))
USER_IDS = [1, 2, 3, 4]

# (method, path template, relative weight, typical status choices)
ACTIVE_ROUTES = [
    ("POST", "/api/login",          10, [200] * 19 + [401]),
    ("GET",  "/api/search",         30, [200]),
    ("POST", "/api/bookings",        5, [201] * 9 + [422]),
    ("GET",  "/api/bookings/{bid}", 25, [200] * 19 + [404]),
    ("POST", "/api/payments",        5, [200] * 8 + [409]),
    ("POST", "/api/refunds",         2, [200] * 4 + [400]),
    ("GET",  "/api/users/{uid}",     6, [200]),
]


def main() -> None:
    rng = random.Random(SEED)
    start = WINDOW_END - timedelta(days=WINDOW_DAYS)
    entries = []
    weights = [r[2] for r in ACTIVE_ROUTES]

    for day in range(WINDOW_DAYS):
        day_start = start + timedelta(days=day)
        weekday = day_start.weekday()
        volume = rng.randint(25, 55) if weekday < 5 else rng.randint(8, 20)
        for _ in range(volume):
            method, tpl, _, statuses = rng.choices(ACTIVE_ROUTES, weights=weights)[0]
            # business hours IST (~03:30-14:30 UTC)
            ts = day_start + timedelta(hours=rng.uniform(3.5, 14.5))
            path = tpl.replace("{bid}", str(rng.choice(BOOKING_IDS))) \
                      .replace("{uid}", str(rng.choice(USER_IDS)))
            entries.append({
                "ts": ts.isoformat(timespec="seconds"),
                "method": method, "path": path, "status": rng.choice(statuses),
                "client_ip": rng.choice(AGENCY_IPS),
                "user_agent": rng.choice(BROWSER_UAS),
                "latency_ms": rng.randint(18, 240),
            })
        # Shadow route: nightly partner-sync job runs roughly every 3 days.
        if day % 3 == 0:
            ts = day_start + timedelta(hours=20, minutes=rng.randint(0, 20))
            entries.append({
                "ts": ts.isoformat(timespec="seconds"),
                "method": "GET", "path": "/api/internal/partner-details", "status": 200,
                "client_ip": "10.0.4.17", "user_agent": "partner-sync/1.4 (python-requests)",
                "latency_ms": rng.randint(30, 90),
            })
        # Zombie route /api/v1/bookings/{id}: intentionally never appears.

    entries.sort(key=lambda e: e["ts"])
    log = {
        "source": "synthetic API gateway access log (mock target)",
        "window_start": start.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "window_days": WINDOW_DAYS,
        "entry_count": len(entries),
        "entries": entries,
    }
    OUT.write_text(json.dumps(log, indent=1))
    print(f"Wrote {len(entries)} entries to {OUT}")


if __name__ == "__main__":
    main()
