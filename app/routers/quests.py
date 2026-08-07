import json
from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import Quest, User, UserBadge, UserQuestProgress
from app.services.quests import (
    ensure_builtin_quests,
    get_user_level_threshold,
    get_user_progression,
    grant_xp,
)

router = APIRouter()


@router.get("/quests")
def list_quests(current_user: User = Depends(require_user)):
    if not db_available():
        return {"quests": []}
    db = SessionLocal()
    try:
        quests = ensure_builtin_quests(db)
        result = []
        for q in quests:
            prog = (
                db.query(UserQuestProgress)
                .filter(UserQuestProgress.user_id == current_user.id, UserQuestProgress.quest_id == q.id)
                .first()
            )
            result.append({
                "id": q.id,
                "quest_key": q.quest_key,
                "title": q.title,
                "description": q.description,
                "quest_type": q.quest_type,
                "target_type": q.target_type,
                "target_value": q.target_value,
                "required_count": q.required_count,
                "reward_xp": q.reward_xp,
                "current_progress": prog.current_progress if prog else 0,
                "completed": bool(prog and prog.completed),
                "claimed": bool(prog and prog.claimed),
            })
        return {"quests": result}
    finally:
        db.close()


@router.post("/quests/{quest_id}/claim")
def claim_quest(quest_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        q = db.query(Quest).filter(Quest.id == quest_id).first()
        if not q:
            raise HTTPException(404, "Quest not found")
        prog = (
            db.query(UserQuestProgress)
            .filter(UserQuestProgress.user_id == current_user.id, UserQuestProgress.quest_id == quest_id)
            .first()
        )
        if not prog or not prog.completed:
            raise HTTPException(400, "Quest is not completed yet")
        if prog.claimed:
            raise HTTPException(400, "Quest reward already claimed")

        prog.claimed = True
        user_prog, new_badges = grant_xp(db, current_user.id, q.reward_xp)
        db.commit()

        return {
            "success": True,
            "claimed_xp": q.reward_xp,
            "total_xp": user_prog.xp,
            "level": user_prog.level,
            "new_badges": new_badges,
        }
    finally:
        db.close()


@router.get("/progression")
def get_progression(current_user: User = Depends(require_user)):
    if not db_available():
        return {"level": 1, "xp": 0, "next_level_xp": 250, "badges": []}
    db = SessionLocal()
    try:
        user_prog = get_user_progression(db, current_user.id)
        next_level_xp = get_user_level_threshold(user_prog.level)
        badges = (
            db.query(UserBadge)
            .filter(UserBadge.user_id == current_user.id)
            .order_by(UserBadge.unlocked_at.desc())
            .all()
        )
        badge_list = [
            {
                "badge_key": b.badge_key,
                "badge_name": b.badge_name,
                "badge_description": b.badge_description,
                "icon_name": b.icon_name,
                "unlocked_at": b.unlocked_at.isoformat() if b.unlocked_at else None,
            }
            for b in badges
        ]
        return {
            "level": user_prog.level,
            "xp": user_prog.xp,
            "next_level_xp": next_level_xp,
            "progress_percent": round(min(1.0, user_prog.xp / max(1, next_level_xp)) * 100, 1),
            "badges": badge_list,
        }
    finally:
        db.close()
