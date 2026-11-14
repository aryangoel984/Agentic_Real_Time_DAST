# Agentic Real-Time DAST — TBO Voyage Hack 4.0

We are building automated security agents that watch a travel booking platform as it changes, find security holes the way a real attacker would (especially logic mistakes like one agency reading another's bookings, or paying ₹100 for a ₹25,000 trip), prove which problems are real, and report them to the right team within minutes. So far (Phase 0) we have built the practice target: a small pretend B2B travel platform, with a clickable agency portal, two agencies, test accounts, bookings, payments and refunds, and exactly five deliberately hidden security holes. It gives our future agents a controlled place to practise, where we already know the right answers. See `docs/PHASE_LOG.md` for the full plain-English story.

## Project layout

```
backend/    FastAPI mock travel platform (the target), SQLite database, traffic log
frontend/   Next.js + Tailwind agency portal (port 3000); public/app.js is the route manifest
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
- Close a planted hole: start with e.g. `FIX_IDOR=true uvicorn app.main:app --port 8000` (see `docs/PLANTED_BUGS.md`)

Test accounts (dev only): `a_admin`, `a_subagent`, `b_admin`, `b_subagent`. Their passwords are in `backend/seed.py`.
