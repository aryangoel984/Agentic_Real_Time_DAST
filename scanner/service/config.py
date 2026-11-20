"""Scanner settings.

The scanner is a separate service from the target. It has its own database
(scanner/data/scanner.db) and never reads or writes the target's database.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Local secrets (e.g. GROQ_API_KEY) can live in scanner/.env, which git ignores.
# A value already set in the terminal wins over the file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("SCANNER_DATABASE_URL", f"sqlite:///{DATA_DIR / 'scanner.db'}")

# Stub stages finish instantly; this pause lets a human watch the pipeline move.
# Remove (set to 0) once stages do real work.
STUB_STAGE_DELAY_SECONDS = float(os.getenv("STUB_STAGE_DELAY_SECONDS", "1.5"))


# The ten pipeline stages, in order.
STAGES = [
    "change_detection",
    "recon",
    "inventory",
    "attack_planning",
    "safety_gateway",
    "execution",
    "verification",
    "triage",
    "reporting",
    "retest",
]

# ---------------- target (Phase 2) ----------------
# Everything the scanner knows about the target comes from this profile file:
# the public portal address and the test accounts it was given. The scanner
# reaches the target only over HTTP through that portal.
import json as _json

TARGET_PROFILE_PATH = Path(os.getenv(
    "TARGET_PROFILE", Path(__file__).resolve().parent.parent / "target_profile.json"))
TARGET_PROFILE = _json.loads(TARGET_PROFILE_PATH.read_text())
# TARGET_URL overrides the profile's portal address (used to point the scanner at the
# flaky proxy in scripts/flaky_proxy.py when demonstrating the health monitor).
TARGET_BASE_URL = os.getenv("TARGET_URL", TARGET_PROFILE["portal_url"]).rstrip("/")
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))
# Show the crawler's browser window instead of running it hidden (for demos/debugging).
CRAWL_HEADED = os.getenv("CRAWL_HEADED", "false").lower() in ("1", "true", "yes")

# ---------------- traffic log input (Phase 3) ----------------
# Access logs are a provided input (as TBO would hand over gateway/LB logs).
# The scanner reads only this file; it never reaches into the target to get it.
TRAFFIC_LOG_PATH = Path(os.getenv(
    "TRAFFIC_LOG_PATH", Path(__file__).resolve().parent.parent / "inputs" / "traffic_log.json"))
# An endpoint with no traffic in the last N days of the log counts as unused (zombie).
TRAFFIC_WINDOW_DAYS = int(os.getenv("TRAFFIC_WINDOW_DAYS", "30"))

# ---------------- attack planner (Phase 4) ----------------
# auto  = use Groq if GROQ_API_KEY is set, otherwise the rule-based planner
# groq  = always try Groq (falls back to rules if the call fails)
# rules = never call an LLM
PLANNER_PROVIDER = os.getenv("PLANNER_PROVIDER", "auto").lower()
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "openai/gpt-oss-120b")
PLANNER_TEMPERATURE = float(os.getenv("PLANNER_TEMPERATURE", "0.3"))
PLANNER_REASONING_EFFORT = os.getenv("PLANNER_REASONING_EFFORT", "medium")
PLANNER_TIMEOUT_SECONDS = float(os.getenv("PLANNER_TIMEOUT_SECONDS", "60"))

# ---------------- safety gateway (Phase 5) ----------------
# Every request to the target passes these checks in target_client.py (see service/gateway).
GATEWAY_MAX_RPS = float(os.getenv("GATEWAY_MAX_RPS", "5"))                  # requests per second, per scan
HEALTH_WINDOW = int(os.getenv("HEALTH_WINDOW", "10"))                       # judge health on the last N responses
HEALTH_MIN_SAMPLES = int(os.getenv("HEALTH_MIN_SAMPLES", "5"))              # don't judge on fewer than this
HEALTH_MAX_CONSECUTIVE_ERRORS = int(os.getenv("HEALTH_MAX_CONSECUTIVE_ERRORS", "3"))  # or this many errors in a row
HEALTH_MAX_ERROR_RATE = float(os.getenv("HEALTH_MAX_ERROR_RATE", "0.5"))    # pause at >= 50% 5xx/connection errors
HEALTH_MAX_LATENCY_MS = int(os.getenv("HEALTH_MAX_LATENCY_MS", "2000"))     # pause at median latency >= 2 s
HEALTH_PROBE_SECONDS = float(os.getenv("HEALTH_PROBE_SECONDS", "5"))        # while paused, check health this often
HEALTH_MAX_PAUSE_SECONDS = float(os.getenv("HEALTH_MAX_PAUSE_SECONDS", "120"))  # then stop the scan safely
APPROVAL_TIMEOUT_SECONDS = float(os.getenv("APPROVAL_TIMEOUT_SECONDS", "900"))  # undecided high-risk tests are denied
