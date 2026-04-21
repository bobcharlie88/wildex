from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.database import SessionLocal, db_available
from app.models import Card, CaptureJob
from app.pipeline.card_generator import generate_card
from app.pipeline.frame_extractor import extract_best_frame, save_frame
from app.pipeline.species_data import get_species_data
from app.pipeline.species_id import (
    SpeciesResult,
    TemporaryIdentificationError,
    identify_species,
    is_temporary_identification_error,
)
from app.services.card_render import apply_render_fields, build_render_card
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
IDENTIFY_RETRY_DELAYS = (1.0, 2.0)
READY_AGE_SECONDS = 5
GROUP_TIME_WINDOW_SECONDS = 90
GROUP_TIME_WINDOW_WITHOUT_GPS_SECONDS = 20
GROUP_DISTANCE_METERS = 150
WORKER_POLL_SECONDS = 3
PROCESSING_STALE_MINUTES = 15
REVIEW_CONFIDENCE_THRESHOLD = 0.70
FAIL_CONFIDENCE_THRESHOLD = 0.45

_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()


@dataclass
class IdentifiedShot:
    job_id: int
    image_url: str | None
    species: SpeciesResult


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
        "encounter_id": job.encounter_id,
        "primary_job_id": job.primary_job_id,
        "is_grouped_secondary": bool(job.primary_job_id),
        "grouped_job_ids": _json_list(job.grouped_job_ids),
        "grouped_count": job.grouped_count or 1,
        "species_name": job.species_name,
        "scientific_name": job.scientific_name,
        "confidence": round(job.confidence, 4) if job.confidence is not None else None,
        "provisional": job.provisional,
        "repeat_state": job.repeat_state,
        "card_id": job.card_id,
        "region": job.region,
        "region_unlocked": job.region_unlocked,
        "error_message": job.error_message,
        "review_reason": job.review_reason,
        "supporting_image_urls": _json_list(job.supporting_image_urls),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def serialize_capture_job(job: CaptureJob) -> dict:
    return _job_payload(job)


def list_capture_jobs_for_user(user_id: int, *, include_secondary: bool = False, limit: int = 40) -> dict:
    if not db_available() or SessionLocal is None:
        return {"items": [], "counts": {"queued": 0, "processing": 0, "complete": 0, "failed": 0, "needs_review": 0}}

    db = SessionLocal()
    try:
        rows = (
            db.query(CaptureJob)
            .filter(CaptureJob.owner_id == user_id)
            .order_by(CaptureJob.created_at.desc(), CaptureJob.id.desc())
            .limit(limit)
            .all()
        )
        if not include_secondary:
            rows = [row for row in rows if row.primary_job_id is None]
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
        _worker_thread.join(timeout=2)


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
    db = SessionLocal()
    try:
        cutoff = _utcnow() - timedelta(minutes=PROCESSING_STALE_MINUTES)
        rows = (
            db.query(CaptureJob)
            .filter(CaptureJob.status == "processing", CaptureJob.started_at < cutoff)
            .all()
        )
        if not rows:
            return
        for row in rows:
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
        ready_before = _utcnow() - timedelta(seconds=READY_AGE_SECONDS)
        row = (
            db.query(CaptureJob)
            .filter(
                CaptureJob.status == "queued",
                CaptureJob.primary_job_id.is_(None),
                CaptureJob.created_at <= ready_before,
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


def _identify_with_retry(image_path: str, lat: float | None = None, lon: float | None = None) -> SpeciesResult:
    last_exc = None
    for idx in range(len(IDENTIFY_RETRY_DELAYS) + 1):
        try:
            return identify_species(image_path, lat=lat, lon=lon)
        except EnvironmentError:
            raise
        except Exception as exc:
            last_exc = exc
            if not isinstance(exc, TemporaryIdentificationError) and not is_temporary_identification_error(exc):
                raise
            if idx >= len(IDENTIFY_RETRY_DELAYS):
                raise
            time.sleep(IDENTIFY_RETRY_DELAYS[idx])
    raise last_exc  # pragma: no cover


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


def _materialize_image(image_url: str) -> tuple[str, bool]:
    if image_url.startswith("/uploads/"):
        local_path = Path("uploads") / Path(image_url).name
        if not local_path.exists():
            log.warning("Missing local image during processing: %s", image_url)
            raise FileNotFoundError("Saved capture image is missing")
        return str(local_path), False
    response = httpx.get(image_url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    suffix = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(response.content)
        return tmp.name, True


def _cluster_key(species: SpeciesResult) -> str:
    if species.taxon_id:
        return f"taxon:{species.taxon_id}"
    if species.scientific_name:
        return f"name:{species.scientific_name.strip().lower()}"
    return f"fallback:{(species.common_name or 'unknown').strip().lower()}:{species.category}"


def _clone_species(species: SpeciesResult, *, confidence: float, provisional: bool, reasoning: str) -> SpeciesResult:
    return SpeciesResult(
        scientific_name=species.scientific_name,
        common_name=species.common_name,
        confidence=confidence,
        rank=species.rank,
        provisional=provisional,
        reasoning=reasoning,
        subject_visible=species.subject_visible,
        category=species.category,
        sub_category=species.sub_category,
        taxon_id=species.taxon_id,
        inat_common_name=species.inat_common_name,
        wikipedia_summary=species.wikipedia_summary,
        iconic_taxon=species.iconic_taxon,
        conservation_status=species.conservation_status,
        observations_count=species.observations_count,
        inat_validated=species.inat_validated,
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


def _save_completed_card(db, *, owner_id: int, species: SpeciesResult, best_job: CaptureJob, supporting_urls: list[str]) -> tuple[Card, bool, str]:
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
        capture_country=gbif.query_country if gbif else None,
        original_image_url=best_job.original_image_url or best_job.primary_image_url or best_job.image_url,
        primary_card_image_url=best_job.primary_image_url or best_job.image_url,
        image_url=best_job.image_url,
        supporting_image_urls=json.dumps(supporting_urls),
    )
    render_data = build_render_card(
        {
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
        }
    )
    apply_render_fields(row, render_data)
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
    supporting_urls: list[str] | None = None,
) -> None:
    encounter_id = primary_job.encounter_id or uuid.uuid4().hex
    grouped_ids = [job.id for job in jobs]
    supporting_json = json.dumps(supporting_urls or [])
    completed_at = _utcnow()
    for job in jobs:
        job.status = status
        job.encounter_id = encounter_id
        job.primary_job_id = None if job.id == primary_job.id else primary_job.id
        job.grouped_job_ids = json.dumps(grouped_ids)
        job.grouped_count = len(grouped_ids)
        job.species_name = species_name
        job.scientific_name = scientific_name
        job.confidence = confidence
        job.provisional = provisional
        job.repeat_state = repeat_state
        job.card_id = card_id
        job.region = region
        job.region_unlocked = region_unlocked
        job.error_message = error_message
        job.review_reason = review_reason
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
        seed.encounter_id = encounter_id

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
        db.commit()

        working_set = [seed] + selected_candidates
        shots: list[IdentifiedShot] = []
        failures: list[str] = []
        for job in working_set:
            if not job.image_url:
                log.warning("Capture job missing primary image before identification job_id=%s original=%s", job.id, job.original_image_url)
                failures.append(f"Capture #{job.id} has no stored image.")
                continue
            try:
                image_path, should_delete = _materialize_image(job.image_url)
                if should_delete:
                    tmp_paths.append(image_path)
                species = _identify_with_retry(image_path, lat=job.latitude, lon=job.longitude)
                shots.append(IdentifiedShot(job_id=job.id, image_url=job.image_url, species=species))
            except EnvironmentError as exc:
                failures.append(str(exc))
            except Exception as exc:
                failures.append(str(exc))

        if not shots:
            failure_text = "; ".join(failures) or "Identification failed for all images in this encounter."
            temporary = failures and all(_looks_temporary_failure(message) for message in failures)
            _set_jobs_terminal(
                db,
                working_set,
                primary_job=seed,
                status="needs_review" if temporary else "failed",
                review_reason="Identification service was temporarily unavailable. Capture preserved for review." if temporary else None,
                error_message=None if temporary else failure_text,
            )
            db.commit()
            return

        clusters: dict[str, list[IdentifiedShot]] = {}
        for shot in shots:
            clusters.setdefault(_cluster_key(shot.species), []).append(shot)
        best_cluster = max(
            clusters.values(),
            key=lambda items: (
                len(items),
                round(sum(item.species.confidence for item in items) / len(items), 5),
                max(item.species.confidence for item in items),
            ),
        )

        selected_ids = {shot.job_id for shot in best_cluster}
        if len(best_cluster) >= 2 and seed.id not in selected_ids:
            selected_ids.add(seed.id)
        selected_jobs = [job for job in working_set if job.id in selected_ids]
        unselected_jobs = [job for job in working_set if job.id not in selected_ids]
        if unselected_jobs:
            _reset_unselected_jobs(unselected_jobs)

        best_shot = max(best_cluster, key=lambda shot: shot.species.confidence)
        best_job = next(job for job in selected_jobs if job.id == best_shot.job_id)
        supporting_urls = [
            (job.primary_image_url or job.image_url)
            for job in selected_jobs
            if job.id != best_job.id and (job.primary_image_url or job.image_url)
        ]
        log.info(
            "Selected primary card image job_id=%s image=%s encounter=%s grouped=%s",
            best_job.id,
            best_job.primary_image_url or best_job.image_url,
            encounter_id,
            len(selected_jobs),
        )

        grouped_confidence = min(
            0.99,
            max(item.species.confidence for item in best_cluster) + (0.03 * max(0, len(best_cluster) - 1)),
        )
        grouped_reasoning = best_shot.species.reasoning
        if len(best_cluster) > 1:
            grouped_reasoning = f"{grouped_reasoning} Cross-checked against {len(best_cluster)} nearby shots."
        grouped_species = _clone_species(
            best_shot.species,
            confidence=grouped_confidence,
            provisional=grouped_confidence < REVIEW_CONFIDENCE_THRESHOLD,
            reasoning=grouped_reasoning,
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
                supporting_urls=supporting_urls,
            )
            db.commit()
            return

        if grouped_species.provisional or grouped_species.confidence < REVIEW_CONFIDENCE_THRESHOLD:
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
            supporting_urls=supporting_urls,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("Capture job %s failed", seed_id)
        row = db.query(CaptureJob).filter(CaptureJob.id == seed_id).first()
        if row:
            rows = (
                db.query(CaptureJob)
                .filter(
                    CaptureJob.owner_id == row.owner_id,
                    CaptureJob.status == "processing",
                    CaptureJob.encounter_id == row.encounter_id,
                )
                .all()
            ) or [row]
            for item in rows:
                item.status = "failed"
                item.error_message = str(exc)
                item.completed_at = _utcnow()
            db.commit()
    finally:
        db.close()
        for path in tmp_paths:
            if os.path.exists(path):
                os.unlink(path)
