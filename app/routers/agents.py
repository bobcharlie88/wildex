from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import Card, User
from app.services.agents.orchestrator import run_agent_task
from app.services.card_render import build_render_card

router = APIRouter(tags=["agents"])


@router.post("/dr/ask")
async def ask_dr(request: Request, current_user: User = Depends(require_user)):
    payload = await request.json()
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")

    card_payload = {}
    card_id = int(payload["card_id"]) if payload.get("card_id") else None
    if card_id:
        if not db_available() or SessionLocal is None:
            raise HTTPException(503, "Database unavailable")
        db = SessionLocal()
        try:
            row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
            if row is None:
                raise HTTPException(404, "Card not found")
            card_payload = build_render_card(row)
        finally:
            db.close()

    result = run_agent_task(
        agent_name="dr",
        task_type="player_help",
        payload={
            "question": question,
            "card": card_payload,
            "card_id": card_id,
        },
        actor_user_id=current_user.id,
        card_id=card_id,
    )
    return result["payload"]
