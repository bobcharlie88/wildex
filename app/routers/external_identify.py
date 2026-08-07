"""
Scoped, API-key-authenticated species identification endpoint for external
clients (e.g. the WildChef Survival mobile app). Deliberately separate from
the cookie-session-authenticated /capture flow used by the wildex web app —
this route does not touch user accounts, capture jobs, or the review
pipeline. It just runs a photo through the existing identification providers
and returns candidates synchronously.
"""

import logging
import os
import tempfile
import time
from collections import deque

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.config import EXTERNAL_API_KEY
from app.pipeline.species_id import TemporaryIdentificationError, identify_species_candidates
from app.services.consensus_identification import build_consensus_payload, identify_group_candidates

log = logging.getLogger("wildex.external_identify")

router = APIRouter()

# Simple in-memory sliding-window limiter. The external API key is a single
# shared secret embedded in the mobile app (extractable via decompilation),
# so this caps the cost/abuse blast radius of a leaked key rather than
# providing per-user fairness.
_RATE_LIMIT_MAX_REQUESTS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_request_times: deque[float] = deque()


def _check_rate_limit() -> None:
    now = time.monotonic()
    while _request_times and now - _request_times[0] > _RATE_LIMIT_WINDOW_SECONDS:
        _request_times.popleft()
    if len(_request_times) >= _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(429, "Too many identification requests — please wait a moment and try again.")
    _request_times.append(now)


def _check_api_key(x_api_key: str | None) -> None:
    if not EXTERNAL_API_KEY:
        raise HTTPException(503, "External identification is not configured on this server.")
    if not x_api_key or x_api_key != EXTERNAL_API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key header.")
    _check_rate_limit()


@router.post("/external/identify")
async def external_identify(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    x_api_key: str | None = Header(default=None),
):
    _check_api_key(x_api_key)

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file was empty.")

    suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        candidates = identify_species_candidates(tmp_path, lat=lat, lon=lon)
    except TemporaryIdentificationError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("external_identify failed")
        raise HTTPException(500, f"Identification failed: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {
        "candidates": [
            {
                "scientific_name": c.scientific_name,
                "common_name": c.common_name,
                "confidence": c.confidence,
                "category": c.category,
                "sub_category": c.sub_category,
                "rank": c.rank,
                "reasoning": c.reasoning,
                "provisional": c.provisional,
                "subject_visible": c.subject_visible,
            }
            for c in candidates
        ]
    }


@router.post("/external/identify-batch")
async def external_identify_batch(
    files: list[UploadFile] = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    x_api_key: str | None = Header(default=None),
):
    """
    Multi-photo consensus identification — the same photo consensus scoring
    used by wildex's own capture review flow (see consensus_identification.py):
    each photo is identified independently, then results that repeat across
    photos get a confidence boost while one-off / contradicting guesses are
    discounted. Feed it several angles of the same plant (leaf, flower, stem,
    whole plant) for a materially more trustworthy result than any single shot.
    """
    _check_api_key(x_api_key)

    if not files:
        raise HTTPException(400, "No files uploaded.")
    if len(files) > 8:
        raise HTTPException(400, "Too many files — send at most 8 photos per request.")

    tmp_paths: list[str] = []
    try:
        shots = []
        for index, file in enumerate(files):
            content = await file.read()
            if not content:
                continue
            suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_paths.append(tmp.name)
            shots.append({"job_id": index, "image_path": tmp.name, "image_url": None})

        if not shots:
            raise HTTPException(400, "All uploaded files were empty.")

        raw_results = identify_group_candidates(shots, lat=lat, lon=lon)
        payload = build_consensus_payload(raw_results, lat=lat, lon=lon)
    except TemporaryIdentificationError as exc:
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("external_identify_batch failed")
        raise HTTPException(500, f"Identification failed: {exc}")
    finally:
        for path in tmp_paths:
            if os.path.exists(path):
                os.unlink(path)

    return payload
