"""Render the report (built in reporting/__init__.py) as Markdown, for download or pasting into a tracker."""


def _dur(s) -> str:
    if s is None:
        return "n/a"
    m, sec = divmod(int(round(s)), 60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"


def ticket_markdown(t: dict) -> str:
    owner = f"{t['owner'] or 'unknown'}{' (guessed)' if t['owner_source'] == 'guessed' else ''}"
    lines = [
        f"**Severity:** {t['severity']} ({t['priority']}) · **Owner:** {owner} · **Status:** "
        + {"ready": "Ready to raise", "draft": "Draft, waiting for human review",
           "resolved": f"Resolved: fixed, retest passed ({t['fixed_at']})"}[t["escalation"]],
        "",
        f"**Business impact.** {t['business_impact']}",
        "",
        f"**Why {t['severity']}.** {t['severity_reason']}",
        "",
        "**Affected endpoints**",
        *[f"- `{a['method']} {a['path']}` ({a['classification'] or 'unclassified'})" for a in t["affected"]],
        "",
        "**Steps to reproduce** (test accounts and synthetic data only; tokens masked)",
        *[f"{i}. {s}" for i, s in enumerate(t["steps"], 1)],
        "",
        f"**Expected:** {t['expected']}",
        f"**Actual:** {t['actual']}",
        "",
        "**How it was verified**",
        *[f"- {'✓' if c['passed'] else '✗' if c['passed'] is False else '?'} {c['name']}: {c['detail']}" for c in t["checks"]],
        "",
        f"**Suggested fix.** {t['fix']}",
    ]
    if t["review"]:
        lines += ["", f"**Review.** {t['review']}"]
    if t["retests"]:
        lines += ["", "**Retest history**",
                  *[f"- {h['at']} ({h['triggered_by']}): {h['result'].replace('_', ' ')}: {h['reason']}" for h in t["retests"]]]
    if t["first_seen_scan_id"] is not None:
        lines += [f"**First seen:** scan {t['first_seen_scan_id']}"]
    return "\n".join(lines)


def report_markdown(r: dict) -> str:
    s, trig, sp, sf = r["summary"], r["trigger"], r["speed"], r["safety"]
    change = " ".join(x for x in (trig["event"], trig["method"], trig["endpoint"], trig["version"]) if x) or "manual scan"
    out = [
        f"# Security scan report: scan {r['scan']['id']}",
        "",
        "## Summary",
        "",
        f"- **What changed:** {change} (received {trig['received_at']})",
        f"- **Time from the change to the first verified finding:** {_dur(sp['change_to_first_verified_s'])}"
        f" · whole scan {_dur(r['scan']['duration_s'])} · status {r['scan']['status']}",
        f"- **Findings:** {s['open']} open ("
        + (", ".join(f"{n} {k}" for k, n in s["by_severity"].items() if n) or "none") + ")"
        + f" · {s['ready']} ready to raise · {s['draft']} waiting for human review · {s['fixed']} fixed",
        f"- **Noise removed:** {s['merged_duplicates']} duplicate(s) merged · {s['false_positives']} false positive(s) "
        f"rejected · {s['unverified']} unverified",
        f"- **API inventory:** {s['endpoints']} endpoints ("
        + ", ".join(f"{n} {k}" for k, n in s["inventory"].items()) + ")",
        "",
    ]
    if s["top_risks"]:
        out += ["**Top risks**", "", *[f"1. {x}" for x in s["top_risks"]], ""]

    out += ["## Findings", ""]
    open_t = [t for t in r["tickets"] if t["escalation"] != "resolved"]
    done_t = [t for t in r["tickets"] if t["escalation"] == "resolved"]
    if not open_t:
        out += ["No open findings in this scan.", ""]
    for t in open_t:
        out += [f"### {t['key']} · {t['title']}", "", ticket_markdown(t), ""]
    if done_t:
        out += ["## Resolved (fixed and retested)", ""]
        for t in done_t:
            out += [f"### {t['key']} · {t['title']}", "", ticket_markdown(t), ""]

    out += ["## Zombie and shadow endpoints", ""]
    if not r["inventory"]:
        out += ["None found.", ""]
    for e in r["inventory"]:
        out += [
            f"### `{e['method']} {e['path']}` ({e['classification']})",
            "",
            f"- **Last real traffic:** {e['last_traffic_at'] or 'none in the log'}"
            + (f" · {e['hits_in_window']} call(s) in the window" if e["hits_in_window"] is not None else "")
            + (f" · callers: {', '.join(e['callers'])}" if e["callers"] else ""),
            f"- **Reachable without a login:** {e['reachable_without_login']} ({e['reachable_basis']})",
            f"- **Data it exposes:** {', '.join(e['data_exposed']) if e['data_exposed'] else 'none seen in a successful response'}",
            f"- **Compared with the current version:** {e['compared_with_current']}",
            f"- **Vulnerabilities:** {'; '.join(e['vulnerabilities']) if e['vulnerabilities'] else 'none verified'}",
            f"- **Likely owner:** {e['owner'] or 'unknown'}",
            f"- **Recommendation:** {e['recommendation'] or 'n/a'}",
            "",
        ]

    c = r["coverage"]
    out += ["## Tested and found clean", ""]
    out += [f"- {x['test']} on `{x['endpoint']}`: {x['result']}" for x in c["clean"]] or ["- none"]
    if c["false_positives"]:
        out += ["", "**Rejected as false positives**", "", *[f"- {x['title']}: {x['reason']}" for x in c["false_positives"]]]
    if c["unverified"]:
        out += ["", "**Not proven (left for a human)**", "", *[f"- {x['title']}: {x['reason']}" for x in c["unverified"]]]
    if c["not_run"]:
        out += ["", "**Not run**", "", *[f"- {x['test']} on `{x['endpoint']}`: {x['result']}" for x in c["not_run"]]]

    out += [
        "", "## Safety record", "",
        f"- **Requests sent to the target:** {sf['sent']} (by stage: "
        + ", ".join(f"{k} {v}" for k, v in sf["by_stage"].items()) + ")",
        f"- **Peak rate:** {sf['max_per_second']} per second (cap {sf['rate_cap']:g})",
        f"- **Blocked by the gateway during the scan:** {sf['blocked']}"
        + "".join(f"\n  - {b['reason']} ({b['count']})" for b in sf["blocked_reasons"]),
        f"- **Gateway self-test:** {sf['self_test_blocked']} deliberately bad requests, all blocked and none sent"
        + "".join(f"\n  - {b['reason']}" for b in sf["self_test_reasons"]),
        f"- **Held for human approval:** {sf['held_for_approval']} · **held while the target struggled:** {sf['held_by_health_monitor']}",
        f"- **Stopped early:** {'yes, by ' + sf['halted_by'] + ': ' + (sf['halt_reason'] or '') if sf['halted_by'] else 'no'}",
        "- **Human decisions:**" + ("".join(f"\n  - {d['at']}: {d['decision']}" for d in sf["human_decisions"]) or " none"),
        "",
        "_Every request went through the safety gateway and is in the scan's audit log. Only the provided test "
        "accounts and synthetic bookings were used; passwords and tokens are masked throughout._",
        "",
    ]
    return "\n".join(out)

