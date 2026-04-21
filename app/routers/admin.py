from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_admin_user
from app.database import SessionLocal, db_available
from app.models import CardTemplate, User
from app.services.card_templates import clear_template_cache, ensure_builtin_templates, list_templates

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/templates")
def admin_templates(current_user: User = Depends(require_admin_user)):
    if not db_available():
        return {"items": [selection.__dict__ | {"asset_url": selection.asset_url} for selection in list_templates()]}
    db = SessionLocal()
    try:
        ensure_builtin_templates(db)
        db.commit()
    finally:
        db.close()
    return {"items": [selection.__dict__ | {"asset_url": selection.asset_url} for selection in list_templates()]}


@router.post("/templates/{template_id}/activate")
def activate_template(template_id: int, current_user: User = Depends(require_admin_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        row = db.query(CardTemplate).filter(CardTemplate.id == template_id).first()
        if not row:
            raise HTTPException(404, "Template not found")
        (
            db.query(CardTemplate)
            .filter(CardTemplate.kingdom == row.kingdom, CardTemplate.side == row.side)
            .update({"active": False}, synchronize_session=False)
        )
        row.active = True
        db.commit()
        clear_template_cache()
        return {"ok": True, "id": row.id, "kingdom": row.kingdom, "side": row.side, "version": row.version}
    finally:
        db.close()
