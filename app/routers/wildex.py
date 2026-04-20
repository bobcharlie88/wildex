from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import get_current_user

router = APIRouter()


@router.get("/wildex")
def wildex(request: Request):
    if get_current_user(request) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse("app/static/wildex.html")
