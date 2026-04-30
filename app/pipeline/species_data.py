"""
GBIF species data integration.

For a given scientific name + GPS coordinates, returns:
  - Rarity tier derived from global occurrence count
  - Geographic range (top countries by observation count)
  - Whether the species is invasive at the GPS location

Invasive status is region-specific: a species invasive in New Zealand may
be native in Australia. The GPS coordinates determine which applies by
cross-referencing GBIF species profiles against the GRIIS
(Global Register of Introduced and Invasive Species).

All GBIF and Nominatim endpoints are free with no authentication required.
"""

import httpx
import pycountry
from dataclasses import dataclass

GBIF_API = "https://api.gbif.org/v1"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "WildEx/0.1 (wildlife-discovery-game)"}

GRIIS_PREFIX = "Global Register of Introduced and Invasive Species - "

# Rarity tiers based on global GBIF occurrence count.
# Thresholds tuned so common species (robin, kangaroo) land in "common"
# while genuinely cryptic/localised species reach "rare" or "very_rare".
RARITY_THRESHOLDS = [
    (100_000, "common"),
    (10_000,  "uncommon"),
    (1_000,   "rare"),
    (0,       "very_rare"),
]


@dataclass
class CountryCount:
    iso_code: str
    count: int


@dataclass
class SpeciesData:
    # GBIF match
    gbif_key: int
    scientific_name: str        # GBIF-confirmed canonical name

    # Rarity
    occurrence_count: int
    rarity_tier: str            # common / uncommon / rare / very_rare

    # Range — top countries by GBIF observation count, descending
    top_countries: list[CountryCount]

    # Invasive registry
    griis_countries: list[str]  # ISO-2 codes listed in GRIIS for this species

    # Result for the queried location
    query_lat: float
    query_lon: float
    query_country: str          # ISO-2 code resolved from GPS
    invasive_at_location: bool  # True only if query_country is in griis_countries


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _match_gbif_species(scientific_name: str) -> tuple[int, str]:
    """Match a scientific name to a GBIF usageKey. Returns (key, canonical_name)."""
    r = httpx.get(
        f"{GBIF_API}/species/match",
        params={"name": scientific_name, "strict": "false"},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("matchType") == "NONE" or "usageKey" not in d:
        raise ValueError(f"GBIF could not match species: '{scientific_name}'")
    return d["usageKey"], d.get("scientificName", scientific_name)


def _get_occurrence_count(gbif_key: int) -> int:
    r = httpx.get(
        f"{GBIF_API}/occurrence/search",
        params={"taxonKey": gbif_key, "limit": 0},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("count", 0)


def _get_top_countries(gbif_key: int, top_n: int = 10) -> list[CountryCount]:
    """Use GBIF occurrence facets to get the top countries by observation count."""
    r = httpx.get(
        f"{GBIF_API}/occurrence/search",
        params={"taxonKey": gbif_key, "facet": "country", "facetLimit": top_n, "limit": 0},
        timeout=15,
    )
    r.raise_for_status()
    results = []
    for facet in r.json().get("facets", []):
        if facet.get("field") == "COUNTRY":
            for c in facet.get("counts", []):
                iso = c["name"]
                if iso and iso != "ZZ":     # ZZ = unknown country in GBIF
                    results.append(CountryCount(iso_code=iso, count=c["count"]))
    return results


def _get_rarity_tier(count: int) -> str:
    for threshold, tier in RARITY_THRESHOLDS:
        if count >= threshold:
            return tier
    return "very_rare"


def _get_griis_countries(gbif_key: int) -> list[str]:
    """
    Return ISO-2 country codes where this species appears in the
    Global Register of Introduced and Invasive Species (GRIIS).
    Parsed from GBIF speciesProfiles source strings.
    """
    r = httpx.get(f"{GBIF_API}/species/{gbif_key}/speciesProfiles", timeout=15)
    r.raise_for_status()
    profiles = r.json().get("results", [])

    countries: set[str] = set()
    for profile in profiles:
        source = profile.get("source", "")
        if not source.startswith(GRIIS_PREFIX):
            continue
        country_name = source[len(GRIIS_PREFIX):]
        try:
            matches = pycountry.countries.search_fuzzy(country_name)
            if matches:
                countries.add(matches[0].alpha_2)
        except LookupError:
            pass

    return sorted(countries)


def _reverse_geocode(lat: float, lon: float) -> str:
    """Return ISO-2 country code for GPS coordinates via Nominatim (OpenStreetMap)."""
    r = httpx.get(
        NOMINATIM_URL,
        params={"lat": lat, "lon": lon, "format": "json"},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("address", {}).get("country_code", "").upper()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_species_data(scientific_name: str, lat: float, lon: float) -> SpeciesData:
    """
    Full GBIF lookup for a species at a GPS location.

    Args:
        scientific_name: Binomial or higher taxon name (from Gemini ID step).
        lat, lon: GPS coordinates of the capture location.

    Returns:
        SpeciesData with rarity tier, geographic range, and invasive flag
        specific to the capture country.
    """
    gbif_key, matched_name = _match_gbif_species(scientific_name)

    occurrence_count = _get_occurrence_count(gbif_key)
    top_countries   = _get_top_countries(gbif_key)
    griis_countries = _get_griis_countries(gbif_key)
    country_code    = _reverse_geocode(lat, lon)

    return SpeciesData(
        gbif_key=gbif_key,
        scientific_name=matched_name,
        occurrence_count=occurrence_count,
        rarity_tier=_get_rarity_tier(occurrence_count),
        top_countries=top_countries,
        griis_countries=griis_countries,
        query_lat=lat,
        query_lon=lon,
        query_country=country_code,
        invasive_at_location=(country_code in griis_countries),
    )
