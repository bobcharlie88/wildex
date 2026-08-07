from __future__ import annotations

import hashlib
import math
from sqlalchemy.orm import Session

from app.models import Card, DexEntry, UserDexDiscovery


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine formula to compute distance in km between two lat/lon points."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    return r * 2.0 * math.asin(math.sqrt(a))


def fuzz_coordinates(
    lat: float | None,
    lon: float | None,
    rarity_tier: str | None = None,
    conservation_status: str | None = None,
) -> tuple[float | None, float | None, bool]:
    """
    Privacy-first coordinate fuzzer.
    Fuzzes exact coordinates by 1-5km for rare/legendary/endangered species on public maps.
    Returns (fuzzed_lat, fuzzed_lon, is_fuzzed).
    """
    if lat is None or lon is None:
        return None, None, False

    rarity = str(rarity_tier or "").lower()
    conservation = str(conservation_status or "").lower()
    is_sensitive = rarity in ("rare", "very_rare", "legendary", "mythic", "extinct") or any(
        kw in conservation for kw in ("endangered", "vulnerable", "threatened", "critically")
    )

    # Use deterministic hash of lat/lon so the fuzzed point stays stable for the same location
    seed_str = f"{lat:.4f}:{lon:.4f}:{rarity}"
    hash_digest = hashlib.md5(seed_str.encode()).hexdigest()
    val1 = int(hash_digest[:8], 16) / 0xFFFFFFFF
    val2 = int(hash_digest[8:16], 16) / 0xFFFFFFFF

    if is_sensitive:
        # Offset 1.0 - 5.0 km (~0.01 to 0.045 degrees)
        lat_offset = (val1 - 0.5) * 0.07
        lon_offset = (val2 - 0.5) * 0.07
        return round(lat + lat_offset, 5), round(lon + lon_offset, 5), True
    else:
        # Minor privacy buffer (~200m)
        lat_offset = (val1 - 0.5) * 0.003
        lon_offset = (val2 - 0.5) * 0.003
        return round(lat + lat_offset, 5), round(lon + lon_offset, 5), False


def get_explore_map_data(
    db: Session,
    user_id: int,
    user_lat: float | None = None,
    user_lon: float | None = None,
    radius_km: float = 25.0,
) -> dict:
    """
    Returns public exploration map layer:
    - fuzzed public markers
    - user's private historical timeline (exact coordinates)
    - nearby undiscovered target radar within radius_km
    """
    all_cards = db.query(Card).order_by(Card.captured_at.desc()).limit(100).all()

    public_markers = []
    user_private_markers = []

    for c in all_cards:
        if c.latitude is None or c.longitude is None:
            continue

        f_lat, f_lon, is_fuzzed = fuzz_coordinates(
            c.latitude, c.longitude, c.rarity_tier, c.conservation_status
        )

        marker_item = {
            "card_id": c.id,
            "species_name": c.species_name,
            "scientific_name": c.scientific_name,
            "rarity_display": c.rarity_display or c.rarity_tier,
            "image_url": c.image_url or c.primary_card_image_url,
            "category": c.category,
            "sub_category": c.sub_category,
            "lat": f_lat,
            "lon": f_lon,
            "is_fuzzed": is_fuzzed,
        }
        public_markers.append(marker_item)

        if c.owner_id == user_id:
            user_private_markers.append({
                **marker_item,
                "lat": c.latitude,  # exact private coordinate
                "lon": c.longitude,
                "is_fuzzed": False,
                "captured_at": c.captured_at.isoformat() if c.captured_at else None,
            })

    # Find nearby undiscovered species targets if user_lat and user_lon provided
    nearby_targets = []
    if user_lat is not None and user_lon is not None:
        user_discoveries = (
            db.query(UserDexDiscovery.dex_entry_id)
            .filter(UserDexDiscovery.user_id == user_id)
            .all()
        )
        discovered_entry_ids = {d[0] for d in user_discoveries}

        dex_entries = db.query(DexEntry).limit(50).all()
        for entry in dex_entries:
            if entry.id in discovered_entry_ids:
                continue
            matching_card = (
                db.query(Card)
                .filter(Card.dex_entry_id == entry.id, Card.latitude.isnot(None))
                .first()
            )
            if matching_card:
                dist = _distance_km(user_lat, user_lon, matching_card.latitude, matching_card.longitude)
                if dist <= radius_km:
                    nearby_targets.append({
                        "dex_id": entry.dex_id,
                        "display_name": entry.display_name or matching_card.species_name,
                        "scientific_name": entry.scientific_name or matching_card.scientific_name,
                        "distance_km": round(dist, 2),
                        "hint": entry.discovery_hint or f"Reported within {round(dist, 1)}km",
                    })

    return {
        "public_markers": public_markers,
        "user_private_markers": user_private_markers,
        "nearby_targets": nearby_targets,
        "total_public_records": len(public_markers),
    }
