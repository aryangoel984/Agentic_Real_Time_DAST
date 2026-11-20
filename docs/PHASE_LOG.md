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

## Phase 3 — The inventory classifier (active, zombie, shadow)

### What it is and why

Recon (Phase 2) gave us a list of every API the scanner could **see** from outside. That isn't the whole picture. Some APIs are switched on but nobody uses them anymore. Others are used every day but are linked from nowhere, so an outsider can't see them. Both kinds are classic places for security holes, because nobody is watching them.

This phase replaces the placeholder **Inventory** step. It compares two lists:

- **What recon could see:** the inventory from Phase 2.
- **What real traffic actually used:** the platform's access log, the record of every request that hit the platform's front gate.

From the comparison, every API gets one of three labels:

| Label | Plain meaning | Why it matters |
|---|---|---|
| **Active** | Recon found it, and real users have called it recently. | Normal. Keep monitoring and testing it. |
| **Zombie** | Recon found it, but nobody has called it recently. | It's still switched on and forgotten. Fixes and patches often skip it. Turn it off or block it. |
| **Shadow** | Real traffic uses it, but recon couldn't see it. | Nobody tracks it, documents it or tests it. Find out who owns it and bring it under control. |

### How the comparison works

1. **Read the access log.** Each line records one request: when, which method (read or write), which address, and who called it.
2. **Tidy every address with the same rule recon uses.** Numbers become `{id}` and anything after `?` is dropped. So `/api/bookings/1003` in the log and `/api/bookings/{id}` in the inventory match. Both sides use the exact same rule, so they can never disagree about spelling.
3. **Count each address in the log:** how many times it was called, when it was last called, and by whom.
4. **Look at a recent window: the last 30 days of the log.** The window is counted back from the log's own last day (14 Nov), not from today. Otherwise, as days pass, everything would slowly look "unused" just because the log is old.
5. **Label each API:**
   - In the inventory and called in the window → **active**.
   - In the inventory, not called in the window → **zombie**. This includes APIs found only by version probing.
   - In the log, but not in the inventory → **shadow**. It's added to the inventory as a new row, marked "found by: traffic log".
6. **Write down for each API:** its label, when it was last seen in traffic (or "never"), how many hits and from whom, a recommended action, and a likely owning team. The owner is guessed from the address (bookings → Bookings team, payments and refunds → Payments team, and so on) and is marked "(guess)".

### What it found

| | API | Why |
|---|---|---|
| **Active (7)** | login, search, create booking, look up booking, pay, refund, look up user | All were called within the last 30 days. |
| **Zombie (1)** | `GET /api/v1/bookings/{id}` | Found by recon's version probing, but **never** seen in the log. The old version is still switched on. |
| **Shadow (1)** | `GET /api/internal/partner-details` | Called 20 times, last on 11 Nov 2026, all by one internal machine (`10.0.4.17`, a program called `partner-sync`). Recon couldn't see it in Phase 2, because nothing links to it. The traffic log is what revealed it. |

### Why the traffic log counts as a "provided input"

TBO's problem statement offers gateway and load-balancer logs as something the security team is **given**. In real life, a company hands its testers a log export. The testers never log into the company's servers to fetch it themselves. We copy that exactly:

- **The handover is one file.** The log was copied once into the scanner's own folder, as `scanner/inputs/traffic_log.json`. That file is "the logs TBO gave us".
- **The scanner reads only that copy.** Its location is a setting (`TRAFFIC_LOG_PATH`), so a real TBO log can be dropped in later.
- **Separation check (done at the end of this phase):**
  - The scanner's code contains no path into the target's folder, database or API port.
  - While it ran, the only files the scanner had open were its own.
  - The scanner's request record shows the Inventory step sent **zero** requests to the target. Every request in that scan came from recon.
- **The log says so too.** The Inventory step's first log line states the file it read and that the target's database and code were not accessed.

### Dashboard changes (API inventory card)

- **Summary in the card header:** **Active 7 · Zombie 1 · Shadow 1**, in green, amber and red.
- **New Class column:**
  - green **Active**
  - amber **Zombie**
  - red **Shadow**
  - grey "pending" while recon is still running and the step hasn't happened yet
- **Shadow and zombie rows come first**, lightly tinted. Each has a line underneath with last seen in traffic, hits and callers, the likely owner, and the recommended action.
- **Last-seen dates are shown in UTC**, the same as the log. Otherwise an evening time on 11 Nov in UTC would show as 12 Nov in India and look like a mismatch.
- **The shadow row honestly shows Auth "Unknown" and no roles.** The scanner has only seen it in the log. It hasn't touched it.

### Key decisions and why

- **The window is counted back from the log's end, not from today.** Explained above. The length (30 days) is a setting (`TRAFFIC_WINDOW_DAYS`).
- **Shadow endpoints are labelled, not tested.** This step only reads a file. Probing or testing the shadow endpoint is for the attack phases, behind the safety gateway.
- **The owner is a keyword guess.** It's a helpful starting point for "who do we tell?". It isn't a real list of which team owns which service.

### Limitations

- **The labels are only as good as the log.** If an API is used but its calls aren't logged, it will look like a zombie.
- **The 30-day window is a choice.** A job that runs once every six weeks would be labelled zombie.
- **The log is a fixed file.** If the target's log is regenerated, copy it again:
  ```bash
  cp backend/data/traffic_log.json scanner/inputs/traffic_log.json
  ```
- **One-time database reset.** The inventory table gained a column for traffic details, so `scanner/data/scanner.db` has to be deleted once after upgrading. This is the same as in Phase 2.

### How to see it working

1. Stop the scanner API, delete the old scanner database (`rm scanner/data/scanner.db*`), and start the scanner API again. The target API (8000), the portal (3000) and the dashboard (3001) should be running too.
2. Fire a scan: `scanner/.venv/bin/python scanner/scripts/fire_event.py`
3. Open **http://localhost:3001**. After recon (about 15–25 seconds), the **Inventory** step runs. The table gains its Class column, and the header shows **Active 7 · Zombie 1 · Shadow 1**.
4. **Top row:** `GET /api/internal/partner-details`, red **Shadow**, found by **traffic log**, last seen 11 Nov 2026 (UTC), 20 hits from `10.0.4.17 (partner-sync/1.4)`, with the recommendation to investigate ownership.
5. **Second row:** `GET /api/v1/bookings/{id}`, amber **Zombie**, last seen **never**, with the recommendation to decommission or restrict.
6. **Agent log, Inventory lines:** the source file (with the note that the target wasn't touched), the log's dates and window, one line per API with its label, a highlighted shadow line, and the final count.

## Phase 4 — The attack planner (the AI plans, it never acts)

### What it is and why

By now the scanner knows every API it can find and whether each one is active, a zombie or a shadow. Before it tests anything, it needs to decide **which tests are worth running on which API, and why**. That decision is called **attack planning**.

Testing every possible attack on every API would be slow, noisy and risky. A refund API needs money tests, like "can I refund twice?". A booking lookup needs an access test: "can agency A read agency B's booking?". A login page needs a password test. Choosing well is what turns a blind scanner into a smart one.

This phase replaces the placeholder **Attack planning** step with a real planner. **It only writes a plan. Nothing is executed.** Phase 5 (the safety gateway) and Phase 6 (execution) act on the plan later.

### Why the AI only plans and never acts

An AI model is good at reasoning about context. For example: "only admins reached this refund API, so test whether a sub-agent can use it too". But an AI can also be wrong, make things up, or be misled. So the jobs are split:

- **The AI only writes suggestions.** It receives a text description of the APIs and replies with a JSON list of `{test_type, reason}` for each one. It is given **no tools, no target address, no passwords, no login tokens and no booking data**, so it has no way to send a request even if it wanted to.
- **Our code has the final say.** Every suggestion is checked against a fixed **approved test catalogue** written in code. Anything not in the catalogue, or not applicable to that API, is thrown away and logged.
- **Our code will do the executing**, later, through the safety gateway, which logs every request and asks before anything risky.

### The approved test catalogue

These are the only test types the scanner may ever plan:

| Test type | What it checks | Applies to | Risk |
|---|---|---|---|
| Cross-agency access | Can agency A read or act on agency B's record? | read & write | medium |
| Duplicate refund | Can the same booking be refunded twice? | write | **high** (moves money) |
| Amount validation / price tampering | Does the server trust an amount sent by the client? | write | **high** (moves money) |
| Role authorization | Can a sub-agent do an admin-only action? | read & write | medium |
| Missing authentication | Does it answer with no login at all? | read & write | low |
| Zombie version ownership check | Does an old version skip checks the current one has? | read | medium |
| Weak authentication | Does login allow weak passwords or unlimited guessing? | write | medium |

The two **high-risk** tests are marked "needs approval before running". Phase 5 will enforce that.

### The two planners

1. **The AI planner (Groq).** Groq is an online service that runs open AI models. We use the model `openai/gpt-oss-120b`, through Groq's official Python library.
   - It runs only when a Groq key (`GROQ_API_KEY`) is set in the terminal where the scanner starts.
   - It makes **one request per scan** for all APIs together.
   - The reply is requested as JSON only.
   - The AI may also suggest ideas outside the catalogue. Those are exactly what the guard drops, and you can see them in the log.
   - Groq has a free tier, and one request per scan fits easily within it.
2. **The rule-based planner (always available).** It is a fixed set of rules in our own code:
   - shadow → missing authentication
   - zombie → ownership check
   - refund → duplicate + amount + role
   - payment → amount (price tampering) + cross-agency
   - lookups by ID → cross-agency
   - create booking → cross-agency
   - login → weak authentication
   - search → no tests, with a reason

   Each test comes with a plain-English reason. It needs no internet and no key.

**Which one runs?**
- **Default (`PLANNER_PROVIDER=auto`):** Groq if a key is set, otherwise rules.
- **Groq call fails:** for any reason (no internet, wrong key, rate limit, unreadable reply), the scan **doesn't fail**. It switches to the rule-based planner and says so in the log.
- **Groq skips an API:** the rules fill that one in, and the log says so.

### The catalogue guard

Every plan, from the AI or from the rules, passes through the same check. A suggestion is kept only if:

- its test type is in the catalogue
- the test applies to that API's method. For example, "duplicate refund" on a read-only lookup is dropped.
- it names an API that exists in this scan
- it has a reason

Duplicates are merged. Every dropped item becomes a warning line in the agent log, and the Attack plan card lists them under "Dropped by the catalogue guard".

To see the guard work without any key, run:
```bash
scanner/.venv/bin/python scanner/scripts/check_plan_validation.py
```
It feeds the guard a fake AI answer containing things like `delete_all_bookings` and `rate_limit_test`, a refund test on a read-only API, and a test with no reason. It prints which items were kept and which were dropped, and why.

### What is stored

- **The `test_cases` table:** each planned test is saved with its API, test type, plain-English reason, risk level, whether it needs approval, which planner chose it, and status **planned**.
- **The scan's saved state:** which planner ran and why, the model name, the number of tests, the dropped items, and the reason for any API with no tests.
- **New columns:** the table gained three (`test_type`, `reason`, `planned_by`), so `scanner/data/scanner.db` must be deleted once after upgrading.

### What it planned (rule-based run)

| API | Planned tests |
|---|---|
| `GET /api/internal/partner-details` (shadow) | missing authentication |
| `GET /api/v1/bookings/{id}` (zombie) | zombie ownership check |
| `POST /api/refunds` | duplicate refund, amount validation, role authorization |
| `POST /api/payments` | amount validation (price tampering), cross-agency access |
| `GET /api/bookings/{id}`, `GET /api/users/{id}`, `POST /api/bookings` | cross-agency access |
| `POST /api/login` | weak authentication |
| `GET /api/search` | none: shared results, no per-agency record, login already enforced |

That's 11 tests across 8 APIs. **0 requests were sent to the target during planning.** The planner counts this from the scanner's request record and states it in the log.

### Keeping the scanner outside the target

- **The planner never contacts the target.** It reads only the scanner's own database (the inventory from Phases 2–3).
- **The only outbound request in this step is the one to Groq**, and only when a key is set. That request carries API descriptions: paths, field names, role labels and classifications. In this project those are all made-up. No passwords, tokens, customer data or the target's address are sent.
- **Rules mode keeps everything on the machine.**

### How it was tested

- **What is sent to Groq:** the exact request was checked. It contains no target address or port, no passwords, no login tokens, no customer data, no caller IPs and no API key. "password" appears only as a field name.
- **Full scans with Groq:** a full scan ran with Groq planning. All 10 steps completed, the inventory had 9 APIs (7 active, 1 zombie, 1 shadow), and the planning step sent **0** requests to the target. All 108 recorded requests came from recon.
- **Repeated planning:**
  - Groq planning was repeated 6 times. Each took 5–30 seconds and produced 12–15 tests.
  - It never planned "missing authentication" on an API where login was already verified.
  - It never proposed a test outside the catalogue. So the guard was proven with the check script rather than by a live AI mistake.
  - One run missed a required test. That is why the rules minimum was added. In the 3 runs after that change, every required test was present.
- **Rules mode:** rules mode (`PLANNER_PROVIDER=rules`) planned the same 11 tests every time.
- **Fallbacks:** a fake key made Groq answer "Invalid API Key", and the scan fell back to rules without failing.

### Key decisions and why

- **One AI request per scan, not one per API.** It's faster, uses far less of the free quota, and gives a consistent plan across APIs.
- **The AI may suggest extra ideas.** We let it, because it's realistic and makes the guard visible. Its ideas are recorded as "dropped", never planned.
- **The fallback is automatic.** A scanner that stops working when an outside AI service is down would be a bad security tool.
- **Groq instead of Claude.** Claude's API needs a paid key that the Claude Pro plan doesn't include. Groq has a free tier. Switching provider later means adding one small file in `scanner/service/planner/`.

### Limitations

- **What the first live Groq run taught us.** The AI planned "missing authentication" on every API, even where recon had already *verified* that login was required. That's 21 tests where about 12 made sense. The cause was that it wasn't being told how auth had been decided. We now pass that detail in and instruct it not to re-test what discovery already proved. The next run planned 14 sensible tests.
- **The AI's choices vary from run to run, so the rules act as a guaranteed minimum.** In testing, one Groq run left out "role authorization" on refunds. So whenever Groq plans, any test the rule-based planner would have chosen but the AI missed is added back. The log shows a line "rules minimum added …", and the dashboard tags it "added by rules". The AI can add to the plan, but it can never shrink it below the rules.
- **The AI still adds a few debatable tests**, for example cross-agency access on search. These are approved types, so they are kept. Over-testing costs time, not safety, because execution is gated in Phase 5.
- **The AI's wording varies between runs.** The guard keeps the *types* of tests within the fixed catalogue, but the reasons will read differently each time.
- **The plan is only as good as the inventory.** The shadow API's login requirement is still "Unknown", because nothing has touched it yet.
- **The planner only knows what's in the catalogue.** New kinds of test need a code change. That is deliberate.
- **Nothing is executed.** No hole is confirmed yet. That starts after the safety gateway (Phase 5).

### How to see it working

1. Stop the scanner API, delete the old database (`rm scanner/data/scanner.db*`), and install the new library once:
   ```bash
   scanner/.venv/bin/pip install -r scanner/requirements.txt
   ```
2. **Without a key:** start the scanner API as usual and fire a scan.
   - The **Attack plan** card (under the inventory) says "Planned by rule-based fallback (no GROQ_API_KEY set)" and shows the 11 tests above, each with its reason.
   - The money tests show "needs approval before running".
   - The footer says 0 requests were sent to the target.
3. **With your Groq key:** put the key in `scanner/.env` as one line, `GROQ_API_KEY=your_key`. The scanner loads this file when it starts, and git ignores it, so it is never committed. Alternatively, set the key in the start command itself (a key typed in the terminal wins over the file):
   ```bash
   cd scanner && GROQ_API_KEY=your_key .venv/bin/uvicorn service.main:app --port 9000
   ```
   Restart the scanner API after adding or changing the key.
   - Fire a scan. The card says "Planned by Groq LLM (openai/gpt-oss-120b)" and the reasons are the AI's own wording.
   - Any suggestions outside the catalogue appear as amber "dropped" lines in the log and at the bottom of the card.
4. **Guard proof without a key:** run `check_plan_validation.py`, as shown above.

## Phase 5 — The safety gateway (one checkpoint every request must pass)

### What it is and why

From Phase 6 on, the scanner will send real attack requests to the target, some of which try to move money. Before that is allowed, there has to be one place that decides, for **every single request**, whether it may go out. That place is the **safety gateway**. It is worth 20% of the judging, and a scanner that hits the wrong host, uses real accounts or floods the platform would be disqualified, so it is enforced in code, not left to each agent to remember.

### Why it is a single choke point

Only one piece of scanner code is able to send anything to the target: `TargetClient.send` in `scanner/service/target_client.py`.

- **No other module can open a connection.** No other scanner file imports an HTTP library. The check script tests this.
- **The crawler's browser can't go around it either.** Every request the browser makes is intercepted and handed to `send`. Off-host requests go there too, and are blocked and recorded.
- **Future agents use the same door.** The Phase 6 attack executor will call the same `send`, so it inherits every check automatically.
- **The gateway runs inside `send`.** It cannot be skipped, because there is no other way to reach the target. The one line that actually puts bytes on the wire comes after all the checks.

### The checks, in order

The first check that says no decides the outcome. Every outcome is written to the audit log.

1. **Kill switch.** If someone pressed the kill switch (or the health monitor gave up), the request is **blocked** and nothing is sent.
2. **Scope.** The request must go to the portal's host only, using GET, POST, HEAD or OPTIONS. DELETE, PUT and PATCH are never needed, so they are refused. Paths listed under `excluded_paths` in `scanner/target_profile.json` are refused as well. Anything else is **blocked**, with the reason.
3. **Credentials.** Only the four test accounts in `target_profile.json` may be used.
   - A login attempt for any other username is **blocked**.
   - A login token is accepted only if the gateway itself saw the target issue it to one of those accounts during this scan. A forged or borrowed token is **blocked**.
   - Every allowed request records which test account it used.
4. **High-risk approval.** A request that belongs to a high-risk test (duplicate refund, price tampering) is **blocked** unless a human has approved that test. This is the code-level lock for Phase 6.
5. **Health monitor.** After every response the gateway notes the status and how long it took. It **pauses** the scan when the target looks unwell:
   - the target answers 503 or refuses the connection (it is down right now), or
   - 3 errors arrive in a row, or
   - at least half of the last 10 answers are errors, or
   - the middle (median) response time of the last 10 answers is 2 seconds or more.

   While paused, new requests are **held**: they wait and are not dropped. The gateway checks the portal's home page every 5 seconds and **resumes** as soon as it answers quickly and without error.

   A request the target did not process (503 or refused) is sent again after recovery, as are failed reads. Other failed writes are never repeated. If the target is still unwell after 120 seconds, the scan is **stopped safely** instead of waiting forever.
6. **Rate limit.** At most **5 requests per second** per scan. Extra requests wait their turn; they are queued, not dropped. The wait is recorded on each request.

**Audit log.** Every decision becomes one row in `audit_logs`, recording:
- the scan and the stage
- method and URL
- the decision (allowed, blocked or held) and the reason
- whether the request was actually sent, and the response status
- response time and how long it waited
- the test account used and the test case, if any

Passwords, tokens, the Authorization header and cookies are masked (`***`) before saving.

### The safety_gateway pipeline stage

The gate guards every stage from the first request onwards. The pipeline's own **Safety gateway** stage, which used to be a placeholder, now does two jobs:

1. **Self-test.** It pushes five deliberately bad requests through the real gate:
   - a request to another website (`example.com`)
   - a DELETE request
   - a login as an account that isn't a test account
   - a forged token
   - an unapproved high-risk refund test

   These run in **dry-run mode**: even if the gate let one through, it would not be sent. All five must be blocked. If any is not, the scan stops before any test can run. This is also how you see a blocked out-of-scope request on every scan.
2. **Approval queue.**
   - Low- and medium-risk tests are marked **cleared**.
   - High-risk tests are marked **waiting** and the pipeline stops here until a human decides each one on the dashboard.
   - **Approve** marks the test *approved*, which means it may run in Phase 6.
   - **Deny** marks it *denied*: it is dropped and will never run.
   - A test nobody decides within 15 minutes is denied automatically, so doing nothing is the safe choice.
   - Each waiting test and each decision is also an audit row. These rows are marked "not sent", because a decision is not a request.

### Dashboard: the Safety gateway card

A new card sits under the Attack plan:

- **Status line.** It shows one of:
  - Running
  - Waiting for your decision
  - Paused (with the reason)
  - Killed / Stopped (with the reason)

  It also shows the counts: sent to target, allowed, held (amber), blocked (red). The rate figure is "highest N in any 1 s (cap 5/s)", computed from the recorded send times.
- **Kill switch.** A red button with a confirm step. It blocks every further request for that scan immediately, and the scan ends as **killed**.
- **High-risk tests.** Each one has Approve and Deny buttons, then shows its result.
- **Audit log.** A live table, newest first, with All / Blocked / Held / Sent filters. Clicking a row shows the request exactly as recorded, with secrets masked.

### Simulating a failing target

`scanner/scripts/flaky_proxy.py` is a tiny stand-in for a struggling target. It sits on port 3099 in front of the portal (3000) and forwards everything. You switch it between three modes from another terminal:
- `ok` forwards normally
- `slow` adds a 4-second delay
- `fail` answers 503

Start the scanner with `TARGET_URL=http://localhost:3099` and the scanner treats the proxy as the target. The target's code is not changed.

The proxy also counts every request it receives. That count is a second, independent proof that nothing goes around the gateway: it should equal "Sent to target" on the dashboard.

### How it was tested

- **`scanner/scripts/check_gateway.py`: 23 of 23 checks passed.** It needs no target, because it uses a throwaway database and a fake in-memory target. It covers:
  - the no-bypass code checks
  - off-scope, DELETE and excluded paths
  - an unlisted account, a forged token, and a real account's token being accepted and attributed
  - an unapproved test blocked, then allowed after approval
  - 20 requests taking at least 3.8 s, with never more than 5 in any second
  - pause after 3 errors, the request held, then resumed
  - a 503 pausing at once and the request re-sent after recovery
  - the kill switch blocking with nothing sent
  - no password or token in any audit row
- **Full scans through the proxy** (6 runs):
  - **Normal scan.** Recon still found the same 8 endpoints.
    - All 5 self-test requests were blocked.
    - 3 high-risk tests waited until they were decided on the dashboard: 2 approved, 1 denied. The scan then finished.
    - The highest rate was 5 in any 1 second.
  - **Slow mode during recon.** The scan paused with "median latency 2.1 s over the last 10 responses". Switching back to `ok` resumed it within 5 seconds, and recon finished normally.
  - **Fail mode during recon.** The scan paused with "target unavailable (HTTP 503)". After switching back to `ok`, the held request was re-sent and recon finished with all 8 endpoints.
  - **Kill switch during recon.** The next request was blocked with "kill switch", and the scan ended as **killed** within about a second.
  - **Kill switch while waiting for approvals.** The scan ended as **killed**, and the remaining tests can no longer be approved.
  - **Request counts.** The proxy's own count equalled "Sent to target" in every scan checked (111 = 111 and 10 = 10).
  - **Masking.** Every audit row showed passwords and tokens as `***`.

### Key decisions and why

- **Hold instead of drop.** Requests held for health or rate reasons wait their turn rather than fail. A short hiccup on the target then doesn't ruin a scan, and the scanner backs off instead of hammering.
- **Fail closed.** The self-test stops the scan if the gate is broken. An undecided high-risk test is denied. A target that stays down stops the scan.
- **Credentials are tied to tokens the gateway saw being issued.** Matching a username alone would not stop a token copied from somewhere else.
- **Retries only where they are safe.** A 503 or refused connection means the target did not process the request, so it is safe to send again. Reads are always safe to repeat. A write that failed in any other way is never repeated, because it might already have changed something.

### Limitations

- **Gateway state lives in the scanner's memory.** This covers tokens, pause state and the rate limit, while kill and pause flags are also saved to the database. Restarting the scanner mid-scan marks the scan interrupted (as before).
- **The rate limit is per scan.** Two scans running at once could together reach twice the cap.
- **A request already on the wire can't be recalled.** The kill switch stops everything after it, not a request that has already left.
- **A failed write isn't repeated.** If the target breaks in the middle of a non-503 write, the crawl step fails and the scan fails safely with a named step.
- **Approval is per test, not per individual request.** Phase 6 will send each approved test's requests tagged with the test, and the gate re-checks the approval on every one.
- **Recon is slower.** Because of the rate limit it now takes about 25–35 seconds instead of 11–16.
- **New columns again.** `scanner/data/scanner.db` must be deleted once after upgrading.

### How to see it working

See the step-by-step check in the project README ("Run the scanner"). The short version:

1. Run `scanner/.venv/bin/python scanner/scripts/check_gateway.py`. It should end with "23/23 checks passed".
2. Fire a scan and open its **Safety gateway** card.
   - You should see 5 red self-test blocks and the rate at 5/s or less.
   - The scan waits at Safety gateway. Approve or deny each high-risk test to let it continue.
3. To see the health monitor, run the proxy and start the scanner with `TARGET_URL=http://localhost:3099`. Switch the proxy to `slow` or `fail` during recon, then back to `ok`.
4. To see the kill switch, press it during recon.

## Phase 6 — The execution agents (run the approved tests, record raw results)

### What it is and why

Until Phase 5 the scanner only *decided* what to test. In this phase the **Execution** stage actually sends each cleared or approved test to the target and writes down what came back.

It records a **raw result** only: **suspicious** or **clean**, plus a little evidence. It does **not** call anything a vulnerability and does **not** give it a severity. One response can mislead, for example a 200 with an empty or harmless body. Phase 7 (verification) re-checks every suspicious result before anything counts as a finding, which protects precision. Phase 8 (triage) decides how serious each one is.

### Ground truth: the scanner makes its own test data

Before testing, the scanner signs in with the 4 test accounts. Then, for each test that needs one, it **creates its own synthetic booking** for agency A, with:
- customer "DAST Synthetic Customer"
- email `dast+synthetic@example.test`
- price ₹25,000

Because the scanner created that booking itself, it knows exactly who owns it, what it costs, and whether it has been paid or refunded. Each result is then a plain comparison between what the target returned and what a secure system must return.

There are two further benefits:
- The evidence never contains the seeded customers' personal details.
- The tests never change the platform's existing bookings.

In every cross-agency test, the "attacker" is an admin from the other agency (**B-admin**) and the "victim" is agency A's synthetic data.

### What each executor does

These are plain code with no AI involved. Each one uses the field names recon recorded for the endpoint.

| Test | What it sends | Suspicious if | Clean if |
|---|---|---|---|
| Cross-agency access, read by ID | B-admin reads A's synthetic booking, or A-admin's user record | 200 with agency A's data | 403 / 404 |
| Cross-agency access, payment | B-admin pays A's synthetic booking | accepted | refused |
| Cross-agency access, create booking | B-admin creates a booking for agency A | created | 403 |
| Zombie ownership check | B-admin reads A's synthetic booking on the old `/api/v1/...` path | 200 with agency A's data | 401 / 403 / 404 / 410 |
| Missing authentication | the endpoint with **no login at all** | 200 with data | 401 / 403 |
| Duplicate refund | A-admin creates a booking, pays it in full, refunds it once (legitimate), then refunds it again | the second refund is accepted | the second refund is refused |
| Amount validation, payment (price tampering) | A-admin pays a ₹25,000 synthetic booking with ₹1 | marked paid | refused |
| Amount validation, refund | refund ₹50,000 on a booking that paid ₹25,000 | accepted | refused |
| Role authorization | A-subagent (not an admin) tries to refund A's paid synthetic booking | allowed | 403 |
| Weak authentication | 3 common passwords (`password`, `123456`, `admin123`) against each test account | any of them signs in | none do |

The weak-password test also notes that the login page did not slow down or lock an account after wrong passwords. It records this as a **note, not a suspicious result**: it isn't one of the things we set out to find, and flagging it would hurt precision.

**Tests that aren't run normally:**
- **Denied (or never approved) at the safety gateway:** marked **skipped**. None of its requests are sent, not even its setup.
- **No recipe for that endpoint** (for example cross-agency access on search, which has no per-agency record): marked **skipped**, with the reason.
- **Setup fails, or the answer is neither the vulnerable nor the secure one:** marked **could not run**, with the reason. A result is never guessed.

### Every request still goes through the safety gateway

- **Same door as everything else.** Every request, including the setup of creating and paying a synthetic booking, goes through the same `TargetClient.send`.
- **Tagged with its test.** Each request carries the id of its test, so the gateway re-checks that test's approval on every single request. A denied money test cannot even create its booking.
- **Logins use only the 4 test accounts**, as before.
- **The weak-password guesses are allowed** because they use the provided test usernames. The passwords are masked in the audit log.

### What is stored

- **`test_cases`** gains a run status (`ran` / `skipped` / `could_not_run`), the raw result, a one-line summary and the time it ran. The approval history (`cleared` / `approved` / `denied`) is kept separately and unchanged.
- **`evidence`** stores one or two exchanges per test. Each has the masked request (who sent it, method, path, `Authorization: Bearer ***`, body) and **only the key fields** of the response, such as `agency_id`, `payment_status` or `total_refunded`. Lists are shown only as counts, never their contents.
- **No `vulnerabilities` rows and no severity** are written.

### Dashboard: the Execution card

A new card sits under the Safety gateway card:
- **Top line:** "5 suspicious · 6 clean · 0 skipped".
- **One row per test:** "ran" or "not run", the result (suspicious in amber, clean in green, skipped in grey) and the one-line summary.
- **Evidence:** click a row to see its masked request and the key response fields.
- **Footer:** these are raw results, not confirmed findings.

### What changes on the target

A scan adds, in agency A:
- about 7 synthetic bookings
- their payments and refunds
- new login tokens

If a cross-agency booking creation ever succeeded, it would add one more booking. `cd backend && python seed.py` wipes and rebuilds the target database, which removes all of it. Tested: after a scan the target had 19 bookings, 9 payments and 3 refunds. After `seed.py` it was back to 8, 5 and 1, with 0 synthetic bookings.

### How it was tested

**Scan 1, rule-based plan, all money tests approved.** Result: **5 suspicious, 6 clean, 0 skipped.**

| Result | Test | What came back |
|---|---|---|
| Suspicious | Cross-agency read | B-admin read A's synthetic booking: 200 with agency_id 1 |
| Suspicious | Duplicate refund | second refund 200; total refunded ₹50,000 on ₹25,000 paid |
| Suspicious | Price tampering | ₹25,000 booking marked paid for ₹1 |
| Suspicious | Zombie v1 | returned A's synthetic booking to B-admin |
| Suspicious | Shadow partner-details | 200 with data and no login |
| Clean | Over-refund | 400 |
| Clean | Sub-agent refund | 403 |
| Clean | Cross-agency payment | 404 |
| Clean | Cross-agency booking creation | 403 |
| Clean | Cross-agency user lookup | 404 |
| Clean | Weak passwords | 0 of 12 guesses worked |

The 5 suspicious results are exactly the 5 planted bugs. The 6 clean ones are true negatives that later phases can rely on.

**Scan 2, price tampering denied on the dashboard.** That test showed **skipped**. The audit log has no sent request tagged with it; it has only its hold, its denial, and the self-test block.

**Checks across both scans:**
- **Everything went through the gateway.** All 37 execution requests were allowed by it.
- **Nothing went around it.** The proxy's own count matched "Sent to target" exactly: 143 = 143.
- **No secrets were stored.** No password or token appears anywhere in the audit log.
- **Nothing was confirmed or graded.** The Findings card stayed empty, and the words "confirmed" and "severity" appear nowhere in the results.
- **The speed limit held.** The highest rate was 5 in any second.

**A rate-limit precision bug was found and fixed.** One earlier 1-second window held 6 requests: a database lookup between taking the speed-limit slot and actually sending let two requests drift 0.16 s apart. The slot is now taken immediately before sending. The gateway check script still passes 23/23.

### Key decisions and why

- **Synthetic bookings instead of the seeded ones.** This gives exact ground truth, no real-looking personal data in evidence, and no damage to existing records.
- **Each test makes its own booking.** Tests can't affect each other's results; for example, the duplicate refund test doesn't reuse a booking another test already refunded.
- **"Could not run" is a separate outcome.** An unexpected answer is not quietly counted as clean. That would hide problems and make the true negatives untrustworthy.
- **No lockout is not flagged.** It's a real weakness, but outside our test plan. It is recorded as a note so triage can decide later.

### Limitations

- **The executors know this platform's shape.** They rely on recon's field names and on simple path hints (a "booking" or "user" in the path). A very different API would need new recipes.
- **A cross-agency write that succeeds actually happens.** On a vulnerable target it really pays or creates the record, only ever on synthetic data. `seed.py` undoes it.
- **One attacker/victim pair.** B-admin attacks agency A; the reverse direction isn't tested separately.
- **Raw results only.** A single response decides suspicious or clean. Repeat checks and false-positive rejection are Phase 7's job.

### How to run it

1. Stop the scanner API.
2. Delete its database once, because new columns were added:
   ```bash
   rm -f scanner/data/scanner.db scanner/data/scanner.db-wal scanner/data/scanner.db-shm
   ```
3. Reset the target:
   ```bash
   cd backend && python seed.py
   ```
4. Start everything as usual and fire a scan.
5. Approve the money tests in the Safety gateway card. The **Execution** card fills in with 5 suspicious and 6 clean.
6. Click any row to see its evidence.
7. Deny a money test in a second scan to see it skipped.
8. Run `python seed.py` afterwards to remove the synthetic bookings.

## Phase 7 — Verification (prove it before it counts)

### What it is and why

Execution (Phase 6) marks a test **suspicious** from a single response, and one response can mislead. It might be a one-off glitch, a page that answers "200" to anything, or a "paid" message where nothing was actually paid. Precision is 20% of the judging, so this stage tries hard to **disprove** every suspicious result before it is reported.

A result becomes a **verified finding** only if it survives. Anything that doesn't is recorded as a **false positive**, with the exact reason.

Clean results are not re-run. They stay as the true negatives.

### The two checks every suspicious result must pass

1. **Repeat on fresh data.** The same attack is run again on a **new** synthetic booking, and it must give the same suspicious answer. This rules out glitches, caching and leftovers from earlier tests.
2. **An independent control check.** This is a different kind of proof that the effect is real:

| Test | Control check | Passes only if |
|---|---|---|
| Cross-agency read, old v1 version | The booking's **owner** reads the same booking, and B-admin also asks for an ID that **doesn't exist** | what B-admin got is identical to the owner's copy (id, agency, customer, amount) **and** the made-up ID is refused, so the endpoint isn't simply answering 200 to everything |
| Missing authentication | the same request **with** a valid login | the no-login answer has the same real fields as the logged-in one, not a placeholder or error message |
| Duplicate refund | the owner **reads the booking back** | the booking itself shows more refunded than paid |
| Price tampering | the owner reads the booking back | the booking shows "paid" with ₹1 against a ₹25,000 price |
| Cross-agency payment or booking creation, sub-agent refund, over-refund (if ever suspicious) | the owner reads the booking back | the change really happened |

**How the result is decided:**
- Both checks pass → **verified**.
- A check contradicts the raw result → **false positive**, with that check's detail as the reason.
- A check can't be carried out (for example the read-back failed) → **unverified**. It is left for a human and never quietly promoted.

All verification requests go through the safety gateway. They are tagged with the same test, so the earlier human approval and every gateway rule still apply, and they appear in the audit log under stage **verification**. They use fresh synthetic bookings, which `python seed.py` removes.

### What is stored

- **One `vulnerabilities` row per suspicious test.** It holds a plain title, the class, the endpoint, the test, and the status (`verified` / `false_positive` / `unverified`). It also stores the reason and each check with a pass or fail mark and one line of detail.
- **Verification evidence:** the repeat and control exchanges. These follow the same rule as before: the request is masked and only the key response fields are kept.
- **Severity, owner and duplicate-merging are left empty** for triage (Phase 8).

### Dashboard

**The Findings card** is now a full-width card under Execution. It shows:
- a top line: "5 verified · 0 false positives · 0 unverified"
- for each finding:
  - its title and status (verified in red, false positive in grey, unverified in amber)
  - each check, with ✓ or ✗ and its detail
  - "severity: set in triage"
  - expandable masked evidence

**In the Execution card,** each suspicious row now also carries its verification tag.

### Proving that false positives are rejected

On the practice target, all 5 suspicious results are genuinely real, so a live scan verifies all 5 and rejects none. To show that the rejection logic works, `scanner/scripts/check_verification.py` runs the real verification stage against a small fake platform held in memory, with nothing sent anywhere:

| Scenario | Result | Why |
|---|---|---|
| Truly vulnerable: cross-agency read, double refund, shadow missing auth | **verified** (3/3) | every check passes |
| Leaks once, then refuses on the repeat | **false positive** | repeat refused (404) |
| Answers 200 for every ID, even made-up ones | **false positive** | the made-up ID returned 200 |
| No-login answer is only a placeholder | **false positive** | its fields differ from the real data |
| Payment says "paid" but nothing changed | **false positive** | read-back shows unpaid, ₹0 paid |

All 7 scenarios behaved as expected.

### How it was tested live

A full scan used the rule-based plan with all money tests approved:
- **Execution:** 5 suspicious, 6 clean.
- **Verification: 5 verified, 0 false positives, 0 unverified.** Both checks passed on each:

| Finding | Check 1 | Check 2 |
|---|---|---|
| Cross-agency read | B-admin got fresh booking #1020 | identical to the owner's copy; made-up ID gave 404 |
| Price tampering | ₹1 payment accepted again | read-back: paid, ₹1 of ₹25,000 |
| Double refund | second refund accepted again | read-back: ₹50,000 refunded against ₹25,000 paid |
| Zombie v1 | leaked fresh booking #1023 | matches the owner's copy; made-up ID gave 404 |
| Shadow partner-details | no-login 200 again | same fields as the logged-in answer |

- **No severity was set** on any finding.
- **All 22 verification requests went through the gateway**, none were blocked, and no password or token appears in the audit log. The highest rate was 5 in any second.
- **Reset works.** The scan left 11 synthetic bookings. `seed.py` returned the target to 8 bookings with 0 synthetic.

### Key decisions and why

- **Two different kinds of proof.** Repeating alone wouldn't catch an endpoint that always says 200. A control check alone wouldn't catch a one-off glitch. Together they cover both.
- **Read the booking back for money bugs.** A "200 OK" message is just text. Only the booking's own totals show whether money actually moved.
- **"Unverified" is its own status.** A check that couldn't run is neither proof nor disproof, so a human decides.
- **The fake platform is used only to demonstrate rejection.** The live target has no misleading cases, so rejection can only be shown on purpose-built ones.

### Limitations

- **One repeat, not many.** A bug that only shows up intermittently could still be rejected as a false positive.
- **Comparisons use a fixed set of key fields.** These are id, agency, customer, amount and username. A different API would need its own list.
- **Clean results are trusted as they are.** A false *negative* would not be caught here.
- **Each verification adds synthetic bookings, payments and refunds to the target.** `seed.py` removes them.

### How to run it

1. Delete the scanner database once, because new columns were added:
   ```bash
   rm -f scanner/data/scanner.db scanner/data/scanner.db-wal scanner/data/scanner.db-shm
   ```
2. Reset the target:
   ```bash
   cd backend && python seed.py
   ```
3. Start everything as usual and fire a scan. Approve the money tests.
4. Watch the **Findings** card fill in with 5 verified findings and their checks.
5. Run the fake-platform check (no servers needed). It should end with "all scenarios behaved as expected":
   ```bash
   scanner/.venv/bin/python scanner/scripts/check_verification.py
   ```
6. Run `python seed.py` afterwards.

## Phase 8 — Triage (rank it, size it, give it to the right team)

### What it is and why

Verification leaves us with a set of proven findings. These are not yet something a team can act on:
- some are the same flaw found twice
- none has a severity
- nobody owns them

The brief describes triage as: remove duplicates, score severity in business context, and map each finding to an owner. It also says a human checks high-severity findings before they are escalated. Triage does exactly that.

Triage only works on what the scanner already recorded. **It sends no requests to the target.**

### What it does

1. **Merges duplicates.** Each verified finding gets a root-cause key made of the type of flaw, the method and the path with any version prefix (like `/v1`) removed. Findings with the same key are one flaw.
   - The finding on the current (active) endpoint becomes the main one.
   - The others are linked to it as **"also affects"**, with their inventory label.
   - On the practice target, the old v1 booking leak is merged into the main booking leak, so 5 verified findings become **4**.
2. **Scores severity by what the endpoint means to the business.** It uses fixed, readable rules (no AI), so every result can be explained and comes out the same on every run:

| Factor | Points |
|---|---|
| **At stake** | money paid out or lost 5 · customer personal data 3 · account takeover 3 · partner and supplier data 2 · internal information 1 |
| **Who can do it** | anyone with no login 3 · any agency user 2 · only a lower role 1 |
| **Exposure** | +1 if the flaw can be reached through a zombie or shadow endpoint that nobody watches |

   A score of 7 or more is **critical**, 5–6 is **high**, 3–4 is **medium**, and below that is **low**. Each finding shows the reason, for example: "at stake: money paid out or lost (+5) · who can do it: any agency user, on their own bookings (+2) → score 7 = critical".

3. **Writes a business-impact line** in plain words, with the real numbers from the test. For example: "An agency can refund the same booking more than once and be paid out more than it ever paid. In the test: booking #1022 now shows ₹50,000 refunded against ₹25,000 paid."
4. **Assigns an owner.** A new `ownership` list in `scanner/target_profile.json` maps path prefixes to teams. The brief lists asset ownership data as an input we may use. A path not on the list falls back to the team inventory guessed from the endpoint's purpose, and is shown as **(guessed)**.
5. **Holds critical and high findings for human review.** On the dashboard a reviewer can:
   - **Confirm** the severity
   - **Change severity**, which requires a reason; the list re-ranks itself

   Each decision is written to the audit log (stage **triage**, nothing sent). Medium and low findings don't need review. Reports (Phase 9) will escalate only reviewed findings.
6. **Matches earlier scans.** A finding whose root-cause key was already verified in an earlier scan shows **"first seen in scan N"**, so new problems stand apart from known ones. Retest (Phase 10) will build on this.

**False positives and unverified results are not ranked.** They are listed below the ranked list under "Not ranked".

### Dashboard

The **Findings** card is now a ranked list.
- **Top line:** "4 findings · 2 critical · 2 high · 1 duplicate merged · 4 awaiting review".
- **Each finding:**
  - rank and severity chip (critical solid red, high light red, medium amber, low grey)
  - title, owner, and "new in this scan" or "first seen in scan N"
  - impact line and why-severity line
  - "also affects" endpoints
  - the verification checks, review controls and evidence

### How it was tested

**`scanner/scripts/check_triage.py`** builds verified findings in a scratch database, in the same shape Phase 7 produces, and runs the real triage stage and review API. No servers are needed. **28/28 checks passed**, covering:
- merging
- each severity rule (critical, high, medium, low)
- owners from the ownership list and guessed owners
- the real numbers in the impact line
- false positives and unverified results kept out of the ranking
- earlier-scan matching
- 0 audit rows from triage
- the review API: confirm, no second review, a reason is required, re-ranking after a downgrade, false positives and merged duplicates refused, and each decision audited

**Live scan 1** (rule-based plan, money tests approved):

| Rank | Severity | Finding | Owner |
|---|---|---|---|
| 1 | critical | Price tampering on POST /api/payments (₹1 paid of ₹25,000) | Payments team |
| 2 | critical | Duplicate refund on POST /api/refunds (₹50,000 refunded against ₹25,000 paid) | Payments team |
| 3 | high | Cross-agency booking read on GET /api/bookings/{id}, also affects GET /api/v1/bookings/{id} (zombie) | Bookings team |
| 4 | high | No login on GET /api/internal/partner-details (shadow) | Partner integrations (guessed) |

- Triage wrote **0 audit rows** and sent nothing. The scan's highest rate was 5 requests per second.
- On the dashboard, finding 1 was confirmed and finding 4 was changed to medium with a reason. Both appear in the audit log with stage triage and sent = no.

**Live scan 2:** the same 4 findings, each marked **"first seen in scan 1"**, again with 0 triage audit rows. The target was reseeded after both scans.

### Key decisions and why

- **Rules, not the LLM, for severity.** Severity drives what gets fixed first, so it must be explainable and the same every time. Each point in the score is shown.
- **The current endpoint leads a merged finding.** The fix belongs in the code that is in use. The zombie copy is listed so it gets turned off, and it raises the severity because nobody watches it.
- **A human reviews serious findings, and a severity change needs a reason.** The brief asks for this. It also keeps the scanner from escalating a critical on its own.

### Limitations

- **The severity points are our judgement.** They are fixed and shown in full, but they are not a standard like CVSS.
- **The impact text is a template for each test type.** A new kind of test would need its own line.
- **The ownership list is a small hand-written input.** In real use it would come from a service catalogue.
- **Merging only joins the same flaw on the same route across versions.** Two different routes with one shared bug stay separate.

### How to run it

1. Delete the scanner database once, because new columns were added:
   ```bash
   rm -f scanner/data/scanner.db scanner/data/scanner.db-wal scanner/data/scanner.db-shm
   ```
2. Reseed the target and start everything as usual.
3. Run a scan and approve the money tests.
4. The **Findings** card shows 4 ranked findings.
5. Confirm one finding and change another's severity with a reason. Check both in the Safety gateway audit log.
6. Run a second scan and look for "first seen in scan 1".
7. Run the rules check (no servers needed). It should end with 28/28:
   ```bash
   scanner/.venv/bin/python scanner/scripts/check_triage.py
   ```
