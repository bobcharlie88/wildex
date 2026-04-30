from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func

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
    mode = (payload.get("mode") or "").strip()
    if not question and not mode:
        raise HTTPException(400, "question or mode is required")

    card_payload = {}
    collection_payload = {}
    card_id = int(payload["card_id"]) if payload.get("card_id") else None
    if card_id or (db_available() and SessionLocal is not None):
        if not db_available() or SessionLocal is None:
            raise HTTPException(503, "Database unavailable")
        db = SessionLocal()
        try:
            if card_id:
                row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
                if row is None:
                    raise HTTPException(404, "Card not found")
                card_payload = build_render_card(row)
            captured_count = db.query(func.count(Card.id)).filter(Card.owner_id == current_user.id).scalar() or 0
            regions_unlocked = (
                db.query(Card.region)
                .filter(Card.owner_id == current_user.id, Card.region.isnot(None))
                .distinct()
                .count()
            )
            collection_payload = {
                "captured_count": int(captured_count),
                "regions_unlocked": int(regions_unlocked),
                "favorite_card_id": current_user.favorite_card_id,
            }
        finally:
            db.close()

    result = run_agent_task(
        agent_name="dr",
        task_type="player_help",
        payload={
            "question": question,
            "mode": mode,
            "card": card_payload,
            "card_id": card_id,
            "biome": payload.get("biome") or card_payload.get("biome"),
            "player_region": payload.get("player_region") or card_payload.get("region"),
            "collection": collection_payload,
            "hunger_state": payload.get("hunger_state"),
            "feed_state": payload.get("feed_state"),
        },
        actor_user_id=current_user.id,
        card_id=card_id,
    )
    return result["payload"]
