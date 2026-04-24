from __future__ import annotations

from app.services.card_templates import list_templates, select_template
from app.services.cards.validators import validate_template_parts


def select_template_payload(*, kingdom: str, side: str, preferred_name: str | None = None, preferred_version: str | None = None) -> dict:
    selection = select_template(
        kingdom=kingdom,
        side=side,
        preferred_name=preferred_name,
        preferred_version=preferred_version,
    )
    template = {
        "id": selection.id,
        "name": selection.name,
        "kingdom": selection.kingdom,
        "side": selection.side,
        "asset_url": selection.asset_url,
        "asset_path": selection.asset_path,
        "version": selection.version,
        "active": selection.active,
        "slug": selection.slug,
        "category": selection.category,
        "family": selection.family,
        "environment": selection.environment,
        "layout_key": selection.layout_key,
        "label": selection.label,
        "notes": selection.notes,
        "parts": [dict(item) for item in (selection.parts or [])],
    }
    validate_template_parts(template)
    return template


def list_template_payloads() -> list[dict]:
    items = []
    for selection in list_templates():
        template = {
            "id": selection.id,
            "name": selection.name,
            "kingdom": selection.kingdom,
            "side": selection.side,
            "asset_url": selection.asset_url,
            "asset_path": selection.asset_path,
            "version": selection.version,
            "active": selection.active,
            "slug": selection.slug,
            "category": selection.category,
            "family": selection.family,
            "environment": selection.environment,
            "layout_key": selection.layout_key,
            "label": selection.label,
            "notes": selection.notes,
            "parts": [dict(item) for item in (selection.parts or [])],
        }
        try:
            items.append(validate_template_parts(template).model_dump(mode="json"))
        except Exception:
            items.append(template)
    return items
