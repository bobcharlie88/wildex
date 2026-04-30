from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Card, SequenceCounter

log = logging.getLogger("wildex.ids")

WILDEX_CARD_COUNTER = "wildex_card"
WILDEX_ID_RE = re.compile(r"^WX-(?P<year>\d{4})-(?P<number>\d{6})$")
_COUNTER_LOCK = threading.Lock()


@dataclass
class WildExIdMigrationReport:
    missing_ids_fixed: int
    duplicates_found: int
    duplicate_cards_requiring_review: list[dict]
    max_sequence_after_migration: int

    def as_dict(self) -> dict:
        return {
            "missing_ids_fixed": self.missing_ids_fixed,
            "duplicates_found": self.duplicates_found,
            "duplicate_cards_requiring_review": self.duplicate_cards_requiring_review,
            "max_sequence_after_migration": self.max_sequence_after_migration,
        }


def format_wildex_id(created_at: datetime | None, sequence_value: int) -> str:
    year = (created_at or datetime.utcnow()).year
    return f"WX-{year:04d}-{sequence_value:06d}"


def parse_wildex_sequence(value: str | None) -> int | None:
    if not value:
        return None
    match = WILDEX_ID_RE.match(value.strip())
    if not match:
        return None
    return int(match.group("number"))


def _max_existing_wildex_sequence(db: Session) -> int:
    max_value = 0
    for (wildex_id,) in db.query(Card.wildex_id).filter(Card.wildex_id.isnot(None)).all():
        parsed = parse_wildex_sequence(wildex_id)
        if parsed and parsed > max_value:
            max_value = parsed
    return max_value


def _counter_row(db: Session) -> SequenceCounter:
    row = (
        db.query(SequenceCounter)
        .filter(SequenceCounter.name == WILDEX_CARD_COUNTER)
        .with_for_update()
        .first()
    )
    if row is not None:
        return row

    row = SequenceCounter(name=WILDEX_CARD_COUNTER, current_value=_max_existing_wildex_sequence(db))
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        row = (
            db.query(SequenceCounter)
            .filter(SequenceCounter.name == WILDEX_CARD_COUNTER)
            .with_for_update()
            .one()
        )
    return row


def next_wildex_sequence(db: Session) -> int:
    with _COUNTER_LOCK:
        row = _counter_row(db)
        current_max = _max_existing_wildex_sequence(db)
        if row.current_value < current_max:
            log.warning(
                "WildEx counter lagged existing IDs; raising counter from %s to %s",
                row.current_value,
                current_max,
            )
            row.current_value = current_max
        row.current_value += 1
        db.flush()
        return row.current_value


def assign_wildex_id(card: Card, db: Session) -> str:
    if card.wildex_id:
        return card.wildex_id

    sequence_value = next_wildex_sequence(db)
    card.wildex_id = format_wildex_id(card.captured_at, sequence_value)
    db.flush()
    log.info("Assigned WildEx ID %s to card db_id=%s", card.wildex_id, card.id)
    return card.wildex_id


def set_wildex_id_once(card: Card, value: str | None, db: Session) -> str | None:
    if not value:
        return card.wildex_id
    if card.wildex_id and card.wildex_id != value:
        log.warning(
            "Blocked attempt to overwrite WildEx ID for card db_id=%s existing=%s attempted=%s",
            card.id,
            card.wildex_id,
            value,
        )
        return card.wildex_id
    if not card.wildex_id:
        card.wildex_id = value
        db.flush()
        log.info("Set legacy WildEx ID %s on card db_id=%s", value, card.id)
    return card.wildex_id


def find_duplicate_wildex_ids(db: Session) -> list[dict]:
    duplicate_values = (
        db.query(Card.wildex_id, func.count(Card.id).label("count"))
        .filter(Card.wildex_id.isnot(None))
        .group_by(Card.wildex_id)
        .having(func.count(Card.id) > 1)
        .all()
    )
    duplicates: list[dict] = []
    for wildex_id, count in duplicate_values:
        rows = (
            db.query(Card)
            .filter(Card.wildex_id == wildex_id)
            .order_by(Card.captured_at.asc(), Card.id.asc())
            .all()
        )
        duplicates.append(
            {
                "wildex_id": wildex_id,
                "count": int(count),
                "card_ids": [row.id for row in rows],
            }
        )
    return duplicates


def migrate_missing_wildex_ids(db: Session) -> WildExIdMigrationReport:
    duplicates = find_duplicate_wildex_ids(db)
    fixed = 0
    rows = (
        db.query(Card)
        .filter(Card.wildex_id.is_(None))
        .order_by(Card.captured_at.asc(), Card.id.asc())
        .all()
    )
    for row in rows:
        assign_wildex_id(row, db)
        fixed += 1
    counter = _counter_row(db)
    max_existing = _max_existing_wildex_sequence(db)
    if counter.current_value < max_existing:
        counter.current_value = max_existing
        db.flush()
    report = WildExIdMigrationReport(
        missing_ids_fixed=fixed,
        duplicates_found=len(duplicates),
        duplicate_cards_requiring_review=duplicates,
        max_sequence_after_migration=counter.current_value,
    )
    log.info("WildEx ID migration report: %s", report.as_dict())
    return report
