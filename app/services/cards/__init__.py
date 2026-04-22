from __future__ import annotations

from importlib import import_module

__all__ = [
    "CardConfigurationError",
    "SLOT_DEFINITIONS",
    "apply_render_fields",
    "build_card_payload",
    "build_preview_render",
    "build_render_card",
    "list_template_payloads",
    "select_template_payload",
    "slot_definitions_for_side",
    "validate_card_payload",
    "validate_slot_assignments",
]

_EXPORTS = {
    "build_card_payload": ("app.services.cards.builder", "build_card_payload"),
    "build_preview_render": ("app.services.cards.preview", "build_preview_render"),
    "apply_render_fields": ("app.services.cards.renderer", "apply_render_fields"),
    "build_render_card": ("app.services.cards.renderer", "build_render_card"),
    "SLOT_DEFINITIONS": ("app.services.cards.slots", "SLOT_DEFINITIONS"),
    "slot_definitions_for_side": ("app.services.cards.slots", "slot_definitions_for_side"),
    "list_template_payloads": ("app.services.cards.templates", "list_template_payloads"),
    "select_template_payload": ("app.services.cards.templates", "select_template_payload"),
    "CardConfigurationError": ("app.services.cards.validators", "CardConfigurationError"),
    "validate_card_payload": ("app.services.cards.validators", "validate_card_payload"),
    "validate_slot_assignments": ("app.services.cards.validators", "validate_slot_assignments"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
