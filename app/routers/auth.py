from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.auth import create_session_token, get_current_user, hash_password, session_cookie_settings, verify_password
from app.database import SessionLocal, db_available
from app.models import User

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


@router.get("/auth/me")
def auth_me(request: Request):
    user = get_current_user(request)
    if user is None:
        raise HTTPException(401, "Not signed in")
    return {"id": user.id, "email": user.email}


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
    response.delete_cookie(session_cookie_settings()["key"], path="/")
    return response
