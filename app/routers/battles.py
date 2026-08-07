import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import BattleMatch, Card, CardProtection, User
from app.services.battle_engine import (
    coin_flip_select_arena,
    execute_losers_tax_transfer,
    register_match_forfeiture,
    simulate_3v3_battle,
)

router = APIRouter()


class RosterSubmission(BaseModel):
    card_ids: List[int]


class ClaimStakeRequest(BaseModel):
    target_card_id: int


class ProtectCardRequest(BaseModel):
    is_protected: bool = True


@router.post("/battles/create")
def create_battle(current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        match_code = f"MATCH-{uuid.uuid4().hex[:8].upper()}"
        arena_biome, coin_flip_seed = coin_flip_select_arena()

        match = BattleMatch(
            match_code=match_code,
            player1_id=current_user.id,
            status="coin_flip",
            arena_biome=arena_biome,
            coin_flip_seed=coin_flip_seed,
        )
        db.add(match)
        db.commit()
        db.refresh(match)

        return {
            "match_code": match.match_code,
            "arena_biome": match.arena_biome,
            "status": match.status,
            "coin_flip_seed": match.coin_flip_seed,
        }
    finally:
        db.close()


@router.post("/battles/{match_code}/roster")
def submit_roster(
    match_code: str,
    body: RosterSubmission,
    current_user: User = Depends(require_user),
):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        match = db.query(BattleMatch).filter(BattleMatch.match_code == match_code).first()
        if not match:
            raise HTTPException(404, "Match not found")

        if len(body.card_ids) != 3:
            raise HTTPException(400, "Must provide exactly 3 cards for battle roster")

        cards = db.query(Card).filter(Card.id.in_(body.card_ids), Card.owner_id == current_user.id).all()
        if len(cards) != 3:
            raise HTTPException(400, "All 3 roster cards must belong to user")

        if match.player1_id == current_user.id:
            match.player1_roster_json = json.dumps(body.card_ids)
        elif match.player2_id is None:
            match.player2_id = current_user.id
            match.player2_roster_json = json.dumps(body.card_ids)
        elif match.player2_id == current_user.id:
            match.player2_roster_json = json.dumps(body.card_ids)
        else:
            raise HTTPException(400, "Match is already full")

        if match.player1_roster_json and match.player2_roster_json:
            match.status = "in_progress"

        db.commit()
        return {"status": match.status, "arena_biome": match.arena_biome}
    finally:
        db.close()


@router.post("/battles/{match_code}/simulate")
def simulate_match(match_code: str, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        match = db.query(BattleMatch).filter(BattleMatch.match_code == match_code).first()
        if not match:
            raise HTTPException(404, "Match not found")
        if not match.player1_roster_json or not match.player2_roster_json:
            raise HTTPException(400, "Both players must submit rosters before simulation")

        p1_ids = json.loads(match.player1_roster_json)
        p2_ids = json.loads(match.player2_roster_json)

        p1_cards = db.query(Card).filter(Card.id.in_(p1_ids)).all()
        p2_cards = db.query(Card).filter(Card.id.in_(p2_ids)).all()

        sim_result = simulate_3v3_battle(p1_cards, p2_cards, match.arena_biome or "Grassland")
        winner_id = match.player1_id if sim_result["winner_player"] == 1 else match.player2_id

        match.status = "completed"
        match.winner_id = winner_id
        match.combat_log_json = json.dumps(sim_result["combat_log"])
        db.commit()

        return {
            "match_code": match.match_code,
            "status": match.status,
            "winner_id": winner_id,
            "arena_biome": match.arena_biome,
            "combat_log": sim_result["combat_log"],
        }
    finally:
        db.close()


@router.post("/battles/{match_code}/claim-stake")
def claim_stake(
    match_code: str,
    body: ClaimStakeRequest,
    current_user: User = Depends(require_user),
):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        match = db.query(BattleMatch).filter(BattleMatch.match_code == match_code).first()
        if not match:
            raise HTTPException(404, "Match not found")
        if match.status not in ("completed", "forfeit"):
            raise HTTPException(400, "Match is not completed yet")
        if match.winner_id != current_user.id:
            raise HTTPException(403, "Only the winning player can claim stake")
        if match.transferred_card_id:
            raise HTTPException(400, "Stake card already claimed for this match")

        loser_id = match.player2_id if current_user.id == match.player1_id else match.player1_id
        if not loser_id:
            raise HTTPException(400, "No opposing player to claim stake from")

        transferred_card = execute_losers_tax_transfer(
            db,
            winner_id=current_user.id,
            loser_id=loser_id,
            target_card_id=body.target_card_id,
        )

        match.transferred_card_id = transferred_card.id
        db.commit()

        return {
            "success": True,
            "claimed_card": {
                "id": transferred_card.id,
                "species_name": transferred_card.species_name,
                "rarity_display": transferred_card.rarity_display,
            },
        }
    finally:
        db.close()


@router.post("/battles/{match_code}/forfeit")
def forfeit_match(match_code: str, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        match = register_match_forfeiture(db, match_code=match_code, forfeiting_player_id=current_user.id)
        return {"status": match.status, "winner_id": match.winner_id}
    finally:
        db.close()


@router.post("/cards/{card_id}/protect")
def protect_card(
    card_id: int,
    body: ProtectCardRequest,
    current_user: User = Depends(require_user),
):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        card = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not card:
            raise HTTPException(404, "Card not found in collection")

        prot = (
            db.query(CardProtection)
            .filter(CardProtection.user_id == current_user.id, CardProtection.card_id == card_id)
            .first()
        )
        if not prot:
            prot = CardProtection(user_id=current_user.id, card_id=card_id, is_protected=body.is_protected)
            db.add(prot)
        else:
            prot.is_protected = body.is_protected

        db.commit()
        return {"card_id": card_id, "is_protected": prot.is_protected}
    finally:
        db.close()
