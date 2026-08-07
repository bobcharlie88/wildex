from typing import Optional
from fastapi import APIRouter, Depends

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import User
from app.services.spatial_map import get_explore_map_data

router = APIRouter()


@router.get("/explore/map")
def get_explore_map(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    current_user: User = Depends(require_user),
):
    if not db_available():
        return {"public_markers": [], "user_private_markers": [], "nearby_targets": []}
    db = SessionLocal()
    try:
        return get_explore_map_data(
            db,
            user_id=current_user.id,
            user_lat=lat,
            user_lon=lon,
        )
    finally:
        db.close()
