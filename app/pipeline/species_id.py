"""
Species identification pipeline.

Provider order:
1. Gemini Vision
2. iNaturalist computer vision (best-effort, unsupported public surface)
3. Google Vision labels/objects
4. iNaturalist taxa enrichment for non-terrain results

Invasive status is not stored here. It remains GPS-specific and is handled in
species_data.py.
"""

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GOOGLE_VISION_API_KEY, INATURALIST_API_KEY

log = logging.getLogger("wildex.species_id")

GEMINI_MODEL = "gemini-2.5-flash"
INAT_TAXA_URL = "https://api.inaturalist.org/v1/taxa"
INAT_CV_URL = "https://api.inaturalist.org/v1/computervision/score_image"
INAT_OBSERVATIONS_URL = "https://api.inaturalist.org/v1/observations"
ALA_OCCURRENCES_URL = "https://api.ala.org.au/occurrences/search"
GOOGLE_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
GBIF_SPECIES_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_OCCURRENCE_URL = "https://api.gbif.org/v1/occurrence/search"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
GEO_HEADERS = {"User-Agent": "WildEx/0.1 (wildlife-discovery-game)"}
CONFIDENCE_THRESHOLD = 0.70
TEMPORARY_ERROR_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "deadline exceeded",
    "high demand",
    "internal error",
    "over capacity",
    "overloaded",
    "quota exceeded",
    "rate limit",
    "resource_exhausted",
    "resource exhausted",
    "service unavailable",
    "temporarily unavailable",
    "timeout",
    "try again later",
    "unavailable",
)

SPECIES_ID_PROMPT = """You are a field naturalist and geologist with global expertise in animals, \
plants, fungi, and terrain.

Analyse this image and identify what is shown. It may be:
- An animal (wildlife, insects, birds, reptiles, fish, arachnids, etc.)
- A plant (tree, flower, grass, cactus, aquatic plant, etc.)
- A fungus or mushroom
- A terrain feature (rock formation, soil type, water body, landscape)

Respond with a single JSON object - no markdown, no explanation, just the JSON:
{
  "scientific_name": "Genus species",
  "common_name": "Most widely used English name",
  "confidence": 0.95,
  "rank": "species",
  "category": "animal",
  "sub_category": "mammal",
  "reasoning": "One sentence: key visual features that led to this identification",
  "subject_visible": true
}

Rules:
- scientific_name: accepted binomial for species/plants/fungi; for terrain use a descriptive name \
like "Granite outcrop" or "Sandstone formation"
- common_name: the most recognisable English name
- confidence: 0.0-1.0; be honest
- rank: one of species, genus, family, order, class; use "formation" for terrain
- category: one of "animal", "plant", "fungi", "terrain"
- sub_category:
  - animal -> one of: mammal, bird, reptile, amphibian, fish, insect, arachnid, marine, other
  - plant  -> one of: tree, flower, grass, cactus, aquatic_plant, shrub, other
  - fungi  -> one of: mushroom, bracket_fungus, mould, other
  - terrain -> one of: rock, soil, water, landscape
- subject_visible: false if nothing identifiable is in the image
- Do not assume geographic region - identify from visual features only
- For plants, reason explicitly from visible botany: leaf arrangement, leaf margin, venation, stem form, \
surface texture, growth habit, flowers/fruit/seed pods if present
- For plants, do not guess a species from weak evidence; prefer genus or family over an invented species name
- Avoid generic labels like "plant", "weed", or "green shrub" unless that is genuinely all that is visible
"""

GOOGLE_LIVING_TERMS = {
    "animal",
    "bird",
    "mammal",
    "reptile",
    "amphibian",
    "fish",
    "insect",
    "spider",
    "arachnid",
    "plant",
    "tree",
    "flower",
    "grass",
    "shrub",
    "cactus",
    "fungus",
    "mushroom",
}

GOOGLE_TERRAIN_TERMS = {
    "rock",
    "stone",
    "cliff",
    "mountain",
    "landscape",
    "geology",
    "soil",
    "sand",
    "desert",
    "beach",
    "coast",
    "ocean",
    "sea",
    "river",
    "stream",
    "lake",
    "wetland",
    "forest",
    "sky",
}

GENERIC_PLANT_NAMES = {
    "flora",
    "flower",
    "grass",
    "green plant",
    "herb",
    "leaf",
    "plant",
    "seedling",
    "shrub",
    "tree",
    "vegetation",
    "weed",
}


@dataclass(init=False)
class SpeciesResult:
    scientific_name: str
    common_name: str
    confidence: float
    rank: str
    provisional: bool
    reasoning: str
    subject_visible: bool
    category: str = "animal"
    sub_category: str = ""

    @property
    def animal_visible(self) -> bool:
        return self.subject_visible

    taxon_id: int | None = None
    inat_common_name: str = ""
    wikipedia_summary: str = ""
    iconic_taxon: str = ""
    conservation_status: str = ""
    observations_count: int = 0
    inat_validated: bool = False

    def __init__(
        self,
        scientific_name: str,
        common_name: str,
        confidence: float,
        rank: str,
        provisional: bool,
        reasoning: str,
        subject_visible: bool | None = None,
        category: str = "animal",
        sub_category: str = "",
        animal_visible: bool | None = None,
        taxon_id: int | None = None,
        inat_common_name: str = "",
        wikipedia_summary: str = "",
        iconic_taxon: str = "",
        conservation_status: str = "",
        observations_count: int = 0,
        inat_validated: bool = False,
    ):
        self.scientific_name = scientific_name
        self.common_name = common_name
        self.confidence = confidence
        self.rank = rank
        self.provisional = provisional
        self.reasoning = reasoning
        self.subject_visible = subject_visible if subject_visible is not None else bool(animal_visible)
        self.category = category
        self.sub_category = sub_category
        self.taxon_id = taxon_id
        self.inat_common_name = inat_common_name
        self.wikipedia_summary = wikipedia_summary
        self.iconic_taxon = iconic_taxon
        self.conservation_status = conservation_status
        self.observations_count = observations_count
        self.inat_validated = inat_validated


class TemporaryIdentificationError(RuntimeError):
    """Raised when identification providers fail for transient reasons."""


def is_temporary_identification_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in TEMPORARY_ERROR_MARKERS)


def _parse_gemini_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _file_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _location_hint_from_coords(lat: float | None, lon: float | None) -> dict | None:
    if lat is None or lon is None:
        return None
    response = httpx.get(
        NOMINATIM_URL,
        params={"lat": lat, "lon": lon, "format": "json"},
        headers=GEO_HEADERS,
        timeout=15.0,
    )
    response.raise_for_status()
    address = response.json().get("address", {})
    country_code = (address.get("country_code") or "").upper()
    if not country_code:
        return None
    return {
        "country": address.get("country") or country_code,
        "country_code": country_code,
        "state": address.get("state") or address.get("region") or "",
        "locality": address.get("city") or address.get("town") or address.get("suburb") or "",
    }


def _build_gemini_prompt(location_hint: dict | None) -> str:
    if not location_hint:
        return SPECIES_ID_PROMPT

    country = location_hint.get("country") or location_hint.get("country_code") or "unknown"
    state = location_hint.get("state") or "unknown"
    locality = location_hint.get("locality") or "unknown"

    return (
        SPECIES_ID_PROMPT
        + f"""

Capture location context:
- Country: {country}
- State/region: {state}
- Locality: {locality}

Use the location as a plausibility filter when visually similar species overlap.
- Prefer taxa that are known from the capture region when multiple look-alikes fit the image.
- If the location makes a species unlikely, lower confidence and prefer genus/family instead of forcing a precise species.
- Do not return an out-of-range exotic species unless the image is visually unmistakable or clearly captive/domestic.
"""
    )


def _country_occurrence_count(scientific_name: str, country_code: str) -> int | None:
    if not scientific_name or not country_code:
        return None

    match = httpx.get(
        GBIF_SPECIES_MATCH_URL,
        params={"name": scientific_name, "strict": "false"},
        timeout=15.0,
    )
    match.raise_for_status()
    usage_key = match.json().get("usageKey")
    if not usage_key:
        return None

    response = httpx.get(
        GBIF_OCCURRENCE_URL,
        params={"taxonKey": usage_key, "country": country_code, "limit": 0},
        timeout=15.0,
    )
    response.raise_for_status()
    return int(response.json().get("count", 0))


def _apply_location_plausibility(result: SpeciesResult, location_hint: dict | None) -> SpeciesResult:
    if not location_hint or result.category == "terrain" or result.rank != "species":
        return result

    country_code = location_hint.get("country_code") or ""
    if not country_code:
        return result

    try:
        occurrence_count = _country_occurrence_count(result.scientific_name, country_code)
    except Exception as exc:
        log.warning("Location plausibility check failed: %s", exc)
        return result

    if occurrence_count == 0:
        result.provisional = True
        result.confidence = min(result.confidence, 0.55)
        warning = f" GPS plausibility warning: no GBIF occurrences found in {country_code}."
        if warning.strip() not in result.reasoning:
            result.reasoning = (result.reasoning or "").rstrip(".") + "." + warning

    return result


def validate_species_location(
    scientific_name: str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    category: str | None = None,
    taxon_id: int | None = None,
) -> dict:
    if not scientific_name or lat is None or lon is None or category == "terrain":
        return {
            "valid": False,
            "country_code": None,
            "gbif_occurrences": None,
            "inat_observations": None,
            "ala_occurrences": None,
            "reason": "No usable location validation context was available.",
        }

    try:
        location_hint = _location_hint_from_coords(lat, lon)
    except Exception as exc:
        log.warning("Could not derive validation location hint: %s", exc)
        location_hint = None

    country_code = (location_hint or {}).get("country_code")
    gbif_occurrences = None
    inat_observations = None
    ala_occurrences = None
    reasons: list[str] = []

    if country_code:
        try:
            gbif_occurrences = _country_occurrence_count(scientific_name, country_code)
        except Exception as exc:
            log.warning("GBIF location validation failed for %s: %s", scientific_name, exc)
        else:
            if gbif_occurrences:
                reasons.append(f"GBIF has {gbif_occurrences} country-level occurrences in {country_code}.")

    try:
        params = {
            "lat": lat,
            "lng": lon,
            "radius": 100,
            "per_page": 1,
        }
        if taxon_id:
            params["taxon_id"] = taxon_id
        else:
            params["taxon_name"] = scientific_name
        response = httpx.get(INAT_OBSERVATIONS_URL, params=params, headers=_inat_headers(), timeout=20.0)
        response.raise_for_status()
        inat_observations = int(response.json().get("total_results") or 0)
        if inat_observations:
            reasons.append(f"iNaturalist has {inat_observations} observations within 100 km.")
    except Exception as exc:
        log.warning("iNaturalist location validation failed for %s: %s", scientific_name, exc)

    if country_code == "AU":
        try:
            response = httpx.get(
                ALA_OCCURRENCES_URL,
                params={
                    "q": f'scientificName:"{scientific_name}"',
                    "lat": lat,
                    "lon": lon,
                    "radius": 100,
                    "pageSize": 0,
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            ala_occurrences = int(payload.get("totalRecords") or payload.get("totalRecordsCount") or 0)
            if ala_occurrences:
                reasons.append(f"ALA has {ala_occurrences} nearby Australian occurrence records.")
        except Exception as exc:
            log.warning("ALA location validation failed for %s: %s", scientific_name, exc)

    valid = any(
        count is not None and count > 0
        for count in (gbif_occurrences, inat_observations, ala_occurrences)
    )
    if not reasons:
        reasons.append(
            f"No GBIF, iNaturalist, or ALA distribution support was found near {country_code or 'the capture location'}."
        )
    return {
        "valid": valid,
        "country_code": country_code,
        "gbif_occurrences": gbif_occurrences,
        "inat_observations": inat_observations,
        "ala_occurrences": ala_occurrences,
        "reason": " ".join(reasons),
    }


def _build_result(
    *,
    scientific_name: str,
    common_name: str,
    confidence: float,
    rank: str,
    reasoning: str,
    subject_visible: bool,
    category: str,
    sub_category: str,
) -> SpeciesResult:
    confidence = max(0.0, min(float(confidence or 0.0), 1.0))
    return SpeciesResult(
        scientific_name=scientific_name or "Unknown",
        common_name=common_name or scientific_name or "Unknown",
        confidence=confidence,
        rank=rank or "species",
        provisional=confidence < CONFIDENCE_THRESHOLD,
        reasoning=reasoning,
        subject_visible=subject_visible,
        category=category,
        sub_category=sub_category,
    )


def _normalize_category(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in {"plantae", "plant"}:
        return "plant"
    if text in {"fungi", "fungus", "mushroom"}:
        return "fungi"
    if text in {"terrain", "landscape", "geology", "rock", "soil", "water"}:
        return "terrain"
    return "animal"


def _sub_category_from_iconic(iconic: str) -> str:
    text = (iconic or "").strip().lower()
    mapping = {
        "mammalia": "mammal",
        "aves": "bird",
        "reptilia": "reptile",
        "amphibia": "amphibian",
        "actinopterygii": "fish",
        "insecta": "insect",
        "arachnida": "arachnid",
        "plantae": "other",
        "fungi": "mushroom",
        "terrain": "landscape",
    }
    return mapping.get(text, "other")


def _classify_google_terms(terms: list[str]) -> tuple[str, str]:
    joined = " ".join(t.lower() for t in terms)
    if any(term in joined for term in ("mushroom", "fungus", "fungi", "mold", "mould")):
        return "fungi", "mushroom"
    if any(term in joined for term in ("tree",)):
        return "plant", "tree"
    if any(term in joined for term in ("flower", "blossom")):
        return "plant", "flower"
    if any(term in joined for term in ("grass",)):
        return "plant", "grass"
    if any(term in joined for term in ("cactus",)):
        return "plant", "cactus"
    if any(term in joined for term in ("plant", "leaf", "shrub", "herb")):
        return "plant", "other"
    if any(term in joined for term in ("bird",)):
        return "animal", "bird"
    if any(term in joined for term in ("reptile", "lizard", "snake", "crocodile")):
        return "animal", "reptile"
    if any(term in joined for term in ("frog", "toad", "amphibian")):
        return "animal", "amphibian"
    if any(term in joined for term in ("fish", "shark", "ray")):
        return "animal", "fish"
    if any(term in joined for term in ("spider", "scorpion", "arachnid")):
        return "animal", "arachnid"
    if any(term in joined for term in ("insect", "butterfly", "bee", "beetle", "moth", "dragonfly", "ant")):
        return "animal", "insect"
    if any(term in joined for term in ("ocean", "sea", "coast", "river", "stream", "lake", "waterfall", "water")):
        return "terrain", "water"
    if any(term in joined for term in ("rock", "stone", "cliff", "boulder", "granite", "sandstone")):
        return "terrain", "rock"
    if any(term in joined for term in ("soil", "mud", "sand", "earth", "dirt")):
        return "terrain", "soil"
    if any(term in joined for term in ("landscape", "mountain", "forest", "desert", "wetland", "valley", "plain")):
        return "terrain", "landscape"
    return "animal", "other"


def _looks_like_generic_plant_name(name: str) -> bool:
    text = (name or "").strip().lower()
    return not text or text in GENERIC_PLANT_NAMES


def _plant_sub_category_from_terms(*terms: str) -> str:
    joined = " ".join((term or "").lower() for term in terms)
    if any(word in joined for word in ("tree", "oak", "eucalyptus", "pine", "acacia", "willow", "birch", "elm")):
        return "tree"
    if any(word in joined for word in ("flower", "orchid", "lily", "rose", "daisy", "blossom", "petal")):
        return "flower"
    if any(word in joined for word in ("grass", "reed", "sedge", "bamboo", "turf")):
        return "grass"
    if any(word in joined for word in ("cactus", "succulent", "agave", "aloe")):
        return "cactus"
    if any(word in joined for word in ("waterlily", "water lily", "pondweed", "duckweed", "kelp", "mangrove", "aquatic")):
        return "aquatic_plant"
    if any(word in joined for word in ("shrub", "bush", "heath", "scrub")):
        return "shrub"
    return "other"


def _inat_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if INATURALIST_API_KEY:
        headers["Authorization"] = f"Bearer {INATURALIST_API_KEY}"
    return headers


def identify_with_gemini(image_path: str, *, location_hint: dict | None = None) -> SpeciesResult:
    key_present = bool(GEMINI_API_KEY) and not (GEMINI_API_KEY or "").startswith("your_")
    path = Path(image_path)
    file_size = path.stat().st_size if path.exists() else 0
    log.info(
        "gemini_start image=%s size=%d key_present=%s model=%s",
        image_path, file_size, key_present, GEMINI_MODEL,
    )

    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("your_"):
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Get a key at https://aistudio.google.com/apikey "
            "and add it to .env as GEMINI_API_KEY."
        )

    path = Path(image_path)
    with path.open("rb") as fh:
        image_bytes = fh.read()

    t0 = time.monotonic()
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=_file_mime(path)),
                _build_gemini_prompt(location_hint),
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        log.warning(
            "gemini_fail elapsed=%.2fs error_type=%s error=%s",
            elapsed, type(exc).__name__, str(exc)[:400],
        )
        raise

    elapsed = time.monotonic() - t0
    text_len = len(response.text or "")
    log.info("gemini_ok elapsed=%.2fs text_len=%d", elapsed, text_len)

    data = _parse_gemini_json(response.text)
    result = _build_result(
        scientific_name=data.get("scientific_name", "Unknown"),
        common_name=data.get("common_name", ""),
        confidence=data.get("confidence", 0.0),
        rank=data.get("rank", "species"),
        reasoning=data.get("reasoning", ""),
        subject_visible=data.get("subject_visible", data.get("animal_visible", True)),
        category=_normalize_category(data.get("category", "animal")),
        sub_category=data.get("sub_category", ""),
    )
    if result.category == "plant":
        if not result.sub_category or result.sub_category == "other":
            result.sub_category = _plant_sub_category_from_terms(result.common_name, result.scientific_name, result.reasoning)
        if _looks_like_generic_plant_name(result.common_name):
            result.provisional = True
    return result


def identify_with_inat_cv(image_path: str) -> SpeciesResult:
    path = Path(image_path)
    file_size = path.stat().st_size if path.exists() else 0
    inat_key_present = bool(INATURALIST_API_KEY)
    log.info("inat_cv_start image=%s size=%d key_present=%s", image_path, file_size, inat_key_present)
    t0 = time.monotonic()
    try:
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, _file_mime(path))}
            response = httpx.post(
                INAT_CV_URL,
                headers=_inat_headers(),
                files=files,
                timeout=30.0,
            )
        elapsed = time.monotonic() - t0
        log.info("inat_cv_response elapsed=%.2fs status=%d", elapsed, response.status_code)
        response.raise_for_status()
    except Exception as exc:
        elapsed = time.monotonic() - t0
        status = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning(
            "inat_cv_fail elapsed=%.2fs status=%s error_type=%s error=%s",
            elapsed, status, type(exc).__name__, str(exc)[:300],
        )
        raise
    data = response.json()

    results = data.get("results") or []
    if not results:
        raise ValueError("iNaturalist CV returned no results")

    top = results[0] or {}
    taxon = top.get("taxon") or {}
    scientific_name = taxon.get("name") or top.get("name") or "Unknown"
    common_name = (
        taxon.get("preferred_common_name")
        or top.get("preferred_common_name")
        or top.get("matched_term")
        or scientific_name
    )
    raw_score = (
        top.get("combined_score")
        or top.get("vision_score")
        or top.get("score")
        or top.get("frequency_score")
        or 0.0
    )
    confidence = float(raw_score)
    if confidence > 1.0:
        confidence = confidence / 100.0

    iconic = taxon.get("iconic_taxon_name", "")
    category = _normalize_category(iconic)
    result = _build_result(
        scientific_name=scientific_name,
        common_name=common_name,
        confidence=confidence,
        rank=taxon.get("rank", "species"),
        reasoning="Fallback via iNaturalist computer vision.",
        subject_visible=True,
        category=category,
        sub_category=_sub_category_from_iconic(iconic),
    )
    result.taxon_id = taxon.get("id")
    result.inat_common_name = common_name
    result.iconic_taxon = iconic
    result.inat_validated = bool(result.taxon_id)
    if result.category == "plant":
        result.sub_category = _plant_sub_category_from_terms(common_name, scientific_name)
        if _looks_like_generic_plant_name(result.common_name):
            result.provisional = True
    return result


def identify_with_google_vision(image_path: str) -> SpeciesResult:
    gv_key_present = bool(GOOGLE_VISION_API_KEY) and not (GOOGLE_VISION_API_KEY or "").startswith("your_")
    log.info("google_vision_start image=%s key_present=%s", image_path, gv_key_present)
    if not GOOGLE_VISION_API_KEY or GOOGLE_VISION_API_KEY.startswith("your_"):
        raise EnvironmentError("GOOGLE_VISION_API_KEY not set.")

    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    payload = {
        "requests": [
            {
                "image": {"content": image_b64},
                "features": [
                    {"type": "LABEL_DETECTION", "maxResults": 10},
                    {"type": "OBJECT_LOCALIZATION", "maxResults": 10},
                ],
            }
        ]
    }
    response = httpx.post(
        GOOGLE_VISION_URL,
        params={"key": GOOGLE_VISION_API_KEY},
        json=payload,
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    result = (data.get("responses") or [{}])[0]
    if result.get("error"):
        raise ValueError(result["error"].get("message", "Google Vision request failed"))

    labels = result.get("labelAnnotations") or []
    objects = result.get("localizedObjectAnnotations") or []
    terms = [item.get("description", "") for item in labels] + [item.get("name", "") for item in objects]
    scored_terms = [
        (item.get("description", ""), float(item.get("score", 0.0)))
        for item in labels
        if item.get("description")
    ] + [
        (item.get("name", ""), float(item.get("score", 0.0)))
        for item in objects
        if item.get("name")
    ]
    if not scored_terms:
        raise ValueError("Google Vision returned no labels")

    category, sub_category = _classify_google_terms(terms)
    preferred = next(
        (
            term
            for term, _ in scored_terms
            if term and (
                term.lower() in GOOGLE_LIVING_TERMS
                or term.lower() in GOOGLE_TERRAIN_TERMS
                or len(term.split()) > 1
            )
        ),
        scored_terms[0][0],
    )
    confidence = max(score for _, score in scored_terms)

    if category == "terrain":
        return _build_result(
            scientific_name=preferred.title(),
            common_name=preferred.title(),
            confidence=confidence,
            rank="formation",
            reasoning="Fallback via Google Vision terrain/object labels.",
            subject_visible=True,
            category=category,
            sub_category=sub_category,
        )

    if category == "plant":
        preferred = next(
            (
                term
                for term, _ in scored_terms
                if term and not _looks_like_generic_plant_name(term)
            ),
            preferred,
        )

    # Use the most specific visible term as a taxa search hint, then let iNat
    # enrichment refine it if possible.
    result = _build_result(
        scientific_name=preferred,
        common_name=preferred.title(),
        confidence=min(confidence, 0.65),
        rank="species" if len(preferred.split()) > 1 else "class",
        reasoning="Fallback via Google Vision labels.",
        subject_visible=True,
        category=category,
        sub_category=sub_category,
    )
    if result.category == "plant":
        result.sub_category = _plant_sub_category_from_terms(preferred, " ".join(terms))
        if _looks_like_generic_plant_name(preferred):
            result.provisional = True
    return result


def identify_with_google_web(image_path: str) -> SpeciesResult:
    log.info("google_web_start image=%s key_present=%s", image_path, bool(GOOGLE_VISION_API_KEY) and not (GOOGLE_VISION_API_KEY or "").startswith("your_"))
    if not GOOGLE_VISION_API_KEY or GOOGLE_VISION_API_KEY.startswith("your_"):
        raise EnvironmentError("GOOGLE_VISION_API_KEY not set.")

    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    payload = {
        "requests": [
            {
                "image": {"content": image_b64},
                "features": [
                    {"type": "WEB_DETECTION", "maxResults": 10},
                ],
            }
        ]
    }
    response = httpx.post(
        GOOGLE_VISION_URL,
        params={"key": GOOGLE_VISION_API_KEY},
        json=payload,
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    result = (data.get("responses") or [{}])[0]
    if result.get("error"):
        raise ValueError(result["error"].get("message", "Google Vision web detection request failed"))

    web = result.get("webDetection") or {}
    entities = web.get("webEntities") or []
    scored_terms = [
        (entity.get("description", ""), float(entity.get("score", 0.0)))
        for entity in entities
        if entity.get("description")
    ]
    if not scored_terms:
        raise ValueError("Google Vision web detection returned no entities")

    terms = [term for term, _ in scored_terms]
    category, sub_category = _classify_google_terms(terms)
    preferred = next(
        (
            term
            for term, _ in scored_terms
            if term and (
                len(term.split()) > 1
                or term.lower() in GOOGLE_LIVING_TERMS
                or term.lower() in GOOGLE_TERRAIN_TERMS
            )
        ),
        scored_terms[0][0],
    )
    confidence = max(score for _, score in scored_terms)

    if category == "terrain":
        return _build_result(
            scientific_name=preferred.title(),
            common_name=preferred.title(),
            confidence=min(confidence, 0.55),
            rank="formation",
            reasoning="Fallback via Google Vision web entities.",
            subject_visible=True,
            category=category,
            sub_category=sub_category,
        )

    if category == "plant":
        preferred = next(
            (
                term
                for term, _ in scored_terms
                if term and not _looks_like_generic_plant_name(term)
            ),
            preferred,
        )

    result = _build_result(
        scientific_name=preferred,
        common_name=preferred.title(),
        confidence=min(confidence, 0.58),
        rank="species" if len(preferred.split()) > 1 else "class",
        reasoning="Fallback via Google Vision web entities.",
        subject_visible=True,
        category=category,
        sub_category=sub_category,
    )
    if result.category == "plant":
        result.sub_category = _plant_sub_category_from_terms(preferred, " ".join(terms))
        if _looks_like_generic_plant_name(preferred):
            result.provisional = True
    return result


def _inat_taxa_lookup(query: str, *, rank: str | None = None, iconic_taxa: str | None = None) -> dict | None:
    params = {"q": query, "per_page": 5}
    if rank:
        params["rank"] = rank
    if iconic_taxa:
        params["iconic_taxa"] = iconic_taxa
    response = httpx.get(
        INAT_TAXA_URL,
        headers=_inat_headers(),
        params=params,
        timeout=15.0,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if iconic_taxa:
        results = [row for row in results if (row.get("iconic_taxon_name") or "").lower() == iconic_taxa.lower()]
    return results[0] if results else None


def enrich_with_inat(result: SpeciesResult) -> SpeciesResult:
    queries: list[str] = []
    preferred_iconic = _CATEGORY_ICONIC.get(result.category)

    for value in (result.scientific_name, result.common_name):
        text = (value or "").strip()
        if not text or text == "Unknown":
            continue
        if result.category == "plant" and _looks_like_generic_plant_name(text):
            continue
        if text not in queries:
            queries.append(text)

    if not queries:
        return result

    taxon = None
    for query in queries:
        taxon = _inat_taxa_lookup(query, rank=result.rank, iconic_taxa=preferred_iconic)
        if taxon:
            break
        taxon = _inat_taxa_lookup(query, iconic_taxa=preferred_iconic)
        if taxon:
            break
        if preferred_iconic:
            continue
        taxon = _inat_taxa_lookup(query, rank=result.rank)
        if taxon:
            break
        taxon = _inat_taxa_lookup(query)
        if taxon:
            break

    if not taxon:
        return result

    cs = taxon.get("conservation_status") or {}
    result.taxon_id = taxon.get("id")
    result.scientific_name = taxon.get("name", result.scientific_name)
    result.inat_common_name = taxon.get("preferred_common_name", "")
    if result.inat_common_name and (not result.common_name or _looks_like_generic_plant_name(result.common_name)):
        result.common_name = result.inat_common_name
    result.wikipedia_summary = taxon.get("wikipedia_summary", "")
    result.iconic_taxon = taxon.get("iconic_taxon_name", "")
    result.conservation_status = cs.get("status_name", "")
    result.observations_count = taxon.get("observations_count", 0)
    result.inat_validated = True
    if result.category == "plant":
        result.sub_category = _plant_sub_category_from_terms(
            result.inat_common_name,
            result.common_name,
            result.scientific_name,
        )
    return result


_CATEGORY_ICONIC = {
    "animal": None,
    "plant": "Plantae",
    "fungi": "Fungi",
    "terrain": "Terrain",
}


def identify_species(image_path: str, lat: float | None = None, lon: float | None = None) -> SpeciesResult:
    log.info("identify_species start image=%s lat=%s lon=%s", image_path, lat, lon)
    provider_errors: list[str] = []
    skipped_providers: list[str] = []
    temporary_failures: list[str] = []
    hard_failures: list[str] = []
    location_hint = None

    if lat is not None and lon is not None:
        try:
            location_hint = _location_hint_from_coords(lat, lon)
        except Exception as exc:
            log.warning("Could not derive location hint from GPS: %s", exc)

    for provider_name, provider in (
        ("gemini", lambda path: identify_with_gemini(path, location_hint=location_hint)),
        ("inaturalist_cv", identify_with_inat_cv),
        ("google_vision", identify_with_google_vision),
        ("google_web", identify_with_google_web),
    ):
        try:
            result = provider(image_path)
            log.info("Species identification succeeded via %s", provider_name)
            break
        except EnvironmentError as exc:
            provider_errors.append(f"{provider_name}: {exc}")
            skipped_providers.append(provider_name)
            log.warning("Species identification provider skipped: %s", provider_errors[-1])
        except Exception as exc:
            provider_errors.append(f"{provider_name}: {exc}")
            if is_temporary_identification_error(exc):
                temporary_failures.append(provider_name)
            else:
                hard_failures.append(provider_name)
            log.warning("Species identification provider failed: %s", provider_errors[-1])
    else:
        message = "All identification providers failed: " + " | ".join(provider_errors)
        log.error(
            "identify_species all_failed skipped=%s temporary=%s hard=%s details=%s",
            skipped_providers, temporary_failures, hard_failures, message[:400],
        )
        if temporary_failures and not hard_failures:
            raise TemporaryIdentificationError(message)
        raise RuntimeError(message)

    if result.category == "terrain":
        result.iconic_taxon = "Terrain"
        return result

    if result.subject_visible and result.confidence > 0.3:
        try:
            enrich_with_inat(result)
        except Exception as exc:
            log.warning("iNaturalist taxa enrichment failed: %s", exc)

        if not result.iconic_taxon and result.category in _CATEGORY_ICONIC:
            result.iconic_taxon = _CATEGORY_ICONIC[result.category] or ""
        if result.category == "plant":
            if not result.sub_category or result.sub_category == "other":
                result.sub_category = _plant_sub_category_from_terms(
                    result.inat_common_name,
                    result.common_name,
                    result.scientific_name,
                    result.reasoning,
                )
            if _looks_like_generic_plant_name(result.common_name) and not result.inat_validated:
                result.provisional = True

    return _apply_location_plausibility(result, location_hint)


def identify_species_candidates(image_path: str, lat: float | None = None, lon: float | None = None) -> list[SpeciesResult]:
    log.info("identify_species_candidates start image=%s lat=%s lon=%s", image_path, lat, lon)
    provider_errors: list[str] = []
    temporary_failures: list[str] = []
    hard_failures: list[str] = []
    location_hint = None

    if lat is not None and lon is not None:
        try:
            location_hint = _location_hint_from_coords(lat, lon)
        except Exception as exc:
            log.warning("Could not derive location hint from GPS: %s", exc)

    collected: list[SpeciesResult] = []
    providers = (
        ("gemini", lambda path: identify_with_gemini(path, location_hint=location_hint)),
        ("inaturalist_cv", identify_with_inat_cv),
        ("google_vision", identify_with_google_vision),
        ("google_web", identify_with_google_web),
    )
    for provider_name, provider in providers:
        try:
            result = provider(image_path)
            if result.category != "terrain" and result.subject_visible and result.confidence > 0.25:
                try:
                    enrich_with_inat(result)
                except Exception as exc:
                    log.warning("iNaturalist taxa enrichment failed during candidate collection: %s", exc)
                if result.category == "plant" and (
                    not result.sub_category or result.sub_category == "other"
                ):
                    result.sub_category = _plant_sub_category_from_terms(
                        result.inat_common_name,
                        result.common_name,
                        result.scientific_name,
                        result.reasoning,
                    )
            result = _apply_location_plausibility(result, location_hint)
            result.reasoning = (result.reasoning or "").rstrip(".") + f". Provider: {provider_name}."
            collected.append(result)
        except EnvironmentError as exc:
            provider_errors.append(f"{provider_name}: {exc}")
        except Exception as exc:
            provider_errors.append(f"{provider_name}: {exc}")
            if is_temporary_identification_error(exc):
                temporary_failures.append(provider_name)
            else:
                hard_failures.append(provider_name)

    if not collected:
        message = "All identification providers failed: " + " | ".join(provider_errors)
        log.error(
            "identify_species_candidates all_failed skipped providers not in lists, temporary=%s hard=%s details=%s",
            temporary_failures, hard_failures, message[:400],
        )
        if temporary_failures and not hard_failures:
            raise TemporaryIdentificationError(message)
        raise RuntimeError(message)

    log.info("identify_species_candidates collected=%d from providers", len(collected))
    by_key: dict[str, SpeciesResult] = {}
    support_counts: dict[str, int] = {}
    for result in collected:
        key = f"{result.taxon_id or ''}:{(result.scientific_name or result.common_name or 'unknown').strip().lower()}"
        support_counts[key] = support_counts.get(key, 0) + 1
        existing = by_key.get(key)
        if existing is None or result.confidence > existing.confidence:
            by_key[key] = result

    ranked = []
    for key, result in by_key.items():
        support = support_counts.get(key, 1)
        if support > 1:
            result.confidence = min(0.99, round(result.confidence + (0.04 * (support - 1)), 4))
            result.reasoning = f"{result.reasoning} Repeated by {support} providers."
        ranked.append(result)

    ranked.sort(key=lambda item: (item.confidence, bool(item.inat_validated), bool(item.taxon_id)), reverse=True)
    return ranked[:6]
