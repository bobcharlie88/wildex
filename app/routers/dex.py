from __future__ import annotations

from collections import defaultdict
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import Card, DexEntry, User, UserDexDiscovery
from app.services.card_render import build_render_card
from app.services.dex import (
    DISCOVERY_CAPTURED,
    DISCOVERY_SEEN,
    DISCOVERY_UNKNOWN,
    backfill_user_cards,
    resolve_or_create_dex_entry,
    set_discovery_state,
)
from app.services.taxonomy import REGION_LABELS, taxonomy_for_entry

router = APIRouter()

RARITY_DISPLAY = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "very_rare": "Legendary",
}


class SeenEntryPayload(BaseModel):
    species_name: str
    scientific_name: str | None = None
    category: str | None = None
    sub_category: str | None = None
    iconic_taxon: str | None = None
    capture_country: str | None = None


def _card_dict(c: Card) -> dict:
    return {
        "id": c.id,
        "species_name": c.species_name,
        "scientific_name": c.scientific_name,
        "rank": c.rank,
        "confidence": round(c.confidence, 4) if c.confidence else None,
        "provisional": c.provisional,
        "rarity_tier": c.rarity_tier,
        "rarity_display": c.rarity_display or RARITY_DISPLAY.get(c.rarity_tier or "", "Unknown"),
        "invasive_at_location": c.invasive_at_location,
        "iconic_taxon": c.iconic_taxon,
        "conservation_status": c.conservation_status,
        "observations_count": c.observations_count,
        "taxon_id": c.taxon_id,
        "gbif_key": c.gbif_key,
        "category": c.category,
        "sub_category": c.sub_category,
        "blurb": c.blurb,
        "stats": {
            "speed": c.speed,
            "attack": c.attack,
            "defence": c.defence,
            "hp": c.hp,
            "stamina_regen": c.stamina_regen,
        },
        "threat_level": c.threat_level,
        "aggression": c.aggression,
        "biome": c.biome,
        "biome_bonus": c.biome_bonus,
        "strength_name": c.strength_name,
        "strength_effect": c.strength_effect,
        "weakness_name": c.weakness_name,
        "weakness_effect": c.weakness_effect,
        "sound_url": c.sound_url,
        "captured_at": c.captured_at.isoformat() if c.captured_at else None,
        "latitude": c.latitude,
        "longitude": c.longitude,
        "capture_country": c.capture_country,
        "image_url": c.image_url,
        "supporting_image_urls": json.loads(c.supporting_image_urls) if c.supporting_image_urls else [],
        "dex_id": c.dex_id,
        "discovery_state": c.discovery_state,
        "region": c.region,
        "kingdom": c.kingdom,
        "group_code": c.group_code,
        "evolution_chain_id": c.evolution_chain_id,
        "evolution_stage": c.evolution_stage,
        "render_card": build_render_card(c),
    }


@router.get("/wilddex/entries")
def list_wilddex_entries(current_user: User = Depends(require_user)):
    if not db_available():
        return []

    db = SessionLocal()
    try:
        backfill_user_cards(db, current_user.id)

        entries = (
            db.query(DexEntry)
            .filter(DexEntry.region.in_(REGION_LABELS.keys()))
            .order_by(
                DexEntry.region.asc(),
                DexEntry.kingdom.asc(),
                DexEntry.group_code.asc(),
                DexEntry.number.asc(),
            )
            .all()
        )
        if not entries:
            return []

        entry_ids = [entry.id for entry in entries]
        discoveries = (
            db.query(UserDexDiscovery)
            .filter(
                UserDexDiscovery.user_id == current_user.id,
                UserDexDiscovery.dex_entry_id.in_(entry_ids),
            )
            .all()
        )
        discovery_map = {row.dex_entry_id: row for row in discoveries}

        card_rows = (
            db.query(Card)
            .filter(
                Card.owner_id == current_user.id,
                Card.dex_entry_id.in_(entry_ids),
            )
            .order_by(Card.captured_at.desc(), Card.id.desc())
            .all()
        )
        latest_card_by_entry: dict[int, Card] = {}
        for row in card_rows:
            if row.dex_entry_id and row.dex_entry_id not in latest_card_by_entry:
                latest_card_by_entry[row.dex_entry_id] = row

        groups = defaultdict(int)
        payload = []
        for entry in entries:
            discovery = discovery_map.get(entry.id)
            state = discovery.discovery_state if discovery else DISCOVERY_UNKNOWN
            card = latest_card_by_entry.get(entry.id)
            if card and state != DISCOVERY_CAPTURED:
                state = DISCOVERY_CAPTURED

            groups[f"{entry.region}-{entry.kingdom}-{entry.group_code}"] += 1

            payload.append(
                {
                    "id": entry.id,
                    "dex_id": entry.dex_id,
                    "region": entry.region,
                    "region_label": REGION_LABELS.get(entry.region, entry.region),
                    "kingdom": entry.kingdom,
                    "group_code": entry.group_code,
                    "number": entry.number,
                    "discovery_state": state,
                    "name": entry.display_name if state in {DISCOVERY_SEEN, DISCOVERY_CAPTURED} else None,
                    "scientific_name": entry.scientific_name if state == DISCOVERY_CAPTURED else None,
                    "category": entry.category,
                    "sub_category": entry.sub_category,
                    "taxonomy": taxonomy_for_entry(
                        category=entry.category,
                        sub_category=entry.sub_category,
                        group_code=entry.group_code,
                        kingdom=entry.kingdom,
                    ),
                    "evolution_chain_id": entry.evolution_chain_id,
                    "evolution_stage": entry.evolution_stage,
                    "evolution_length": entry.evolution_length,
                    "is_placeholder": state == DISCOVERY_UNKNOWN,
                    "card": _card_dict(card) if card and state == DISCOVERY_CAPTURED else None,
                    "group_size": groups[f"{entry.region}-{entry.kingdom}-{entry.group_code}"],
                }
            )

        return payload
    finally:
        db.close()


@router.post("/wilddex/seen")
def mark_wilddex_seen(payload: SeenEntryPayload, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")

    db = SessionLocal()
    try:
        entry = resolve_or_create_dex_entry(
            db,
            common_name=payload.species_name,
            scientific_name=payload.scientific_name or payload.species_name,
            category=payload.category,
            sub_category=payload.sub_category,
            iconic_taxon=payload.iconic_taxon,
            capture_country=payload.capture_country,
        )
        set_discovery_state(
            db,
            user_id=current_user.id,
            dex_entry_id=entry.id,
            state=DISCOVERY_SEEN,
        )
        db.commit()
        return {
            "marked": True,
            "dex_id": entry.dex_id,
            "discovery_state": DISCOVERY_SEEN,
            "name": entry.display_name,
        }
    finally:
        db.close()
