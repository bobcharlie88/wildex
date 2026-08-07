from __future__ import annotations

import hashlib
import json
import logging
import random
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import BattleMatch, Card, CardProtection, User

log = logging.getLogger("wildex.battle_engine")

ARENA_BIOMES = ["Marine", "Desert", "Forest", "Alpine", "Wetland", "Urban", "Grassland"]

BIOME_MODIFIER_MATRIX = {
    "Marine": {
        "buffs": ["marine", "fish", "actinopterygii", "ocean"],
        "buff_mult": {"spd": 1.25, "def": 1.15},
        "penalties": ["desert", "arid", "reptile"],
        "penalty_mult": {"spd": 0.65, "def": 0.75},
    },
    "Desert": {
        "buffs": ["desert", "arid", "reptile", "dragon"],
        "buff_mult": {"atk": 1.25, "def": 1.15},
        "penalties": ["marine", "fish", "ocean", "wetland"],
        "penalty_mult": {"spd": 0.65, "def": 0.75},
    },
    "Forest": {
        "buffs": ["forest", "plant", "insect", "canopy"],
        "buff_mult": {"hp": 1.20, "def": 1.15},
        "penalties": ["desert", "arid"],
        "penalty_mult": {"def": 0.85},
    },
    "Alpine": {
        "buffs": ["alpine", "bird", "aves", "cliff", "sky"],
        "buff_mult": {"spd": 1.25, "atk": 1.20},
        "penalties": ["wetland", "marine"],
        "penalty_mult": {"spd": 0.80},
    },
    "Wetland": {
        "buffs": ["wetland", "plant", "amphibian", "botanical"],
        "buff_mult": {"hp": 1.20, "def": 1.20},
        "penalties": ["desert", "arid"],
        "penalty_mult": {"spd": 0.75},
    },
    "Urban": {
        "buffs": ["urban", "mammal", "paw"],
        "buff_mult": {"atk": 1.15, "spd": 1.15},
        "penalties": [],
        "penalty_mult": {},
    },
    "Grassland": {
        "buffs": ["grassland", "mammal", "paw"],
        "buff_mult": {"atk": 1.20, "spd": 1.15},
        "penalties": ["marine"],
        "penalty_mult": {"spd": 0.80},
    },
}


def coin_flip_select_arena(seed_str: str | None = None) -> tuple[str, str]:
    """Pre-match coin flip protocol selecting arena biome."""
    if not seed_str:
        seed_str = uuid.uuid4().hex
    digest = hashlib.sha256(seed_str.encode()).hexdigest()
    idx = int(digest[:8], 16) % len(ARENA_BIOMES)
    selected_biome = ARENA_BIOMES[idx]
    return selected_biome, seed_str


def derive_card_primary_biome(card: Card) -> str:
    tags = " ".join(filter(None, [
        card.category,
        card.sub_category,
        card.iconic_taxon,
        card.biome,
        card.species_name,
    ])).lower()

    if any(k in tags for k in ("fish", "marine", "shark", "ocean", "actinopterygii")):
        return "Marine"
    if any(k in tags for k in ("reptile", "dragon", "desert", "arid")):
        return "Desert"
    if any(k in tags for k in ("bird", "aves", "eagle", "cliff", "sky", "alpine")):
        return "Alpine"
    if any(k in tags for k in ("plant", "pitcher", "wetland", "botanical")):
        return "Wetland"
    if any(k in tags for k in ("insect", "forest", "canopy")):
        return "Forest"
    return "Grassland"


def calculate_biome_modifiers(card: Card, arena_biome: str) -> dict[str, float]:
    """Calculates modified combat stats for a card based on active arena environment."""
    matrix = BIOME_MODIFIER_MATRIX.get(arena_biome, {})
    card_biome = derive_card_primary_biome(card).lower()
    card_tags = f"{card_biome} {(card.category or '').lower()} {(card.sub_category or '').lower()} {(card.iconic_taxon or '').lower()}"

    base_stats = {
        "hp": float(card.hp or 50),
        "atk": float(card.attack or 50),
        "def": float(card.defence or 50),
        "spd": float(card.speed or 50),
    }

    modified_stats = dict(base_stats)

    # Check buffs
    for buff_tag in matrix.get("buffs", []):
        if buff_tag in card_tags:
            for stat, mult in matrix.get("buff_mult", {}).items():
                modified_stats[stat] *= mult
            break

    # Check penalties
    for penalty_tag in matrix.get("penalties", []):
        if penalty_tag in card_tags:
            for stat, mult in matrix.get("penalty_mult", {}).items():
                modified_stats[stat] *= mult
            break

    return {k: round(v, 2) for k, v in modified_stats.items()}


def evaluate_roster_diversity_penalty(roster_cards: list[Card], arena_biome: str) -> float:
    """
    Applies -20% mono-roster environmental debuff if all cards share 1 biome
    deployed into an opposing arena environment.
    """
    if len(roster_cards) < 3:
        return 1.0
    primary_biomes = {derive_card_primary_biome(c) for c in roster_cards}
    if len(primary_biomes) == 1:
        mono_biome = list(primary_biomes)[0]
        matrix = BIOME_MODIFIER_MATRIX.get(arena_biome, {})
        for penalty_tag in matrix.get("penalties", []):
            if penalty_tag in mono_biome.lower():
                log.info("Mono-roster penalty triggered for mono-biome '%s' in '%s' arena", mono_biome, arena_biome)
                return 0.80
    return 1.0


def simulate_3v3_battle(
    player1_roster: list[Card],
    player2_roster: list[Card],
    arena_biome: str,
) -> dict:
    """Executes turn-based 3v3 battle simulation and returns complete combat log & winner index."""
    p1_penalty = evaluate_roster_diversity_penalty(player1_roster, arena_biome)
    p2_penalty = evaluate_roster_diversity_penalty(player2_roster, arena_biome)

    p1_active = []
    for c in player1_roster:
        mods = calculate_biome_modifiers(c, arena_biome)
        p1_active.append({
            "card_id": c.id,
            "name": c.species_name,
            "hp": mods["hp"] * p1_penalty,
            "max_hp": mods["hp"] * p1_penalty,
            "atk": mods["atk"] * p1_penalty,
            "def": mods["def"] * p1_penalty,
            "spd": mods["spd"] * p1_penalty,
        })

    p2_active = []
    for c in player2_roster:
        mods = calculate_biome_modifiers(c, arena_biome)
        p2_active.append({
            "card_id": c.id,
            "name": c.species_name,
            "hp": mods["hp"] * p2_penalty,
            "max_hp": mods["hp"] * p2_penalty,
            "atk": mods["atk"] * p2_penalty,
            "def": mods["def"] * p2_penalty,
            "spd": mods["spd"] * p2_penalty,
        })

    combat_log = [
        f"Arena Environment: {arena_biome.upper()}",
        f"Player 1 Roster Penalty Multiplier: {p1_penalty:.2f}",
        f"Player 2 Roster Penalty Multiplier: {p2_penalty:.2f}",
    ]

    p1_idx, p2_idx = 0, 0
    round_num = 1

    while p1_idx < len(p1_active) and p2_idx < len(p2_active) and round_num <= 50:
        c1 = p1_active[p1_idx]
        c2 = p2_active[p2_idx]

        # Determine initiative
        if c1["spd"] >= c2["spd"]:
            first, second = c1, c2
            first_team, second_team = 1, 2
        else:
            first, second = c2, c1
            first_team, second_team = 2, 1

        # First strikes
        damage1 = max(5.0, first["atk"] - (second["def"] * 0.4))
        second["hp"] -= damage1
        combat_log.append(f"Turn {round_num}: {first['name']} (Player {first_team}) attacks {second['name']} for {damage1:.1f} DMG!")

        if second["hp"] <= 0:
            second["hp"] = 0
            combat_log.append(f"{second['name']} knocked out!")
            if second_team == 1:
                p1_idx += 1
            else:
                p2_idx += 1
            round_num += 1
            continue

        # Second retaliates
        damage2 = max(5.0, second["atk"] - (first["def"] * 0.4))
        first["hp"] -= damage2
        combat_log.append(f"Turn {round_num}: {second['name']} retaliates against {first['name']} for {damage2:.1f} DMG!")

        if first["hp"] <= 0:
            first["hp"] = 0
            combat_log.append(f"{first['name']} knocked out!")
            if first_team == 1:
                p1_idx += 1
            else:
                p2_idx += 1

        round_num += 1

    winner_player = 1 if p2_idx >= len(p2_active) else 2
    combat_log.append(f"Match Finished! Winner: Player {winner_player}")

    return {
        "winner_player": winner_player,
        "combat_log": combat_log,
        "p1_remaining": len(p1_active) - p1_idx,
        "p2_remaining": len(p2_active) - p2_idx,
    }


def execute_losers_tax_transfer(
    db: Session,
    *,
    winner_id: int,
    loser_id: int,
    target_card_id: int,
) -> Card:
    """
    Executes stake-based card transfer ("The Loser's Tax").
    Transfers card ownership from defeated player to victorious player.
    """
    card = db.query(Card).filter(Card.id == target_card_id, Card.owner_id == loser_id).first()
    if not card:
        raise ValueError("Selected card not found in loser's collection")

    # Check card protection
    protected_row = (
        db.query(CardProtection)
        .filter(CardProtection.user_id == loser_id, CardProtection.card_id == target_card_id)
        .first()
    )
    if protected_row and protected_row.is_protected:
        raise ValueError("Selected card is shielded by Card Protection")

    loser_user = db.query(User).filter(User.id == loser_id).first()
    if loser_user and loser_user.favorite_card_id == target_card_id:
        raise ValueError("Selected card is shielded as loser's favorite card")

    card.owner_id = winner_id
    db.commit()
    db.refresh(card)

    log.info("Loser's Tax executed! Card id=%s ('%s') transferred from user %s to user %s", card.id, card.species_name, loser_id, winner_id)
    return card


def register_match_forfeiture(
    db: Session,
    *,
    match_code: str,
    forfeiting_player_id: int,
) -> BattleMatch:
    """Handles anti-cheat & abandonment forfeiture, awarding instant victory to active opponent."""
    match = db.query(BattleMatch).filter(BattleMatch.match_code == match_code).first()
    if not match:
        raise ValueError("Battle match not found")
    if match.status == "completed":
        raise ValueError("Match is already completed")

    winner_id = match.player2_id if forfeiting_player_id == match.player1_id else match.player1_id
    if not winner_id:
        winner_id = match.player1_id

    match.status = "forfeit"
    match.winner_id = winner_id
    match.completed_at = datetime.utcnow()
    match.combat_log_json = json.dumps([f"Match Forfeited by User {forfeiting_player_id}. User {winner_id} declared winner by default."])

    db.commit()
    db.refresh(match)
    return match
