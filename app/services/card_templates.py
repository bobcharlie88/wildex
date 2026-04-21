from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.database import SessionLocal, db_available

try:
    from app.models import CardTemplate
except Exception:  # pragma: no cover
    CardTemplate = None


@dataclass(frozen=True)
class TemplateSelection:
    name: str
    kingdom: str
    side: str
    asset_path: str
    version: str
    active: bool
    label: str | None = None
    notes: str | None = None

    @property
    def asset_url(self) -> str:
        return self.asset_path


BUILTIN_TEMPLATES = (
    {
        "name": "reptile-front-master",
        "kingdom": "reptile",
        "side": "front",
        "asset_path": "/static/card_templates/reptile/front-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Reptile Front Master",
        "notes": "Built-in fixed-slot front template.",
    },
    {
        "name": "reptile-back-master",
        "kingdom": "reptile",
        "side": "back",
        "asset_path": "/static/card_templates/reptile/back-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Reptile Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
    {
        "name": "mammal-front-master",
        "kingdom": "mammal",
        "side": "front",
        "asset_path": "/static/card_templates/mammal/front-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Mammal Front Master",
        "notes": "Built-in fixed-slot front template.",
    },
    {
        "name": "mammal-back-master",
        "kingdom": "mammal",
        "side": "back",
        "asset_path": "/static/card_templates/mammal/back-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Mammal Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
    {
        "name": "fish-front-master",
        "kingdom": "fish",
        "side": "front",
        "asset_path": "/static/card_templates/fish/front-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Fish Front Master",
        "notes": "Built-in fixed-slot front template.",
    },
    {
        "name": "fish-back-master",
        "kingdom": "fish",
        "side": "back",
        "asset_path": "/static/card_templates/fish/back-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Fish Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
    {
        "name": "bird-front-master",
        "kingdom": "bird",
        "side": "front",
        "asset_path": "/static/card_templates/bird/front-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Bird Front Master",
        "notes": "Built-in fixed-slot front template.",
    },
    {
        "name": "bird-back-master",
        "kingdom": "bird",
        "side": "back",
        "asset_path": "/static/card_templates/bird/back-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Bird Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
    {
        "name": "insect-front-master",
        "kingdom": "insect",
        "side": "front",
        "asset_path": "/static/card_templates/insect/front-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Insect Front Master",
        "notes": "Built-in fixed-slot front template.",
    },
    {
        "name": "insect-back-master",
        "kingdom": "insect",
        "side": "back",
        "asset_path": "/static/card_templates/insect/back-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Insect Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
    {
        "name": "plant-front-master",
        "kingdom": "plant",
        "side": "front",
        "asset_path": "/static/card_templates/plant/front-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Plant Front Master",
        "notes": "Built-in fixed-slot front template.",
    },
    {
        "name": "plant-back-master",
        "kingdom": "plant",
        "side": "back",
        "asset_path": "/static/card_templates/plant/back-v1.svg",
        "version": "1.0.0",
        "active": True,
        "label": "Plant Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
)


def _builtin_selection(item: dict) -> TemplateSelection:
    return TemplateSelection(**item)


def _builtin_lookup(kingdom: str, side: str, name: str | None = None, version: str | None = None) -> TemplateSelection | None:
    normalized = (kingdom or "mammal").strip().lower()
    for item in BUILTIN_TEMPLATES:
        if item["kingdom"] != normalized or item["side"] != side:
            continue
        if name and item["name"] != name:
            continue
        if version and item["version"] != version:
            continue
        return _builtin_selection(item)
    if normalized != "mammal":
        return _builtin_lookup("mammal", side, name=None, version=None)
    return None


def _row_to_selection(row) -> TemplateSelection:
    return TemplateSelection(
        name=row.name,
        kingdom=row.kingdom,
        side=row.side,
        asset_path=row.asset_path,
        version=row.version,
        active=bool(row.active),
        label=row.label,
        notes=row.notes,
    )


def ensure_builtin_templates(db) -> None:
    if CardTemplate is None:
        return
    for item in BUILTIN_TEMPLATES:
        row = (
            db.query(CardTemplate)
            .filter(CardTemplate.name == item["name"], CardTemplate.version == item["version"])
            .first()
        )
        if row is None:
            row = CardTemplate(
                name=item["name"],
                kingdom=item["kingdom"],
                side=item["side"],
                asset_path=item["asset_path"],
                version=item["version"],
                active=False,
                label=item.get("label"),
                notes=item.get("notes"),
            )
            db.add(row)
            db.flush()
        else:
            row.asset_path = item["asset_path"]
            row.label = item.get("label")
            row.notes = item.get("notes")

        active_exists = (
            db.query(CardTemplate)
            .filter(
                CardTemplate.kingdom == item["kingdom"],
                CardTemplate.side == item["side"],
                CardTemplate.active.is_(True),
            )
            .first()
        )
        if active_exists is None:
            row.active = True
    db.flush()
    clear_template_cache()


def list_templates() -> list[TemplateSelection]:
    rows: list[TemplateSelection] = []
    if CardTemplate is not None and db_available() and SessionLocal is not None:
        db = SessionLocal()
        try:
            rows = [_row_to_selection(row) for row in db.query(CardTemplate).order_by(CardTemplate.kingdom.asc(), CardTemplate.side.asc(), CardTemplate.version.desc()).all()]
        finally:
            db.close()
    if rows:
        return rows
    return [_builtin_selection(item) for item in BUILTIN_TEMPLATES]


def clear_template_cache() -> None:
    _select_template_cached.cache_clear()


@lru_cache(maxsize=128)
def _select_template_cached(kingdom: str, side: str, preferred_name: str | None, preferred_version: str | None) -> TemplateSelection:
    if CardTemplate is not None and db_available() and SessionLocal is not None:
        db = SessionLocal()
        try:
            if preferred_name and preferred_version:
                row = (
                    db.query(CardTemplate)
                    .filter(
                        CardTemplate.name == preferred_name,
                        CardTemplate.version == preferred_version,
                        CardTemplate.side == side,
                    )
                    .first()
                )
                if row:
                    return _row_to_selection(row)
            row = (
                db.query(CardTemplate)
                .filter(
                    CardTemplate.kingdom == kingdom,
                    CardTemplate.side == side,
                    CardTemplate.active.is_(True),
                )
                .order_by(CardTemplate.version.desc(), CardTemplate.id.desc())
                .first()
            )
            if row:
                return _row_to_selection(row)
        finally:
            db.close()
    fallback = _builtin_lookup(kingdom, side, name=preferred_name, version=preferred_version)
    if fallback:
        return fallback
    raise LookupError(f"No template found for kingdom={kingdom} side={side}")


def select_template(
    *,
    kingdom: str,
    side: str,
    preferred_name: str | None = None,
    preferred_version: str | None = None,
) -> TemplateSelection:
    return _select_template_cached(
        (kingdom or "mammal").strip().lower(),
        side,
        preferred_name,
        preferred_version,
    )
