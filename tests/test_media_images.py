from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.models import Card, CaptureJob
from app.services.capture_jobs import serialize_capture_job
from app.utils.card_serializer import card_to_dict
from app.utils.media_urls import local_upload_path_from_url, media_url_for_client
from main import app


def test_local_upload_path_preserves_nested_directories():
    path = local_upload_path_from_url("/uploads/admin/cards/photo-abc123.jpg")
    assert path.as_posix().endswith("uploads/admin/cards/photo-abc123.jpg")


def test_remote_image_url_is_rewritten_to_same_origin_proxy():
    proxied = media_url_for_client("https://cdn.example.com/captures/kangaroo.jpg")
    assert proxied == "/media/image?url=https%3A%2F%2Fcdn.example.com%2Fcaptures%2Fkangaroo.jpg"


def test_card_serializer_overlays_client_safe_image_url_in_stored_render_json():
    card = Card(
        id=7,
        species_name="Quokka",
        scientific_name="Setonix brachyurus",
        wildex_id="WX-2026-000007",
        image_url="https://cdn.example.com/captures/quokka.jpg",
        primary_card_image_url="https://cdn.example.com/captures/quokka.jpg",
        render_status="ready",
        render_card_json=json.dumps(
            {
                "image_url": "https://old.example.com/stale.jpg",
                "original_image_url": "https://old.example.com/stale.jpg",
                "slot_content": {"creature_art": {"image_url": "https://old.example.com/stale.jpg"}},
            }
        ),
    )

    payload = card_to_dict(card)

    assert payload["image_url"].startswith("/media/image?url=")
    assert payload["render_card"]["image_url"] == payload["image_url"]
    assert payload["render_card"]["slot_content"]["creature_art"]["image_url"] == payload["image_url"]
    assert payload["render_card"]["card_number"] == "WX-2026-000007"


def test_capture_job_serializer_uses_client_safe_image_urls():
    job = CaptureJob(
        id=9,
        status="queued",
        image_url="https://cdn.example.com/captures/job.jpg",
        primary_image_url="https://cdn.example.com/captures/job.jpg",
        original_image_url="https://cdn.example.com/captures/original.jpg",
    )

    payload = serialize_capture_job(job)

    assert payload["image_url"].startswith("/media/image?url=")
    assert payload["primary_image_url"].startswith("/media/image?url=")
    assert payload["stored_image_url"] == "https://cdn.example.com/captures/job.jpg"


def test_media_image_serves_nested_local_upload(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    nested = uploads / "admin" / "cards"
    nested.mkdir(parents=True)
    image = nested / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0test")
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    response = client.get("/media/image", params={"url": "/uploads/admin/cards/photo.jpg"})

    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xe0test"
    assert response.headers["content-type"].startswith("image/jpeg")
