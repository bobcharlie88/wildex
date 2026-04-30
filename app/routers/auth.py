import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.auth import (
    create_session_token,
    get_current_user,
    hash_one_time_token,
    hash_password,
    session_cookie_settings,
    verify_password,
)
from app.config import APP_BASE_URL, PASSWORD_RESET_TOKEN_TTL_SECONDS
from app.database import SessionLocal, db_available
from app.models import PasswordResetToken, User
from app.services.email import email_configured, send_email

router = APIRouter()


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _validate_credentials(email: str, password: str) -> tuple[str, str]:
    email = _normalize_email(email)
    password = password or ""
    if not email or "@" not in email:
        raise HTTPException(400, "Enter a valid email address")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    return email, password


def _login_response(user: User) -> JSONResponse:
    response = JSONResponse({"ok": True, "user": {"id": user.id, "email": user.email}})
    response.set_cookie(value=create_session_token(user.id), **session_cookie_settings())
    return response


@router.get("/login")
def login_page():
    return FileResponse("app/static/login.html")


@router.get("/reset-password")
def reset_password_page():
    return FileResponse("app/static/reset_password.html")


@router.get("/auth/me")
def auth_me(request: Request):
    user = get_current_user(request)
    if user is None:
        raise HTTPException(401, "Not signed in")
    return {"id": user.id, "email": user.email, "favorite_card_id": user.favorite_card_id}


@router.post("/auth/register")
async def auth_register(request: Request):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    data = await request.json()
    email, password = _validate_credentials(data.get("email", ""), data.get("password", ""))

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(409, "An account with that email already exists")
        user = User(email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return _login_response(user)
    finally:
        db.close()


@router.post("/auth/login")
async def auth_login(request: Request):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    data = await request.json()
    email, password = _validate_credentials(data.get("email", ""), data.get("password", ""))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(401, "Invalid email or password")
        return _login_response(user)
    finally:
        db.close()


@router.post("/auth/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    settings = session_cookie_settings()
    response.delete_cookie(
        key=settings["key"],
        path=settings["path"],
        httponly=settings["httponly"],
        samesite=settings["samesite"],
        secure=settings["secure"],
    )
    return response


@router.post("/auth/forgot-password")
async def auth_forgot_password(request: Request):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    data = await request.json()
    email = _normalize_email(data.get("email", ""))
    if not email or "@" not in email:
        raise HTTPException(400, "Enter a valid email address")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            now = datetime.now(timezone.utc)
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            ).update({"used_at": now}, synchronize_session=False)
            raw_token = secrets.token_urlsafe(32)
            token = PasswordResetToken(
                user_id=user.id,
                token_hash=hash_one_time_token(raw_token),
                expires_at=now + timedelta(seconds=PASSWORD_RESET_TOKEN_TTL_SECONDS),
                requested_ip=(request.client.host if request.client else None),
            )
            db.add(token)
            db.commit()
            reset_url = f"{APP_BASE_URL or str(request.base_url).rstrip('/')}/reset-password?token={raw_token}"
            email_sent = send_email(
                to_email=user.email,
                subject="WildEx password reset",
                text_body=(
                    "A password reset was requested for your WildEx account.\n\n"
                    f"Reset your password here:\n{reset_url}\n\n"
                    f"This link expires in {PASSWORD_RESET_TOKEN_TTL_SECONDS // 60} minutes."
                ),
            )
            if not email_sent:
                # Keep the flow generic for users; the fallback is logged for environments without SMTP.
                import logging
                logging.getLogger("wildex.auth").warning("Password reset link for %s: %s", user.email, reset_url)
        return {
            "ok": True,
            "message": "If that account exists, password reset instructions have been sent.",
            "email_delivery": "sent" if user is not None and email_configured() else "pending",
        }
    finally:
        db.close()


@router.post("/auth/reset-password")
async def auth_reset_password(request: Request):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    data = await request.json()
    token_value = str(data.get("token") or "").strip()
    password = data.get("password") or ""
    if not token_value:
        raise HTTPException(400, "Reset token missing")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        token = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.token_hash == hash_one_time_token(token_value),
                PasswordResetToken.used_at.is_(None),
            )
            .first()
        )
        if token is None or token.expires_at.replace(tzinfo=timezone.utc) < now:
            raise HTTPException(400, "This reset link is invalid or expired")
        user = db.query(User).filter(User.id == token.user_id).first()
        if user is None:
            raise HTTPException(400, "This reset link is invalid or expired")
        user.password_hash = hash_password(password)
        token.used_at = now
        db.commit()
        return _login_response(user)
    finally:
        db.close()
