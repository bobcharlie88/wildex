"""
Tests for card_generator.py

Modes:
  python tests/test_card_generator.py          -- unit/mock tests only
  python tests/test_card_generator.py --live   -- full Gemini live test
"""

import sys, os, json
from unittest.mock import patch, MagicMock
from dataclasses import asdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pipeline.card_generator import generate_card, WildCard, CardStats, RARITY_DISPLAY
from app.pipeline.species_id import SpeciesResult
from app.pipeline.species_data import SpeciesData, CountryCount

LIVE_TESTS_ENABLED = os.getenv("WILDEX_LIVE_TESTS") == "1"


# ── Fixtures ──────────────────────────────────────────────────────────────

def kelpie_species_result() -> SpeciesResult:
    """Realistic SpeciesResult for Canis familiaris / Australian Kelpie."""
    return SpeciesResult(
        scientific_name    = "Canis familiaris",
        common_name        = "Australian Kelpie",
        confidence         = 0.91,
        rank               = "species",
        provisional        = False,
        reasoning          = "Lean, athletic build with erect ears and characteristic herding posture.",
        animal_visible     = True,
        taxon_id           = 47144,
        inat_common_name   = "Domestic Dog",
        wikipedia_summary  = (
            "The domestic dog is a domesticated descendant of the wolf. "
            "The Australian Kelpie is a breed developed in Australia for mustering sheep."
        ),
        iconic_taxon       = "Mammalia",
        conservation_status = "least concern",
        observations_count = 4_812_006,
        inat_validated     = True,
    )


def kelpie_species_data() -> SpeciesData:
    """Realistic SpeciesData (GBIF) for Canis familiaris in Sydney, AU."""
    return SpeciesData(
        gbif_key              = 5219243,
        scientific_name       = "Canis lupus familiaris Linnaeus, 1758",
        occurrence_count      = 10_234_801,
        rarity_tier           = "common",
        top_countries         = [
            CountryCount("US", 3_100_000),
            CountryCount("AU", 1_200_000),
            CountryCount("GB",   800_000),
        ],
        griis_countries       = [],
        query_lat             = -33.8688,
        query_lon             = 151.2093,
        query_country         = "AU",
        invasive_at_location  = False,
    )


MOCK_GEMINI_RESPONSE = {
    "blurb": (
        "Built for endurance rather than speed, the Australian Kelpie can muster "
        "thousands of sheep across scorching outback terrain without breaking stride. "
        "Its double coat insulates against both heat and cold, while an almost supernatural "
        "work ethic makes it one of the most tireless herding dogs on Earth."
    ),
    "speed":         72,
    "attack":        54,
    "defence":       37,
    "hp":            69,
    "stamina_regen": 91,
}


# ── Unit tests ────────────────────────────────────────────────────────────

def test_rarity_display_mapping():
    assert RARITY_DISPLAY["common"]    == "Common"
    assert RARITY_DISPLAY["uncommon"]  == "Uncommon"
    assert RARITY_DISPLAY["rare"]      == "Rare"
    assert RARITY_DISPLAY["very_rare"] == "Legendary"
    print("  Rarity display labels correct")
    print("  PASS")


def test_card_fields_populated():
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(MOCK_GEMINI_RESPONSE)

    with patch("app.pipeline.card_generator.GEMINI_API_KEY", "fake_key_abc"):
        with patch("google.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = mock_resp
            card = generate_card(kelpie_species_result(), kelpie_species_data())

    assert card.scientific_name == "Canis familiaris"
    assert card.common_name     == "Australian Kelpie" # breed name takes priority when more specific
    assert card.rarity_tier     == "common"
    assert card.rarity_display  == "Common"
    assert card.provisional     is False
    assert card.invasive_at_location is False
    assert card.taxon_id        == 47144
    assert card.gbif_key        == 5219243
    assert len(card.blurb)      > 20

    s = card.stats
    assert 1 <= s.speed         <= 100
    assert 1 <= s.attack        <= 100
    assert 1 <= s.defence       <= 100
    assert 1 <= s.hp            <= 100
    assert 1 <= s.stamina_regen <= 100
    print(f"  Card fields all populated correctly")
    print(f"  Stats: speed={s.speed} atk={s.attack} def={s.defence} hp={s.hp} stam={s.stamina_regen}")
    print("  PASS")


def test_card_without_gbif():
    """Card generates fine when GBIF data is unavailable."""
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(MOCK_GEMINI_RESPONSE)

    with patch("app.pipeline.card_generator.GEMINI_API_KEY", "fake_key_abc"):
        with patch("google.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = mock_resp
            card = generate_card(kelpie_species_result(), gbif=None)

    assert card.gbif_key            is None
    assert card.rarity_tier         == "unknown"
    assert card.invasive_at_location is False
    print("  Card generates correctly without GBIF data (gbif=None)")
    print("  PASS")


def test_breed_name_takes_priority_over_species_name():
    """When Gemini identifies a breed more specific than the iNat species name, use the breed."""
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(MOCK_GEMINI_RESPONSE)
    species = kelpie_species_result()
    species.inat_common_name = "Domestic Dog"      # species-level from iNat
    species.common_name      = "Australian Kelpie" # breed-level from Gemini Vision

    with patch("app.pipeline.card_generator.GEMINI_API_KEY", "fake_key_abc"):
        with patch("google.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = mock_resp
            card = generate_card(species)

    assert card.common_name == "Australian Kelpie"
    print("  Breed name ('Australian Kelpie') correctly used over species name ('Domestic Dog')")
    print("  PASS")


# ── Live test ─────────────────────────────────────────────────────────────

def _print_card(card: WildCard):
    W = 42

    def rule(l="+-", r="-+"):
        return "  " + l + "-" * (W - 2) + r

    def row(text=""):
        return f"  | {text:<{W - 2}} |"

    def stat_row(label, val):
        filled = round(val / 100 * 20)
        bar = "#" * filled + "." * (20 - filled)
        return f"  | {label}  [{bar}] {val:>3}  |"

    print()
    print(rule("+-", "-+"))
    print(row(f"  {card.common_name}"))
    print(row(f"  {card.scientific_name}"))
    prov = "  [PROVISIONAL]" if card.provisional else ""
    print(row(f"  {card.rarity_display}{prov}"))
    print(rule("|=", "=|"))
    print(row())

    # Word-wrap blurb
    words = card.blurb.split()
    line  = ""
    for w in words:
        if len(line) + len(w) + 1 <= W - 4:
            line = (line + " " + w).lstrip()
        else:
            print(row(f"  {line}"))
            line = w
    if line:
        print(row(f"  {line}"))

    print(row())
    print(rule("|=", "=|"))
    s = card.stats
    for label, val in [("SPD", s.speed), ("ATK", s.attack), ("DEF", s.defence),
                        ("HP ", s.hp),   ("STM", s.stamina_regen)]:
        print(stat_row(label, val))
    print(rule("|=", "=|"))
    print(row(f"  Taxon ID      : {card.taxon_id}"))
    print(row(f"  Conservation  : {card.conservation_status or 'not listed'}"))
    print(row(f"  iNat sightings: {card.observations_count:,}"))
    print(row(f"  Invasive here : {'YES' if card.invasive_at_location else 'No'}"))
    print(rule("+-", "-+"))
    print()


@pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="live test; set WILDEX_LIVE_TESTS=1")
def test_live_kelpie():
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("your_"):
        print("  SKIPPED — GEMINI_API_KEY not set")
        return

    print("\n  Generating card for Australian Kelpie (Canis familiaris)...")
    card = generate_card(kelpie_species_result(), kelpie_species_data())
    _print_card(card)

    assert card.blurb, "Blurb must not be empty"
    assert 1 <= card.stats.speed         <= 100
    assert 1 <= card.stats.attack        <= 100
    assert 1 <= card.stats.defence       <= 100
    assert 1 <= card.stats.hp            <= 100
    assert 1 <= card.stats.stamina_regen <= 100

    # Kelpie stamina should be high — it's the defining trait of the breed
    assert card.stats.stamina_regen >= 75, (
        f"Kelpie stamina_regen should reflect legendary endurance, got {card.stats.stamina_regen}"
    )
    print("  PASS")


# ── Runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    live = "--live" in sys.argv

    print("\n[test_rarity_display_mapping]")
    test_rarity_display_mapping()

    print("\n[test_card_fields_populated]")
    test_card_fields_populated()

    print("\n[test_card_without_gbif]")
    test_card_without_gbif()

    print("\n[test_breed_name_takes_priority_over_species_name]")
    test_breed_name_takes_priority_over_species_name()

    if live:
        print("\n[test_live_kelpie]")
        test_live_kelpie()
    else:
        print("\n[test_live_kelpie] -- skipped (run with --live)")

    print("\nAll unit tests passed.")
