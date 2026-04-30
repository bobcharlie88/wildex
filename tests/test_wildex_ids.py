from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Card, SequenceCounter
from app.services.cards.renderer import build_render_card
from app.services.wildex_ids import assign_wildex_id, migrate_missing_wildex_ids


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'wildex-id-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _card(**kwargs) -> Card:
    data = {
        "species_name": "Quokka",
        "scientific_name": "Setonix brachyurus",
        "captured_at": datetime(2026, 4, 29, 12, 0, 0),
    }
    data.update(kwargs)
    return Card(**data)


def test_creating_one_card_assigns_unique_wildex_id(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        card = _card()
        db.add(card)
        db.flush()
        assert assign_wildex_id(card, db) == "WX-2026-000001"
        db.commit()
        assert card.wildex_id == "WX-2026-000001"
    finally:
        db.close()


def test_rerender_does_not_change_wildex_id(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        card = _card(wildex_id="WX-2026-000123", dex_id="AU-MAM-MAR-001")
        db.add(card)
        db.commit()
        before = card.wildex_id

        monkeypatch.setattr(
            "app.services.cards.renderer.select_template_payload",
            lambda **kwargs: {
                "id": 1,
                "name": kwargs.get("preferred_name") or "naturalist",
                "kingdom": kwargs["kingdom"],
                "side": kwargs["side"],
                "asset_url": "",
                "asset_path": "",
                "version": "1.0.0",
                "active": True,
                "parts": [],
            },
        )
        render = build_render_card(card)
        assert card.wildex_id == before
        assert render["wildex_id"] == before
        assert render["card_number"] == before
        assert render["slot_content"]["number_badge"]["text"] == before
    finally:
        db.close()


def test_backfill_does_not_change_existing_wildex_ids(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        existing = _card(wildex_id="WX-2026-000777")
        missing = _card(species_name="Western Grey Kangaroo", scientific_name="Macropus fuliginosus")
        db.add_all([existing, missing])
        db.commit()

        report = migrate_missing_wildex_ids(db)
        db.commit()

        assert report.missing_ids_fixed == 1
        assert existing.wildex_id == "WX-2026-000777"
        assert missing.wildex_id == "WX-2026-000778"
    finally:
        db.close()


def test_failed_render_does_not_consume_another_id_for_same_card(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        card = _card()
        db.add(card)
        db.flush()
        first = assign_wildex_id(card, db)
        second = assign_wildex_id(card, db)
        db.commit()

        assert first == second == "WX-2026-000001"
        assert db.query(SequenceCounter).filter_by(name="wildex_card").one().current_value == 1
    finally:
        db.close()


def test_two_concurrent_cards_do_not_get_same_wildex_id(tmp_path):
    Session = _session_factory(tmp_path)

    def create_one(index: int) -> str:
        db = Session()
        try:
            card = _card(species_name=f"Species {index}", scientific_name=f"Species testus {index}")
            db.add(card)
            db.flush()
            wildex_id = assign_wildex_id(card, db)
            db.commit()
            return wildex_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create_one, [1, 2]))

    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert sorted(ids) == ["WX-2026-000001", "WX-2026-000002"]


def test_missing_legacy_ids_are_backfilled_in_created_order(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        later = _card(species_name="Later", scientific_name="Later testus", captured_at=datetime(2026, 5, 2))
        earlier = _card(species_name="Earlier", scientific_name="Earlier testus", captured_at=datetime(2026, 5, 1))
        db.add_all([later, earlier])
        db.commit()

        report = migrate_missing_wildex_ids(db)
        db.commit()

        assert report.missing_ids_fixed == 2
        assert earlier.wildex_id == "WX-2026-000001"
        assert later.wildex_id == "WX-2026-000002"
        assert report.max_sequence_after_migration == 2
        assert report.duplicates_found == 0
        assert report.duplicate_cards_requiring_review == []
    finally:
        db.close()


def test_duplicate_legacy_ids_are_detected_and_reported(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        db.execute(text("DROP INDEX IF EXISTS ix_cards_wildex_id"))
        first = _card(
            species_name="First",
            scientific_name="First testus",
            wildex_id="WX-2026-000005",
        )
        second = _card(
            species_name="Second",
            scientific_name="Second testus",
            wildex_id="WX-2026-000005",
        )
        db.add_all([first, second])
        db.commit()

        report = migrate_missing_wildex_ids(db)

        assert report.missing_ids_fixed == 0
        assert report.duplicates_found == 1
        assert report.duplicate_cards_requiring_review == [
            {"wildex_id": "WX-2026-000005", "count": 2, "card_ids": [first.id, second.id]}
        ]
        assert report.max_sequence_after_migration == 5
    finally:
        db.close()
