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

SPECIES_ID_PROMPT = """You are an expert wildlife biologist with global species knowledge.
Analyse this image and identify the animal, insect, bird, reptile, or other wildlife shown.

Respond with a single JSON object — no markdown, no explanation, just the JSON:
{
  "scientific_name": "Genus species",
  "common_name": "Most widely used English common name",
  "confidence": 0.95,
  "rank": "species",
  "reasoning": "One sentence: key visual features that led to this identification",
  "animal_visible": true
}

Rules:
- scientific_name must be the accepted binomial (or genus if species-level is uncertain)
- confidence is 0.0–1.0; be honest — use <0.5 if genuinely unsure
- rank is one of: species, genus, family, order, class
- If no animal is clearly visible, set animal_visible to false and confidence to 0.0
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
    animal_visible: bool

    # iNaturalist enrichment (populated after taxa lookup)
    taxon_id: int | None = None
    inat_common_name: str = ""
    wikipedia_summary: str = ""
    iconic_taxon: str = ""      # Animalia, Plantae, Fungi, etc.
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
    return SpeciesResult(
        scientific_name=data.get("scientific_name", "Unknown"),
        common_name=data.get("common_name", ""),
        confidence=confidence,
        rank=data.get("rank", "species"),
        provisional=confidence < CONFIDENCE_THRESHOLD,
        reasoning=data.get("reasoning", ""),
        animal_visible=data.get("animal_visible", True),
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


def identify_species(image_path: str) -> SpeciesResult:
    """Full pipeline: Gemini Vision ID → iNaturalist enrichment."""
    result = identify_with_gemini(image_path)
    if result.animal_visible and result.confidence > 0.3:
        enrich_with_inat(result)
    return result
