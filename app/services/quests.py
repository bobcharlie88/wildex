from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Card,
    Quest,
    UserBadge,
    UserQuestProgress,
    UserProgression,
)

log = logging.getLogger("wildex.quests")

RARITY_XP = {
    "common": 50,
    "uncommon": 100,
    "rare": 250,
    "very_rare": 500,
    "legendary": 500,
    "mythic": 1000,
    "cryptic": 750,
    "extinct": 1500,
}

BUILTIN_QUESTS = [
    {
        "quest_key": "daily_discover_1",
        "title": "Daily Field Record",
        "description": "Log 1 wildlife observation in WildEx.",
        "quest_type": "daily",
        "target_type": "count",
        "target_value": "any",
        "required_count": 1,
        "reward_xp": 100,
    },
    {
        "quest_key": "daily_bird_1",
        "title": "Avian Spotter",
        "description": "Discover 1 Bird species today.",
        "quest_type": "daily",
        "target_type": "category",
        "target_value": "bird",
        "required_count": 1,
        "reward_xp": 150,
    },
    {
        "quest_key": "daily_insect_1",
        "title": "Micro-Fauna Tracker",
        "description": "Log 1 Insect or Arachnid species today.",
        "quest_type": "daily",
        "target_type": "category",
        "target_value": "insect",
        "required_count": 1,
        "reward_xp": 150,
    },
    {
        "quest_key": "weekly_rare_1",
        "title": "Rare Specimen Hunter",
        "description": "Discover 1 Rare or Legendary creature this week.",
        "quest_type": "weekly",
        "target_type": "rarity",
        "target_value": "rare",
        "required_count": 1,
        "reward_xp": 400,
    },
    {
        "quest_key": "weekly_explore_5",
        "title": "Expedition Master",
        "description": "Log 5 total wildlife observations across any biome this week.",
        "quest_type": "weekly",
        "target_type": "count",
        "target_value": "any",
        "required_count": 5,
        "reward_xp": 500,
    },
]


def ensure_builtin_quests(db: Session) -> list[Quest]:
    """Ensures active daily & weekly quests are registered in DB."""
    quests = []
    for qdata in BUILTIN_QUESTS:
        existing = db.query(Quest).filter(Quest.quest_key == qdata["quest_key"]).first()
        if not existing:
            existing = Quest(**qdata)
            db.add(existing)
            db.flush()
        quests.append(existing)
    db.commit()
    return quests


def get_user_progression(db: Session, user_id: int) -> UserProgression:
    prog = db.query(UserProgression).filter(UserProgression.user_id == user_id).first()
    if not prog:
        prog = UserProgression(user_id=user_id, level=1, xp=0, unlocked_badges_json=json.dumps([]))
        db.add(prog)
        db.commit()
        db.refresh(prog)
    return prog


def get_user_level_threshold(level: int) -> int:
    return level * 250


def grant_xp(db: Session, user_id: int, amount: int) -> tuple[UserProgression, list[str]]:
    prog = get_user_progression(db, user_id)
    prog.xp += max(0, amount)
    new_badges = []

    # Check level up
    while True:
        threshold = get_user_level_threshold(prog.level)
        if prog.xp >= threshold:
            prog.level += 1
            log.info("User id=%s leveled up to Level %d!", user_id, prog.level)
        else:
            break

    # Badge checks
    if prog.level >= 5:
        if _unlock_badge(db, user_id, "level_5", "Seasoned Naturalist", "Reached Level 5 in WildEx", "award"):
            new_badges.append("level_5")
    if prog.level >= 10:
        if _unlock_badge(db, user_id, "level_10", "Master Explorer", "Reached Level 10 in WildEx", "trophy"):
            new_badges.append("level_10")

    db.commit()
    return prog, new_badges


def _unlock_badge(db: Session, user_id: int, key: str, name: str, desc: str, icon: str) -> bool:
    existing = db.query(UserBadge).filter(UserBadge.user_id == user_id, UserBadge.badge_key == key).first()
    if not existing:
        badge = UserBadge(
            user_id=user_id,
            badge_key=key,
            badge_name=name,
            badge_description=desc,
            icon_name=icon,
        )
        db.add(badge)
        db.commit()
        return True
    return False


def process_discovery_event(
    db: Session,
    *,
    user_id: int,
    card: Card,
    is_new_species: bool = True,
    is_region_unlock: bool = False,
) -> dict:
    """
    Hooks into card discovery flow.
    Calculates XP gains, updates daily/weekly quests, and unlocks badges.
    """
    ensure_builtin_quests(db)

    # Base XP by rarity
    rarity_key = str(card.rarity_tier or "common").lower()
    base_xp = RARITY_XP.get(rarity_key, 50)
    bonus_xp = (150 if is_new_species else 25) + (300 if is_region_unlock else 0)
    total_gained_xp = base_xp + bonus_xp

    prog, level_badges = grant_xp(db, user_id, total_gained_xp)

    # First discovery badge check
    discovery_badges = []
    if _unlock_badge(db, user_id, "first_discovery", "First Discovery", "Recorded your first WildEx field capture!", "compass"):
        discovery_badges.append("first_discovery")
    if card.rarity_tier in ("rare", "very_rare", "legendary", "mythic"):
        if _unlock_badge(db, user_id, "rare_hunter", "Apex Finder", "Discovered a Rare or Legendary species!", "star"):
            discovery_badges.append("rare_hunter")

    # Update quests
    quests = db.query(Quest).all()
    updated_quests = []
    for q in quests:
        prog_row = (
            db.query(UserQuestProgress)
            .filter(UserQuestProgress.user_id == user_id, UserQuestProgress.quest_id == q.id)
            .first()
        )
        if not prog_row:
            prog_row = UserQuestProgress(user_id=user_id, quest_id=q.id, current_progress=0, completed=False, claimed=False)
            db.add(prog_row)

        if prog_row.completed:
            continue

        match = False
        if q.target_type == "count":
            match = True
        elif q.target_type == "category":
            category = (card.category or card.sub_category or card.iconic_taxon or "").lower()
            target = (q.target_value or "").lower()
            if target in category:
                match = True
        elif q.target_type == "rarity":
            rarity = str(card.rarity_tier or "").lower()
            if rarity in ("rare", "very_rare", "legendary", "mythic"):
                match = True

        if match:
            prog_row.current_progress += 1
            if prog_row.current_progress >= q.required_count:
                prog_row.completed = True
                log.info("User id=%s completed quest '%s'", user_id, q.title)
            updated_quests.append(q.quest_key)

    db.commit()

    return {
        "xp_gained": total_gained_xp,
        "new_level": prog.level,
        "current_xp": prog.xp,
        "new_badges": level_badges + discovery_badges,
        "updated_quests": updated_quests,
    }
