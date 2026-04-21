from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import or_

from app.database import SessionLocal, db_available
from app.models import CardAsset

ALLOWED_ASSET_MIME_TYPES = {
    "image/svg+xml",
    "image/png",
    "image/webp",
    "image/jpeg",
    "image/jpg",
}

ASSET_SECTIONS = (
    "template",
    "template_part",
    "icon",
    "frame_art",
    "background_art",
    "banner_art",
    "map_asset",
    "animal_art",
)

TEMPLATE_PART_SLOTS = (
    "base_frame",
    "background_texture",
    "top_bar",
    "number_badge",
    "title_banner",
    "kingdom_badge",
    "photo_frame",
    "info_banner",
    "fact_banner",
    "bottom_strip",
    "map_frame",
    "status_panel",
    "frame_overlay",
    "rarity_overlay",
    "family_icon",
    "species_icon",
    "special_badge",
)


@dataclass(frozen=True)
class AssetSelection:
    id: int
    name: str
    slug: str
    asset_type: str
    file_path: str
    mime_type: str | None
    kingdom: str | None
    family: str | None
    environment: str | None
    side: str | None
    template_part: str | None
    version: str
    active: bool
    sort_order: int
    tags: list[str]
    notes: str | None

    @property
    def asset_url(self) -> str:
        return self.file_path


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-") or "asset"


def normalize_tags(value: str | list[str] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        parts = [part.strip() for part in str(value).split(",") if part.strip()]
    return json.dumps(parts) if parts else None


def parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
        if isinstance(loaded, list):
            return [str(item) for item in loaded if str(item).strip()]
    except Exception:
        pass
    return [part.strip() for part in str(value).split(",") if part.strip()]


def asset_to_dict(row: CardAsset) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "asset_type": row.asset_type,
        "file_path": row.file_path,
        "asset_url": row.file_path,
        "mime_type": row.mime_type,
        "kingdom": row.kingdom,
        "family": row.family,
        "environment": row.environment,
        "side": row.side,
        "template_part": row.template_part,
        "version": row.version,
        "active": bool(row.active),
        "sort_order": row.sort_order,
        "tags": parse_tags(row.tags),
        "notes": row.notes,
        "uploaded_by": row.uploaded_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def selection_from_row(row: CardAsset) -> AssetSelection:
    return AssetSelection(
        id=row.id,
        name=row.name,
        slug=row.slug,
        asset_type=row.asset_type,
        file_path=row.file_path,
        mime_type=row.mime_type,
        kingdom=row.kingdom,
        family=row.family,
        environment=row.environment,
        side=row.side,
        template_part=row.template_part,
        version=row.version,
        active=bool(row.active),
        sort_order=row.sort_order or 100,
        tags=parse_tags(row.tags),
        notes=row.notes,
    )


def list_assets() -> list[dict]:
    if not db_available() or SessionLocal is None:
        return []
    db = SessionLocal()
    try:
        rows = (
            db.query(CardAsset)
            .order_by(CardAsset.asset_type.asc(), CardAsset.kingdom.asc(), CardAsset.name.asc(), CardAsset.version.desc())
            .all()
        )
        return [asset_to_dict(row) for row in rows]
    except Exception:
        return []
    finally:
        db.close()


def select_context_asset(
    *,
    asset_type: str | None = None,
    template_part: str,
    side: str | None = None,
    kingdom: str | None = None,
    family: str | None = None,
    environment: str | None = None,
) -> AssetSelection | None:
    if not db_available() or SessionLocal is None:
        return None
    db = SessionLocal()
    try:
        query = db.query(CardAsset).filter(
            CardAsset.active.is_(True),
            CardAsset.template_part == template_part,
        )
        if asset_type:
            query = query.filter(CardAsset.asset_type == asset_type)
        if side:
            query = query.filter(or_(CardAsset.side.is_(None), CardAsset.side == side))
        candidates = query.all()
        if not candidates:
            return None

        def score(row: CardAsset) -> tuple[int, int, int, int, str]:
            return (
                3 if family and row.family and row.family == family else 0,
                2 if kingdom and row.kingdom and row.kingdom == kingdom else 0,
                1 if environment and row.environment and row.environment == environment else 0,
                1 if not row.family and not row.kingdom else 0,
                row.version,
            )

        best = sorted(candidates, key=score, reverse=True)[0]
        return selection_from_row(best)
    except Exception:
        return None
    finally:
        db.close()
