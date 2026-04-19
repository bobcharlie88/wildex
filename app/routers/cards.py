from fastapi import APIRouter, HTTPException
from sqlalchemy import desc

from app.database import SessionLocal, db_available
from app.models import Card

router = APIRouter()

RARITY_DISPLAY = {
    "common":    "Common",
    "uncommon":  "Uncommon",
    "rare":      "Rare",
    "very_rare": "Legendary",
}


def _card_dict(c: Card) -> dict:
    return {
        "id":                   c.id,
        "species_name":         c.species_name,
        "scientific_name":      c.scientific_name,
        "rank":                 c.rank,
        "confidence":           round(c.confidence, 4) if c.confidence else None,
        "provisional":          c.provisional,
        "rarity_tier":          c.rarity_tier,
        "rarity_display":       RARITY_DISPLAY.get(c.rarity_tier or "", "Unknown"),
        "invasive_at_location": c.invasive_at_location,
        "iconic_taxon":         c.iconic_taxon,
        "conservation_status":  c.conservation_status,
        "observations_count":   c.observations_count,
        "taxon_id":             c.taxon_id,
        "gbif_key":             c.gbif_key,
        "category":             c.category,
        "sub_category":         c.sub_category,
        "blurb":                c.blurb,
        "stats": {
            "speed":         c.speed,
            "attack":        c.attack,
            "defence":       c.defence,
            "hp":            c.hp,
            "stamina_regen": c.stamina_regen,
        },
        "captured_at":     c.captured_at.isoformat() if c.captured_at else None,
        "latitude":        c.latitude,
        "longitude":       c.longitude,
        "capture_country": c.capture_country,
        "photo_url":       f"/uploads/{c.id}.jpg",
    }


@router.get("/cards")
def list_cards():
    if not db_available():
        return []
    db = SessionLocal()
    try:
        rows = db.query(Card).order_by(desc(Card.captured_at)).all()
        return [_card_dict(r) for r in rows]
    finally:
        db.close()


@router.get("/cards/{card_id}")
def get_card(card_id: int):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        row = db.query(Card).filter(Card.id == card_id).first()
        if not row:
            raise HTTPException(404, "Card not found")
        return _card_dict(row)
    finally:
        db.close()
