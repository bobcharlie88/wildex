from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/wildex")
def wildex():
    return FileResponse("app/static/wildex.html")
