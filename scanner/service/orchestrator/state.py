"""What a scan carries from stage to stage."""
import operator
from typing import Annotated, TypedDict


class ScanState(TypedDict, total=False):
    scan_id: int
    event: dict                                        # the change event that started this scan
    stage_history: Annotated[list[str], operator.add]  # stages entered, in order (appended by each stage)
    retest_round: int                                  # how many times retest has looped back
    findings_to_retest: list[int]                      # vulnerability ids waiting for a re-check (empty for now)
    endpoint_count: int                                # endpoints recon put in the API inventory
    classification: dict                               # {active, zombie, shadow} counts from inventory
    plan: dict                                         # attack planner summary: planner, model, counts, dropped, skips
