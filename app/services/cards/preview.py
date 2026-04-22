from __future__ import annotations

from app.services.card_assets import asset_to_dict
from app.services.cards.renderer import build_render_card
from app.services.cards.validators import validate_slot_assignments


def build_preview_render(*, source, front_template: dict | None = None, back_template: dict | None = None, slot_overrides: dict | None = None, asset_lookup=None) -> dict:
    render_card = build_render_card(source)
    if front_template:
        render_card["front_template"] = dict(front_template)
    if back_template:
        render_card["back_template"] = dict(back_template)

    for side_name, mapping in (slot_overrides or {}).items():
        template_key = "front_template" if side_name == "front" else "back_template"
        parts = [dict(item) for item in render_card[template_key].get("parts") or []]
        by_slot = {item.get("slot_name"): item for item in parts}
        normalized_assignments = {}
        for slot_name, asset in (mapping or {}).items():
            if not asset:
                by_slot.pop(slot_name, None)
                continue
            normalized_assignments[slot_name] = asset
            by_slot[slot_name] = {
                "id": asset.get("id"),
                "asset_id": asset.get("id"),
                "slot_name": slot_name,
                "asset_url": asset.get("asset_url") or asset.get("file_path"),
                "asset_type": asset.get("asset_type"),
                "template_part": asset.get("template_part"),
                "mime_type": asset.get("mime_type"),
                "name": asset.get("name"),
                "slug": asset.get("slug"),
                "version": asset.get("version"),
                "sort_order": asset.get("sort_order"),
                "active": bool(asset.get("active", True)),
            }
        validate_slot_assignments(template_side=side_name, assignments=normalized_assignments)
        render_card[template_key]["parts"] = sorted(
            by_slot.values(),
            key=lambda item: (int(item.get("sort_order") or 100), item.get("slot_name") or ""),
        )
    return render_card
