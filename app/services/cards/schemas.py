from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SlotRow(BaseModel):
    label: str
    value: str | int | float | None = None


class SlotTextBlock(BaseModel):
    text: str | None = None
    title: str | None = None
    subtitle: str | None = None
    rows: list[SlotRow | str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    image_url: str | None = None
    enabled: bool | None = None
    mode: str | None = None


class CardStatsSchema(BaseModel):
    hp: int
    atk: int
    defense: int = Field(alias="def")
    spd: int
    stamina_regen: int | None = None

    model_config = {"populate_by_name": True}


class RenderHintsSchema(BaseModel):
    theme: str
    layout_variant: str
    icon_family: str | None = None


class CardPayloadSchema(BaseModel):
    card_title: str
    scientific_name: str
    common_name: str
    rarity: str
    diet: str
    habitat_text: str
    flavor_text: str
    fact_snippets: list[str] = Field(default_factory=list)
    stats: CardStatsSchema
    moves: list[str] = Field(default_factory=list)
    threat_level: str
    aggression: str
    biome: str
    biome_bonus: str
    strength_name: str
    strength_effect: str
    weakness_name: str
    weakness_effect: str
    type_label: str
    banner_text: str
    length_text: str
    original_image_url: str | None = None
    primary_image_url: str | None = None
    sound_url: str | None = None
    slot_content: dict[str, SlotTextBlock | dict[str, Any]]
    render_hints: RenderHintsSchema


class TemplatePartSchema(BaseModel):
    id: int | None = None
    asset_id: int | None = None
    slot_name: str
    asset_url: str
    asset_type: str
    template_part: str | None = None
    mime_type: str | None = None
    name: str | None = None
    slug: str | None = None
    version: str | None = None
    sort_order: int | None = None
    active: bool | None = None


class TemplateSchema(BaseModel):
    id: int | None = None
    name: str
    kingdom: str
    side: str
    asset_url: str
    asset_path: str | None = None
    version: str
    active: bool = False
    slug: str | None = None
    category: str | None = None
    family: str | None = None
    environment: str | None = None
    layout_key: str | None = None
    label: str | None = None
    notes: str | None = None
    parts: list[TemplatePartSchema] = Field(default_factory=list)
