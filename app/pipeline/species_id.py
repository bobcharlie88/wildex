"""
Species identification pipeline.

Step 1 — Gemini Vision: identify species from image (global coverage)
Step 2 — iNaturalist taxa API: validate scientific name, enrich with
          taxonomy, conservation status, observation count, Wikipedia summary

Invasive status is NOT stored here — it is GPS-region-specific and handled
in species_data.py using GBIF checklists at capture coordinates.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-2.5-flash"
INAT_TAXA_URL = "https://api.inaturalist.org/v1/taxa"
CONFIDENCE_THRESHOLD = 0.70

SPECIES_ID_PROMPT = """You are a field naturalist and geologist with global expertise in animals, \
plants, fungi, and terrain.

Analyse this image and identify what is shown. It may be:
- An animal (wildlife, insects, birds, reptiles, fish, arachnids, etc.)
- A plant (tree, flower, grass, cactus, aquatic plant, etc.)
- A fungus or mushroom
- A terrain feature (rock formation, soil type, water body, landscape)

Respond with a single JSON object — no markdown, no explanation, just the JSON:
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
- confidence: 0.0–1.0; be honest
- rank: one of species, genus, family, order, class; use "formation" for terrain
- category: one of "animal", "plant", "fungi", "terrain"
- sub_category:
  - animal → one of: mammal, bird, reptile, amphibian, fish, insect, arachnid, marine, other
  - plant  → one of: tree, flower, grass, cactus, aquatic_plant, shrub, other
  - fungi  → one of: mushroom, bracket_fungus, mould, other
  - terrain → one of: rock, soil, water, landscape
- subject_visible: false if nothing identifiable is in the image
- Do not assume geographic region — identify from visual features only
"""


@dataclass
class SpeciesResult:
    # Gemini identification
    scientific_name: str
    common_name: str
    confidence: float
    rank: str
    provisional: bool           # True when confidence < CONFIDENCE_THRESHOLD
    reasoning: str
    subject_visible: bool
    category: str = "animal"    # animal / plant / fungi / terrain
    sub_category: str = ""      # mammal, bird, tree, rock, etc.

    # Keep old field name as alias for backward compatibility
    @property
    def animal_visible(self) -> bool:
        return self.subject_visible

    # iNaturalist enrichment (populated after taxa lookup)
    taxon_id: int | None = None
    inat_common_name: str = ""
    wikipedia_summary: str = ""
    iconic_taxon: str = ""      # Animalia, Plantae, Fungi, Terrain
    conservation_status: str = ""
    observations_count: int = 0
    inat_validated: bool = False


def _parse_gemini_json(text: str) -> dict:
    """Extract JSON from Gemini response — handles accidental markdown fences."""
    text = text.strip()
    # Strip ```json ... ``` wrappers if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def identify_with_gemini(image_path: str) -> SpeciesResult:
    """
    Submit image to Gemini Vision and return a SpeciesResult.
    Raises EnvironmentError if GEMINI_API_KEY is not set.
    Raises ValueError if Gemini returns no usable identification.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("your_"):
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Get a key at https://aistudio.google.com/apikey "
            "and add it to .env as GEMINI_API_KEY."
        )

    path = Path(image_path)
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    client = genai.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            SPECIES_ID_PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    data = _parse_gemini_json(response.text)

    confidence = float(data.get("confidence", 0.0))
    category = data.get("category", "animal").lower()
    return SpeciesResult(
        scientific_name=data.get("scientific_name", "Unknown"),
        common_name=data.get("common_name", ""),
        confidence=confidence,
        rank=data.get("rank", "species"),
        provisional=confidence < CONFIDENCE_THRESHOLD,
        reasoning=data.get("reasoning", ""),
        subject_visible=data.get("subject_visible", data.get("animal_visible", True)),
        category=category,
        sub_category=data.get("sub_category", ""),
    )


def enrich_with_inat(result: SpeciesResult) -> SpeciesResult:
    """
    Query iNaturalist taxa API with the scientific name from Gemini.
    Populates taxon_id, inat_common_name, wikipedia_summary, iconic_taxon,
    conservation_status, and observations_count on the result in place.
    No auth required.
    """
    if not result.scientific_name or result.scientific_name == "Unknown":
        return result

    response = httpx.get(
        INAT_TAXA_URL,
        params={"q": result.scientific_name, "rank": result.rank, "per_page": 1},
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    if not results:
        # Try without rank constraint (handles cases where rank is approximate)
        response = httpx.get(
            INAT_TAXA_URL,
            params={"q": result.scientific_name, "per_page": 1},
            timeout=15.0,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

    if not results:
        return result

    taxon = results[0]
    cs = taxon.get("conservation_status") or {}

    result.taxon_id = taxon.get("id")
    result.inat_common_name = taxon.get("preferred_common_name", "")
    result.wikipedia_summary = taxon.get("wikipedia_summary", "")
    result.iconic_taxon = taxon.get("iconic_taxon_name", "")
    result.conservation_status = cs.get("status_name", "")
    result.observations_count = taxon.get("observations_count", 0)
    result.inat_validated = True

    return result


_CATEGORY_ICONIC = {
    "animal":  None,     # iNat will set the real iconic_taxon
    "plant":   "Plantae",
    "fungi":   "Fungi",
    "terrain": "Terrain",
}


def identify_species(image_path: str) -> SpeciesResult:
    """Full pipeline: Gemini Vision ID → iNaturalist enrichment (skipped for terrain)."""
    result = identify_with_gemini(image_path)
    if result.category == "terrain":
        # Terrain has no iNaturalist data — set iconic_taxon directly
        result.iconic_taxon = "Terrain"
        return result
    if result.subject_visible and result.confidence > 0.3:
        enrich_with_inat(result)
        # If iNat didn't set iconic_taxon, use category fallback
        if not result.iconic_taxon and result.category in _CATEGORY_ICONIC:
            result.iconic_taxon = _CATEGORY_ICONIC[result.category] or ""
    return result
