from __future__ import annotations

from app.services.cards.schemas import CardPayloadSchema, TemplateSchema
from app.services.cards.slots import SLOT_DEFINITIONS, get_slot_definition, slot_definitions_for_side


class CardConfigurationError(ValueError):
    pass


def validate_card_payload(payload: dict) -> CardPayloadSchema:
    model = CardPayloadSchema.model_validate(payload)
    slot_names = list(model.slot_content.keys())
    if len(slot_names) != len(set(slot_names)):
        raise CardConfigurationError("Duplicate slot content keys detected")

    for slot in slot_definitions_for_side("front") + slot_definitions_for_side("back"):
        if slot.required and slot.content_type != "asset" and slot.name not in model.slot_content:
            raise CardConfigurationError(f"Missing required slot content: {slot.name}")
        if slot.name in model.slot_content and slot.map_only and slot.content_type not in {"map", "asset"}:
            raise CardConfigurationError(f"Map-only slot {slot.name} has an invalid content configuration")
    return model


def validate_template_parts(template: dict | TemplateSchema) -> TemplateSchema:
    model = template if isinstance(template, TemplateSchema) else TemplateSchema.model_validate(template)
    seen = set()
    for part in model.parts:
        slot_name = (part.slot_name or "").strip().lower()
        if not slot_name:
            raise CardConfigurationError("Template contains a blank slot assignment")
        if slot_name in seen:
            raise CardConfigurationError(f"Duplicate template slot assignment: {slot_name}")
        seen.add(slot_name)
        slot = get_slot_definition(slot_name)
        if slot is None:
            raise CardConfigurationError(f"Unknown slot: {slot_name}")
        if slot.side not in {"both", model.side}:
            raise CardConfigurationError(f"Slot {slot_name} is not valid on template side {model.side}")
        if part.asset_type not in slot.allowed_asset_types:
            raise CardConfigurationError(
                f"Slot {slot_name} does not accept asset type {part.asset_type}. "
                f"Allowed: {', '.join(slot.allowed_asset_types)}"
            )
        if slot.map_only and part.asset_type not in {"map_asset", "template_part", "frame_art"}:
            raise CardConfigurationError(f"Map slot {slot_name} requires a map-compatible asset")
    return model


def validate_slot_assignments(*, template_side: str, assignments: dict[str, dict]) -> None:
    seen = set()
    for slot_name, asset in assignments.items():
        normalized = (slot_name or "").strip().lower()
        if normalized in seen:
            raise CardConfigurationError(f"Duplicate slot population: {normalized}")
        seen.add(normalized)
        slot = get_slot_definition(normalized)
        if slot is None:
            raise CardConfigurationError(f"Unknown slot {normalized}")
        if slot.side not in {"both", template_side}:
            raise CardConfigurationError(f"Slot {normalized} is not valid for template side {template_side}")
        asset_type = (asset.get("asset_type") or "").strip().lower()
        if asset_type and asset_type not in slot.allowed_asset_types:
            raise CardConfigurationError(
                f"Invalid asset type {asset_type} for slot {normalized}. "
                f"Allowed: {', '.join(slot.allowed_asset_types)}"
            )
        asset_side = (asset.get("side") or "").strip().lower()
        if asset_side and asset_side not in {"both", template_side}:
            raise CardConfigurationError(f"Asset side {asset_side} cannot be assigned to {template_side} slot {normalized}")
        asset_part = (asset.get("template_part") or "").strip().lower()
        if asset_part and asset_part not in {normalized, "base_frame"} and asset_type not in {"template", "animal_art"}:
            raise CardConfigurationError(
                f"Asset template part {asset_part} does not match slot {normalized}"
            )
        if slot.map_only and asset_type and asset_type not in {"map_asset", "template_part", "frame_art"}:
            raise CardConfigurationError(f"Map slot {normalized} requires a map-compatible asset")
