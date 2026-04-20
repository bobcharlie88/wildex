import os
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import Card, User
from app.pipeline.card_generator import generate_card
from app.pipeline.species_data import get_species_data
from app.pipeline.species_id import TemporaryIdentificationError, identify_species, is_temporary_identification_error

router = APIRouter()
UPLOADS_DIR = Path("uploads")


def _is_local_upload_path(path: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(UPLOADS_DIR.resolve())
    except Exception:
        return False

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
        "image_url":       c.image_url,
    }


@router.get("/cards")
def list_cards(current_user: User = Depends(require_user)):
    if not db_available():
        return []
    db = SessionLocal()
    try:
        rows = db.query(Card).filter(Card.owner_id == current_user.id).order_by(desc(Card.captured_at)).all()
        return [_card_dict(r) for r in rows]
    finally:
        db.close()


@router.get("/cards/{card_id}")
def get_card(card_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not row:
            raise HTTPException(404, "Card not found")
        return _card_dict(row)
    finally:
        db.close()


@router.delete("/cards/{card_id}")
def delete_card(card_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not row:
            raise HTTPException(404, "Card not found")
        db.delete(row)
        db.commit()
        return {"deleted": True, "card_id": card_id}
    finally:
        db.close()


@router.post("/cards/{card_id}/reidentify")
def reidentify_card(card_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")

    db = SessionLocal()
    try:
        row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not row:
            raise HTTPException(404, "Card not found")
        if not row.image_url:
            raise HTTPException(400, "Card has no saved image to re-identify")
    finally:
        db.close()

    tmp_path = None
    try:
        if row.image_url.startswith("/uploads/"):
            local_path = UPLOADS_DIR / Path(row.image_url).name
            if not local_path.exists():
                raise HTTPException(404, "Saved image file is missing")
            tmp_path = str(local_path)
        else:
            response = httpx.get(row.image_url, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            suffix = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name

        try:
            species = identify_species(tmp_path, lat=row.latitude, lon=row.longitude)
        except EnvironmentError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:
            if isinstance(exc, TemporaryIdentificationError) or is_temporary_identification_error(exc):
                raise HTTPException(503, f"Identification temporarily unavailable: {exc}")
            raise HTTPException(500, f"Re-identification failed: {exc}")

        gbif = None
        if row.latitude is not None and row.longitude is not None:
            try:
                gbif = get_species_data(species.scientific_name, row.latitude, row.longitude)
            except Exception:
                gbif = None

        try:
            card = generate_card(species, gbif)
        except EnvironmentError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"Card generation failed: {exc}")

        db = SessionLocal()
        try:
            row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
            if not row:
                raise HTTPException(404, "Card not found")

            row.species_name = card.common_name
            row.scientific_name = card.scientific_name
            row.rank = card.rank
            row.confidence = card.confidence
            row.provisional = card.provisional
            row.taxon_id = card.taxon_id
            row.iconic_taxon = card.iconic_taxon
            row.conservation_status = card.conservation_status
            row.observations_count = card.observations_count
            row.gbif_key = card.gbif_key
            row.rarity_tier = card.rarity_tier
            row.invasive_at_location = card.invasive_at_location
            row.category = species.category
            row.sub_category = species.sub_category
            row.blurb = card.blurb
            row.speed = card.stats.speed
            row.attack = card.stats.attack
            row.defence = card.stats.defence
            row.hp = card.stats.hp
            row.stamina_regen = card.stats.stamina_regen
            row.capture_country = gbif.query_country if gbif else row.capture_country
            db.commit()
            db.refresh(row)
            return _card_dict(row)
        finally:
            db.close()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not fetch saved image for re-identification: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path) and not _is_local_upload_path(tmp_path):
            os.unlink(tmp_path)
