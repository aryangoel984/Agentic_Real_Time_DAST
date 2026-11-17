# Agentic Real-Time DAST — TBO Voyage Hack 4.0

We are building automated security agents that watch a travel booking platform as it changes, find security holes the way a real attacker would (especially logic mistakes like one agency reading another's bookings, or paying ₹100 for a ₹25,000 trip), prove which problems are real, and report them to the right team within minutes. So far we have built two separate things. The first is the practice target (Phase 0): a small pretend B2B travel platform, with a clickable agency portal, two agencies, test accounts, bookings, payments and refunds, and exactly five deliberately hidden security holes, so our agents have a place to practise where we already know the right answers. The second is the scanner: an independent service that hears "something changed", starts a scan, walks it through a ten-stage pipeline, records everything in its own database, and shows it live on a "Security Command Center" dashboard (Phase 1). Its first real stage is recon (Phase 2): it explores the target only from the outside, by signing in to the portal as each test user and clicking through the real flows, reading the portal's JavaScript, and trying older API versions, and it builds an inventory of every API it can see, with parameters, login requirement and which users can reach it. The remaining stages are still placeholders. See `docs/PHASE_LOG.md` for the full plain-English story.

## Project layout

```
backend/    THE TARGET: FastAPI mock travel platform (port 8000), SQLite database, traffic log
frontend/   THE TARGET: Next.js + Tailwind agency portal (port 3000); public/app.js is the route manifest
scanner/    THE SCANNER: independent service with its own venv, database and dashboard
  service/    FastAPI API (port 9000): deploy-event intake + LangGraph orchestrator
    recon/      discovery agent: portal crawl (Playwright), app.js parsing, version probing
    target_client.py  the single choke point every request to the target goes through
  target_profile.json  what the scanner is told about the target: portal URL, test accounts
  scripts/    fire_event.py: send a sample deploy event
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

**Tab B: dashboard (port 3001)**

```bash
cd scanner/dashboard && npm run dev
```

**Tab C: trigger a scan**

```bash
scanner/.venv/bin/python scanner/scripts/fire_event.py --endpoint /api/refunds --method POST --version v2
```

The target (backend on 8000 and portal on 3000) must be running too: recon explores it through the portal. Open **http://localhost:3001** and watch the scan move through the pipeline while the **API inventory** fills in. The scanner's data lives in `scanner/data/scanner.db`; delete that file to start with an empty history (needed once after upgrading to Phase 2, because the inventory table gained columns). Each scan's crawl creates a few unpaid test bookings on the target; `python seed.py` resets them. Set `CRAWL_HEADED=true` before starting the scanner API to watch the browser click through the portal.
