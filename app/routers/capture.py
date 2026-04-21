import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.auth import require_user
from app.models import User
from app.pipeline.species_id import TemporaryIdentificationError, identify_species, is_temporary_identification_error
from app.services.capture_jobs import (
    ALLOWED_TYPES,
    create_capture_job,
    list_capture_jobs_for_user,
)

router = APIRouter()


@router.post("/capture")
async def capture(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    current_user: User = Depends(require_user),
):
    content = await file.read()
    try:
        job = create_capture_job(
            owner_id=current_user.id,
            content=content,
            content_type=file.content_type,
            lat=lat,
            lon=lon,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail.startswith("Unsupported image type:"):
            raise HTTPException(415, detail)
        raise HTTPException(400, detail)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Could not queue capture: {exc}")

    return {
        "queued": job["status"] == "queued",
        "job": job,
        "message": "Capture queued for background processing." if job["status"] == "queued" else "Capture failed before processing could start.",
    }


@router.get("/capture/jobs")
def capture_jobs(
    include_secondary: bool = Query(False),
    limit: int = Query(40, ge=1, le=200),
    current_user: User = Depends(require_user),
):
    return list_capture_jobs_for_user(current_user.id, include_secondary=include_secondary, limit=limit)


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
            if isinstance(exc, TemporaryIdentificationError) or is_temporary_identification_error(exc):
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
