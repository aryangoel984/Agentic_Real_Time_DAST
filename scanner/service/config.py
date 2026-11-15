"""Scanner settings.

The scanner is a separate service from the target. It has its own database
(scanner/data/scanner.db) and never reads or writes the target's database.
"""
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("SCANNER_DATABASE_URL", f"sqlite:///{DATA_DIR / 'scanner.db'}")

# Stub stages finish instantly; this pause lets a human watch the pipeline move.
# Remove (set to 0) once stages do real work.
STUB_STAGE_DELAY_SECONDS = float(os.getenv("STUB_STAGE_DELAY_SECONDS", "1.5"))

# How many times the retest stage may loop back to verification in one scan.
MAX_RETEST_ROUNDS = int(os.getenv("MAX_RETEST_ROUNDS", "1"))

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
