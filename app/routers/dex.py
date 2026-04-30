from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import Card, DexEntry, User, UserDexDiscovery
from app.utils.card_serializer import card_to_dict as _card_dict_shared
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


class SeenEntryPayload(BaseModel):
    species_name: str
    scientific_name: str | None = None
    category: str | None = None
    sub_category: str | None = None
    iconic_taxon: str | None = None
    capture_country: str | None = None


def _card_dict(c: Card) -> dict:
    return _card_dict_shared(c)


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
