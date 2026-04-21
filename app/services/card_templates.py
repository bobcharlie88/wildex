from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from app.database import SessionLocal, db_available
from app.services.card_assets import asset_to_dict, normalize_tags, slugify

try:
    from app.models import CardAsset, CardTemplate, TemplatePartAssignment
except Exception:  # pragma: no cover
    CardAsset = None
    CardTemplate = None
    TemplatePartAssignment = None


@dataclass(frozen=True)
class TemplateSelection:
    name: str
    kingdom: str
    side: str
    asset_path: str
    version: str
    active: bool
    slug: str | None = None
    category: str | None = None
    family: str | None = None
    environment: str | None = None
    layout_key: str | None = None
    config: dict | None = None
    label: str | None = None
    notes: str | None = None
    parts: list[dict] | None = None
    id: int | None = None

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
        "slug": "reptile-front-master",
        "category": "default",
        "layout_key": "master-front",
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
        "slug": "reptile-back-master",
        "category": "default",
        "layout_key": "master-back",
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
        "slug": "mammal-front-master",
        "category": "default",
        "layout_key": "master-front",
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
        "slug": "mammal-back-master",
        "category": "default",
        "layout_key": "master-back",
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
        "slug": "fish-front-master",
        "category": "default",
        "layout_key": "master-front",
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
        "slug": "fish-back-master",
        "category": "default",
        "layout_key": "master-back",
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
        "slug": "bird-front-master",
        "category": "default",
        "layout_key": "master-front",
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
        "slug": "bird-back-master",
        "category": "default",
        "layout_key": "master-back",
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
        "slug": "insect-front-master",
        "category": "default",
        "layout_key": "master-front",
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
        "slug": "insect-back-master",
        "category": "default",
        "layout_key": "master-back",
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
        "slug": "plant-front-master",
        "category": "default",
        "layout_key": "master-front",
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
        "slug": "plant-back-master",
        "category": "default",
        "layout_key": "master-back",
        "active": True,
        "label": "Plant Back Master",
        "notes": "Built-in fixed-slot back template.",
    },
)


def _builtin_selection(item: dict) -> TemplateSelection:
    payload = dict(item)
    payload.setdefault("config", {"layout_key": item.get("layout_key")})
    payload.setdefault("parts", [{"slot_name": "base_frame", "asset_url": item["asset_path"], "asset_type": "template", "sort_order": 0}])
    return TemplateSelection(**payload)


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
    parts = []
    if getattr(row, "part_assignments", None):
        parts = [
            {
                "id": assignment.asset.id,
                "slot_name": assignment.slot_name,
                "asset_id": assignment.asset.id,
                "asset_url": assignment.asset.file_path,
                "asset_type": assignment.asset.asset_type,
                "template_part": assignment.asset.template_part,
                "mime_type": assignment.asset.mime_type,
                "name": assignment.asset.name,
                "slug": assignment.asset.slug,
                "version": assignment.asset.version,
                "sort_order": assignment.asset.sort_order or 100,
                "active": bool(assignment.asset.active),
            }
            for assignment in sorted(row.part_assignments, key=lambda item: ((item.asset.sort_order or 100), item.slot_name))
            if assignment.asset is not None
        ]
    if not parts and getattr(row, "asset_path", None):
        parts = [{
            "slot_name": "base_frame",
            "asset_url": row.asset_path,
            "asset_type": "template",
            "sort_order": 0,
        }]
    return TemplateSelection(
        id=row.id,
        name=row.name,
        kingdom=row.kingdom,
        side=row.side,
        asset_path=row.asset_path,
        version=row.version,
        active=bool(row.active),
        slug=row.slug,
        category=row.category,
        family=row.family,
        environment=row.environment,
        layout_key=row.layout_key,
        config=json.loads(row.config_json) if row.config_json else {},
        label=row.label,
        notes=row.notes,
        parts=parts,
    )


def ensure_builtin_templates(db) -> None:
    if CardTemplate is None or CardAsset is None or TemplatePartAssignment is None:
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
                slug=item.get("slug") or slugify(item["name"]),
                category=item.get("category"),
                layout_key=item.get("layout_key"),
                config_json=json.dumps({"layout_key": item.get("layout_key")}),
                active=False,
                label=item.get("label"),
                notes=item.get("notes"),
            )
            db.add(row)
            db.flush()
        else:
            row.asset_path = item["asset_path"]
            row.slug = item.get("slug") or row.slug or slugify(item["name"])
            row.category = item.get("category") or row.category
            row.layout_key = item.get("layout_key") or row.layout_key
            row.config_json = json.dumps({"layout_key": item.get("layout_key") or row.layout_key})
            row.label = item.get("label")
            row.notes = item.get("notes")

        asset_slug = item.get("slug") or slugify(item["name"])
        asset_row = (
            db.query(CardAsset)
            .filter(CardAsset.slug == asset_slug, CardAsset.version == item["version"])
            .first()
        )
        if asset_row is None:
            asset_row = CardAsset(
                name=item.get("label") or item["name"],
                slug=asset_slug,
                asset_type="template",
                file_path=item["asset_path"],
                mime_type="image/svg+xml",
                kingdom=item["kingdom"],
                side=item["side"],
                template_part="base_frame",
                version=item["version"],
                active=True,
                sort_order=0,
                tags=normalize_tags(["builtin", item["kingdom"], item["side"]]),
                notes=item.get("notes"),
            )
            db.add(asset_row)
            db.flush()
        else:
            asset_row.file_path = item["asset_path"]
            asset_row.mime_type = "image/svg+xml"
            asset_row.asset_type = "template"
            asset_row.template_part = "base_frame"
            asset_row.side = item["side"]
            asset_row.kingdom = item["kingdom"]
            asset_row.active = True
            asset_row.sort_order = 0
        assignment = (
            db.query(TemplatePartAssignment)
            .filter(
                TemplatePartAssignment.template_id == row.id,
                TemplatePartAssignment.slot_name == "base_frame",
            )
            .first()
        )
        if assignment is None:
            db.add(TemplatePartAssignment(template_id=row.id, slot_name="base_frame", asset_id=asset_row.id))
        else:
            assignment.asset_id = asset_row.id

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
            query = (
                db.query(CardTemplate)
                .order_by(CardTemplate.kingdom.asc(), CardTemplate.side.asc(), CardTemplate.version.desc())
            )
            rows = [_row_to_selection(row) for row in query.all()]
        except Exception:
            rows = []
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
        except Exception:
            pass
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
