import logging
import os
import tempfile
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import require_user
from app.database import SessionLocal, db_available
from app.models import Card, User
from app.pipeline.card_generator import generate_card
from app.pipeline.frame_extractor import extract_best_frame, save_frame
from app.pipeline.species_data import get_species_data
from app.pipeline.species_id import TemporaryIdentificationError, identify_species, is_temporary_identification_error
from app.services.card_render import apply_render_fields, build_render_card
from app.services.dex import DISCOVERY_CAPTURED, sync_card_to_dex
from app.utils.storage import upload_capture_asset

router = APIRouter()
log = logging.getLogger("wildex.capture")

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/3gpp", "video/x-m4v"}
ALLOWED_TYPES = IMAGE_TYPES | VIDEO_TYPES
IDENTIFY_RETRY_DELAYS = (1.0, 2.0)


def _is_temporary_identification_failure(exc: Exception) -> bool:
    return isinstance(exc, TemporaryIdentificationError) or is_temporary_identification_error(exc)


def _identify_with_retry(image_path: str, lat: float | None = None, lon: float | None = None):
    last_exc = None
    for idx in range(len(IDENTIFY_RETRY_DELAYS) + 1):
        try:
            return identify_species(image_path, lat=lat, lon=lon)
        except EnvironmentError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_temporary_identification_failure(exc) or idx >= len(IDENTIFY_RETRY_DELAYS):
                raise
            delay = IDENTIFY_RETRY_DELAYS[idx]
            log.warning("Temporary species identification failure; retrying in %.1fs: %s", delay, exc)
            time.sleep(delay)
    raise last_exc


def _pending_card_payload(image_url: str | None, lat: float | None, lon: float | None, message: str) -> dict:
    payload = {
        "species_name": "Pending identification",
        "scientific_name": "Unknown",
        "rank": "unknown",
        "confidence": 0.0,
        "provisional": True,
        "rarity_tier": None,
        "rarity_display": None,
        "invasive_at_location": False,
        "iconic_taxon": "Pending",
        "conservation_status": None,
        "observations_count": 0,
        "taxon_id": None,
        "blurb": message,
        "stats": {
            "speed": 0,
            "attack": 0,
            "defence": 0,
            "hp": 0,
            "stamina_regen": 0,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "latitude": lat,
        "longitude": lon,
        "image_url": image_url,
    }
    payload["render_card"] = build_render_card(payload)
    return payload


@router.post("/capture")
async def capture(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    current_user: User = Depends(require_user),
):
    """
    Full pipeline: species ID -> GBIF data -> card generation -> DB save.

    lat/lon are optional. When absent the GBIF lookup (rarity + invasive
    check) is skipped and the card is generated without location context.
    Card generation is never blocked; lookup failures are logged and the
    pipeline continues.
    """
    if file.content_type and file.content_type.lower() not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported image type: {file.content_type}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file received")

    content_type = (file.content_type or "").lower()
    is_video = content_type in VIDEO_TYPES
    if is_video:
        suffix = ".mp4"
    elif content_type.endswith("png"):
        suffix = ".png"
    elif content_type.endswith("webp"):
        suffix = ".webp"
    elif content_type.endswith("heic"):
        suffix = ".heic"
    elif content_type.endswith("heif"):
        suffix = ".heif"
    else:
        suffix = ".jpg"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    frame_path = None
    try:
        if is_video:
            try:
                frame, _, _ = extract_best_frame(tmp_path)
                frame_tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                frame_tmp.close()
                frame_path = frame_tmp.name
                save_frame(frame, frame_path)
                identify_path = frame_path
            except Exception as exc:
                raise HTTPException(422, f"Could not extract frame from video: {exc}")
        else:
            identify_path = tmp_path

        image_url = upload_capture_asset(
            original_bytes=content,
            original_content_type=file.content_type,
            original_suffix=suffix,
            extracted_frame_path=frame_path if is_video else None,
        )
        if not image_url:
            log.error("Capture image upload failed; continuing without persistent image")

        try:
            species = _identify_with_retry(identify_path, lat=lat, lon=lon)
        except EnvironmentError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:
            if _is_temporary_identification_failure(exc):
                log.warning("Species identification unavailable; saving pending capture instead: %s", exc)
                pending_message = (
                    "Photo saved. Identification is pending because the identification service "
                    "is temporarily unavailable."
                )
                saved = False
                card_id = None
                db_error = None

                if db_available():
                    db = SessionLocal()
                    try:
                        row = Card(
                            owner_id=current_user.id,
                            species_name="Pending identification",
                            scientific_name="Unknown",
                            rank="unknown",
                            confidence=0.0,
                            provisional=True,
                            iconic_taxon="Pending",
                            observations_count=0,
                            blurb=pending_message,
                            speed=0,
                            attack=0,
                            defence=0,
                            hp=0,
                            stamina_regen=0,
                            captured_at=datetime.now(timezone.utc),
                            latitude=lat,
                            longitude=lon,
                            image_url=image_url,
                        )
                        db.add(row)
                        db.commit()
                        db.refresh(row)
                        card_id = row.id
                        saved = True
                        log.info("Saved pending capture card id=%s user_id=%s image_url=%s", row.id, current_user.id, image_url)
                    except Exception as db_exc:
                        db.rollback()
                        log.exception("Failed to save pending capture for user_id=%s", current_user.id)
                        db_error = str(db_exc)
                    finally:
                        db.close()
                else:
                    db_error = "Database not configured - update DATABASE_URL in .env"

                return {
                    "saved": saved,
                    "card_id": card_id,
                    "db_error": db_error,
                    "identification_error": str(exc),
                    "card": _pending_card_payload(image_url, lat, lon, pending_message),
                }
            raise HTTPException(500, f"Species identification failed: {exc}")

        gbif = None
        if lat is not None and lon is not None:
            try:
                gbif = get_species_data(species.scientific_name, lat, lon)
            except Exception:
                pass

        try:
            card = generate_card(species, gbif)
        except EnvironmentError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"Card generation failed: {exc}")

        saved = False
        card_id = None
        dex_id = None
        db_error = None

        if db_available():
            db = SessionLocal()
            try:
                row = Card(
                    owner_id=current_user.id,
                    species_name=card.common_name,
                    scientific_name=card.scientific_name,
                    rank=card.rank,
                    confidence=card.confidence,
                    provisional=card.provisional,
                    taxon_id=card.taxon_id,
                    iconic_taxon=card.iconic_taxon,
                    conservation_status=card.conservation_status,
                    observations_count=card.observations_count,
                    gbif_key=card.gbif_key,
                    rarity_tier=card.rarity_tier,
                    invasive_at_location=card.invasive_at_location,
                    category=species.category,
                    sub_category=species.sub_category,
                    blurb=card.blurb,
                    speed=card.stats.speed,
                    attack=card.stats.attack,
                    defence=card.stats.defence,
                    hp=card.stats.hp,
                    stamina_regen=card.stats.stamina_regen,
                    captured_at=datetime.now(timezone.utc),
                    latitude=lat,
                    longitude=lon,
                    capture_country=gbif.query_country if gbif else None,
                    image_url=image_url,
                )
                render_data = build_render_card({
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
                    },
                    "category": species.category,
                    "sub_category": species.sub_category,
                    "capture_country": gbif.query_country if gbif else None,
                    "image_url": image_url,
                })
                apply_render_fields(row, render_data)
                db.add(row)
                db.flush()
                sync_card_to_dex(db, row)
                row.discovery_state = DISCOVERY_CAPTURED
                db.commit()
                db.refresh(row)
                card_id = row.id
                dex_id = row.dex_id
                saved = True
                log.info(
                    "Saved capture card id=%s dex_id=%s region=%s user_id=%s image_url=%s",
                    row.id,
                    row.dex_id,
                    row.region,
                    current_user.id,
                    image_url,
                )
            except Exception as exc:
                db.rollback()
                log.exception("Failed to save capture card for user_id=%s species=%s", current_user.id, card.common_name)
                db_error = str(exc)
            finally:
                db.close()
        else:
            db_error = "Database not configured - update DATABASE_URL in .env"

        card_payload = {
                "dex_id": dex_id,
                "species_name": card.common_name,
                "scientific_name": card.scientific_name,
                "rank": card.rank,
                "confidence": round(card.confidence, 4),
                "provisional": card.provisional,
                "rarity_tier": card.rarity_tier,
                "rarity_display": card.rarity_display,
                "invasive_at_location": card.invasive_at_location,
                "iconic_taxon": card.iconic_taxon,
                "conservation_status": card.conservation_status,
                "observations_count": card.observations_count,
                "taxon_id": card.taxon_id,
                "blurb": card.blurb,
                "stats": {
                    "speed": card.stats.speed,
                    "attack": card.stats.attack,
                    "defence": card.stats.defence,
                    "hp": card.stats.hp,
                    "stamina_regen": card.stats.stamina_regen,
                },
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "latitude": lat,
                "longitude": lon,
                "capture_country": gbif.query_country if gbif else None,
                "category": species.category,
                "sub_category": species.sub_category,
                "image_url": image_url,
            }
        card_payload["render_card"] = build_render_card(card_payload)
        return {
            "saved": saved,
            "card_id": card_id,
            "db_error": db_error,
            "card": card_payload,
        }
    finally:
        os.unlink(tmp_path)
        if frame_path and os.path.exists(frame_path):
            os.unlink(frame_path)


@router.post("/identify")
async def identify(file: UploadFile = File(...)):
    if file.content_type and file.content_type.lower() not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported image type: {file.content_type}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file received")

    suffix = ".png" if (file.content_type or "").endswith("png") else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        try:
            result = identify_species(tmp_path)
        except EnvironmentError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:
            if _is_temporary_identification_failure(exc):
                raise HTTPException(503, f"Identification temporarily unavailable: {exc}")
            raise HTTPException(500, f"Identification failed: {exc}")

        return {
            "scientific_name": result.scientific_name,
            "common_name": result.common_name,
            "confidence": round(result.confidence, 4),
            "provisional": result.provisional,
            "rank": result.rank,
            "reasoning": result.reasoning,
            "animal_visible": result.animal_visible,
            "taxon_id": result.taxon_id,
            "inat_common_name": result.inat_common_name,
            "iconic_taxon": result.iconic_taxon,
            "conservation_status": result.conservation_status,
            "observations_count": result.observations_count,
        }
    finally:
        os.unlink(tmp_path)
