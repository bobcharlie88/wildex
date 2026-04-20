import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from app.config import (
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE,
    SESSION_MAX_AGE_SECONDS,
    SESSION_SECRET,
)
from app.database import SessionLocal, db_available
from app.models import User


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 240_000)
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{salt}${digest_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, expected = password_hash.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, f"{salt}${expected}")


def _sign(data: bytes) -> str:
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).decode("ascii")


def create_session_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": int(datetime.now(timezone.utc).timestamp()) + SESSION_MAX_AGE_SECONDS,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    signature = _sign(body.encode("utf-8"))
    return f"{body}.{signature}"


def parse_session_token(token: str | None) -> int | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(body.encode("utf-8")), signature):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        return None
    user_id = payload.get("user_id")
    return int(user_id) if isinstance(user_id, int) or str(user_id).isdigit() else None


def get_current_user(request: Request) -> User | None:
    if not db_available():
        return None
    user_id = parse_session_token(request.cookies.get(SESSION_COOKIE_NAME))
    if not user_id:
        return None
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def require_user(request: Request) -> User:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


def session_cookie_settings() -> dict:
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "max_age": SESSION_MAX_AGE_SECONDS,
        "samesite": "lax",
        "secure": SESSION_COOKIE_SECURE,
        "path": "/",
    }
