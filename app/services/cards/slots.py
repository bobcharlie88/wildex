from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotDefinition:
    name: str
    side: str
    content_type: str
    allowed_asset_types: tuple[str, ...]
    required: bool = False
    map_only: bool = False
    description: str = ""


SLOT_DEFINITIONS: tuple[SlotDefinition, ...] = (
    SlotDefinition("base_frame", "both", "asset", ("template", "frame_art", "template_part"), required=True, description="Main frame art for the card side."),
    SlotDefinition("background_texture", "both", "asset", ("background_art", "template_part", "frame_art"), description="Atmosphere texture behind content."),
    SlotDefinition("top_bar", "both", "asset", ("banner_art", "template_part", "frame_art"), description="Top bar ornament or banner art."),
    SlotDefinition("number_badge", "both", "text", ("template_part", "banner_art"), required=True, description="Badge showing card number."),
    SlotDefinition("title_banner", "both", "text", ("banner_art", "template_part"), required=True, description="Top title or dex banner area."),
    SlotDefinition("kingdom_badge", "both", "text", ("icon", "banner_art", "template_part"), required=True, description="Kingdom badge/icon plate."),
    SlotDefinition("name_plate", "both", "text", ("banner_art", "template_part"), required=True, description="Primary species/common name block."),
    SlotDefinition("scientific_name_line", "front", "text", ("banner_art", "template_part"), required=True, description="Scientific name line on the front."),
    SlotDefinition("creature_art", "front", "image", ("animal_art",), required=True, description="Primary species/capture image."),
    SlotDefinition("photo_frame", "front", "asset", ("frame_art", "template_part"), description="Decorative frame around creature art."),
    SlotDefinition("info_panel", "front", "text", ("template_part",), required=True, description="Structured info rows such as length, habitat, diet."),
    SlotDefinition("info_banner", "front", "text", ("banner_art", "template_part"), required=True, description="Banner label for the info text block."),
    SlotDefinition("flavor_text_block", "front", "text", ("template_part",), required=True, description="Main flavor/lore text block."),
    SlotDefinition("fact_banner", "front", "text", ("banner_art", "template_part"), required=True, description="Fact strip banner."),
    SlotDefinition("fact_text", "front", "text", ("template_part",), required=True, description="Fact strip content."),
    SlotDefinition("status_panel", "back", "text", ("template_part",), required=True, description="Compact rarity/threat/aggression panel."),
    SlotDefinition("map_frame", "back", "asset", ("map_asset", "template_part", "frame_art"), map_only=True, description="Map frame and region-map art."),
    SlotDefinition("map_panel", "back", "map", ("map_asset", "template_part"), required=True, map_only=True, description="Rendered map content container."),
    SlotDefinition("strength_box", "back", "text", ("template_part",), required=True, description="Strength panel."),
    SlotDefinition("weakness_box", "back", "text", ("template_part",), required=True, description="Weakness panel."),
    SlotDefinition("stat_panel", "back", "text", ("template_part",), required=True, description="Stats block."),
    SlotDefinition("moves_panel", "back", "text", ("template_part",), description="Moves/abilities block."),
    SlotDefinition("diet_panel", "back", "text", ("template_part",), description="Diet or ecology box."),
    SlotDefinition("habitat_line", "back", "text", ("template_part",), description="Habitat/region line."),
    SlotDefinition("type_panel", "back", "text", ("template_part",), required=True, description="Type and biome panel."),
    SlotDefinition("abilities_panel", "back", "text", ("template_part",), required=True, description="Abilities/moves listing."),
    SlotDefinition("environment_panel", "back", "text", ("template_part",), required=True, description="Environment triggers panel."),
    SlotDefinition("call_button", "back", "text", ("template_part",), description="Sound/call button slot."),
    SlotDefinition("bottom_strip", "back", "text", ("banner_art", "template_part"), required=True, description="Bottom footer row for rarity/threat/aggression."),
    SlotDefinition("frame_overlay", "both", "asset", ("frame_art", "template_part"), description="Overlay frame flourishes."),
    SlotDefinition("rarity_overlay", "both", "asset", ("frame_art", "banner_art", "template_part"), description="Rare/special overlay art."),
    SlotDefinition("family_icon", "both", "asset", ("icon", "template_part"), description="Family or kingdom icon."),
    SlotDefinition("species_icon", "both", "asset", ("icon", "template_part"), description="Species-specific icon."),
    SlotDefinition("special_badge", "both", "asset", ("icon", "banner_art", "template_part"), description="Special rarity or event badge."),
)


def get_slot_definition(name: str) -> SlotDefinition | None:
    normalized = (name or "").strip().lower()
    for item in SLOT_DEFINITIONS:
        if item.name == normalized:
            return item
    return None


def slot_definitions_for_side(side: str | None) -> list[SlotDefinition]:
    normalized = (side or "").strip().lower()
    return [item for item in SLOT_DEFINITIONS if item.side in {"both", normalized}]
