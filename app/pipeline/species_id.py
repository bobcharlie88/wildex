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
GOOGLE_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
CONFIDENCE_THRESHOLD = 0.70

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


def _inat_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if INATURALIST_API_KEY:
        headers["Authorization"] = f"Bearer {INATURALIST_API_KEY}"
    return headers


def identify_with_gemini(image_path: str) -> SpeciesResult:
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("your_"):
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Get a key at https://aistudio.google.com/apikey "
            "and add it to .env as GEMINI_API_KEY."
        )

    path = Path(image_path)
    with path.open("rb") as fh:
        image_bytes = fh.read()

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=_file_mime(path)),
            SPECIES_ID_PROMPT,
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    data = _parse_gemini_json(response.text)
    return _build_result(
        scientific_name=data.get("scientific_name", "Unknown"),
        common_name=data.get("common_name", ""),
        confidence=data.get("confidence", 0.0),
        rank=data.get("rank", "species"),
        reasoning=data.get("reasoning", ""),
        subject_visible=data.get("subject_visible", data.get("animal_visible", True)),
        category=_normalize_category(data.get("category", "animal")),
        sub_category=data.get("sub_category", ""),
    )


def identify_with_inat_cv(image_path: str) -> SpeciesResult:
    path = Path(image_path)
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, _file_mime(path))}
        response = httpx.post(
            INAT_CV_URL,
            headers=_inat_headers(),
            files=files,
            timeout=30.0,
        )
    response.raise_for_status()
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
    return result


def identify_with_google_vision(image_path: str) -> SpeciesResult:
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

    # Use the most specific visible term as a taxa search hint, then let iNat
    # enrichment refine it if possible.
    return _build_result(
        scientific_name=preferred,
        common_name=preferred.title(),
        confidence=min(confidence, 0.65),
        rank="species" if len(preferred.split()) > 1 else "class",
        reasoning="Fallback via Google Vision labels.",
        subject_visible=True,
        category=category,
        sub_category=sub_category,
    )


def enrich_with_inat(result: SpeciesResult) -> SpeciesResult:
    query = result.scientific_name or result.common_name
    if not query or query == "Unknown":
        return result

    response = httpx.get(
        INAT_TAXA_URL,
        headers=_inat_headers(),
        params={"q": query, "rank": result.rank, "per_page": 1},
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    if not results:
        response = httpx.get(
            INAT_TAXA_URL,
            headers=_inat_headers(),
            params={"q": query, "per_page": 1},
            timeout=15.0,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

    if not results:
        return result

    taxon = results[0]
    cs = taxon.get("conservation_status") or {}
    result.taxon_id = taxon.get("id")
    result.scientific_name = taxon.get("name", result.scientific_name)
    result.inat_common_name = taxon.get("preferred_common_name", "")
    if result.inat_common_name and not result.common_name:
        result.common_name = result.inat_common_name
    result.wikipedia_summary = taxon.get("wikipedia_summary", "")
    result.iconic_taxon = taxon.get("iconic_taxon_name", "")
    result.conservation_status = cs.get("status_name", "")
    result.observations_count = taxon.get("observations_count", 0)
    result.inat_validated = True
    return result


_CATEGORY_ICONIC = {
    "animal": None,
    "plant": "Plantae",
    "fungi": "Fungi",
    "terrain": "Terrain",
}


def identify_species(image_path: str) -> SpeciesResult:
    provider_errors: list[str] = []

    for provider_name, provider in (
        ("gemini", identify_with_gemini),
        ("inaturalist_cv", identify_with_inat_cv),
        ("google_vision", identify_with_google_vision),
    ):
        try:
            result = provider(image_path)
            log.info("Species identification succeeded via %s", provider_name)
            break
        except EnvironmentError as exc:
            provider_errors.append(f"{provider_name}: {exc}")
            log.warning("Species identification provider skipped: %s", provider_errors[-1])
        except Exception as exc:
            provider_errors.append(f"{provider_name}: {exc}")
            log.warning("Species identification provider failed: %s", provider_errors[-1])
    else:
        raise RuntimeError("All identification providers failed: " + " | ".join(provider_errors))

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

    return result
