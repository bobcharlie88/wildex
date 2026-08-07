from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.pipeline.species_id import SpeciesResult, identify_species_candidates, validate_species_location


@dataclass
class RawImageIdentification:
    job_id: int
    image_url: str | None
    top_species: SpeciesResult
    candidates: list[SpeciesResult]


def _species_key(species: SpeciesResult) -> str:
    if species.taxon_id:
        return f"taxon:{species.taxon_id}"
    return f"name:{(species.scientific_name or species.common_name or 'unknown').strip().lower()}"


def _candidate_payload(
    species: SpeciesResult,
    *,
    consensus_score: float | None = None,
    location_validated: bool | None = None,
    location_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "label": species.common_name or species.scientific_name,
        "common_name": species.common_name or species.scientific_name,
        "scientific_name": species.scientific_name,
        "confidence": round(float(species.confidence or 0.0), 4),
        "reason": species.reasoning,
        "category": species.category,
        "sub_category": species.sub_category,
        "rank": species.rank,
        "taxon_id": species.taxon_id,
        "iconic_taxon": species.iconic_taxon,
        "provisional": species.provisional,
        "consensus_score": round(float(consensus_score or 0.0), 4) if consensus_score is not None else None,
        "location_validated": location_validated,
        "location_reason": location_reason,
    }


def _identify_one(shot: dict[str, Any], *, lat: float | None, lon: float | None) -> RawImageIdentification:
    candidates = identify_species_candidates(shot["image_path"], lat=shot.get("latitude", lat), lon=shot.get("longitude", lon))
    return RawImageIdentification(
        job_id=int(shot["job_id"]),
        image_url=shot.get("image_url"),
        top_species=candidates[0],
        candidates=candidates,
    )


def identify_group_candidates(
    shots: list[dict[str, Any]],
    *,
    lat: float | None = None,
    lon: float | None = None,
) -> list[RawImageIdentification]:
    if len(shots) <= 1:
        return [_identify_one(shot, lat=lat, lon=lon) for shot in shots]

    # Each shot is I/O-bound (Gemini + iNaturalist/GBIF HTTP calls), so
    # running them on worker threads cuts wall-clock time roughly linearly
    # with photo count instead of processing one photo after another.
    with ThreadPoolExecutor(max_workers=min(len(shots), 6)) as executor:
        return list(executor.map(lambda shot: _identify_one(shot, lat=lat, lon=lon), shots))


def build_consensus_payload(
    raw_results: list[RawImageIdentification],
    *,
    lat: float | None = None,
    lon: float | None = None,
    plant_group_id: str | None = None,
) -> dict[str, Any]:
    if not raw_results:
        raise ValueError("No raw identifications were supplied for consensus.")

    aggregate: dict[str, dict[str, Any]] = {}
    total_images = len(raw_results)
    for raw in raw_results:
        seen_for_image: set[str] = set()
        for index, candidate in enumerate(raw.candidates[:4]):
            key = _species_key(candidate)
            if key in seen_for_image:
                continue
            seen_for_image.add(key)
            validation = validate_species_location(
                candidate.scientific_name,
                lat=lat,
                lon=lon,
                category=candidate.category,
                taxon_id=candidate.taxon_id,
            ) if lat is not None and lon is not None else {
                "valid": False,
                "reason": "No GPS location available for validation.",
            }
            location_bonus = 0.12 if validation.get("valid") else (-0.16 if lat is not None and lon is not None else 0.0)
            rank_weight = 1.0 if index == 0 else 0.72 if index == 1 else 0.5 if index == 2 else 0.3
            weighted_score = max(0.0, (candidate.confidence * rank_weight) + location_bonus)
            item = aggregate.setdefault(
                key,
                {
                    "species": candidate,
                    "weighted_total": 0.0,
                    "confidence_total": 0.0,
                    "support_jobs": set(),
                    "location_hits": 0,
                    "location_reason": validation.get("reason"),
                },
            )
            item["weighted_total"] += weighted_score
            item["confidence_total"] += candidate.confidence
            item["support_jobs"].add(raw.job_id)
            if validation.get("valid"):
                item["location_hits"] += 1
            if candidate.confidence > item["species"].confidence:
                item["species"] = candidate
                item["location_reason"] = validation.get("reason")

    ranked: list[dict[str, Any]] = []
    for item in aggregate.values():
        support_count = len(item["support_jobs"])
        if total_images >= 3 and support_count == 1 and item["weighted_total"] < 0.55:
            continue
        avg_confidence = item["confidence_total"] / max(1, support_count)
        support_ratio = support_count / max(1, total_images)
        location_validated = item["location_hits"] > 0
        consensus_score = min(0.99, round(item["weighted_total"] / max(1.0, total_images), 4))
        final_confidence = min(
            0.99,
            round(
                (avg_confidence * 0.55)
                + (support_ratio * 0.3)
                + (0.15 if location_validated else 0.0),
                4,
            ),
        )
        ranked.append(
            {
                "species": item["species"],
                "support_count": support_count,
                "support_job_ids": sorted(item["support_jobs"]),
                "support_ratio": round(support_ratio, 4),
                "avg_confidence": round(avg_confidence, 4),
                "consensus_score": consensus_score,
                "confidence": final_confidence,
                "location_validated": location_validated,
                "location_reason": item["location_reason"],
            }
        )

    if not ranked:
        top_raw = max(raw_results, key=lambda row: row.top_species.confidence)
        ranked = [
            {
                "species": top_raw.top_species,
                "support_count": 1,
                "support_ratio": round(1 / max(1, total_images), 4),
                "avg_confidence": round(top_raw.top_species.confidence, 4),
                "consensus_score": round(top_raw.top_species.confidence * 0.5, 4),
                "confidence": round(min(0.6, top_raw.top_species.confidence), 4),
                "location_validated": False,
                "location_reason": "No candidate had enough repeated support to form a strong consensus.",
            }
        ]

    ranked.sort(
        key=lambda item: (
            item["location_validated"],
            item["support_count"],
            item["consensus_score"],
            item["confidence"],
        ),
        reverse=True,
    )

    top = ranked[0]
    alternatives = [
        _candidate_payload(
            item["species"],
            consensus_score=item["consensus_score"],
            location_validated=item["location_validated"],
            location_reason=item["location_reason"],
        )
        for item in ranked[1:4]
    ]
    raw_payload = [
        {
            "job_id": row.job_id,
            "image_url": row.image_url,
            "top_result": _candidate_payload(row.top_species),
            "candidate_list": [_candidate_payload(candidate) for candidate in row.candidates[:4]],
        }
        for row in raw_results
    ]
    return {
        "plant_group_id": plant_group_id,
        "top_candidates": [
            {
                **_candidate_payload(
                    item["species"],
                    consensus_score=item["consensus_score"],
                    location_validated=item["location_validated"],
                    location_reason=item["location_reason"],
                ),
                "support_count": item["support_count"],
                "support_job_ids": item["support_job_ids"],
                "support_ratio": item["support_ratio"],
            }
            for item in ranked[:4]
        ],
        "raw_results": raw_payload,
        "final_species": top["species"].common_name or top["species"].scientific_name,
        "scientific_name": top["species"].scientific_name,
        "confidence": top["confidence"],
        "consensus_score": top["consensus_score"],
        "location_validated": top["location_validated"],
        "alternatives": alternatives,
        "reasoning": (
            f"{top['species'].common_name or top['species'].scientific_name} was repeated across "
            f"{top['support_count']} of {total_images} shots. {top['location_reason'] or ''}".strip()
        ),
        "category": top["species"].category,
        "sub_category": top["species"].sub_category,
        "rank": top["species"].rank,
        "taxon_id": top["species"].taxon_id,
        "iconic_taxon": top["species"].iconic_taxon,
        "provisional": bool(top["confidence"] < 0.78 or top["consensus_score"] < 0.68),
    }
