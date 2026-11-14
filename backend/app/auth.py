"""Password hashing and login tokens.

- Passwords: PBKDF2-SHA256 from Python's standard library (no bcrypt dependency).
- Tokens: random opaque strings stored in the `sessions` table, sent as
  `Authorization: Bearer <token>`. Deliberately not JWT, so we don't
  accidentally plant extra token bugs beyond the five on purpose.
"""
import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session as DBSession

from .db import Session, User, get_db

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def issue_token(db: DBSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(token=token, user_id=user.id))
    db.commit()
    return token


def current_user(authorization: str | None = Header(default=None),
                 db: DBSession = Depends(get_db)) -> User:
    """Require a valid Bearer token; return the logged-in user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    session = db.get(Session, token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
