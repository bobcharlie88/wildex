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
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY
from app.pipeline.species_id import SpeciesResult
from app.pipeline.species_data import SpeciesData

GEMINI_MODEL = "gemini-2.5-flash"

STAT_PROMPT = """\
You are the game designer of WildEx, a real-world wildlife discovery game.
Your job is to create a card for the species below using real biology — not
guesswork. Read the species data carefully before writing anything.

── SPECIES DATA ──────────────────────────────────────────────────────────
Common name    : {common_name}
Scientific name: {scientific_name}
Taxonomy       : {rank} · {iconic_taxon}
Conservation   : {conservation_status}
iNat sightings : {observations_count}
GBIF rarity    : {rarity_tier}
{invasive_line}
── TASKS ─────────────────────────────────────────────────────────────────

1. BLURB — Write 2-3 sentences in the style of an exciting wildlife
   encyclopaedia for a game. Present tense. Name the animal in the first
   sentence. Highlight 1-2 genuinely distinctive biological traits.
   Do NOT start with "The {common_name} is". Be creative.

2. STATS — Five integers, each 1–100, calibrated against the anchors below.
   Reason from actual biology. Do not use round numbers unless they truly fit.

   SPEED — locomotion capability
     97 Cheetah · 88 Peregrine Falcon (dive) · 80 Greyhound · 72 Thoroughbred
     55 Human sprinter · 38 Domestic Cat · 22 Elephant · 15 Tortoise · 3 Slug

   ATTACK — offensive threat from natural weapons (teeth, claws, venom, size)
     96 Saltwater Crocodile · 85 Grizzly Bear · 75 Golden Eagle · 68 Honey Badger
     58 Domestic Dog (large) · 45 Domestic Cat · 30 Rabbit · 8 Earthworm

   DEFENCE — passive defences (armour, quills, toxins, thick hide, camouflage)
     95 Armadillo · 90 Tortoise · 82 Porcupine · 72 Pangolin · 55 Wild Boar
     40 Wolf · 32 Domestic Dog · 22 Rabbit · 12 Butterfly

   HP — vitality and toughness; correlates with body mass, lifespan, wound recovery
     97 Elephant · 88 Grizzly Bear · 78 Hippo · 70 Wolf · 62 Domestic Dog (large)
     50 Domestic Cat · 40 Rabbit · 25 Pigeon · 14 Mouse · 8 Butterfly

   STAMINA_REGEN — endurance and recovery; high for migratory / working animals
     97 Arctic Tern · 90 Sled Dog (Iditarod) · 82 Migratory Swallow · 75 Wolf
     68 Human (marathon) · 58 Domestic Dog (average) · 45 Lion · 28 Giant Panda
     18 Koala · 10 Bulldog

── OUTPUT FORMAT ─────────────────────────────────────────────────────────
Respond with ONLY this JSON object — no markdown, no commentary:
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
    # Use iNat name as the authoritative species name; keep Gemini's name
    # as a breed/variety hint when the two differ (e.g. "Domestic Dog" vs
    # "Australian Kelpie" — we want Kelpie-specific stats, not generic dog stats).
    inat_name   = species.inat_common_name
    gemini_name = species.common_name
    if inat_name and gemini_name and inat_name.lower() != gemini_name.lower():
        display_name  = gemini_name          # breed is more specific for stats
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

    return STAT_PROMPT.format(
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
        model    = GEMINI_MODEL,
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
    data   = _call_gemini(prompt)

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
