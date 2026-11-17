"""Mock B2B travel platform: the TARGET our security scanner will test.

Contains exactly five deliberately planted vulnerabilities. Each one is
marked with a `PLANTED BUG #n` comment and can be closed with its FIX_*
switch in config.py. Everything else is written to behave correctly.
All data is synthetic.
"""
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from . import config
from .auth import current_user, issue_token, verify_password
from .db import Agency, Booking, Payment, Refund, User, get_db

# Auto-generated API docs (/docs, /redoc, /openapi.json) are switched off so the
# scanner cannot use them as a shortcut: it must discover routes from the outside.
app = FastAPI(title="TravelHub B2B (mock target)", version="3.2.0",
              docs_url=None, redoc_url=None, openapi_url=None)


# ---------- request bodies ----------

class LoginIn(BaseModel):
    username: str
    password: str


class BookingIn(BaseModel):
    user_id: int
    agency_id: int
    amount: float = Field(gt=0)
    customer_name: str = "Walk-in Customer"
    customer_email: str = "customer@example.com"
    customer_phone: str = "+91-90000-00000"
    item: str = "Flight DEL-BOM"
    travel_date: str = "2026-12-20"


class PaymentIn(BaseModel):
    booking_id: int
    amount: float = Field(gt=0)


class RefundIn(BaseModel):
    booking_id: int
    amount: float = Field(gt=0)


# ---------- helpers ----------

def booking_view(b: Booking, db: DBSession) -> dict:
    agency = db.get(Agency, b.agency_id)
    paid = sum(p.amount for p in db.scalars(select(Payment).where(Payment.booking_id == b.id)))
    refunded = sum(r.amount for r in db.scalars(select(Refund).where(Refund.booking_id == b.id)))
    return {
        "id": b.id,
        "agency_id": b.agency_id,
        "agency_name": agency.name if agency else None,
        "booked_by_user_id": b.user_id,
        "customer_name": b.customer_name,
        "customer_email": b.customer_email,
        "customer_phone": b.customer_phone,
        "item": b.item,
        "travel_date": b.travel_date,
        "amount": b.amount,
        "payment_status": b.payment_status,
        "total_paid": paid,
        "refund_eligible": b.refund_eligible,
        "refund_status": b.refund_status,
        "total_refunded": refunded,
    }


def get_booking_or_404(db: DBSession, booking_id: int) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


def require_same_agency(user: User, booking: Booking) -> None:
    # Return 404 (not 403) so outsiders can't even confirm the booking exists.
    if booking.agency_id != user.agency_id:
        raise HTTPException(status_code=404, detail="Booking not found")


# ---------- core endpoints (the legitimate surface) ----------

@app.get("/")
def health():
    return {"service": "TravelHub B2B (mock target)", "status": "ok", "fixes": config.active_fixes()}


@app.post("/api/login")
def login(body: LoginIn, db: DBSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": issue_token(db, user), "user_id": user.id,
            "role": user.role, "agency_id": user.agency_id}


@app.get("/api/search")
def search(type: str = "flight", origin: str = "DEL", destination: str = "BOM",
           user: User = Depends(current_user)):
    if type == "hotel":
        return {"type": "hotel", "city": destination, "results": [
            {"code": "HTL-501", "name": "Seaside Residency", "per_night": 6500},
            {"code": "HTL-502", "name": "Harbour View Inn", "per_night": 4200},
            {"code": "HTL-503", "name": "Grand Palms Suites", "per_night": 11800},
        ]}
    return {"type": "flight", "origin": origin, "destination": destination, "results": [
        {"code": "FL-221", "carrier": "SkyIndia", "departs": "06:10", "fare": 5400},
        {"code": "FL-348", "carrier": "AirVista", "departs": "11:45", "fare": 6150},
        {"code": "FL-512", "carrier": "SkyIndia", "departs": "19:30", "fare": 4890},
    ]}


@app.post("/api/bookings", status_code=201)
def create_booking(body: BookingIn, user: User = Depends(current_user),
                   db: DBSession = Depends(get_db)):
    # You can only book for your own agency, and only on behalf of a user in it.
    if body.agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="Cannot create bookings for another agency")
    booker = db.get(User, body.user_id)
    if booker is None or booker.agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="user_id must belong to your agency")
    b = Booking(agency_id=body.agency_id, user_id=body.user_id, amount=body.amount,
                customer_name=body.customer_name, customer_email=body.customer_email,
                customer_phone=body.customer_phone, item=body.item,
                travel_date=body.travel_date, payment_status="unpaid",
                refund_eligible=True, refund_status="none")
    db.add(b)
    db.commit()
    db.refresh(b)
    return booking_view(b, db)


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: int, user: User = Depends(current_user),
                db: DBSession = Depends(get_db)):
    b = get_booking_or_404(db, booking_id)
    # PLANTED BUG #1 — Cross-agency IDOR.
    # The ownership check only runs when FIX_IDOR is on, so any logged-in
    # user from any agency can read any booking (including customer PII).
    if config.FIX_IDOR:
        require_same_agency(user, b)
    return booking_view(b, db)


@app.post("/api/payments")
def pay(body: PaymentIn, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    b = get_booking_or_404(db, body.booking_id)
    require_same_agency(user, b)
    if b.payment_status == "paid":
        raise HTTPException(status_code=409, detail="Booking is already paid")
    # PLANTED BUG #3 — Price tampering.
    # The server should charge the booking's own price. Instead it trusts
    # whatever amount the client sends and still marks the booking fully paid.
    if config.FIX_PRICE_TAMPER and body.amount != b.amount:
        raise HTTPException(status_code=400,
                            detail=f"Amount must equal the booking price ({b.amount})")
    charged = body.amount
    db.add(Payment(booking_id=b.id, amount=charged, paid_by=user.id))
    b.payment_status = "paid"
    db.commit()
    return {"booking_id": b.id, "booking_price": b.amount, "amount_charged": charged,
            "payment_status": b.payment_status}


@app.post("/api/refunds")
def refund(body: RefundIn, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only agency admins can issue refunds")
    b = get_booking_or_404(db, body.booking_id)
    require_same_agency(user, b)
    if b.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Booking has not been paid")
    if not b.refund_eligible:
        raise HTTPException(status_code=400, detail="Booking fare is non-refundable")
    paid = sum(p.amount for p in db.scalars(select(Payment).where(Payment.booking_id == b.id)))
    if body.amount > paid:
        raise HTTPException(status_code=400, detail=f"Refund cannot exceed amount paid ({paid})")
    # PLANTED BUG #2 — Double refund.
    # Nothing stops a booking that is already refunded from being refunded
    # again, so the same money can be paid out twice.
    if config.FIX_DOUBLE_REFUND and b.refund_status == "refunded":
        raise HTTPException(status_code=409, detail="Booking has already been refunded")
    db.add(Refund(booking_id=b.id, amount=body.amount, refunded_by=user.id))
    b.refund_status = "refunded"
    db.commit()
    total = sum(r.amount for r in db.scalars(select(Refund).where(Refund.booking_id == b.id)))
    return {"booking_id": b.id, "refunded_now": body.amount, "total_refunded": total,
            "amount_paid": paid, "refund_status": b.refund_status}


@app.get("/api/users/{user_id}")
def get_user(user_id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None or target.agency_id != user.agency_id:
        raise HTTPException(status_code=404, detail="User not found")
    agency = db.get(Agency, target.agency_id)
    return {"id": target.id, "username": target.username, "full_name": target.full_name,
            "email": target.email, "role": target.role, "agency_id": target.agency_id,
            "agency_name": agency.name if agency else None}


# ---------- leftovers the current frontend does not use ----------

@app.get("/api/v1/bookings/{booking_id}")
def get_booking_v1(booking_id: int, user: User = Depends(current_user),
                   db: DBSession = Depends(get_db)):
    # PLANTED BUG #4 — Zombie endpoint.
    # Old v1 route from before the current API. Nothing calls it any more,
    # but it is still live and never got the agency ownership check.
    if config.FIX_ZOMBIE:
        raise HTTPException(status_code=410, detail="API v1 has been retired")
    b = get_booking_or_404(db, booking_id)
    return booking_view(b, db)


@app.get("/api/internal/partner-details")
def partner_details(authorization: str | None = Header(default=None),
                    db: DBSession = Depends(get_db)):
    # PLANTED BUG #5 — Missing authentication (shadow route).
    # Used by an internal partner-sync job, never documented, and reachable
    # with no token at all. Data below is synthetic.
    if config.FIX_SHADOW_AUTH:
        caller = current_user(authorization, db)   # raises 401 without a valid token
        if caller.role != "admin":
            raise HTTPException(status_code=403, detail="Admins only")
    agencies = db.scalars(select(Agency)).all()
    return {
        "note": "internal use only",
        "agencies": [{"id": a.id, "name": a.name, "city": a.city,
                      "commission_rate_pct": 7.5 if a.code == "A" else 6.0,
                      "credit_limit_inr": 1_500_000 if a.code == "A" else 1_000_000}
                     for a in agencies],
        "suppliers": [
            {"name": "SkyIndia (synthetic)", "contract": "NET-30", "markup_pct": 4.0,
             "sandbox_api_key": "SANDBOX-SKY-0000-FAKE"},
            {"name": "Seaside Hotels (synthetic)", "contract": "PREPAID", "markup_pct": 9.5,
             "sandbox_api_key": "SANDBOX-SEA-0000-FAKE"},
        ],
    }
