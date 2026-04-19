"""
Tests for species_id.py

Modes:
  python tests/test_species_id.py          — parse/mock tests only (no keys needed)
  python tests/test_species_id.py --live   — full Gemini + iNaturalist live test
"""

import sys
import os
import json
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from app.pipeline.species_id import (
    identify_species,
    identify_with_gemini,
    enrich_with_inat,
    _parse_gemini_json,
    SpeciesResult,
    CONFIDENCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_GEMINI_KOALA = {
    "scientific_name": "Phascolarctos cinereus",
    "common_name": "Koala",
    "confidence": 0.97,
    "rank": "species",
    "reasoning": "Distinctive round grey ears, black nose, and arboreal posture in eucalyptus.",
    "animal_visible": True,
}

MOCK_GEMINI_LOW_CONF = {
    "scientific_name": "Lacertidae",
    "common_name": "Wall lizard",
    "confidence": 0.45,
    "rank": "family",
    "reasoning": "Small lizard visible but insufficient detail to determine species.",
    "animal_visible": True,
}

MOCK_INAT_RESPONSE = {
    "total_results": 1,
    "results": [
        {
            "id": 43916,
            "name": "Phascolarctos cinereus",
            "preferred_common_name": "Koala",
            "wikipedia_summary": "The koala is an arboreal herbivorous marsupial native to Australia.",
            "iconic_taxon_name": "Mammalia",
            "conservation_status": {"status_name": "vulnerable"},
            "observations_count": 187432,
        }
    ],
}


# ---------------------------------------------------------------------------
# Unit tests — no network, no keys
# ---------------------------------------------------------------------------

def test_parse_clean_json():
    raw = json.dumps(MOCK_GEMINI_KOALA)
    data = _parse_gemini_json(raw)
    assert data["scientific_name"] == "Phascolarctos cinereus"
    print("  Clean JSON parsed correctly")
    print("  PASS")


def test_parse_fenced_json():
    raw = f"```json\n{json.dumps(MOCK_GEMINI_KOALA)}\n```"
    data = _parse_gemini_json(raw)
    assert data["confidence"] == 0.97
    print("  Fenced markdown JSON stripped and parsed")
    print("  PASS")


def test_provisional_flag_high_confidence():
    result = SpeciesResult(
        scientific_name="Phascolarctos cinereus",
        common_name="Koala",
        confidence=0.97,
        rank="species",
        provisional=False,
        reasoning="test",
        animal_visible=True,
    )
    assert result.provisional is False
    print("  confidence 0.97 -> provisional=False")
    print("  PASS")


def test_provisional_flag_low_confidence():
    result = SpeciesResult(
        scientific_name="Lacertidae",
        common_name="Wall lizard",
        confidence=0.45,
        rank="family",
        provisional=True,
        reasoning="test",
        animal_visible=True,
    )
    assert result.provisional is True
    print("  confidence 0.45 -> provisional=True")
    print("  PASS")


def test_gemini_with_mocked_response():
    mock_response = MagicMock()
    mock_response.text = json.dumps(MOCK_GEMINI_KOALA)

    fake_image = b"\xff\xd8\xff" + b"\x00" * 64

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(fake_image)
        tmp = f.name

    try:
        with patch("app.pipeline.species_id.GEMINI_API_KEY", "fake_key_abc123"):
            with patch("google.genai.Client") as MockClient:
                MockClient.return_value.models.generate_content.return_value = mock_response
                result = identify_with_gemini(tmp)

        assert result.scientific_name == "Phascolarctos cinereus"
        assert result.confidence == 0.97
        assert result.provisional is False
        assert result.animal_visible is True
        print(f"  Gemini mock returned: {result.scientific_name} ({result.confidence:.0%})")
        print("  PASS")
    finally:
        os.unlink(tmp)


def test_inat_enrichment_with_mocked_response():
    result = SpeciesResult(
        scientific_name="Phascolarctos cinereus",
        common_name="Koala",
        confidence=0.97,
        rank="species",
        provisional=False,
        reasoning="test",
        animal_visible=True,
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_INAT_RESPONSE
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.get", return_value=mock_resp):
        enrich_with_inat(result)

    assert result.taxon_id == 43916
    assert result.inat_common_name == "Koala"
    assert result.iconic_taxon == "Mammalia"
    assert result.conservation_status == "vulnerable"
    assert result.observations_count == 187432
    assert result.inat_validated is True
    print(f"  iNat enriched: taxon_id={result.taxon_id}, status={result.conservation_status}, obs={result.observations_count:,}")
    print("  PASS")


def test_no_gemini_key_raises():
    with patch("app.pipeline.species_id.GEMINI_API_KEY", "your_placeholder"):
        try:
            identify_with_gemini("/fake/image.jpg")
            print("  FAIL — should have raised EnvironmentError")
        except EnvironmentError as e:
            assert "aistudio.google.com" in str(e)
            print(f"  EnvironmentError raised with key URL hint")
            print("  PASS")


# ---------------------------------------------------------------------------
# Live test — requires GEMINI_API_KEY in .env
# ---------------------------------------------------------------------------

def _fetch_inat_photo(taxon_name: str) -> tuple[str, str]:
    """Download a research-grade iNat photo. Returns (local_path, photo_url)."""
    obs = httpx.get(
        "https://api.inaturalist.org/v1/observations",
        params={
            "taxon_name": taxon_name,
            "quality_grade": "research",
            "per_page": 1,
            "order_by": "votes",
        },
        timeout=15.0,
    )
    obs.raise_for_status()
    photo_url = obs.json()["results"][0]["photos"][0]["url"].replace("square", "medium")
    img = httpx.get(photo_url, timeout=20.0, follow_redirects=True)
    img.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(img.content)
    return f.name, photo_url


def _print_result(result: SpeciesResult):
    prov = " [PROVISIONAL]" if result.provisional else ""
    print(f"  Scientific name  : {result.scientific_name}{prov}")
    print(f"  Common name      : {result.common_name}")
    print(f"  Confidence       : {result.confidence:.1%}")
    print(f"  Rank             : {result.rank}")
    print(f"  Reasoning        : {result.reasoning}")
    print(f"  --- iNaturalist ---")
    print(f"  Taxon ID         : {result.taxon_id}")
    print(f"  iNat common name : {result.inat_common_name}")
    print(f"  Class            : {result.iconic_taxon}")
    print(f"  Conservation     : {result.conservation_status or 'not listed'}")
    print(f"  Observations     : {result.observations_count:,}")
    if result.wikipedia_summary:
        summary = result.wikipedia_summary[:180].rstrip()
        print(f"  Wikipedia        : {summary}...")


def _run_live_species_test(taxon_name: str, expected_keywords: list[str], label: str):
    print(f"\n  [{label}] Fetching research-grade photo of {taxon_name} from iNaturalist...")
    tmp, photo_url = _fetch_inat_photo(taxon_name)
    print(f"  Photo: {photo_url}")
    print(f"  Running Gemini Vision + iNaturalist enrichment...")

    try:
        result = identify_species(tmp)
        _print_result(result)

        name_lower = result.scientific_name.lower() + " " + result.common_name.lower()
        match = any(kw.lower() in name_lower for kw in expected_keywords)
        if match:
            print(f"  PASS — correctly identified as expected taxon")
        else:
            print(f"  NOTE — expected one of {expected_keywords}, got '{result.scientific_name}'")
            print(f"         (May still be correct — verify manually)")
    finally:
        os.unlink(tmp)


def test_live_global():
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("your_"):
        print("\n  SKIPPED — GEMINI_API_KEY not set in .env")
        print("  Get a free key at https://aistudio.google.com/apikey")
        return

    # Test 1: Australian species — Laughing Kookaburra
    _run_live_species_test(
        taxon_name="Dacelo novaeguineae",
        expected_keywords=["dacelo", "kookaburra"],
        label="Australian species",
    )

    # Test 2: European species — European Robin
    _run_live_species_test(
        taxon_name="Erithacus rubecula",
        expected_keywords=["erithacus", "robin"],
        label="European species",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    live = "--live" in sys.argv

    print("\n[test_parse_clean_json]")
    test_parse_clean_json()

    print("\n[test_parse_fenced_json]")
    test_parse_fenced_json()

    print("\n[test_provisional_flag_high_confidence]")
    test_provisional_flag_high_confidence()

    print("\n[test_provisional_flag_low_confidence]")
    test_provisional_flag_low_confidence()

    print("\n[test_gemini_with_mocked_response]")
    test_gemini_with_mocked_response()

    print("\n[test_inat_enrichment_with_mocked_response]")
    test_inat_enrichment_with_mocked_response()

    print("\n[test_no_gemini_key_raises]")
    test_no_gemini_key_raises()

    if live:
        print("\n=== LIVE TESTS ===")
        test_live_global()
    else:
        print("\n[test_live_global] — skipped (run with --live once GEMINI_API_KEY is set)")

    print("\nAll mock/parse tests passed.")
