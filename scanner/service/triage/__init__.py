"""The triage stage: turn verified findings into a short, ranked, owned list.

1. Merge duplicates: findings with the same root cause (same flaw, same resource, any API
   version) become one; the others are linked to it as "also affects".
2. Score severity by what the endpoint means to the business (rules.py).
3. Write a plain business-impact line and map each finding to an owner.
4. Mark critical and high findings for human review before escalation.
5. Match earlier scans so a recurring flaw shows when it was first seen.

Only verified findings are ranked; false positives and unverified ones stay out.
Triage reads the scanner's own database only. It sends nothing to the target.
"""
import json

from sqlalchemy import select

from ..db import ApiEndpoint, SessionLocal, TestCase, Vulnerability
from . import rules

STAGE = "triage"


def run_triage(scan_id: int, log) -> dict:
    with SessionLocal() as db:
        vulns = db.scalars(select(Vulnerability).where(Vulnerability.scan_id == scan_id,
                                                       Vulnerability.status == "verified")
                           .order_by(Vulnerability.id)).all()
        if not vulns:
            log("nothing to triage: no verified findings")
            return {"findings": 0, "merged": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "awaiting_review": 0}
        eps = {e.id: e for e in db.scalars(select(ApiEndpoint).where(ApiEndpoint.scan_id == scan_id))}
        tests = {t.id: t for t in db.scalars(select(TestCase).where(TestCase.scan_id == scan_id))}

        # 1. group by root cause
        groups: dict[str, list[Vulnerability]] = {}
        for v in vulns:
            ep, tc = eps[v.endpoint_id], tests[v.test_case_id]
            v.dedupe_key = rules.root_cause_key(tc.test_type, ep.method, ep.path)
            groups.setdefault(v.dedupe_key, []).append(v)

        merged, primaries = 0, []
        for key, items in groups.items():
            # the current (active) endpoint leads; zombie/shadow copies are listed under it
            items.sort(key=lambda v: (eps[v.endpoint_id].classification != "active", v.id))
            primary, dupes = items[0], items[1:]
            ep, tc = eps[primary.endpoint_id], tests[primary.test_case_id]
            for d in dupes:
                d.duplicate_of, d.rank, d.severity, d.review_status = primary.id, None, None, None
                d.severity_reason = f"merged into finding #{primary.id}: same root cause ({key})"
                merged += 1
                dep = eps[d.endpoint_id]
                log(f"merged #{d.id} ({dep.method} {dep.path}) into #{primary.id} ({ep.method} {ep.path}): same root cause")

            # 2. severity, from every place the flaw is reachable
            exposed = [eps[v.endpoint_id].classification for v in items
                       if eps[v.endpoint_id].classification in ("zombie", "shadow")]
            primary.severity_score, primary.severity, primary.severity_reason = rules.score(
                tc.test_type, ep.method, ep.path, ep.business_area, exposed)

            # 3. impact and owner
            also = [(eps[d.endpoint_id].method, eps[d.endpoint_id].path, eps[d.endpoint_id].classification or "?")
                    for d in dupes]
            checks = json.loads(primary.checks_json or "[]")
            primary.business_impact = rules.impact(tc.test_type, ep.method, ep.path, checks, also)
            primary.owner, primary.owner_source = rules.owner_for(ep.path, ep.business_area, ep.owner)

            # 4. human review before escalation
            primary.review_status = "awaiting_review" if primary.severity in rules.NEEDS_REVIEW else "not_needed"

            # 5. seen in an earlier scan?
            earlier = db.scalar(select(Vulnerability).where(Vulnerability.dedupe_key == key,
                                                            Vulnerability.scan_id < scan_id,
                                                            Vulnerability.status.in_(("verified", "fixed")),
                                                            Vulnerability.duplicate_of.is_(None))
                                .order_by(Vulnerability.scan_id))
            primary.first_seen_scan_id = earlier.first_seen_scan_id or earlier.scan_id if earlier else scan_id
            if earlier:
                primary.first_seen_at = earlier.first_seen_at
            primaries.append(primary)

        primaries.sort(key=lambda v: (rules.SEVERITY_ORDER[v.severity], -v.severity_score, v.id))
        for i, v in enumerate(primaries, 1):
            v.rank = i
            ep = eps[v.endpoint_id]
            seen = "new in this scan" if v.first_seen_scan_id == scan_id else f"first seen in scan {v.first_seen_scan_id}"
            log(f"#{i} {v.severity.upper()} {v.title} · owner {v.owner or 'unknown'}"
                f"{' (guessed)' if v.owner_source == 'guessed' else ''} · {seen}"
                f"{' · awaiting human review' if v.review_status == 'awaiting_review' else ''}",
                "warn" if v.severity in rules.NEEDS_REVIEW else "info")
        db.commit()

        counts = {s: sum(1 for v in primaries if v.severity == s) for s in rules.SEVERITY_ORDER}
        counts.update(findings=len(primaries), merged=merged,
                      awaiting_review=sum(1 for v in primaries if v.review_status == "awaiting_review"))
    log(f"triage done: {counts['findings']} finding(s) after merging {merged} duplicate(s): "
        f"{counts['critical']} critical, {counts['high']} high, {counts['medium']} medium, {counts['low']} low; "
        f"{counts['awaiting_review']} awaiting human review. No requests were sent")
    return counts
