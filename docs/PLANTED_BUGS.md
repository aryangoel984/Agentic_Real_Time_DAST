# Planted Bugs — DEV ONLY (answer key)

> This file is the answer key for our mock target. The scanner must never read it.
> All data is synthetic. Every bug can be switched off with its `FIX_*` setting (see `backend/app/config.py`).
> Reset the data before each run: `cd backend && python seed.py`

## Setup for the commands below

Start the target (from `backend/`): `uvicorn app.main:app --port 8000`

Get tokens (copy each `"token"` value from the response):

```bash
# B-admin (Mumbai Holidays)
curl -s -X POST http://localhost:8000/api/login -H 'Content-Type: application/json' \
  -d '{"username":"b_admin","password":"MumbaiAdmin@123"}'

# A-admin (Delhi Travels)
curl -s -X POST http://localhost:8000/api/login -H 'Content-Type: application/json' \
  -d '{"username":"a_admin","password":"DelhiAdmin@123"}'
```

Then: `export B_TOKEN=<b_admin token>` and `export A_TOKEN=<a_admin token>`.

| # | Name | Class | Endpoint | Fix switch |
|---|------|-------|----------|-----------|
| 1 | Cross-agency IDOR | Access control | `GET /api/bookings/{id}` | `FIX_IDOR` |
| 2 | Double refund | Business logic | `POST /api/refunds` | `FIX_DOUBLE_REFUND` |
| 3 | Price tampering | Business logic | `POST /api/payments` | `FIX_PRICE_TAMPER` |
| 4 | Zombie endpoint | Zombie API + access control | `GET /api/v1/bookings/{id}` | `FIX_ZOMBIE` |
| 5 | Missing authentication | Shadow API + API hygiene | `GET /api/internal/partner-details` | `FIX_SHADOW_AUTH` |

---

## 1. Cross-agency IDOR — `GET /api/bookings/{id}`

**Flaw:** the endpoint checks that you are logged in, but not that the booking belongs to your agency.

```bash
curl -s http://localhost:8000/api/bookings/1001 -H "Authorization: Bearer $B_TOKEN"
```

**Vulnerable result:** `200`, with Delhi Travels' booking: customer Rahul Verma, his email and phone, ₹25,000.
**Fixed result (`FIX_IDOR=true`):** `404 Booking not found`.
**Business impact:** any agency can read every competitor's bookings and customer personal data.

## 2. Double refund — `POST /api/refunds`

**Flaw:** no check for whether the booking was already refunded.

```bash
# run this twice
curl -s -X POST http://localhost:8000/api/refunds -H "Authorization: Bearer $B_TOKEN" \
  -H 'Content-Type: application/json' -d '{"booking_id":1002,"amount":18000}'
```

**Vulnerable result:** both calls return `200`. After the second call, `total_refunded` is 36000 and `amount_paid` is 18000.
**Fixed result (`FIX_DOUBLE_REFUND=true`):** the first call returns `200` and the second returns `409 Booking has already been refunded`.
**Business impact:** money is paid out twice for one booking.

## 3. Price tampering — `POST /api/payments`

**Flaw:** the server charges whatever amount the client sends, and still marks the booking fully paid.

```bash
curl -s -X POST http://localhost:8000/api/payments -H "Authorization: Bearer $A_TOKEN" \
  -H 'Content-Type: application/json' -d '{"booking_id":1001,"amount":100}'
```

**Vulnerable result:** `200` with `"booking_price":25000, "amount_charged":100, "payment_status":"paid"`.
**Fixed result (`FIX_PRICE_TAMPER=true`):** `400 Amount must equal the booking price (25000.0)`.
**Business impact:** a ₹25,000 trip is bought for ₹100.
*(Only unpaid bookings can be paid. After a reset, the unpaid ones are 1001 and 1008. Booking 1005 is also unpaid but belongs to agency B, so use B_TOKEN for it.)*

## 4. Zombie endpoint — `GET /api/v1/bookings/{id}`

**Flaw:** an old v1 route is still live. The frontend no longer calls it, and the traffic log shows **zero** hits in 60 days. It never got the agency ownership check.

```bash
curl -s http://localhost:8000/api/v1/bookings/1001 -H "Authorization: Bearer $B_TOKEN"
```

**Vulnerable result:** `200` with agency A's booking. This leaks even when Bug 1 is fixed, because the old route is a separate path.
**Fixed result (`FIX_ZOMBIE=true`):** `410 API v1 has been retired`.
**Business impact:** a forgotten back door around the current access controls.

## 5. Missing authentication — `GET /api/internal/partner-details`

**Flaw:** an undocumented internal route that needs no token at all. It is **used**: the traffic log shows an internal sync job (`10.0.4.17`, `partner-sync/1.4`) calling it about every 3 days. But it is **not** listed in the frontend route manifest. That makes it a shadow API.

```bash
curl -s http://localhost:8000/api/internal/partner-details
```

**Vulnerable result:** `200` with commission rates, credit limits, supplier markups and supplier API keys. All of these values are fake.
**Fixed result (`FIX_SHADOW_AUTH=true`):** `401` without a token, and `403` for non-admins.
**Business impact:** anyone on the internet can read confidential commercial terms and supplier credentials.

---

## Turning fixes on

```bash
cd backend
python seed.py
FIX_IDOR=true FIX_DOUBLE_REFUND=true uvicorn app.main:app --port 8000   # any combination
```

`GET http://localhost:8000/` shows which fixes are currently on.
