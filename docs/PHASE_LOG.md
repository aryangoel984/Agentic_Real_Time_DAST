# Project Log — Agentic Real-Time DAST (TBO Voyage Hack 4.0)

This file explains the whole project in plain English, one section per phase.
No technical background needed.

## The problem, in one paragraph

Travel booking platforms like TBO change every day: new features, new payment rules, new partner connections. Each change can accidentally open a security hole. The most damaging ones usually aren't classic "hacker" bugs. They are logic mistakes. One travel agency can read another agency's customer bookings. A customer pays ₹100 for a ₹25,000 trip. A refund gets paid out twice. Today, most companies check for security holes on a fixed schedule, with generic tools that miss these logic mistakes and raise lots of false alarms. TBO's challenge is to build **automated security "agents"**: software that notices when the platform changes, works out what the platform does, safely tries to break it the way a real attacker would, proves which problems are real, and reports them to the right team within minutes.

---

## Phase 0 — Building a practice target

### What it is and why

Before we build the security agents, we need something for them to test. TBO's real test environment only opens in later rounds, so we built our own small **pretend travel booking platform** to practise on.

We hid **exactly five security holes** in it on purpose. Because we know exactly what is broken, we can measure our agents fairly:
- Did they find all five holes?
- Did they raise alarms about things that aren't really broken?

You can think of it as a practice exam where we already hold the answer key.

### What was built

- **The pretend platform** (the "backend", in the `backend/` folder). This is a program that answers requests the way a real booking website's server would. You can:
  - log in
  - search flights and hotels
  - create a booking
  - look up a booking
  - pay for it
  - refund it
  - look up a user
- **Pretend data:**
  - Two travel agencies: *Delhi Travels* (agency A) and *Mumbai Holidays* (agency B).
  - Each agency has an admin and a junior "sub-agent" account.
  - Eight bookings, with made-up customers, prices, and payment and refund states.
  - Booking 1001 belongs to Delhi Travels: customer Rahul, ₹25,000.
  - Booking 1002 belongs to Mumbai Holidays: customer Amit, ₹18,000.
- **A reset button** (`seed.py`). It wipes everything and restores the exact starting data, so every demo starts from the same state.
- **A fake "website code" file** (`frontend/public/app.js`). This is the code a browser would download, and it lists which addresses the website uses. Later our agents will read it to learn the platform's layout, just as a real attacker would.
- **Two months of fake visitor records** (`backend/data/traffic_log.json`). This is about 1,900 log lines of the kind a real server records, showing which addresses were used and when. Later our agents will compare these against what they discover.
- **The answer key** (`docs/PLANTED_BUGS.md`). For each of the five holes, it gives the exact command that triggers it.

### The five hidden holes

| # | Hole | Plain-English meaning |
|---|------|-----------------------|
| 1 | Peeking at other agencies' bookings | Mumbai's admin can open Delhi's booking 1001 and see the customer's name, email and phone. The system checks that you are logged in, but not that the booking is yours. |
| 2 | Double refund | The same booking can be refunded twice. ₹18,000 paid, ₹36,000 refunded. |
| 3 | Choose-your-own price | When paying, the system accepts whatever amount the customer's browser says. A ₹25,000 trip can be paid for with ₹100 and still counts as "fully paid". |
| 4 | Forgotten old door ("zombie") | An old version of the booking lookup is still switched on. Nobody uses it any more (zero visits in two months), and it skips the ownership check. |
| 5 | Hidden unlocked room ("shadow") | A secret internal page shows partner commission rates and supplier keys, and anyone can open it without logging in. It is actively used by an internal job, but it isn't listed anywhere in the website's code. |

### Key decisions and why

- **SQLite rather than Postgres.** Postgres would need a separate database server running in Docker, and Docker wasn't running on this machine. SQLite keeps the whole database in a single file, so there is nothing to set up, and the reset button just rebuilds that file. We can switch to Postgres later by changing one setting.
- **Each hole has its own on/off fix switch.** Each fix starts switched off, so every hole starts open. Later we can demonstrate the full cycle: the agent finds a hole, the developer "fixes" it (we flip the switch), and the agent re-checks and confirms it's closed. We tested every switch in both positions.
- **Simple login passes instead of a fancier token format.** After you log in, the platform hands you a random pass code, and it keeps a record of every pass it has issued. We avoided a more complex format called JWT because it has well-known weaknesses of its own. Using it could add accidental extra holes and spoil the "exactly five" answer key.
- **Passwords are stored scrambled.** The database only keeps a scrambled version of each password ("hashed"), as real systems should. The plain passwords appear only in the reset script, clearly marked as for development only.
- **The zombie and shadow addresses show different patterns in the visitor records.** The zombie gets **no** traffic: it is alive but unused. The shadow gets **some** traffic but is missing from the website's code: it is used but undocumented. That matches TBO's own definitions, so our agents can tell the two apart.
- **Frontend and backend live in separate folders.** This keeps the "server" and "website" parts clearly apart, as they are in real platforms.

### Limitations

- This is a deliberately small imitation, not a real booking system. Search results are fixed, and no real payments or emails happen.
- The visitor records are generated by a script, not recorded from real users.
- The automatic API reference page at `/docs` lists every address, including the hidden ones. It's convenient for checking things by hand now, but the agents must not be allowed to use it. It will be switched off before the scanner phases. *(Done in Phase 2.)*
- The fake website code file isn't served over the web yet. It's just a file in the project.

### How to see it working

Use the clickable portal described in Phase 0.1 below. *(The `/docs` page was switched off in Phase 2.)* The ready-made commands for all five holes are in `docs/PLANTED_BUGS.md`.

---

## Phase 0.1 — A clickable portal for the practice target

### What it is and why

The automatic `/docs` page was awkward to test with. You had to copy a pass code around and read raw data. So we built a proper website for the pretend platform: a clean agency portal where you sign in, look up bookings, pay, refund and search by clicking, the way a travel agent would. It also stands in for "the platform's website", which our agents will later crawl to learn the platform's layout.

### What was built (in `frontend/`)

- **Sign-in page.** A normal username and password form. Clicking an account name fills in the username.
- **Header.** Always shows who you are, your agency, and your role.
- **Bookings page:**
  - Look up any booking by number.
  - Pay for a booking. The amount box starts at the real price, and you can change it.
  - Refund a booking. This appears for admins only.
  - Create a new booking.
  - The booking card flags problems in red: another agency's booking, a booking marked "paid" for less than its price, or more refunded than was paid.
- **Search page:** flight and hotel results.
- **Users page:** look up a colleague.
- **Request console:** type any address and send it, with or without your pass code. This is how you reach the hidden routes, which the portal deliberately never links to.
- **Status under every action:** a coloured label shows what the server answered. Green means success, amber means refused, red means error. You can expand it to see the full response.

### Key decisions and why

- **The website never mentions the hidden routes or any passwords.** Later, our agents will read the website's code to find out which addresses it uses, as a real attacker would. If the website had buttons for the zombie or shadow routes, those routes would no longer be hidden, and our answer key would be wrong. The same applies to passwords: putting them in the website would be a sixth, unplanned hole. We checked the finished website code: none of these appear in it.
- **The website forwards all `/api/...` requests to the backend.** The browser only ever talks to one address (port 3000). The alternative was a "CORS" setting on the backend, a rule about which other websites may call it. If set too loosely, that setting is itself a security hole. Forwarding avoids it, and the backend code didn't need to change at all.
- **The route list file (`app.js`) is now served at `http://localhost:3000/app.js`.** That makes it a real web address our agents can fetch later, like a real site's code bundle.
- **No "reset data" button.** It would need a new backend address that wipes the database, and the scanner would find that too. Resetting stays as the `python seed.py` command.
- **Built with Next.js and Tailwind.** These are standard modern tools for building websites and styling them, and they're the project's standard for every screen.

### Limitations

- The portal remembers your sign-in in the browser's own storage. That's fine for a practice target, but not how a hardened real site would do it.
- The portal is for testing by hand. It doesn't run any security checks itself.
- `/docs` on the backend (port 8000) still lists every address. It will be switched off before the scanner phases. *(Done in Phase 2.)*

### How to see it working

1. Start the backend and the portal in two Terminal tabs (see `README.md`). Open **http://localhost:3000**.
2. Sign in as `b_admin`. The password is in `backend/seed.py`. Look up booking **1001**: Rahul's booking appears under a red "Another agency's booking" banner. That is hole #1.
3. Still as `b_admin`, look up **1002** and press **Refund** twice. Both succeed, and "Refunded" shows ₹36,000 in red against ₹18,000 paid. That is hole #2.
4. Sign out and sign in as `a_admin`. Look up **1001**, change the Pay amount to **100**, and press **Pay**. It's accepted and the booking shows "paid" with ₹100 paid. That is hole #3.
5. Open **Request console** and send `GET /api/v1/bookings/1002`. You get another agency's booking through the old route. That is hole #4.
6. Untick "Send my login token" and send `GET /api/internal/partner-details`. You get confidential partner data with no login. That is hole #5.
7. Run `python seed.py` in `backend/` to reset everything.

---

## Phase 1 — The scanner's backbone

### What it is and why

Phases 0 and 0.1 built the **target**, the pretend travel platform with five hidden holes. Phase 1 starts the **scanner**, the system that will hunt for those holes. Before it can test anything, it needs a backbone:

- a way to hear "something just changed on the platform"
- a manager that runs each scan through a fixed series of steps
- a notebook where it records everything it does and finds
- a screen to watch it on

This phase builds that backbone. **No actual security testing happens yet.** Every step is a placeholder (a "stub") that simply says "I'm here", marks itself done, and passes the scan along. Later phases will fill in each step with real work.

### The key ideas, in plain English

- **Change event.** When developers release new code, their release system can send a short message such as "the refunds API was just deployed, version 2". The scanner listens for these messages. Each one starts a new scan, because a change is exactly when a new hole might appear. This matches TBO's ask to "test within minutes of a deploy".
- **The orchestrator (the manager).** This is the part that walks a scan through ten steps, in order:
  1. **Change detection:** what changed?
  2. **Recon:** discover the platform's addresses.
  3. **Inventory:** label each address as in use, zombie or shadow.
  4. **Attack planning:** choose which tests to run.
  5. **Safety gateway:** check scope, speed limits and approvals.
  6. **Execution:** send the tests.
  7. **Verification:** prove each hit is real.
  8. **Triage:** remove duplicates and rate how serious each one is.
  9. **Reporting:** write it up for the owner.
  10. **Retest:** re-check after a fix.

  Retest can send the scan **back** to verification ("did the fix work?"), so the pipeline has a loop, not just a straight line. It's built with **LangGraph**, a tool for wiring up step-by-step agent workflows, which later lets us put AI reasoning inside individual steps.
- **The datastore (the notebook).** This is the scanner's own database file. Every scan gets a row, and everything the scan produces is filed under it:
  - the change message that triggered it
  - each step's status
  - a running log
  - and, in later phases: the endpoints found, the tests planned, the findings, the proof for each finding, every request sent to the target, and every re-check after a fix.

  All of these tables exist now, so later phases fill in a fixed shape instead of reshaping it.
- **The Security Command Center.** A dashboard at `localhost:3001`. On the left is a list of scans. On the right is the selected scan: what triggered it, a ten-step timeline that turns green step by step, a live activity log, and a Findings area that stays empty for now.

### Why the scanner is kept separate from the target

The scanner is meant to behave like an **outside auditor**. A real attacker, or TBO's real staging environment in later rounds, never gives us the platform's database or source code. We only get its web address. If our scanner peeked at the target's database, it would "find" holes it could never find in real life, and our results would be worthless.

So the separation is built in, not just promised:

- The scanner lives in its own folder (`scanner/`).
- It has its **own Python environment**, its own list of dependencies, and its **own database** (`scanner/data/scanner.db`).
- It cannot accidentally load the target's code, because that code isn't even installed where the scanner runs.
- The dashboard talks only to the scanner, never to the target.
- In later phases, the scanner will reach the target only the way any outsider can: over the web (HTTP), through a safety gateway that logs every request.

**Separation check (done at the end of this phase):**

- We searched all the scanner's code for any mention of the target's database file (`travel.db`), its folder (`backend/`), its code (`app...`), its reset script (`seed.py`), or its address (`:8000`). We found **zero matches**.
- While the scanner was running, the only database files it had open were its own: `scanner.db` and that database's two working files.

### Key decisions and why

- **Progress is saved to the database after every step.** That's why a scan's progress survives a page refresh or even a scanner restart, and why anyone can inspect it. We tested both.
  - LangGraph also offers its own "save point" system for resuming a half-finished scan after a crash. We left it out for now: it would be a second copy of the same information, and resuming isn't useful until the steps do real work.
  - Instead, if the scanner restarts mid-scan, that scan is honestly marked **interrupted** rather than left looking as if it's still running.
- **Each placeholder step pauses for 1.5 seconds.** Ten instant steps would finish in a blink, and you couldn't watch the pipeline move. The pause is a single setting (`STUB_STAGE_DELAY_SECONDS`), and it will be removed once the steps do real work.
- **The dashboard checks for updates every 1.5 seconds.** The alternative is keeping a live two-way connection open ("WebSockets"), which is more complex. Checking every 1.5 seconds is simpler and plenty fast for scans that take seconds or minutes.
- **The retest loop has a limit.** It can send a scan back to verification at most once per scan (a setting), so a stubborn finding can't make the scanner go round in circles forever. We tested the loop with a pretend finding, and it went back exactly once and then stopped.
- **The selected scan is part of the web address** (`?scan=2`), so refreshing or sharing the link reopens the same scan.
- **Separate ports.** The target uses 8000 and 3000. The scanner uses 9000 (API) and 3001 (dashboard).

### Limitations

- No real testing yet. Every step is a placeholder, and the Findings area is always empty.
- The scanner doesn't contact the target at all yet. That starts with recon in a later phase.
- Anyone who can reach port 9000 can send a change message. Real release systems "sign" their messages so fakes can be rejected; we'll add that when it matters.
- A scan interrupted by a restart isn't resumed. It's marked interrupted, and you fire a new event.
- Scans run one after another in the background of a single service. That's fine for a demo, but it isn't built for many simultaneous scans yet.

### How to see it working

1. Start the scanner API and the dashboard in two Terminal tabs (see "Run the scanner" in `README.md`). Open **http://localhost:3001**. It says "No scans yet", with "Scanner online" shown in green.
2. In a third tab, fire a change message: `scanner/.venv/bin/python scanner/scripts/fire_event.py --endpoint /api/refunds --method POST --version v2`
3. Within about 2 seconds, **Scan #1** appears. Watch its ten steps turn green one by one, about 15 seconds in total. The activity log shows "entered change_detection", "entered recon" and so on, ending with **scan completed**.
4. Refresh the page: everything is still there. Stop the scanner API (Ctrl + C) and start it again: still there.
5. Fire another event with a different endpoint (for example `--endpoint /api/payments`). A second scan appears at the top of the list.

## Phase 2 — The recon (discovery) agent

### What it is and why

Before you can test a platform for holes, you need a list of its doors: every API address it answers, what each one expects, and who can use it. That list is called an **API inventory**, and building it is called **discovery** (or **recon**). In Phase 1, the recon step was a placeholder. Now it does real work: when a change message arrives, the scanner explores the target **from the outside**, writes down every API it can see, and shows that list on the dashboard while it works.

This matters for TBO because the riskiest APIs are often the ones nobody remembers: an old version that was never switched off, or a route that was added quietly. A scanner can only test what it knows about, so discovery comes first.

### The three ways the scanner discovers APIs

1. **Using the portal like a real person (the crawl).** The scanner opens a hidden web browser (using a tool called **Playwright**) and signs in as each of the four test users: Delhi admin, Delhi sub-agent, Mumbai admin and Mumbai sub-agent. For each user it:
   - searches for flights
   - looks up one of its own bookings
   - presses Pay
   - presses Refund (admins only; sub-agents aren't shown the Refund form)
   - creates a booking
   - looks up its own profile

   Every time the page talks to the server, the scanner notes the address, the method (read or write), the fields sent, whether a login token was attached, and what the server answered.
2. **Reading the portal's code (`app.js`).** Every website ships some JavaScript to your browser, and that code contains the API addresses the site uses. The scanner downloads `app.js` from the portal and pulls out every route listed in it.
3. **Trying older and newer versions (version probing).** Teams often release `/api/v2/...` and forget to switch off `/api/v1/...`. For every address the scanner already found, it tries `/api/v0/`, `/api/v1/` and `/api/v2/` versions. Anything that answers (anything other than "not found") goes into the inventory.

### What the inventory records for each API

- **Method and path**, for example `POST /api/refunds`. Real numbers in addresses are turned into placeholders, so `/api/bookings/1003` becomes `/api/bookings/{id}`. That way the same API found by different methods becomes one row.
- **Parameters seen:** values in the address (`id`), in the query (`type, origin, destination`), and in the body (`amount, booking_id`).
- **Whether a login is required**, and how we know:
  - **verified** means the scanner repeated a *read* request without a login token and the server refused it with 401.
  - **observed** means we judged from what the portal did. Login was called without a token and worked, so it needs no login. The others always carried a token, so they need one.
- **Roles reached:** which of the four test users actually got through. Refunds shows only the two admins.
- **Purpose:** a one-word guess from the address: auth, search, booking, payment, refund or user.
- **Found by:** crawl, app.js or version probe (often more than one).

### What it found (with all five planted holes still open)

**8 APIs:**

- **The 7 the portal uses:** login, search, create booking, look up booking, pay, refund, look up user. Each was found by both the crawl and app.js.
- **The old `GET /api/v1/bookings/{id}`,** found only by version probing. Labelling it a "zombie" is Phase 3's job; here it's simply "discovered".

**The hidden `/api/internal/partner-details` does not appear.** No page links to it, the code doesn't call it, and it isn't a version of anything we found. So an outsider using these three methods simply cannot see it. You can confirm this in the agent log: the last lines list every API in the inventory, and it isn't there. Finding it needs a different source (the traffic log), which is Phase 3.

### One shared door for every request (the "choke point")

Every request the scanner sends to the target goes through **one piece of code**: the shared target client. That includes the hidden browser's requests. The browser doesn't talk to the target directly: each request it makes is caught, handed to the shared client, and the answer is passed back to the browser. The shared client does three things:

- **Checks scope.** It will only contact the target portal's address (`localhost:3000`). Anything else is refused and never sent.
- **Records the request** in the scanner's `audit_logs` table: the address, the method, the answer code, and whether it was allowed. Passwords and login tokens are masked as `***` before saving.
- **Leaves one empty "gate" slot.** In Phase 5, the safety gateway (speed limits, approvals for risky tests) goes into that slot. Because everything already passes through it, nothing can sneak around it.

### Keeping it safe: Pay and Refund don't move money

Clicking Pay and Refund for real would change data on the target. So the crawl fills those forms with values the server is guaranteed to refuse:

- **Pay** is pressed for a booking that is **already paid**, so the server answers 409 "already paid".
- **Refund** asks for **more money than was paid**, so the server answers 400.

The scanner still learns the address, the fields and the answer, but nothing changes. **Create booking is done for real**, for the user's own agency. It only adds one harmless unpaid booking per user per scan. Run `python seed.py` in `backend/` to reset.

The scanner also never sends **guessed write requests**. Version probing and the "no token" check only send *read* requests. Writes on guessed addresses wait for the safety gateway (Phase 5).

### Why the scanner stays outside the target

- **Only over the web.** The scanner reaches the target only through the public portal address (`localhost:3000`), the same as any outsider. It never talks to the target's API port (8000) directly, never imports the target's code, and never opens the target's database.
- **The "brief" is a file.** The only things the scanner is told about the target are in `scanner/target_profile.json`: the portal address, the four test accounts, and one known booking number per agency. A real security test team gets exactly this kind of brief.
- **Separation check (done at the end of this phase):**
  - Searching the scanner's code for the target's database file, folder or API port found nothing that could reach them.
  - While the scanner was running, the only database files it had open were its own.
  - Every one of the 107 requests in the audit log went to the portal's address.

### Change made to the target: auto-docs switched off

FastAPI (the tool the target is built with) automatically publishes a page at `/docs` that lists **every** API, hidden ones included. A real platform wouldn't leave that open, and it would let the scanner cheat. So we switched it off: `/docs`, `/redoc` and `/openapi.json` on port 8000 now answer "not found". This is a one-line change in `backend/app/main.py`. Use the portal's Request console to try APIs by hand instead.

### Key decisions and why

- **The developer comment in `app.js` is ignored.** The mock `app.js` contains a comment naming the old v1 route and the hidden internal route. Real production code is "minified" (squashed down) and has no comments, so the scanner removes comments before reading the code. Otherwise the hidden route would have leaked into the inventory through a note no real attacker would see.
- **The inventory is saved after each step**, so the dashboard table fills in while recon runs:
  - first the 7 routes from app.js
  - then roles and parameters after each user's crawl
  - then the v1 route
  - then the verified login checks
- **The browser runs hidden** for speed. Set `CRAWL_HEADED=true` before starting the scanner API to watch it click.
- **The live-reload connection of the portal's development server is blocked.** It isn't part of the app, and letting it through would be a route around the shared client.

### Limitations

- **The crawl can only find what the portal shows.** That's by design. The hidden route needs other evidence (Phase 3).
- **Write APIs (POST) are not version-probed or retried without a token.** Their login requirement is "observed", not "verified". This waits for the safety gateway.
- **Recon needs both the portal (3000) and the target API (8000) running.** Before crawling, recon checks both:
  - If the portal is down, it stops with "could not reach the target portal...".
  - If the portal is up but the API behind it is down, it stops with "the portal is up but its API is not answering... Is the target API running?"
  - If a crawl step breaks later, the error names the user, the step, and the last API answer, for example "crawl A-admin, step 'sign in': POST /api/login returned HTTP 500".
- **The crawl follows fixed steps written for this portal.** It doesn't yet explore unknown sites on its own.
- **Each scan adds four unpaid bookings to the target.** Reset with `python seed.py`.
- **Recon takes about 15–25 seconds**, mostly the four browser sign-ins. The other steps are still 1.5-second placeholders.

### How to see it working

1. One-time setup for the scanner's new tools: `scanner/.venv/bin/pip install -r scanner/requirements.txt`, then `scanner/.venv/bin/playwright install chromium`. This downloads a hidden browser of about 100 MB.
2. Delete the old scanner database once: its inventory table has new columns. `rm scanner/data/scanner.db*`
3. Start all four: the target API (8000), the portal (3000), the scanner API (9000) and the dashboard (3001). Run `python seed.py` first. The commands are in `README.md`.
4. Fire a change message: `scanner/.venv/bin/python scanner/scripts/fire_event.py`
5. Open **http://localhost:3001**. While **Recon** is running, the **API inventory** card says "discovering…":
   - The 7 portal routes appear first, found by app.js.
   - Within about 20 seconds, the roles, parameters and the crawl source fill in.
   - Then `GET /api/v1/bookings/{id}` appears, found by version probe.
   - The final count is **8 endpoints**.
6. Read the agent log: you'll see each user sign in, every request captured, every version tried, and the final list, which contains no `partner-details`.
7. Refresh the page or restart the scanner API: the inventory is still there.
8. Open **http://localhost:8000/docs**: it says "Not Found".
