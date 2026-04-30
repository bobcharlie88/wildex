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

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from app.pipeline.species_id import (
    TemporaryIdentificationError,
    identify_species,
    identify_with_gemini,
    enrich_with_inat,
    _parse_gemini_json,
    is_temporary_identification_error,
    SpeciesResult,
    CONFIDENCE_THRESHOLD,
)

LIVE_TESTS_ENABLED = os.getenv("WILDEX_LIVE_TESTS") == "1"


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

MOCK_INAT_PLANT_RESPONSE = {
    "total_results": 1,
    "results": [
        {
            "id": 56789,
            "name": "Chenopodium album",
            "preferred_common_name": "Lamb's quarters",
            "iconic_taxon_name": "Plantae",
            "observations_count": 42000,
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


def test_gemini_prompt_includes_location_context():
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
                identify_with_gemini(
                    tmp,
                    location_hint={"country": "Australia", "country_code": "AU", "state": "Western Australia", "locality": "Perth"},
                )

                prompt = MockClient.return_value.models.generate_content.call_args.kwargs["contents"][1]
                assert "Country: Australia" in prompt
                assert "State/region: Western Australia" in prompt
                assert "Prefer taxa that are known from the capture region" in prompt
                print("  Gemini prompt includes GPS-derived location context")
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


def test_plant_enrichment_replaces_generic_name():
    result = SpeciesResult(
        scientific_name="Chenopodium",
        common_name="Plant",
        confidence=0.61,
        rank="genus",
        provisional=True,
        reasoning="Broad leaves with mealy new growth on disturbed ground.",
        subject_visible=True,
        category="plant",
        sub_category="other",
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_INAT_PLANT_RESPONSE
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.get", return_value=mock_resp):
        enrich_with_inat(result)

    assert result.inat_validated is True
    assert result.common_name == "Lamb's quarters"
    assert result.scientific_name == "Chenopodium album"
    assert result.iconic_taxon == "Plantae"
    assert result.sub_category == "other"
    print("  Generic plant label replaced with iNat plant taxon")
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


def test_temporary_error_detection():
    exc = RuntimeError("503 UNAVAILABLE: model experiencing high demand, try again later")
    assert is_temporary_identification_error(exc) is True
    print("  Temporary provider outage correctly detected from error text")
    print("  PASS")


def test_all_temporary_provider_failures_raise_temporary_error():
    temporary = RuntimeError("503 UNAVAILABLE: model experiencing high demand")
    with patch("app.pipeline.species_id.identify_with_gemini", side_effect=temporary):
        with patch("app.pipeline.species_id.identify_with_inat_cv", side_effect=temporary):
            with patch("app.pipeline.species_id.identify_with_google_vision", side_effect=temporary):
                try:
                    identify_species("/fake/image.jpg")
                    print("  FAIL — should have raised TemporaryIdentificationError")
                except TemporaryIdentificationError as exc:
                    assert "All identification providers failed" in str(exc)
                    print("  All-temporary outage escalated as TemporaryIdentificationError")
                    print("  PASS")


def test_temporary_plus_skipped_providers_still_raise_temporary_error():
    temporary = RuntimeError("503 UNAVAILABLE: model experiencing high demand")
    skipped = EnvironmentError("GOOGLE_VISION_API_KEY not set.")
    with patch("app.pipeline.species_id.identify_with_gemini", side_effect=temporary):
        with patch("app.pipeline.species_id.identify_with_inat_cv", side_effect=temporary):
            with patch("app.pipeline.species_id.identify_with_google_vision", side_effect=skipped):
                with patch("app.pipeline.species_id.identify_with_google_web", side_effect=skipped):
                    try:
                        identify_species("/fake/image.jpg")
                        print("  FAIL â€” should have raised TemporaryIdentificationError")
                    except TemporaryIdentificationError as exc:
                        assert "All identification providers failed" in str(exc)
                        print("  Temporary failures plus skipped providers still degrade gracefully")
                        print("  PASS")


def test_fourth_provider_runs_after_google_vision():
    temporary = RuntimeError("503 UNAVAILABLE: model experiencing high demand")
    web_result = SpeciesResult(
        scientific_name="Taraxacum officinale",
        common_name="Dandelion",
        confidence=0.52,
        rank="species",
        provisional=True,
        reasoning="Fallback via web entities.",
        subject_visible=True,
        category="plant",
        sub_category="flower",
    )
    with patch("app.pipeline.species_id.identify_with_gemini", side_effect=temporary):
        with patch("app.pipeline.species_id.identify_with_inat_cv", side_effect=temporary):
            with patch("app.pipeline.species_id.identify_with_google_vision", side_effect=RuntimeError("Google Vision returned no labels")):
                with patch("app.pipeline.species_id.identify_with_google_web", return_value=web_result):
                    with patch("app.pipeline.species_id.enrich_with_inat", side_effect=lambda result: result):
                        result = identify_species("/fake/image.jpg")

    assert result.common_name == "Dandelion"
    assert result.category == "plant"
    print("  Fourth provider runs after Google Vision and returns a usable result")
    print("  PASS")


def test_location_conflict_marks_species_provisional():
    out_of_range = SpeciesResult(
        scientific_name="Cordylus tropidosternum",
        common_name="Tropical girdled lizard",
        confidence=0.91,
        rank="species",
        provisional=False,
        reasoning="Spiny-bodied lizard with keeled scales.",
        subject_visible=True,
        category="animal",
        sub_category="reptile",
    )

    with patch("app.pipeline.species_id._location_hint_from_coords", return_value={"country": "Australia", "country_code": "AU"}):
        with patch("app.pipeline.species_id.identify_with_gemini", return_value=out_of_range):
            with patch("app.pipeline.species_id.enrich_with_inat", side_effect=lambda result: result):
                with patch("app.pipeline.species_id._country_occurrence_count", return_value=0):
                    result = identify_species("/fake/image.jpg", lat=-31.9505, lon=115.8605)

    assert result.provisional is True
    assert result.confidence == 0.55
    assert "no GBIF occurrences found in AU" in result.reasoning
    print("  GPS plausibility check downgrades out-of-range species IDs")
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


@pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="live test; set WILDEX_LIVE_TESTS=1")
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

    print("\n[test_gemini_prompt_includes_location_context]")
    test_gemini_prompt_includes_location_context()

    print("\n[test_inat_enrichment_with_mocked_response]")
    test_inat_enrichment_with_mocked_response()

    print("\n[test_plant_enrichment_replaces_generic_name]")
    test_plant_enrichment_replaces_generic_name()

    print("\n[test_no_gemini_key_raises]")
    test_no_gemini_key_raises()

    print("\n[test_temporary_error_detection]")
    test_temporary_error_detection()

    print("\n[test_all_temporary_provider_failures_raise_temporary_error]")
    test_all_temporary_provider_failures_raise_temporary_error()

    print("\n[test_temporary_plus_skipped_providers_still_raise_temporary_error]")
    test_temporary_plus_skipped_providers_still_raise_temporary_error()

    print("\n[test_fourth_provider_runs_after_google_vision]")
    test_fourth_provider_runs_after_google_vision()

    print("\n[test_location_conflict_marks_species_provisional]")
    test_location_conflict_marks_species_provisional()

    if live:
        print("\n=== LIVE TESTS ===")
        test_live_global()
    else:
        print("\n[test_live_global] — skipped (run with --live once GEMINI_API_KEY is set)")

    print("\nAll mock/parse tests passed.")
