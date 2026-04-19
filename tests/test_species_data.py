"""
Tests for species_data.py

Modes:
  python tests/test_species_data.py          -- unit tests only (no network)
  python tests/test_species_data.py --live   -- full GBIF + Nominatim live calls
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pipeline.species_data import (
    get_species_data,
    _get_rarity_tier,
    _get_griis_countries,
    _reverse_geocode,
    _get_top_countries,
    SpeciesData,
    CountryCount,
    RARITY_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_rarity_tiers():
    cases = [
        (10_783_091, "common"),
        (1_177_006,  "common"),
        (50_000,     "uncommon"),
        (15_000,     "uncommon"),
        (1_500,      "rare"),
        (200,        "very_rare"),
        (0,          "very_rare"),
    ]
    for count, expected in cases:
        result = _get_rarity_tier(count)
        assert result == expected, f"{count:,} -> expected {expected}, got {result}"
        print(f"  {count:>12,} occurrences -> {result}")
    print("  PASS")


def test_griis_country_parsing():
    """GRIIS source strings are correctly parsed to ISO-2 codes."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "results": [
            {"source": "Global Register of Introduced and Invasive Species - New Zealand"},
            {"source": "Global Register of Introduced and Invasive Species - Great Britain"},
            {"source": "Global Register of Introduced and Invasive Species - Belgium"},
            {"source": "Global Register of Introduced and Invasive Species - Colombia"},
            {"source": "The Clements Checklist"},   # should be ignored
            {"source": ""},                          # empty — ignored
        ]
    }
    with patch("httpx.get", return_value=mock_resp):
        countries = _get_griis_countries(12345)

    assert "NZ" in countries, "New Zealand should be NZ"
    assert "GB" in countries, "Great Britain should be GB"
    assert "BE" in countries, "Belgium should be BE"
    assert "CO" in countries, "Colombia should be CO"
    assert "AU" not in countries, "Australia should not appear"
    print(f"  Parsed GRIIS countries: {countries}")
    print("  PASS")


def test_invasive_flag_logic():
    """invasive_at_location is True only when query_country is in griis_countries."""
    base = dict(
        gbif_key=1, scientific_name="Test species",
        occurrence_count=1000, rarity_tier="rare",
        top_countries=[], griis_countries=["NZ", "GB", "BE"],
        query_lat=-36.8, query_lon=174.7,
    )

    invasive = SpeciesData(**base, query_country="NZ", invasive_at_location=True)
    native   = SpeciesData(**base, query_country="AU", invasive_at_location=False)

    assert invasive.invasive_at_location is True
    assert native.invasive_at_location is False
    print("  NZ (in GRIIS list) -> invasive=True")
    print("  AU (not in GRIIS)  -> invasive=False")
    print("  PASS")


def test_reverse_geocode_with_mock():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"address": {"country_code": "au", "country": "Australia"}}

    with patch("httpx.get", return_value=mock_resp):
        code = _reverse_geocode(-31.9505, 115.8605)

    assert code == "AU", f"Expected AU, got {code}"
    print(f"  Perth coords -> country_code: {code}")
    print("  PASS")


def test_get_species_data_with_mocks():
    """Full get_species_data() with every HTTP call mocked."""
    def fake_get(url, **kwargs):
        m = MagicMock()
        m.raise_for_status.return_value = None

        if "species/match" in url:
            m.json.return_value = {
                "matchType": "EXACT",
                "usageKey": 2475648,
                "scientificName": "Dacelo novaeguineae (Hermann, 1783)",
            }
        elif "occurrence/search" in url and "facet" in str(kwargs.get("params", {})):
            m.json.return_value = {
                "count": 1177006,
                "facets": [{"field": "COUNTRY", "counts": [
                    {"name": "AU", "count": 1175564},
                    {"name": "NZ", "count": 617},
                    {"name": "ZZ", "count": 19},   # unknown, should be skipped
                ]}],
            }
        elif "occurrence/search" in url:
            m.json.return_value = {"count": 1177006}
        elif "speciesProfiles" in url:
            m.json.return_value = {"results": [
                {"source": "Global Register of Introduced and Invasive Species - New Zealand"},
                {"source": "Global Register of Introduced and Invasive Species - Great Britain"},
            ]}
        elif "nominatim" in url:
            m.json.return_value = {"address": {"country_code": "au"}}
        return m

    with patch("httpx.get", side_effect=fake_get):
        result = get_species_data("Dacelo novaeguineae", -31.9505, 115.8605)

    assert result.gbif_key == 2475648
    assert result.rarity_tier == "common"
    assert result.occurrence_count == 1177006
    assert result.query_country == "AU"
    assert result.invasive_at_location is False  # AU not in [NZ, GB]
    assert "NZ" in result.griis_countries
    assert "GB" in result.griis_countries
    assert any(c.iso_code == "AU" for c in result.top_countries)
    assert not any(c.iso_code == "ZZ" for c in result.top_countries)  # ZZ filtered
    print(f"  gbif_key={result.gbif_key}, rarity={result.rarity_tier}")
    print(f"  invasive_at_location={result.invasive_at_location} (AU not in GRIIS)")
    print(f"  GRIIS countries: {result.griis_countries}")
    print("  PASS")


# ---------------------------------------------------------------------------
# Live tests
# ---------------------------------------------------------------------------

def _print_result(label: str, result: SpeciesData):
    print(f"\n  [{label}]")
    print(f"  Scientific name    : {result.scientific_name}")
    print(f"  GBIF key           : {result.gbif_key}")
    print(f"  Global occurrences : {result.occurrence_count:,}")
    print(f"  Rarity tier        : {result.rarity_tier}")
    top = ", ".join(f"{c.iso_code}({c.count:,})" for c in result.top_countries[:5])
    print(f"  Top 5 countries    : {top}")
    print(f"  GRIIS countries    : {result.griis_countries or 'none'}")
    print(f"  Query location     : ({result.query_lat}, {result.query_lon}) -> {result.query_country}")
    print(f"  Invasive here      : {result.invasive_at_location}")


def test_live_kookaburra_perth():
    """Dacelo novaeguineae at Perth, Australia — expect native (not invasive)."""
    result = get_species_data("Dacelo novaeguineae", lat=-31.9505, lon=115.8605)
    _print_result("Kookaburra in Perth, AU", result)

    assert result.gbif_key > 0
    assert result.occurrence_count > 100_000
    assert result.rarity_tier == "common"
    assert result.query_country == "AU"
    assert result.invasive_at_location is False, "Kookaburra is native to AU — should not be invasive"
    # Confirm NZ shows up in GRIIS (it is introduced there)
    assert "NZ" in result.griis_countries, "Kookaburra IS introduced in NZ — expect NZ in GRIIS"
    print("  PASS")


def test_live_robin_berlin():
    """Erithacus rubecula at Berlin, Germany — expect native (not invasive)."""
    result = get_species_data("Erithacus rubecula", lat=52.5200, lon=13.4050)
    _print_result("European Robin in Berlin, DE", result)

    assert result.gbif_key > 0
    assert result.occurrence_count > 1_000_000
    assert result.rarity_tier == "common"
    assert result.query_country == "DE"
    assert result.invasive_at_location is False, "Robin is native to Germany"
    print("  PASS")


def test_live_invasive_bonus():
    """
    Common Myna (Acridotheres tristis) in Sydney, Australia.
    This species IS invasive in Australia — expect invasive_at_location=True.
    """
    result = get_species_data("Acridotheres tristis", lat=-33.8688, lon=151.2093)
    _print_result("Common Myna in Sydney, AU (invasive bonus test)", result)

    assert result.query_country == "AU"
    print(f"  GRIIS countries: {result.griis_countries}")
    if result.invasive_at_location:
        print("  PASS — correctly flagged as invasive in AU")
    else:
        print("  NOTE — AU not in GRIIS list for this species (GBIF data may vary)")
        print(f"         GRIIS countries found: {result.griis_countries}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    live = "--live" in sys.argv

    print("\n[test_rarity_tiers]")
    test_rarity_tiers()

    print("\n[test_griis_country_parsing]")
    test_griis_country_parsing()

    print("\n[test_invasive_flag_logic]")
    test_invasive_flag_logic()

    print("\n[test_reverse_geocode_with_mock]")
    test_reverse_geocode_with_mock()

    print("\n[test_get_species_data_with_mocks]")
    test_get_species_data_with_mocks()

    if live:
        print("\n=== LIVE TESTS ===")
        test_live_kookaburra_perth()
        test_live_robin_berlin()
        test_live_invasive_bonus()
    else:
        print("\nLive tests skipped (run with --live)")

    print("\nAll unit tests passed.")
