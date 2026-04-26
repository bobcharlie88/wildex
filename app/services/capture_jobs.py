from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app.database import SessionLocal, db_available
from app.models import Card, CaptureJob, ReviewQueueItem, SpeciesResultRecord
from app.pipeline.card_generator import generate_card
from app.pipeline.frame_extractor import extract_best_frame, save_frame
from app.pipeline.species_data import get_species_data
from app.pipeline.species_id import (
    SpeciesResult,
    is_temporary_identification_error,
)
from app.services.agents.orchestrator import run_agent_task
from app.services.card_render import apply_render_fields, build_render_card
from app.services.consensus_identification import _candidate_payload, build_consensus_payload, identify_group_candidates
from app.services.dex import (
    DISCOVERY_CAPTURED,
    DISCOVERY_SEEN,
    DISCOVERY_UNKNOWN,
    derive_region_code,
    sync_card_to_dex,
)
from app.utils.storage import persist_capture_media

log = logging.getLogger("wildex.capture_jobs")

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/3gpp", "video/x-m4v"}
ALLOWED_TYPES = IMAGE_TYPES | VIDEO_TYPES
READY_AGE_SECONDS = 5
GROUP_TIME_WINDOW_SECONDS = 90
GROUP_TIME_WINDOW_WITHOUT_GPS_SECONDS = 20
GROUP_DISTANCE_METERS = 150
WORKER_POLL_SECONDS = 3
PROCESSING_STALE_MINUTES = 3
REVIEW_CONFIDENCE_THRESHOLD = 0.70
FAIL_CONFIDENCE_THRESHOLD = 0.45
MAX_TEMPORARY_ID_RETRIES = 3
TEMPORARY_ID_RETRY_DELAY_SECONDS = 60

_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()
_last_stale_requeue: float = 0.0
_STALE_REQUEUE_INTERVAL = 60.0


def _utcnow() -> datetime:
    return datetime.utcnow()


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _job_payload(job: CaptureJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "media_type": job.media_type,
        "original_image_url": job.original_image_url or job.image_url,
        "primary_image_url": job.primary_image_url or job.image_url,
        "image_url": job.image_url,
        "latitude": job.latitude,
        "longitude": job.longitude,
        "plant_group_id": job.plant_group_id,
        "encounter_id": job.encounter_id,
        "primary_job_id": job.primary_job_id,
        "is_grouped_secondary": bool(job.primary_job_id),
        "grouped_job_ids": _json_list(job.grouped_job_ids),
        "grouped_count": job.grouped_count or 1,
        "species_name": job.species_name,
        "scientific_name": job.scientific_name,
        "confidence": round(job.confidence, 4) if job.confidence is not None else None,
        "consensus_score": round(job.consensus_score, 4) if job.consensus_score is not None else None,
        "location_validated": bool(job.location_validated),
        "provisional": job.provisional,
        "repeat_state": job.repeat_state,
        "card_id": job.card_id,
        "region": job.region,
        "region_unlocked": job.region_unlocked,
        "error_message": job.error_message,
        "review_reason": job.review_reason,
        "identification_reasoning": job.identification_reasoning,
        "alternatives": _json_list(job.alternatives_json),
        "supporting_image_urls": _json_list(job.supporting_image_urls),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def serialize_capture_job(job: CaptureJob) -> dict:
    return _job_payload(job)


def get_capture_job_for_user(user_id: int, job_id: int) -> dict | None:
    if not db_available() or SessionLocal is None:
        return None
    db = SessionLocal()
    try:
        job = db.query(CaptureJob).filter(CaptureJob.id == job_id, CaptureJob.owner_id == user_id).first()
        return serialize_capture_job(job) if job else None
    finally:
        db.close()


def list_capture_jobs_for_user(user_id: int, *, include_secondary: bool = False, limit: int = 40) -> dict:
    if not db_available() or SessionLocal is None:
        return {"items": [], "counts": {"queued": 0, "processing": 0, "complete": 0, "failed": 0, "needs_review": 0}}
    # Self-heal after deploys or worker crashes so jobs do not sit in processing forever.
    start_capture_worker()
    # Throttle stale-job requeue to once per minute to avoid hammering the DB on every poll.
    global _last_stale_requeue
    now = time.monotonic()
    if now - _last_stale_requeue >= _STALE_REQUEUE_INTERVAL:
        _last_stale_requeue = now
        _requeue_stale_jobs()

    db = SessionLocal()
    try:
        query = db.query(CaptureJob).filter(CaptureJob.owner_id == user_id)
        # Apply secondary filter in SQL so the LIMIT is applied after filtering,
        # not before (previous bug: limit ran first, leaving too few primary jobs).
        if not include_secondary:
            query = query.filter(CaptureJob.primary_job_id.is_(None))
        rows = (
            query
            .order_by(CaptureJob.created_at.desc(), CaptureJob.id.desc())
            .limit(limit)
            .all()
        )
        counts = {
            "queued": 0,
            "processing": 0,
            "complete": 0,
            "failed": 0,
            "needs_review": 0,
        }
        for row in rows:
            if row.status in counts:
                counts[row.status] += 1
        return {"items": [serialize_capture_job(row) for row in rows], "counts": counts}
    finally:
        db.close()


def retry_capture_job(*, user_id: int, job_id: int) -> dict:
    if not db_available() or SessionLocal is None:
        raise RuntimeError("Database unavailable")
    db = SessionLocal()
    try:
        job = (
            db.query(CaptureJob)
            .filter(CaptureJob.id == job_id, CaptureJob.owner_id == user_id)
            .first()
        )
        if job is None:
            raise ValueError("Capture job not found")
        if job.status not in ("needs_review", "failed"):
            raise ValueError("Only failed or needs-review captures can be retried")
        if not (job.image_url or job.primary_image_url or job.original_image_url):
            raise ValueError("No image available to retry identification")
        job.status = "queued"
        job.started_at = None
        job.error_message = None
        job.review_reason = None
        job.encounter_id = None
        job.primary_job_id = None
        db.commit()
        db.refresh(job)
        log.info("Re-queued job_id=%s for retry by user_id=%s", job.id, user_id)
        start_capture_worker()
        return serialize_capture_job(job)
    finally:
        db.close()


def confirm_capture_job_species(*, user_id: int, job_id: int, scientific_name: str | None = None) -> dict:
    if not db_available() or SessionLocal is None:
        raise RuntimeError("Database unavailable")

    db = SessionLocal()
    try:
        job = (
            db.query(CaptureJob)
            .filter(CaptureJob.id == job_id, CaptureJob.owner_id == user_id)
            .first()
        )
        if job is None:
            raise ValueError("Capture job not found")
        if job.primary_job_id:
            job = db.query(CaptureJob).filter(CaptureJob.id == job.primary_job_id).first() or job
        if job.status != "needs_review":
            raise ValueError("Only needs-review captures can be confirmed")

        alternatives = _json_list(job.alternatives_json)
        chosen = None
        if scientific_name:
            for item in alternatives:
                if (item.get("scientific_name") or "").strip().lower() == scientific_name.strip().lower():
                    chosen = item
                    break
        if chosen is None and alternatives:
            chosen = alternatives[0]
        if chosen is None and job.scientific_name:
            chosen = {
                "common_name": job.species_name,
                "scientific_name": job.scientific_name,
                "confidence": job.confidence,
                "category": None,
                "sub_category": None,
                "rank": "species",
                "taxon_id": None,
                "iconic_taxon": None,
                "reason": job.identification_reasoning or "User confirmed stored capture result.",
            }
        if chosen is None:
            raise ValueError("No candidate species is available to confirm")

        grouped_ids = _json_list(job.grouped_job_ids) or [job.id]
        selected_jobs = (
            db.query(CaptureJob)
            .filter(CaptureJob.owner_id == user_id, CaptureJob.id.in_(grouped_ids))
            .order_by(CaptureJob.created_at.asc(), CaptureJob.id.asc())
            .all()
        ) or [job]
        best_job = next((item for item in selected_jobs if item.id == job.id), selected_jobs[0])
        supporting_urls = [
            (item.primary_image_url or item.image_url)
            for item in selected_jobs
            if item.id != best_job.id and (item.primary_image_url or item.image_url)
        ]
        species = _species_from_candidate(
            chosen,
            confidence=float(chosen.get("confidence") or job.confidence or REVIEW_CONFIDENCE_THRESHOLD),
            reasoning=job.identification_reasoning or chosen.get("reason") or "User confirmed consensus candidate.",
            provisional=False,
        )
        card_row, region_unlocked, repeat_state = _save_completed_card(
            db,
            owner_id=user_id,
            species=species,
            best_job=best_job,
            supporting_urls=supporting_urls,
            plant_group_id=job.plant_group_id,
            consensus_score=job.consensus_score,
            location_validated=bool(job.location_validated),
            alternatives=alternatives,
            identification_reasoning=job.identification_reasoning or chosen.get("reason"),
        )
        normalized_species = run_agent_task(
            agent_name="species",
            task_type="normalize_capture_species",
            payload={
                "species": species,
                "candidate_list": alternatives[:4],
                "alternatives": alternatives[1:4],
                "consensus_score": job.consensus_score,
                "location_validated": job.location_validated,
                "needs_review": False,
            },
            actor_user_id=user_id,
            capture_job_id=best_job.id,
            card_id=card_row.id,
        )
        _persist_species_result(
            db,
            capture_job_id=best_job.id,
            card_id=card_row.id,
            agent_result=normalized_species,
            plant_group_id=job.plant_group_id,
            record_type="final_confirmed",
            consensus_score=job.consensus_score,
            location_validated=job.location_validated,
            alternatives=alternatives,
            source_job_ids=grouped_ids,
        )
        _set_jobs_terminal(
            db,
            selected_jobs,
            primary_job=best_job,
            status="complete",
            species_name=card_row.species_name,
            scientific_name=card_row.scientific_name,
            confidence=card_row.confidence,
            provisional=False,
            repeat_state=repeat_state,
            card_id=card_row.id,
            region=card_row.region,
            region_unlocked=region_unlocked,
            plant_group_id=job.plant_group_id,
            consensus_score=job.consensus_score,
            location_validated=bool(job.location_validated),
            alternatives=alternatives,
            identification_reasoning=(job.identification_reasoning or chosen.get("reason")),
            supporting_urls=supporting_urls,
        )
        for item in (
            db.query(ReviewQueueItem)
            .filter(ReviewQueueItem.capture_job_id.in_(grouped_ids), ReviewQueueItem.status == "open")
            .all()
        ):
            item.status = "resolved"
            item.resolved_at = _utcnow()
        db.commit()
        db.refresh(best_job)
        return {"job": serialize_capture_job(best_job), "card_id": card_row.id}
    finally:
        db.close()


def _file_suffix(content_type: str) -> str:
    if content_type in VIDEO_TYPES:
        return ".mp4"
    if content_type.endswith("png"):
        return ".png"
    if content_type.endswith("webp"):
        return ".webp"
    if content_type.endswith("heic"):
        return ".heic"
    if content_type.endswith("heif"):
        return ".heif"
    return ".jpg"


def validate_capture_upload(content_type: str | None, content: bytes) -> tuple[str, bool]:
    lowered = (content_type or "").lower()
    if lowered and lowered not in ALLOWED_TYPES:
        raise ValueError(f"Unsupported image type: {content_type}")
    if not content:
        raise ValueError("Empty file received")
    return _file_suffix(lowered), lowered in VIDEO_TYPES


def create_capture_job(*, owner_id: int, content: bytes, content_type: str | None, lat: float | None, lon: float | None) -> dict:
    suffix, is_video = validate_capture_upload(content_type, content)
    if SessionLocal is None:
        raise RuntimeError("Database not configured")
    start_capture_worker()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    frame_path = None
    try:
        if is_video:
            frame, _, _ = extract_best_frame(tmp_path)
            frame_tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            frame_tmp.close()
            frame_path = frame_tmp.name
            save_frame(frame, frame_path)

        persisted = persist_capture_media(
            original_bytes=content,
            original_content_type=content_type,
            original_suffix=suffix,
            extracted_frame_path=frame_path if is_video else None,
        )
        original_image_url = persisted["original_url"]
        primary_image_url = persisted["primary_url"]
        image_url = primary_image_url
        status = "queued" if primary_image_url else "failed"
        error_message = persisted["error"] or (
            None if primary_image_url else "Capture upload failed before background processing could start."
        )
        log.info(
            "Capture upload persisted owner_id=%s media_type=%s original=%s primary=%s",
            owner_id,
            "video" if is_video else "image",
            original_image_url,
            primary_image_url,
        )

        db = SessionLocal()
        try:
            row = CaptureJob(
                owner_id=owner_id,
                status=status,
                media_type="video" if is_video else "image",
                original_image_url=original_image_url,
                primary_image_url=primary_image_url,
                image_url=image_url,
                latitude=lat,
                longitude=lon,
                error_message=error_message,
                completed_at=_utcnow() if status == "failed" else None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return serialize_capture_job(row)
        except Exception:
            log.exception(
                "DB save failed after capture upload owner_id=%s original=%s primary=%s",
                owner_id,
                original_image_url,
                primary_image_url,
            )
            raise
        finally:
            db.close()
    finally:
        os.unlink(tmp_path)
        if frame_path and os.path.exists(frame_path):
            os.unlink(frame_path)


def start_capture_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    if not db_available() or SessionLocal is None:
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="wildex-capture-worker", daemon=True)
    _worker_thread.start()


def stop_capture_worker() -> None:
    _worker_stop.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=20)
        if _worker_thread.is_alive():
            log.warning("Capture worker did not stop cleanly within 20 s — will recover stale jobs on next start")


def _worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            _requeue_stale_jobs()
            seed_id = _claim_seed_job_id()
            if seed_id is None:
                _worker_stop.wait(WORKER_POLL_SECONDS)
                continue
            _process_seed_job(seed_id)
        except Exception:
            log.exception("Capture worker loop failed")
            _worker_stop.wait(WORKER_POLL_SECONDS)


def _requeue_stale_jobs() -> None:
    if SessionLocal is None:
        return
    from sqlalchemy import or_
    db = SessionLocal()
    try:
        cutoff = _utcnow() - timedelta(minutes=PROCESSING_STALE_MINUTES)
        rows = (
            db.query(CaptureJob)
            .filter(
                CaptureJob.status == "processing",
                or_(
                    CaptureJob.started_at < cutoff,
                    CaptureJob.started_at.is_(None),  # catch rows stuck without a start timestamp
                ),
            )
            .all()
        )
        if not rows:
            return
        log.warning("Requeuing %d stale processing job(s)", len(rows))
        for row in rows:
            log.warning("Requeuing stale job id=%s encounter_id=%s started_at=%s", row.id, row.encounter_id, row.started_at)
            row.status = "queued"
            row.started_at = None
            row.encounter_id = None
            row.primary_job_id = None
            row.error_message = "Processing timed out and was re-queued."
        db.commit()
    finally:
        db.close()


def _claim_seed_job_id() -> int | None:
    if SessionLocal is None:
        return None
    db = SessionLocal()
    try:
        from sqlalchemy import or_
        ready_before = _utcnow() - timedelta(seconds=READY_AGE_SECONDS)
        now = _utcnow()
        row = (
            db.query(CaptureJob)
            .filter(
                CaptureJob.status == "queued",
                CaptureJob.primary_job_id.is_(None),
                CaptureJob.created_at <= ready_before,
                or_(
                    CaptureJob.started_at.is_(None),
                    CaptureJob.started_at <= now,
                ),
            )
            .order_by(CaptureJob.created_at.asc(), CaptureJob.id.asc())
            .first()
        )
        if not row:
            return None
        row.status = "processing"
        row.started_at = _utcnow()
        db.commit()
        return row.id
    finally:
        db.close()


def _distance_meters(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in {lat1, lon1, lat2, lon2}:
        return None
    from math import asin, cos, radians, sin, sqrt

    rlat1 = radians(float(lat1))
    rlat2 = radians(float(lat2))
    dlat = radians(float(lat2) - float(lat1))
    dlon = radians(float(lon2) - float(lon1))
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return 6371000 * 2 * asin(sqrt(a))


def _candidate_is_near(seed: CaptureJob, candidate: CaptureJob) -> bool:
    gap = abs((candidate.created_at - seed.created_at).total_seconds())
    if seed.latitude is None or seed.longitude is None or candidate.latitude is None or candidate.longitude is None:
        return gap <= GROUP_TIME_WINDOW_WITHOUT_GPS_SECONDS
    distance = _distance_meters(seed.latitude, seed.longitude, candidate.latitude, candidate.longitude)
    return gap <= GROUP_TIME_WINDOW_SECONDS and distance is not None and distance <= GROUP_DISTANCE_METERS


MAX_ID_IMAGE_PX = 1024


def _materialize_image(image_url: str) -> tuple[str, bool]:
    if image_url.startswith("/uploads/"):
        local_path = Path("uploads") / Path(image_url).name
        if not local_path.exists():
            log.warning("Missing local image during processing: %s", image_url)
            raise FileNotFoundError("Saved capture image is missing")
        return str(local_path), False
    with httpx.stream("GET", image_url, timeout=30.0, follow_redirects=True) as response:
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        suffix = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            for chunk in response.iter_bytes(chunk_size=65536):
                tmp.write(chunk)
            return tmp.name, True


def _resize_for_identification(image_path: str) -> tuple[str, bool]:
    from PIL import Image
    path = Path(image_path)
    original_size = path.stat().st_size
    try:
        with Image.open(path) as img:
            w, h = img.size
            if max(w, h) <= MAX_ID_IMAGE_PX:
                log.info("Image already within limit w=%d h=%d size=%d bytes", w, h, original_size)
                return image_path, False
            ratio = MAX_ID_IMAGE_PX / max(w, h)
            new_w, new_h = int(w * ratio), int(h * ratio)
            resized = img.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            resized.save(tmp.name, "JPEG", quality=85, optimize=True)
            new_size = Path(tmp.name).stat().st_size
        log.info(
            "Resized image for identification %dx%d->%dx%d size=%d->%d bytes",
            w, h, new_w, new_h, original_size, new_size,
        )
        return tmp.name, True
    except Exception as exc:
        log.warning("Image resize failed, using original: %s", exc)
        return image_path, False


def _species_from_candidate(candidate: dict[str, object], *, confidence: float, reasoning: str, provisional: bool) -> SpeciesResult:
    return SpeciesResult(
        scientific_name=str(candidate.get("scientific_name") or candidate.get("label") or "Unknown species"),
        common_name=str(candidate.get("common_name") or candidate.get("label") or candidate.get("scientific_name") or "Unknown species"),
        confidence=confidence,
        rank=str(candidate.get("rank") or "species"),
        provisional=provisional,
        reasoning=reasoning,
        subject_visible=True,
        category=str(candidate.get("category") or "animal"),
        sub_category=str(candidate.get("sub_category") or ""),
        taxon_id=candidate.get("taxon_id"),
        iconic_taxon=str(candidate.get("iconic_taxon") or ""),
    )


def _user_has_region_unlock(db, user_id: int, region: str | None) -> bool:
    if not region:
        return False
    from app.models import DexEntry, UserDexDiscovery

    return bool(
        db.query(UserDexDiscovery)
        .join(DexEntry, DexEntry.id == UserDexDiscovery.dex_entry_id)
        .filter(
            UserDexDiscovery.user_id == user_id,
            DexEntry.region == region,
            UserDexDiscovery.discovery_state == DISCOVERY_CAPTURED,
        )
        .first()
    )


def _repeat_state_from_previous(previous_state: str) -> str:
    if previous_state == DISCOVERY_CAPTURED:
        return "repeat_capture"
    if previous_state == DISCOVERY_SEEN:
        return "first_capture_after_seen"
    return "new_capture"


def _looks_temporary_failure(message: str) -> bool:
    return is_temporary_identification_error(RuntimeError(message))


def _get_id_retry_count(error_message: str | None) -> int:
    msg = (error_message or "").strip()
    if msg.startswith("id_retry:"):
        try:
            return int(msg.split(":")[1])
        except (IndexError, ValueError):
            pass
    return 0


def _persist_species_result(
    db,
    *,
    capture_job_id: int | None,
    card_id: int | None,
    agent_result: dict,
    plant_group_id: str | None = None,
    record_type: str | None = None,
    consensus_score: float | None = None,
    location_validated: bool | None = None,
    alternatives: list[dict] | None = None,
    source_job_ids: list[int] | None = None,
) -> SpeciesResultRecord:
    payload = agent_result.get("payload") or {}
    row = SpeciesResultRecord(
        capture_job_id=capture_job_id,
        card_id=card_id,
        agent_task_id=agent_result.get("task_id"),
        plant_group_id=plant_group_id,
        record_type=record_type,
        common_name=payload.get("common_name"),
        scientific_name=payload.get("scientific_name"),
        confidence=payload.get("confidence"),
        consensus_score=consensus_score if consensus_score is not None else payload.get("consensus_score"),
        location_validated=bool(location_validated if location_validated is not None else payload.get("location_validated")),
        needs_review=bool(payload.get("needs_review")),
        review_reason=payload.get("review_reason"),
        evidence_summary=payload.get("evidence_summary"),
        candidate_list_json=json.dumps(payload.get("candidate_list") or []),
        alternatives_json=json.dumps(alternatives if alternatives is not None else payload.get("alternatives") or []),
        source_job_ids_json=json.dumps(source_job_ids or []),
        taxon_id=payload.get("taxon_id"),
        iconic_taxon=payload.get("iconic_taxon"),
    )
    db.add(row)
    db.flush()
    return row


def _create_review_queue_item(
    db,
    *,
    capture_job_id: int | None,
    card_id: int | None,
    species_result_id: int | None,
    agent_result: dict,
) -> ReviewQueueItem:
    payload = agent_result.get("payload") or {}
    row = ReviewQueueItem(
        capture_job_id=capture_job_id,
        card_id=card_id,
        species_result_id=species_result_id,
        reason=payload.get("reason") or "Capture requires manual review.",
        priority=payload.get("priority") or "medium",
        status="open",
        evidence_summary=payload.get("evidence_summary"),
    )
    db.add(row)
    db.flush()
    return row


def _save_completed_card(
    db,
    *,
    owner_id: int,
    species: SpeciesResult,
    best_job: CaptureJob,
    supporting_urls: list[str],
    plant_group_id: str | None = None,
    consensus_score: float | None = None,
    location_validated: bool = False,
    alternatives: list[dict] | None = None,
    identification_reasoning: str | None = None,
) -> tuple[Card, bool, str]:
    gbif = None
    if best_job.latitude is not None and best_job.longitude is not None:
        try:
            gbif = get_species_data(species.scientific_name, best_job.latitude, best_job.longitude)
        except Exception:
            gbif = None

    card = generate_card(species, gbif)
    region_guess = derive_region_code(gbif.query_country if gbif else None, lat=best_job.latitude, lon=best_job.longitude)
    region_was_unlocked = _user_has_region_unlock(db, owner_id, region_guess)

    row = Card(
        owner_id=owner_id,
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
        captured_at=_utcnow(),
        latitude=best_job.latitude,
        longitude=best_job.longitude,
        plant_group_id=plant_group_id,
        consensus_score=consensus_score,
        location_validated=location_validated,
        alternatives_json=json.dumps(alternatives or []),
        identification_reasoning=identification_reasoning,
        capture_country=gbif.query_country if gbif else None,
        original_image_url=best_job.original_image_url or best_job.primary_image_url or best_job.image_url,
        primary_card_image_url=best_job.primary_image_url or best_job.image_url,
        image_url=best_job.image_url,
        supporting_image_urls=json.dumps(supporting_urls),
    )
    builder_source = {
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
        "capture_country": gbif.query_country if gbif else None,
        "original_image_url": best_job.original_image_url or best_job.image_url,
        "primary_card_image_url": best_job.primary_image_url or best_job.image_url,
        "image_url": best_job.primary_image_url or best_job.image_url,
        "sound_url": None,
    }
    card_builder_result = run_agent_task(
        agent_name="card_builder",
        task_type="build_card_payload",
        payload={"source": builder_source},
        actor_user_id=owner_id,
        capture_job_id=best_job.id,
    )
    render_data = build_render_card(builder_source)
    apply_render_fields(row, render_data)
    row.card_payload_json = json.dumps(card_builder_result.get("payload") or {})
    row.card_payload_version = "1.0.0"
    row.render_status = "ready"
    row.front_template_id = render_data.get("front_template", {}).get("id")
    row.back_template_id = render_data.get("back_template", {}).get("id")
    row.render_card_json = json.dumps(render_data)
    db.add(row)
    db.flush()
    log.info(
        "Saved completed card id=%s owner_id=%s species=%s original=%s primary=%s supporting=%s",
        row.id,
        owner_id,
        row.species_name,
        row.original_image_url,
        row.primary_card_image_url,
        len(supporting_urls),
    )
    _, previous_state = sync_card_to_dex(db, row)
    row.discovery_state = DISCOVERY_CAPTURED
    db.flush()
    run_agent_task(
        agent_name="map",
        task_type="sync_progress",
        payload={
            "user_id": owner_id,
            "region": row.region,
            "region_unlocked": not region_was_unlocked and bool(row.region),
            "repeat_state": _repeat_state_from_previous(previous_state),
        },
        actor_user_id=owner_id,
        card_id=row.id,
        capture_job_id=best_job.id,
    )
    return row, (not region_was_unlocked and bool(row.region)), _repeat_state_from_previous(previous_state)


def _set_jobs_terminal(
    db,
    jobs: list[CaptureJob],
    *,
    primary_job: CaptureJob,
    status: str,
    species_name: str | None = None,
    scientific_name: str | None = None,
    confidence: float | None = None,
    provisional: bool = False,
    repeat_state: str | None = None,
    card_id: int | None = None,
    region: str | None = None,
    region_unlocked: bool = False,
    error_message: str | None = None,
    review_reason: str | None = None,
    plant_group_id: str | None = None,
    consensus_score: float | None = None,
    location_validated: bool = False,
    alternatives: list[dict] | None = None,
    identification_reasoning: str | None = None,
    supporting_urls: list[str] | None = None,
) -> None:
    encounter_id = primary_job.encounter_id or uuid.uuid4().hex
    grouped_ids = [job.id for job in jobs]
    supporting_json = json.dumps(supporting_urls or [])
    alternatives_json = json.dumps(alternatives or [])
    completed_at = _utcnow()
    for job in jobs:
        job.status = status
        job.encounter_id = encounter_id
        job.plant_group_id = plant_group_id or encounter_id
        job.primary_job_id = None if job.id == primary_job.id else primary_job.id
        job.grouped_job_ids = json.dumps(grouped_ids)
        job.grouped_count = len(grouped_ids)
        job.species_name = species_name
        job.scientific_name = scientific_name
        job.confidence = confidence
        job.consensus_score = consensus_score
        job.location_validated = location_validated
        job.provisional = provisional
        job.repeat_state = repeat_state
        job.card_id = card_id
        job.region = region
        job.region_unlocked = region_unlocked
        job.error_message = error_message
        job.review_reason = review_reason
        job.identification_reasoning = identification_reasoning
        job.alternatives_json = alternatives_json
        job.supporting_image_urls = supporting_json
        job.completed_at = completed_at


def _reset_unselected_jobs(jobs: list[CaptureJob]) -> None:
    for job in jobs:
        job.status = "queued"
        job.started_at = None
        job.encounter_id = None
        job.primary_job_id = None


def _process_seed_job(seed_id: int) -> None:
    if SessionLocal is None:
        return

    db = SessionLocal()
    tmp_paths: list[str] = []
    try:
        seed = db.query(CaptureJob).filter(CaptureJob.id == seed_id).first()
        if not seed or seed.status != "processing":
            return
        encounter_id = seed.encounter_id or uuid.uuid4().hex
        plant_group_id = seed.plant_group_id or encounter_id
        seed.encounter_id = encounter_id
        seed.plant_group_id = plant_group_id

        candidates = (
            db.query(CaptureJob)
            .filter(
                CaptureJob.owner_id == seed.owner_id,
                CaptureJob.status == "queued",
                CaptureJob.primary_job_id.is_(None),
                CaptureJob.id != seed.id,
            )
            .order_by(CaptureJob.created_at.asc(), CaptureJob.id.asc())
            .limit(8)
            .all()
        )
        selected_candidates = [job for job in candidates if _candidate_is_near(seed, job)]
        for job in selected_candidates:
            job.status = "processing"
            job.started_at = _utcnow()
            job.encounter_id = encounter_id
            job.plant_group_id = plant_group_id
        db.commit()

        log.info(
            "Processing seed job_id=%s owner_id=%s image=%s retry_count=%d grouped_with=%d",
            seed.id, seed.owner_id, seed.image_url,
            _get_id_retry_count(seed.error_message), len(selected_candidates),
        )
        working_set = [seed] + selected_candidates
        raw_identifications = []
        failures: list[str] = []
        failures_temporary: list[bool] = []
        shot_inputs: list[dict[str, object]] = []
        for job in working_set:
            if not job.image_url:
                log.warning(
                    "Capture job missing image job_id=%s owner_id=%s original=%s",
                    job.id, job.owner_id, job.original_image_url,
                )
                failures.append(f"Capture #{job.id} has no stored image.")
                failures_temporary.append(False)
                continue
            try:
                image_path, should_delete = _materialize_image(job.image_url)
                log.info("Materialized image job_id=%s url=%s path=%s tmp=%s", job.id, job.image_url, image_path, should_delete)
                if should_delete:
                    tmp_paths.append(image_path)
                resized_path, should_delete_resized = _resize_for_identification(image_path)
                if should_delete_resized:
                    tmp_paths.append(resized_path)
                shot_inputs.append(
                    {
                        "job_id": job.id,
                        "image_url": job.image_url,
                        "image_path": resized_path,
                        "latitude": job.latitude,
                        "longitude": job.longitude,
                    }
                )
            except Exception as exc:
                log.error(
                    "Materialize image failed job_id=%s url=%s error_type=%s error=%s",
                    job.id, job.image_url, type(exc).__name__, str(exc)[:300],
                )
                failures.append(str(exc))
                failures_temporary.append(_looks_temporary_failure(str(exc)))

        if not shot_inputs:
            failure_text = "; ".join(failures) or "No loadable images in this encounter."
            temporary = bool(failures_temporary) and all(failures_temporary)
            log.error(
                "No shot_inputs for job_id=%s temporary=%s failure=%s",
                seed.id, temporary, failure_text[:300],
            )
            retry_count = _get_id_retry_count(seed.error_message)
            if temporary and retry_count < MAX_TEMPORARY_ID_RETRIES:
                retry_at = _utcnow() + timedelta(seconds=TEMPORARY_ID_RETRY_DELAY_SECONDS)
                log.warning(
                    "Re-queuing job_id=%s attempt=%d/%d retry_after=%s",
                    seed.id, retry_count + 1, MAX_TEMPORARY_ID_RETRIES, retry_at,
                )
                for job in working_set:
                    job.status = "queued"
                    job.started_at = retry_at
                    job.error_message = f"id_retry:{retry_count + 1}: {failure_text[:200]}"
                db.commit()
                return
            _set_jobs_terminal(
                db,
                working_set,
                primary_job=seed,
                status="needs_review" if temporary else "failed",
                review_reason="Identification service was temporarily unavailable. Capture preserved for review." if temporary else None,
                error_message=None if temporary else failure_text,
                plant_group_id=plant_group_id,
            )
            db.commit()
            return

        from app.pipeline.species_id import TemporaryIdentificationError as _TempIDError
        for shot in shot_inputs:
            log.info("Identifying species job_id=%s image=%s", shot["job_id"], shot.get("image_url"))
            try:
                raw_result = identify_group_candidates(
                    [shot],
                    lat=shot.get("latitude"),
                    lon=shot.get("longitude"),
                )[0]
                log.info(
                    "Identification success job_id=%s top=%s confidence=%.2f",
                    shot["job_id"], raw_result.top_species.scientific_name, raw_result.top_species.confidence,
                )
                raw_identifications.append(raw_result)
            except _TempIDError as exc:
                log.warning("Identification temporary failure job_id=%s error=%s", shot["job_id"], str(exc)[:300])
                failures.append(str(exc))
                failures_temporary.append(True)
            except EnvironmentError as exc:
                log.warning("Identification provider not configured job_id=%s error=%s", shot["job_id"], str(exc)[:200])
                failures.append(str(exc))
                failures_temporary.append(False)
            except Exception as exc:
                log.error(
                    "Identification hard failure job_id=%s error_type=%s error=%s",
                    shot["job_id"], type(exc).__name__, str(exc)[:400],
                )
                failures.append(str(exc))
                failures_temporary.append(is_temporary_identification_error(exc))

        if not raw_identifications:
            failure_text = "; ".join(failures) or "Identification failed for all images in this encounter."
            temporary = bool(failures_temporary) and all(failures_temporary)
            log.error(
                "All identification attempts failed job_id=%s temporary=%s failure=%s",
                seed.id, temporary, failure_text[:400],
            )
            retry_count = _get_id_retry_count(seed.error_message)
            if temporary and retry_count < MAX_TEMPORARY_ID_RETRIES:
                retry_at = _utcnow() + timedelta(seconds=TEMPORARY_ID_RETRY_DELAY_SECONDS)
                log.warning(
                    "Re-queuing job_id=%s attempt=%d/%d retry_after=%s",
                    seed.id, retry_count + 1, MAX_TEMPORARY_ID_RETRIES, retry_at,
                )
                for job in working_set:
                    job.status = "queued"
                    job.started_at = retry_at
                    job.error_message = f"id_retry:{retry_count + 1}: {failure_text[:200]}"
                db.commit()
                return
            _set_jobs_terminal(
                db,
                working_set,
                primary_job=seed,
                status="needs_review" if temporary else "failed",
                review_reason="Identification service was temporarily unavailable. Capture preserved for review." if temporary else None,
                error_message=None if temporary else failure_text,
                plant_group_id=plant_group_id,
            )
            db.commit()
            return

        for raw in raw_identifications:
            raw_agent_result = run_agent_task(
                agent_name="species",
                task_type="normalize_capture_species",
                payload={
                    "species": raw.top_species,
                    "candidate_list": [_candidate_payload(candidate) for candidate in raw.candidates[:4]],
                    "alternatives": [_candidate_payload(candidate) for candidate in raw.candidates[1:4]],
                    "needs_review": raw.top_species.provisional,
                    "review_reason": "Single-image result is provisional and awaiting group consensus." if raw.top_species.provisional else None,
                },
                actor_user_id=seed.owner_id,
                capture_job_id=raw.job_id,
            )
            _persist_species_result(
                db,
                capture_job_id=raw.job_id,
                card_id=None,
                agent_result=raw_agent_result,
                plant_group_id=plant_group_id,
                record_type="raw_image",
            )

        consensus_payload = build_consensus_payload(
            raw_identifications,
            lat=seed.latitude,
            lon=seed.longitude,
            plant_group_id=plant_group_id,
        )
        research_result = run_agent_task(
            agent_name="research",
            task_type="confirm_consensus_identification",
            payload=consensus_payload,
            actor_user_id=seed.owner_id,
            capture_job_id=seed.id,
        )
        final_payload = research_result.get("payload") or {}
        top_candidate = (consensus_payload.get("top_candidates") or [{}])[0]
        support_job_ids = set(top_candidate.get("support_job_ids") or [])
        if not support_job_ids:
            support_job_ids = {item.job_id for item in raw_identifications}

        selected_jobs = [job for job in working_set if job.id in support_job_ids]
        if not selected_jobs:
            selected_jobs = [job for job in working_set if any(raw.job_id == job.id for raw in raw_identifications)]
        unselected_jobs = [job for job in working_set if job.id not in support_job_ids]
        if unselected_jobs:
            _reset_unselected_jobs(unselected_jobs)

        matching_species = None
        for raw in raw_identifications:
            if raw.job_id not in support_job_ids:
                continue
            for candidate in raw.candidates:
                if (
                    candidate.scientific_name == final_payload.get("scientific_name")
                    or (candidate.taxon_id and candidate.taxon_id == final_payload.get("taxon_id"))
                ):
                    matching_species = candidate
                    break
            if matching_species is not None:
                break
        if matching_species is None:
            matching_species = max(raw_identifications, key=lambda item: item.top_species.confidence).top_species

        grouped_species = _species_from_candidate(
            {
                "common_name": final_payload.get("final_species"),
                "scientific_name": final_payload.get("scientific_name"),
                "category": final_payload.get("category") or matching_species.category,
                "sub_category": final_payload.get("sub_category") or matching_species.sub_category,
                "rank": final_payload.get("rank") or matching_species.rank,
                "taxon_id": final_payload.get("taxon_id") or matching_species.taxon_id,
                "iconic_taxon": final_payload.get("iconic_taxon") or matching_species.iconic_taxon,
            },
            confidence=float(final_payload.get("confidence") or matching_species.confidence),
            provisional=bool(final_payload.get("provisional")),
            reasoning=final_payload.get("reasoning") or matching_species.reasoning,
        )

        consensus_species_result = run_agent_task(
            agent_name="species",
            task_type="normalize_capture_species",
            payload={
                "species": grouped_species,
                "candidate_list": consensus_payload.get("top_candidates") or [],
                "alternatives": final_payload.get("alternatives") or consensus_payload.get("alternatives") or [],
                "needs_review": grouped_species.provisional or grouped_species.confidence < REVIEW_CONFIDENCE_THRESHOLD,
                "review_reason": "Identification confidence was too low for an automatic save." if grouped_species.provisional or grouped_species.confidence < REVIEW_CONFIDENCE_THRESHOLD else None,
                "consensus_score": final_payload.get("consensus_score"),
                "location_validated": final_payload.get("location_validated"),
            },
            actor_user_id=seed.owner_id,
            capture_job_id=seed.id,
        )
        best_job = max(
            [job for job in selected_jobs if job.primary_image_url or job.image_url],
            key=lambda job: next(
                (
                    candidate.confidence
                    for raw in raw_identifications
                    if raw.job_id == job.id
                    for candidate in raw.candidates
                    if candidate.scientific_name == grouped_species.scientific_name
                ),
                next((raw.top_species.confidence for raw in raw_identifications if raw.job_id == job.id), 0.0),
            ),
        )
        supporting_urls = [
            (job.primary_image_url or job.image_url)
            for job in selected_jobs
            if job.id != best_job.id and (job.primary_image_url or job.image_url)
        ]
        log.info(
            "Selected primary card image job_id=%s image=%s encounter=%s grouped=%s plant_group=%s",
            best_job.id,
            best_job.primary_image_url or best_job.image_url,
            encounter_id,
            len(selected_jobs),
            plant_group_id,
        )
        species_row = _persist_species_result(
            db,
            capture_job_id=best_job.id,
            card_id=None,
            agent_result=consensus_species_result,
            plant_group_id=plant_group_id,
            record_type="consensus",
            consensus_score=final_payload.get("consensus_score"),
            location_validated=final_payload.get("location_validated"),
            alternatives=final_payload.get("alternatives") or consensus_payload.get("alternatives") or [],
            source_job_ids=sorted(support_job_ids),
        )

        if not grouped_species.subject_visible or grouped_species.confidence < FAIL_CONFIDENCE_THRESHOLD:
            _set_jobs_terminal(
                db,
                selected_jobs,
                primary_job=best_job,
                status="failed",
                species_name=grouped_species.common_name,
                scientific_name=grouped_species.scientific_name,
                confidence=grouped_species.confidence,
                provisional=True,
                repeat_state=None,
                error_message="Capture did not contain a clear enough subject to identify.",
                plant_group_id=plant_group_id,
                consensus_score=final_payload.get("consensus_score"),
                location_validated=bool(final_payload.get("location_validated")),
                alternatives=final_payload.get("alternatives") or consensus_payload.get("alternatives") or [],
                identification_reasoning=final_payload.get("reasoning"),
                supporting_urls=supporting_urls,
            )
            db.commit()
            return

        if grouped_species.provisional or grouped_species.confidence < REVIEW_CONFIDENCE_THRESHOLD:
            review_result = run_agent_task(
                agent_name="review",
                task_type="flag_capture_review",
                payload={
                    "needs_review": True,
                    "confidence": grouped_species.confidence,
                    "reason": "Identification confidence was too low for an automatic save.",
                    "evidence_summary": final_payload.get("reasoning") or grouped_species.reasoning,
                },
                actor_user_id=seed.owner_id,
                capture_job_id=best_job.id,
            )
            _create_review_queue_item(
                db,
                capture_job_id=best_job.id,
                card_id=None,
                species_result_id=species_row.id,
                agent_result=review_result,
            )
            _set_jobs_terminal(
                db,
                selected_jobs,
                primary_job=best_job,
                status="needs_review",
                species_name=grouped_species.common_name,
                scientific_name=grouped_species.scientific_name,
                confidence=grouped_species.confidence,
                provisional=True,
                repeat_state=None,
                review_reason="Identification confidence was too low for an automatic save.",
                plant_group_id=plant_group_id,
                consensus_score=final_payload.get("consensus_score"),
                location_validated=bool(final_payload.get("location_validated")),
                alternatives=final_payload.get("alternatives") or consensus_payload.get("alternatives") or [],
                identification_reasoning=final_payload.get("reasoning"),
                supporting_urls=supporting_urls,
            )
            db.commit()
            return

        card_row, region_unlocked, repeat_state = _save_completed_card(
            db,
            owner_id=seed.owner_id,
            species=grouped_species,
            best_job=best_job,
            supporting_urls=supporting_urls,
            plant_group_id=plant_group_id,
            consensus_score=final_payload.get("consensus_score"),
            location_validated=bool(final_payload.get("location_validated")),
            alternatives=final_payload.get("alternatives") or consensus_payload.get("alternatives") or [],
            identification_reasoning=final_payload.get("reasoning"),
        )
        species_row.card_id = card_row.id
        if card_row.rarity_display in {"Legendary", "Mythic", "Cryptic", "Extinct"}:
            review_result = run_agent_task(
                agent_name="review",
                task_type="flag_unusual_capture",
                payload={
                    "needs_review": True,
                    "confidence": grouped_species.confidence,
                    "reason": f"{card_row.rarity_display} capture flagged for admin review.",
                    "evidence_summary": final_payload.get("reasoning") or grouped_species.reasoning,
                    "rarity": card_row.rarity_display,
                },
                actor_user_id=seed.owner_id,
                capture_job_id=best_job.id,
                card_id=card_row.id,
            )
            _create_review_queue_item(
                db,
                capture_job_id=best_job.id,
                card_id=card_row.id,
                species_result_id=species_row.id,
                agent_result=review_result,
            )
        _set_jobs_terminal(
            db,
            selected_jobs,
            primary_job=best_job,
            status="complete",
            species_name=card_row.species_name,
            scientific_name=card_row.scientific_name,
            confidence=card_row.confidence,
            provisional=card_row.provisional,
            repeat_state=repeat_state,
            card_id=card_row.id,
            region=card_row.region,
            region_unlocked=region_unlocked,
            plant_group_id=plant_group_id,
            consensus_score=final_payload.get("consensus_score"),
            location_validated=bool(final_payload.get("location_validated")),
            alternatives=final_payload.get("alternatives") or consensus_payload.get("alternatives") or [],
            identification_reasoning=final_payload.get("reasoning"),
            supporting_urls=supporting_urls,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("Capture job %s failed", seed_id)
        row = db.query(CaptureJob).filter(CaptureJob.id == seed_id).first()
        if row:
            if row.encounter_id:
                # Only fail jobs that belong to the same encounter group.
                failed_rows = (
                    db.query(CaptureJob)
                    .filter(
                        CaptureJob.owner_id == row.owner_id,
                        CaptureJob.status == "processing",
                        CaptureJob.encounter_id == row.encounter_id,
                    )
                    .all()
                ) or [row]
            else:
                # encounter_id not yet assigned — only fail the seed job itself to
                # avoid incorrectly failing other unrelated in-flight jobs.
                failed_rows = [row]
            for item in failed_rows:
                item.status = "failed"
                item.error_message = str(exc)
                item.completed_at = _utcnow()
            db.commit()
    finally:
        db.close()
        for path in tmp_paths:
            if os.path.exists(path):
                os.unlink(path)
