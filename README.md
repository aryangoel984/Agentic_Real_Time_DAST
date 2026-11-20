# Agentic Real-Time DAST — TBO Voyage Hack 4.0

We are building automated security agents that watch a travel booking platform as it changes, find security holes the way a real attacker would (especially logic mistakes like one agency reading another's bookings, or paying ₹100 for a ₹25,000 trip), prove which problems are real, and report them to the right team within minutes. So far we have built two separate things. The first is the practice target (Phase 0): a small pretend B2B travel platform, with a clickable agency portal, two agencies, test accounts, bookings, payments and refunds, and exactly five deliberately hidden security holes, so our agents have a place to practise where we already know the right answers. The second is the scanner: an independent service that hears "something changed", starts a scan, walks it through a ten-stage pipeline, records everything in its own database, and shows it live on a "Security Command Center" dashboard (Phase 1). Its first real stage is recon (Phase 2): it explores the target only from the outside, by signing in to the portal as each test user and clicking through the real flows, reading the portal's JavaScript, and trying older API versions, and it builds an inventory of every API it can see, with parameters, login requirement and which users can reach it. The next stage, inventory (Phase 3), compares that list with the platform's access logs (a file handed to the scanner, as a client would provide) and labels every API active, zombie (switched on but unused) or shadow (used but invisible from outside), with a recommended action for each. Attack planning (Phase 4) then decides which approved tests each API needs and why: an AI model on Groq suggests a plan when a free Groq key is set, a rule-based planner does it otherwise, and every suggestion is checked against a fixed catalogue of approved test types in code. The AI only plans; it is given no tools or target access, and nothing is executed yet. Every request the scanner sends passes the safety gateway (Phase 5), a single checkpoint in code that enforces scope, allows only the provided test accounts, limits speed, pauses when the target struggles, holds high-risk money tests until a human approves them on the dashboard, offers a kill switch, and records every decision in a masked audit log. Execution (Phase 6) then runs each cleared or approved test through that gateway, using synthetic bookings the scanner creates itself, and records a raw result (suspicious or clean) with minimal masked evidence. On the practice target this flags exactly the five planted holes and comes back clean on six properly-secured behaviours; Verification (Phase 7) then tries to disprove each suspicious result: it must reproduce on fresh synthetic data and pass an independent control check (matching the owner's copy, refusing a made-up ID, or reading the booking back to see the money really moved). Survivors become verified findings; the rest are recorded as false positives with the reason. Triage (Phase 8) turns the verified findings into a short ranked list: the same flaw found on several API versions is merged into one finding, each finding gets a severity from what is at stake for the business (money, customer data, partner data), who can exploit it and whether it sits on an unmonitored zombie or shadow endpoint, plus a plain business-impact line with the test's real numbers and an owning team. Critical and high findings wait for a human to confirm or change their severity on the dashboard, and a flaw seen in an earlier scan shows when it was first seen. Triage sends nothing to the target. Reporting (Phase 9) turns that list into a report a team can act on: a summary with the time from the change to the first verified finding, one ticket per finding (severity, owner, business impact, steps to reproduce from the masked evidence, expected versus actual, the checks that proved it, a suggested fix, and whether it is ready to raise or still waiting for human review), the zombie and shadow endpoints with everything the brief asks for each, the tests that came back clean, and the safety record. It opens as a printable page and downloads as Markdown or as tracker-ready tickets (JSON); it is rebuilt from the database on every open, so a review shows up at once. Retest (Phase 10) closes the loop: after a fix is deployed, a Retest button on each open finding re-runs its proof through the safety gateway, and every new scan automatically retests open findings from earlier scans (a flaw the new scan finds again simply stays open). A finding is closed as fixed only if the attack now fails on fresh data and the rightful use still works, so a "fix" that breaks the endpoint for everyone is not accepted; a merged finding fixed in only one place is reported as partly fixed. Every attempt is kept in the finding's retest history and shown in the report, where fixed tickets move to a Resolved section. All ten stages now do real work. See `docs/PHASE_LOG.md` for the full plain-English story.

## Project layout

```
backend/    THE TARGET: FastAPI mock travel platform (port 8000), SQLite database, traffic log
frontend/   THE TARGET: Next.js + Tailwind agency portal (port 3000); public/app.js is the route manifest
scanner/    THE SCANNER: independent service with its own venv, database and dashboard
  service/    FastAPI API (port 9000): deploy-event intake + LangGraph orchestrator
    recon/      discovery agent: portal crawl (Playwright), app.js parsing, version probing
    target_client.py  the single choke point every request to the target goes through
    gateway/    safety gateway: scope, credentials, approvals, health pause, rate limit, kill switch, self-test
    executor/   execution agents: one plain-code executor per test type, synthetic bookings, evidence
    verifier/   verification: repeat on fresh data + control check per suspicious result
    triage/     triage: merge duplicates, business severity, impact line, owner, human review
    reporting/  report: summary, tickets with steps + fix, zombie/shadow detail, safety record; Markdown + JSON
    retest/     retest: attack must now fail + rightful use must still work; manual button and every new scan
    inventory/  classifier: labels endpoints active / zombie / shadow against the traffic log
    planner/    attack planner: approved test catalogue, rule-based planner, Groq LLM planner, guard
  target_profile.json  what the scanner is told about the target: portal URL, test accounts
  inputs/     provided inputs: traffic_log.json (access logs handed to the scanner)
  scripts/    fire_event.py (send a deploy event), check_plan_validation.py, check_gateway.py,
              flaky_proxy.py (a stand-in failing target for the health-monitor demo)
  dashboard/  Next.js + Tailwind "Security Command Center" (port 3001)
docs/       PHASE_LOG.md (plain-English project log), PLANTED_BUGS.md (dev-only answer key)
```

## Run it

Requires Python 3.11+ and Node 20+. You need two Terminal tabs, both starting from the project root.

**One-time setup**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install
```

**Tab 1: backend (API on port 8000)**

```bash
source .venv/bin/activate
cd backend
python seed.py                         # reset database to known state
uvicorn app.main:app --port 8000
```

**Tab 2: frontend (portal on port 3000)**

```bash
cd frontend
npm run dev
```

Then open **http://localhost:3000** and sign in. The portal forwards every `/api/...` call to the backend, so you only ever use port 3000. The **Request console** page lets you send any request, including to routes the portal doesn't link to.

- Reset data any time: `python seed.py` (from `backend/`)
- Regenerate the traffic log: `python scripts/generate_traffic.py` (from `backend/`)
- The auto-generated `/docs` page is switched off (so the scanner can't use it as a shortcut); use the portal's Request console instead
- Close a planted hole: start with e.g. `FIX_IDOR=true uvicorn app.main:app --port 8000` (see `docs/PLANTED_BUGS.md`)

Test accounts (dev only): `a_admin`, `a_subagent`, `b_admin`, `b_subagent`. Their passwords are in `backend/seed.py`.

## Run the scanner

The scanner is a separate service with its own Python environment. Run these from the project root.

**One-time setup**

```bash
python3 -m venv scanner/.venv
scanner/.venv/bin/pip install -r scanner/requirements.txt
scanner/.venv/bin/playwright install chromium   # hidden browser for the crawl (~100 MB)
cd scanner/dashboard && npm install
```

**Tab A: scanner API (port 9000)**

```bash
cd scanner && .venv/bin/uvicorn service.main:app --port 9000
```

Optional: to let an AI model plan the tests (Phase 4), put `GROQ_API_KEY=your_key` in `scanner/.env` (git-ignored, loaded when the scanner starts), or set it in the start command: `cd scanner && GROQ_API_KEY=your_key .venv/bin/uvicorn service.main:app --port 9000`. Without a key the rule-based planner is used. `scanner/.venv/bin/python scanner/scripts/check_plan_validation.py` shows the catalogue guard dropping unapproved tests.

**Tab B: dashboard (port 3001)**

```bash
cd scanner/dashboard && npm run dev
```

**Tab C: trigger a scan**

```bash
scanner/.venv/bin/python scanner/scripts/fire_event.py --endpoint /api/refunds --method POST --version v2
```

The target (backend on 8000 and portal on 3000) must be running too: recon explores it through the portal. Open **http://localhost:3001** and watch the scan move through the pipeline while the **API inventory** fills in. The scanner's data lives in `scanner/data/scanner.db`; delete that file to start with an empty history (needed once after upgrading to each of Phases 2 to 8 and 10, because tables gained columns). Each scan's crawl creates a few unpaid test bookings on the target; `python seed.py` resets them. Set `CRAWL_HEADED=true` before starting the scanner API to watch the browser click through the portal. The traffic log the classifier reads is `scanner/inputs/traffic_log.json`; if you regenerate the target's log, copy it again with `cp backend/data/traffic_log.json scanner/inputs/traffic_log.json`.


**Safety gateway (Phase 5)**

- `scanner/.venv/bin/python scanner/scripts/check_gateway.py` checks every gateway rule without the target running (23 checks).
- Each scan stops at the **Safety gateway** stage until you approve or deny its high-risk tests in the Safety gateway card. Undecided tests are denied after 15 minutes.
- The red **Kill switch** button in that card blocks every further request for the scan.
- To demo the health monitor, run the stand-in failing target `scanner/.venv/bin/python scanner/scripts/flaky_proxy.py`. Then start the scanner API with `TARGET_URL=http://localhost:3099` and switch the proxy with `flaky_proxy.py slow`, `fail` or `ok` while a scan runs.
- Limits are set in `scanner/service/config.py`: `GATEWAY_MAX_RPS` (default 5) and the `HEALTH_*` settings. Allowed methods and excluded paths are in `scanner/target_profile.json` under `scope`.

**Execution (Phase 6)**

- After you approve or deny the money tests, the **Execution** card shows each test's raw result (suspicious, clean or skipped) with expandable masked evidence.
- Each scan adds a few synthetic bookings ("DAST Synthetic Customer") with payments and refunds to the target. Run `python seed.py` from `backend/` afterwards to remove them.

**Verification (Phase 7)**

- The **Findings** card lists each suspicious result as verified, false positive or unverified, with its two checks.
- `scanner/.venv/bin/python scanner/scripts/check_verification.py` shows false positives being rejected on a fake in-memory platform (no servers needed).

**Triage (Phase 8)**

- The **Findings** card ranks verified findings by severity, with owner, business impact, the reason for the severity, merged duplicates and review buttons for critical and high findings.
- `scanner/.venv/bin/python scanner/scripts/check_triage.py` checks merging, every severity rule, owners, earlier-scan matching and the review API on made-up findings (no servers needed).

**Reporting (Phase 9)**

- The **Report** card shows the time from the change to the first verified finding and how many tickets are ready or still drafts. **Open report** opens a printable page (Print → Save as PDF); **Download Markdown** and **Download tickets (JSON)** give the same content as files.
- `scanner/.venv/bin/python scanner/scripts/check_report.py` checks every report section, both downloads, Draft → Ready after a review, and that no password or token appears (no servers needed).

**Retest (Phase 10)**

- After a fix is deployed, click **Retest** on an open finding. The result (fixed, partly fixed, still vulnerable or inconclusive) and its two checks appear under the finding; fixed findings move to the **Fixed** group and to **Resolved** in the report. Every new scan also retests open findings from earlier scans on its own.
- To see it on the practice target, restart the backend with a fix switch on, for example `FIX_IDOR=true FIX_ZOMBIE=true uvicorn app.main:app --port 8000` (the switches are listed in `backend/app/config.py`).
- `scanner/.venv/bin/python scanner/scripts/check_retest.py` proves it on a fake platform with switchable fixes (no servers needed).
