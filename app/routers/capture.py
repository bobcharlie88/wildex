import logging
import os
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.database import SessionLocal, db_available
from app.models import Card
from app.pipeline.card_generator import generate_card
from app.pipeline.frame_extractor import extract_best_frame, save_frame
from app.pipeline.species_data import get_species_data
from app.pipeline.species_id import identify_species
from app.utils.storage import upload_capture_asset

router = APIRouter()
log = logging.getLogger("wildex.capture")

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/3gpp", "video/x-m4v"}
ALLOWED_TYPES = IMAGE_TYPES | VIDEO_TYPES


@router.post("/capture")
async def capture(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
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

        try:
            species = identify_species(identify_path)
        except EnvironmentError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:
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

        image_url = upload_capture_asset(
            original_bytes=content,
            original_content_type=file.content_type,
            original_suffix=suffix,
            extracted_frame_path=frame_path if is_video else None,
        )
        if not image_url:
            log.error("Capture image upload failed; continuing without persistent image")

        saved = False
        card_id = None
        db_error = None

        if db_available():
            db = SessionLocal()
            try:
                row = Card(
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
                db.add(row)
                db.commit()
                db.refresh(row)
                card_id = row.id
                saved = True
            except Exception as exc:
                db.rollback()
                db_error = str(exc)
            finally:
                db.close()
        else:
            db_error = "Database not configured - update DATABASE_URL in .env"

        return {
            "saved": saved,
            "card_id": card_id,
            "db_error": db_error,
            "card": {
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
                "image_url": image_url,
            },
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
