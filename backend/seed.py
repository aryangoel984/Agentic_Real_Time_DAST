"""Reset the database to a known starting state.

Run from the backend/ folder:   python seed.py

Wipes every table and rebuilds it, so every demo and every retest starts
from exactly the same data. All people, emails and phone numbers are fake.
"""
from datetime import datetime, timedelta, timezone

from app.auth import hash_password
from app.db import (Agency, Base, Booking, Payment, Refund, SessionLocal, User,
                    engine)

# ---------------------------------------------------------------------------
# DEV-ONLY plaintext test accounts. Never do this outside a mock target.
# The database itself only stores the hashed versions.
# ---------------------------------------------------------------------------
TEST_ACCOUNTS = [
    # username      password          role        agency  full name
    ("a_admin",     "DelhiAdmin@123",  "admin",    "A",    "Ritu Sharma"),
    ("a_subagent",  "DelhiSub@123",    "subagent", "A",    "Karan Mehta"),
    ("b_admin",     "MumbaiAdmin@123", "admin",    "B",    "Anjali Desai"),
    ("b_subagent",  "MumbaiSub@123",   "subagent", "B",    "Rohan Patil"),
]
# The fifth "account" is no account at all: calls with no token (unauthenticated).

AGENCIES = [
    (1, "A", "Delhi Travels", "New Delhi"),
    (2, "B", "Mumbai Holidays", "Mumbai"),
]

# id, agency, booked_by(username), customer, item, travel_date, amount, paid?, refundable?, already_refunded?
BOOKINGS = [
    (1001, "A", "a_admin",    "Rahul Verma",  "Flight DEL-BOM FL-221, 2 pax",   "2026-12-18", 25000, False, True,  False),
    (1002, "B", "b_admin",    "Amit Kulkarni", "Flight BOM-GOI FL-348, 3 pax",  "2026-12-22", 18000, True,  True,  False),
    (1003, "A", "a_subagent", "Priya Nair",   "Hotel Seaside Residency, 5 nts", "2027-01-05", 42500, True,  True,  False),
    (1004, "A", "a_subagent", "Sneha Iyer",   "Flight DEL-BLR FL-512, 1 pax",   "2026-11-29",  9800, True,  False, False),
    (1005, "B", "b_subagent", "Vikram Joshi", "Hotel Harbour View Inn, 6 nts",  "2027-01-12", 31200, False, True,  False),
    (1006, "B", "b_subagent", "Neha Shah",    "Flight BOM-DEL FL-221, 2 pax",   "2026-11-20", 15600, True,  True,  True),
    (1007, "A", "a_admin",    "Arjun Kapoor", "Hotel Grand Palms Suites, 4 nts", "2027-02-02", 67000, True,  True,  False),
    (1008, "B", "b_admin",    "Kavya Reddy",  "Flight BOM-CCU FL-348, 1 pax",   "2026-12-30", 12300, False, False, False),
]


def seed() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        agency_ids = {}
        for aid, code, name, city in AGENCIES:
            db.add(Agency(id=aid, code=code, name=name, city=city))
            agency_ids[code] = aid

        user_ids = {}
        for uid, (username, password, role, agency, full_name) in enumerate(TEST_ACCOUNTS, start=1):
            db.add(User(id=uid, username=username, password_hash=hash_password(password),
                        full_name=full_name, email=f"{username}@example.com",
                        role=role, agency_id=agency_ids[agency]))
            user_ids[username] = uid
        db.flush()

        base = datetime.now(timezone.utc) - timedelta(days=20)
        for i, (bid, agency, booker, customer, item, date, amount, paid, refundable, refunded) \
                in enumerate(BOOKINGS):
            created = base + timedelta(days=i * 2)
            slug = customer.split()[0].lower()
            db.add(Booking(id=bid, agency_id=agency_ids[agency], user_id=user_ids[booker],
                           customer_name=customer, customer_email=f"{slug}@example.com",
                           customer_phone=f"+91-90000-0{bid}", item=item, travel_date=date,
                           amount=amount, payment_status="paid" if paid else "unpaid",
                           refund_eligible=refundable,
                           refund_status="refunded" if refunded else "none",
                           created_at=created))
            if paid:
                db.add(Payment(booking_id=bid, amount=amount, paid_by=user_ids[booker],
                               created_at=created + timedelta(hours=1)))
            if refunded:
                admin = "a_admin" if agency == "A" else "b_admin"
                db.add(Refund(booking_id=bid, amount=amount, refunded_by=user_ids[admin],
                              created_at=created + timedelta(days=1)))
        db.commit()
    finally:
        db.close()
    print(f"Seeded {len(AGENCIES)} agencies, {len(TEST_ACCOUNTS)} users, {len(BOOKINGS)} bookings.")
    print("Test accounts (dev only):")
    for username, password, role, agency, _ in TEST_ACCOUNTS:
        print(f"  {username:<11} {password:<16} {role:<9} agency {agency}")


if __name__ == "__main__":
    seed()
