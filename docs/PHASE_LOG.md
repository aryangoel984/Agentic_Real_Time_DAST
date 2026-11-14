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
- The automatic API reference page at `/docs` lists every address, including the hidden ones. It's convenient for checking things by hand now, but the agents must not be allowed to use it. It will be switched off before the scanner phases.
- The fake website code file isn't served over the web yet. It's just a file in the project.

### How to see it working

Use the clickable portal described in Phase 0.1 below. The original method still works too: open **http://localhost:8000/docs** while the backend is running, log in there, and try each address. The ready-made commands for all five holes are in `docs/PLANTED_BUGS.md`.

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
- `/docs` on the backend (port 8000) still lists every address. It will be switched off before the scanner phases.

### How to see it working

1. Start the backend and the portal in two Terminal tabs (see `README.md`). Open **http://localhost:3000**.
2. Sign in as `b_admin`. The password is in `backend/seed.py`. Look up booking **1001**: Rahul's booking appears under a red "Another agency's booking" banner. That is hole #1.
3. Still as `b_admin`, look up **1002** and press **Refund** twice. Both succeed, and "Refunded" shows ₹36,000 in red against ₹18,000 paid. That is hole #2.
4. Sign out and sign in as `a_admin`. Look up **1001**, change the Pay amount to **100**, and press **Pay**. It's accepted and the booking shows "paid" with ₹100 paid. That is hole #3.
5. Open **Request console** and send `GET /api/v1/bookings/1002`. You get another agency's booking through the old route. That is hole #4.
6. Untick "Send my login token" and send `GET /api/internal/partner-details`. You get confidential partner data with no login. That is hole #5.
7. Run `python seed.py` in `backend/` to reset everything.
