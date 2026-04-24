import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

import httpx
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import AgentTask, Card, CardTemplate, CaptureJob, ReviewQueueItem, SpeciesResultRecord, User, UserDexDiscovery
from app.pipeline.card_generator import generate_card
from app.pipeline.species_data import get_species_data
from app.pipeline.species_id import TemporaryIdentificationError, identify_species, is_temporary_identification_error
from app.services.card_render import apply_render_fields, build_card_payload, build_render_card
from app.utils.card_serializer import card_to_dict as _card_to_dict
from app.services.dex import DISCOVERY_CAPTURED, DISCOVERY_SEEN, sync_card_to_dex

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
    return _card_to_dict(c)


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


@router.get("/cards/{card_id}/inat-qr.png")
def get_card_inat_qr(card_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not row:
            raise HTTPException(404, "Card not found")
        if row.taxon_id and str(row.taxon_id).isdigit():
            target_url = f"https://www.inaturalist.org/taxa/{int(row.taxon_id)}"
        elif row.scientific_name:
            target_url = f"https://www.inaturalist.org/taxa/search?q={row.scientific_name.replace(' ', '+')}"
        else:
            raise HTTPException(404, "No iNaturalist target available")
        image = qrcode.make(target_url)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="image/png")
    finally:
        db.close()


@router.delete("/cards/{card_id}")
def delete_card(card_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == current_user.id).first()
        row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not row:
            raise HTTPException(404, "Card not found")
        dex_entry_id = row.dex_entry_id
        (
            db.query(CaptureJob)
            .filter(CaptureJob.card_id == row.id)
            .update({CaptureJob.card_id: None}, synchronize_session=False)
        )
        (
            db.query(AgentTask)
            .filter(AgentTask.card_id == row.id)
            .update({AgentTask.card_id: None}, synchronize_session=False)
        )
        (
            db.query(SpeciesResultRecord)
            .filter(SpeciesResultRecord.card_id == row.id)
            .update({SpeciesResultRecord.card_id: None}, synchronize_session=False)
        )
        (
            db.query(ReviewQueueItem)
            .filter(ReviewQueueItem.card_id == row.id)
            .update({ReviewQueueItem.card_id: None}, synchronize_session=False)
        )
        (
            db.query(CardTemplate)
            .filter(CardTemplate.preview_card_id == row.id)
            .update({CardTemplate.preview_card_id: None}, synchronize_session=False)
        )
        (
            db.query(UserDexDiscovery)
            .filter(UserDexDiscovery.last_card_id == row.id)
            .update({UserDexDiscovery.last_card_id: None}, synchronize_session=False)
        )
        if user and user.favorite_card_id == row.id:
            user.favorite_card_id = None
        db.delete(row)
        db.flush()
        if dex_entry_id:
            remaining = (
                db.query(Card)
                .filter(Card.owner_id == current_user.id, Card.dex_entry_id == dex_entry_id)
                .count()
            )
            discovery = (
                db.query(UserDexDiscovery)
                .filter(
                    UserDexDiscovery.user_id == current_user.id,
                    UserDexDiscovery.dex_entry_id == dex_entry_id,
                )
                .first()
            )
            if discovery and remaining == 0:
                discovery.discovery_state = DISCOVERY_SEEN
                discovery.last_card_id = None
        db.commit()
        return {"deleted": True, "card_id": card_id}
    finally:
        db.close()


@router.post("/cards/{card_id}/favorite")
def favorite_card(card_id: int, current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == current_user.id).first()
        row = db.query(Card).filter(Card.id == card_id, Card.owner_id == current_user.id).first()
        if not user or not row:
            raise HTTPException(404, "Card not found")
        user.favorite_card_id = row.id
        db.commit()
        return {"ok": True, "favorite_card_id": row.id}
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
        primary_image_url = row.primary_card_image_url or row.image_url
        if not primary_image_url:
            raise HTTPException(400, "Card has no saved image to re-identify")
    finally:
        db.close()

    tmp_path = None
    try:
        if primary_image_url.startswith("/uploads/"):
            local_path = UPLOADS_DIR / Path(primary_image_url).name
            if not local_path.exists():
                raise HTTPException(404, "Saved image file is missing")
            tmp_path = str(local_path)
        else:
            response = httpx.get(primary_image_url, timeout=30.0, follow_redirects=True)
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
            row.rarity_display = card.rarity_display
            render_source = {
                "species_name": card.common_name,
                "scientific_name": card.scientific_name,
                "rank": card.rank,
                "confidence": card.confidence,
                "provisional": card.provisional,
                "rarity_tier": card.rarity_tier,
                "rarity_display": card.rarity_display,
                "iconic_taxon": card.iconic_taxon,
                "conservation_status": card.conservation_status,
                "observations_count": card.observations_count,
                "blurb": card.blurb,
                "stats": {
                    "speed": card.stats.speed,
                    "attack": card.stats.attack,
                    "defence": card.stats.defence,
                    "hp": card.stats.hp,
                    "stamina_regen": card.stats.stamina_regen,
                },
                "category": species.category,
                "sub_category": species.sub_category,
                "capture_country": gbif.query_country if gbif else row.capture_country,
                "original_image_url": row.original_image_url or row.primary_card_image_url or row.image_url,
                "primary_card_image_url": row.primary_card_image_url or row.image_url,
                "image_url": row.primary_card_image_url or row.image_url,
            }
            render_data = build_render_card(render_source)
            apply_render_fields(row, render_data)
            row.card_payload_json = json.dumps(build_card_payload(render_source))
            row.render_status = "ready"
            row.card_payload_version = "1.0.0"
            row.front_template_id = render_data.get("front_template", {}).get("id")
            row.back_template_id = render_data.get("back_template", {}).get("id")
            sync_card_to_dex(db, row)
            row.discovery_state = DISCOVERY_CAPTURED
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
