"""
Card generator — takes enriched species data and produces a WildCard.

One Gemini call generates both the Pokédex-style blurb and the five
biology-based stats. Stats are calibrated against real animal anchors so
a cheetah lands near 97 Speed and a koala lands near 15 Stamina Regen,
not because the model guessed, but because the prompt forces it to reason
from biology.

species_data (GBIF) is optional — the card generates fine without it, it
just won't have a rarity tier or invasive flag.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.pipeline.species_id import SpeciesResult
from app.pipeline.species_data import SpeciesData

CARD_GEMINI_MODEL = GEMINI_MODEL
log = logging.getLogger("wildex.card_generator")

STAT_PROMPT_ANIMAL = """\
You are the game designer of WildEx, a real-world wildlife discovery game.
Create a card for the creature below using real biology — not guesswork.

── SPECIES DATA ──────────────────────────────────────────────────────────
Common name    : {common_name}
Scientific name: {scientific_name}
Taxonomy       : {rank} · {iconic_taxon}
Conservation   : {conservation_status}
iNat sightings : {observations_count}
GBIF rarity    : {rarity_tier}
{invasive_line}
── TASKS ─────────────────────────────────────────────────────────────────

1. BLURB — 2-3 sentences, exciting wildlife encyclopaedia style. Present tense.
   Name the creature in the first sentence. Highlight 1-2 distinctive biological
   traits. Do NOT start with "The {common_name} is".

2. STATS — Five integers 1–100. Reason from real biology. Avoid round numbers.

   SPEED — locomotion capability
     97 Cheetah · 88 Peregrine Falcon · 55 Human sprinter · 22 Elephant · 3 Slug

   ATTACK — offensive threat (teeth, claws, venom, size)
     96 Saltwater Crocodile · 85 Grizzly Bear · 68 Honey Badger · 8 Earthworm

   DEFENCE — passive defences (armour, quills, toxins, camouflage)
     95 Armadillo · 82 Porcupine · 55 Wild Boar · 12 Butterfly

   HP — vitality; correlates with body mass, lifespan, wound recovery
     97 Elephant · 70 Wolf · 50 Domestic Cat · 14 Mouse · 8 Butterfly

   STAMINA_REGEN — endurance and recovery; high for migratory / working animals
     97 Arctic Tern · 90 Sled Dog · 75 Wolf · 18 Koala · 10 Bulldog

── OUTPUT FORMAT ─────────────────────────────────────────────────────────
Respond with ONLY this JSON — no markdown, no commentary:
{{
  "blurb": "...",
  "speed": 0,
  "attack": 0,
  "defence": 0,
  "hp": 0,
  "stamina_regen": 0
}}
"""

STAT_PROMPT_PLANT = """\
You are the game designer of WildEx. Create a card for the plant below using
real botany — not guesswork.

── PLANT DATA ────────────────────────────────────────────────────────────
Common name    : {common_name}
Scientific name: {scientific_name}
Category       : {iconic_taxon}
Conservation   : {conservation_status}
iNat sightings : {observations_count}
GBIF rarity    : {rarity_tier}
{invasive_line}
── TASKS ─────────────────────────────────────────────────────────────────

1. BLURB — 2-3 sentences about this plant in exciting field-guide style.
   Name it in the first sentence. Highlight distinctive features.

2. STATS — Five integers 1–100. For plants the stats are reinterpreted:
   SPEED       = Growth rate (97 Bamboo · 70 Kudzu · 30 Oak · 5 Bristlecone Pine)
   ATTACK      = Toxicity/Hazard (95 Manchineel · 70 Stinging Nettle · 10 Dandelion)
   DEFENCE     = Drought/stress resilience (95 Cactus · 75 Olive · 15 Lettuce)
   HP          = Lifespan potential (99 Sequoia · 80 Oak · 40 Sunflower · 5 Annual grass)
   STAMINA_REGEN = Seed dispersal reach (95 Dandelion · 80 Coconut · 10 Truffles)

── OUTPUT FORMAT ─────────────────────────────────────────────────────────
Respond with ONLY this JSON — no markdown, no commentary:
{{
  "blurb": "...",
  "speed": 0,
  "attack": 0,
  "defence": 0,
  "hp": 0,
  "stamina_regen": 0
}}
"""

STAT_PROMPT_TERRAIN = """\
You are the game designer of WildEx. Create a card for the terrain feature below.

── TERRAIN DATA ──────────────────────────────────────────────────────────
Name           : {common_name}
Type           : {sub_category}
Rarity         : {rarity_tier}

── TASKS ─────────────────────────────────────────────────────────────────

1. BLURB — 2-3 sentences describing this terrain in dramatic naturalist style.
   Name it in the first sentence. Highlight its geological or ecological significance.

2. STATS — Five integers 1–100. For terrain the stats represent:
   SPEED         = Rate of change / erosion speed (95 Lava flow · 60 River · 2 Granite)
   ATTACK        = Hazard level (95 Active volcano · 70 Quicksand · 5 Meadow)
   DEFENCE       = Hardness / durability (98 Granite · 80 Sandstone · 20 Clay)
   HP            = Age / geological timescale (99 Precambrian shield · 50 Limestone · 5 Sand dune)
   STAMINA_REGEN = Ecosystem recovery speed (90 Wetland · 60 Forest · 10 Desert)

── OUTPUT FORMAT ─────────────────────────────────────────────────────────
Respond with ONLY this JSON — no markdown, no commentary:
{{
  "blurb": "...",
  "speed": 0,
  "attack": 0,
  "defence": 0,
  "hp": 0,
  "stamina_regen": 0
}}
"""

RARITY_DISPLAY = {
    "common":    "Common",
    "uncommon":  "Uncommon",
    "rare":      "Rare",
    "very_rare": "Legendary",
}


@dataclass
class CardStats:
    speed:        int
    attack:       int
    defence:      int
    hp:           int
    stamina_regen: int


@dataclass
class WildCard:
    # ── Identity ──────────────────────────────────────────────────
    scientific_name:    str
    common_name:        str           # display name (iNat preferred if available)
    rank:               str
    confidence:         float
    provisional:        bool

    # ── iNaturalist ───────────────────────────────────────────────
    taxon_id:           int | None
    iconic_taxon:       str
    conservation_status: str
    observations_count: int
    wikipedia_summary:  str

    # ── GBIF ──────────────────────────────────────────────────────
    gbif_key:           int | None
    rarity_tier:        str           # common / uncommon / rare / very_rare
    rarity_display:     str           # Common / Uncommon / Rare / Legendary
    invasive_at_location: bool

    # ── Generated ─────────────────────────────────────────────────
    blurb:  str
    stats:  CardStats


def _build_prompt(species: SpeciesResult, gbif: SpeciesData | None) -> str:
    if species.category == "terrain":
        return STAT_PROMPT_TERRAIN.format(
            common_name  = species.common_name,
            sub_category = species.sub_category or "terrain",
            rarity_tier  = "unknown",
        )
    if species.category == "plant":
        rarity_tier   = gbif.rarity_tier if gbif else "unknown"
        invasive_line = (
            "INVASIVE in capture region — mention in blurb if space allows."
            if gbif and gbif.invasive_at_location else ""
        )
        obs_str = f"{species.observations_count:,}" if species.observations_count else "unknown"
        return STAT_PROMPT_PLANT.format(
            common_name         = species.inat_common_name or species.common_name,
            scientific_name     = species.scientific_name,
            iconic_taxon        = species.iconic_taxon or "Plantae",
            conservation_status = species.conservation_status or "not listed",
            observations_count  = obs_str,
            rarity_tier         = rarity_tier,
            invasive_line       = invasive_line,
        )
    return _build_animal_prompt(species, gbif)


def _build_animal_prompt(species: SpeciesResult, gbif: SpeciesData | None) -> str:
    # Use iNat name as the authoritative species name; keep Gemini's name
    # as a breed/variety hint when the two differ (e.g. "Domestic Dog" vs
    # "Australian Kelpie" — we want Kelpie-specific stats, not generic dog stats).
    inat_name   = species.inat_common_name
    gemini_name = species.common_name
    if inat_name and gemini_name and inat_name.lower() != gemini_name.lower():
        display_name  = gemini_name
        variety_line  = f"Breed/variety  : {gemini_name} (species: {inat_name})"
    else:
        display_name  = inat_name or gemini_name
        variety_line  = ""

    rarity_tier   = gbif.rarity_tier if gbif else "unknown"
    invasive_line = (
        "INVASIVE in capture region — mention this in the blurb if space allows."
        if gbif and gbif.invasive_at_location else ""
    )
    obs_str = f"{species.observations_count:,}" if species.observations_count else "unknown"

    return STAT_PROMPT_ANIMAL.format(
        common_name          = display_name,
        scientific_name      = species.scientific_name,
        rank                 = species.rank,
        iconic_taxon         = species.iconic_taxon or "unknown",
        conservation_status  = species.conservation_status or "not listed",
        observations_count   = obs_str,
        rarity_tier          = rarity_tier,
        invasive_line        = variety_line + ("\n" if variety_line and invasive_line else "") + invasive_line,
    )


def _call_gemini(prompt: str) -> dict:
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("your_"):
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Get a key at https://aistudio.google.com/apikey"
        )
    client   = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model    = CARD_GEMINI_MODEL,
        contents = [prompt],
        config   = types.GenerateContentConfig(
            response_mime_type = "application/json",
        ),
    )
    text = response.text.strip()
    # Strip accidental markdown fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _deterministic_stats(species: SpeciesResult, gbif: SpeciesData | None) -> dict:
    category = (species.category or "animal").lower()
    iconic = (species.iconic_taxon or "").lower()
    observations = int(species.observations_count or 0)
    confidence = float(species.confidence or 0.5)
    obs_band = min(24, int(observations and len(str(max(observations, 1))) * 4))
    rarity_bonus = {
        "common": 0,
        "uncommon": 4,
        "rare": 9,
        "very_rare": 15,
        "legendary": 18,
        "mythic": 20,
        "cryptic": 14,
        "extinct": 22,
    }.get((gbif.rarity_tier if gbif else "unknown") or "unknown", 6)

    if category == "plant":
        return {
            "speed": min(92, 18 + obs_band + rarity_bonus),
            "attack": min(88, 10 + rarity_bonus + (8 if gbif and gbif.invasive_at_location else 0)),
            "defence": min(94, 40 + rarity_bonus + int(confidence * 20)),
            "hp": min(96, 34 + obs_band + rarity_bonus),
            "stamina_regen": min(90, 26 + obs_band + int(confidence * 24)),
        }
    if category == "terrain":
        return {
            "speed": min(82, 8 + rarity_bonus + int(confidence * 18)),
            "attack": min(86, 14 + rarity_bonus + (8 if "volcano" in species.common_name.lower() else 0)),
            "defence": min(98, 52 + rarity_bonus),
            "hp": min(99, 60 + rarity_bonus),
            "stamina_regen": min(88, 18 + obs_band + int(confidence * 18)),
        }
    mobility = {
        "aves": 82,
        "actinopterygii": 68,
        "reptilia": 44,
        "mammalia": 58,
        "insecta": 60,
        "arachnida": 48,
        "amphibia": 38,
    }.get(iconic, 50)
    threat = 18 + rarity_bonus + (10 if gbif and gbif.invasive_at_location else 0)
    return {
        "speed": min(96, mobility + int(confidence * 10)),
        "attack": min(94, threat + obs_band + (8 if "shark" in species.common_name.lower() else 0)),
        "defence": min(90, 24 + rarity_bonus + int(confidence * 22)),
        "hp": min(96, 26 + obs_band + rarity_bonus + int(confidence * 18)),
        "stamina_regen": min(95, 24 + obs_band + int(confidence * 26)),
    }


def _fallback_generated_data(species: SpeciesResult, gbif: SpeciesData | None) -> dict:
    display_name = species.inat_common_name or species.common_name or species.scientific_name
    rarity_label = RARITY_DISPLAY.get((gbif.rarity_tier if gbif else "unknown") or "unknown", "Unknown")
    locality = f" in {gbif.query_country}" if gbif and gbif.query_country else ""
    invasive_line = " It is flagged as invasive at this capture location." if gbif and gbif.invasive_at_location else ""
    observation_line = (
        f" Field data currently links it to {int(species.observations_count):,} recorded observations."
        if species.observations_count else
        " Field data is still being expanded for this species."
    )
    stats = _deterministic_stats(species, gbif)
    return {
        "blurb": (
            f"{display_name} is logged by WildEx as a {rarity_label.lower()} field encounter{locality}. "
            f"Its entry is built from observed taxonomy and known ecology rather than a live generated lore pass."
            f"{invasive_line}{observation_line}"
        ),
        **stats,
    }


def generate_card(
    species: SpeciesResult,
    gbif: SpeciesData | None = None,
) -> WildCard:
    """
    Generate a complete WildCard for a species.

    Args:
        species: Output of identify_species() — Gemini ID + iNat enrichment.
        gbif:    Output of get_species_data() — GBIF rarity + invasive flag.
                 Optional; card still generates if GBIF lookup failed.

    Returns:
        WildCard with blurb, stats, and all aggregated species data.
    """
    prompt = _build_prompt(species, gbif)
    try:
        data = _call_gemini(prompt)
    except Exception as exc:
        log.warning("Card generation fell back to deterministic mode for %s: %s", species.scientific_name, exc)
        data = _fallback_generated_data(species, gbif)

    # Prefer the breed/variety name (from Gemini Vision) when it is more
    # specific than the iNat species-level name (e.g. "Australian Kelpie"
    # beats "Domestic Dog" as a card title).
    inat_name    = species.inat_common_name
    gemini_name  = species.common_name
    if inat_name and gemini_name and inat_name.lower() != gemini_name.lower():
        display_name = gemini_name
    else:
        display_name = inat_name or gemini_name
    rarity_tier  = gbif.rarity_tier if gbif else "unknown"

    return WildCard(
        scientific_name      = species.scientific_name,
        common_name          = display_name,
        rank                 = species.rank,
        confidence           = species.confidence,
        provisional          = species.provisional,
        taxon_id             = species.taxon_id,
        iconic_taxon         = species.iconic_taxon,
        conservation_status  = species.conservation_status,
        observations_count   = species.observations_count,
        wikipedia_summary    = species.wikipedia_summary,
        gbif_key             = gbif.gbif_key if gbif else None,
        rarity_tier          = rarity_tier,
        rarity_display       = RARITY_DISPLAY.get(rarity_tier, rarity_tier.title()),
        invasive_at_location = gbif.invasive_at_location if gbif else False,
        blurb                = data.get("blurb", ""),
        stats                = CardStats(
            speed         = int(data.get("speed", 50)),
            attack        = int(data.get("attack", 50)),
            defence       = int(data.get("defence", 50)),
            hp            = int(data.get("hp", 50)),
            stamina_regen = int(data.get("stamina_regen", 50)),
        ),
    )
