from __future__ import annotations

from app.services.cards.builder import THEMES, build_card_payload
from app.services.cards.templates import select_template_payload
from app.services.cards.validators import validate_template_parts


def _value(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _kingdom(category: str | None, sub_category: str | None, iconic_taxon: str | None) -> str:
    category = (category or "").lower()
    sub_category = (sub_category or "").lower()
    iconic_taxon = (iconic_taxon or "").lower()
    if sub_category == "reptile" or iconic_taxon == "reptilia":
        return "reptile"
    if sub_category == "bird" or iconic_taxon == "aves":
        return "bird"
    if sub_category in {"fish", "marine"} or iconic_taxon == "actinopterygii":
        return "fish"
    if sub_category in {"insect", "arachnid"}:
        return "insect"
    if category == "plant" or iconic_taxon == "plantae":
        return "plant"
    return "mammal"


def _primary_image(source) -> str | None:
    value = _value(source, "primary_card_image_url")
    if not value:
        value = _value(source, "primary_image_url")
    if not value:
        value = _value(source, "image_url")
    return value


def _original_image(source) -> str | None:
    value = _value(source, "original_image_url")
    return value or _primary_image(source)


def _range_mode(name: str, kingdom: str, capture_country: str | None) -> tuple[str, list[str], list[dict]]:
    lowered = name.lower()
    if "shark" in lowered or kingdom == "fish":
        return "ocean", ["PACIFIC", "INDIAN", "ATLANTIC"], []
    if capture_country == "AU" or "kangaroo" in lowered or "dragon" in lowered:
        return "region", ["AU"], [{"region": "AU", "x": 79, "y": 60}]
    if "bald eagle" in lowered:
        return "world", ["NA"], [{"region": "NA", "x": 34, "y": 36}]
    if "pitcher plant" in lowered:
        return "world", ["AS"], [{"region": "AS", "x": 139, "y": 48}]
    return "world", ([capture_country] if capture_country else ["GLOBAL"]), []


def _merge_template_parts(*, kingdom_key: str, side_name: str, template: dict, family_key: str | None, environment_key: str | None) -> list[dict]:
    parts = [dict(item) for item in (template.get("parts") or [])]
    template["parts"] = sorted(parts, key=lambda item: (int(item.get("sort_order") or 100), item.get("slot_name") or ""))
    validate_template_parts(template)
    return template["parts"]


def build_render_card(source) -> dict:
    payload = build_card_payload(source)
    species_name = payload["card_title"]
    scientific_name = payload["scientific_name"]
    kingdom_key = _kingdom(_value(source, "category"), _value(source, "sub_category"), _value(source, "iconic_taxon"))
    theme = THEMES[kingdom_key]
    front_template = select_template_payload(
        kingdom=_value(source, "kingdom") or kingdom_key,
        side="front",
        preferred_name=_value(source, "front_template_name") or "naturalist-front-v1",
        preferred_version=_value(source, "front_template_version") or "1.0.0",
    )
    back_template = select_template_payload(
        kingdom=_value(source, "kingdom") or kingdom_key,
        side="back",
        preferred_name=_value(source, "back_template_name") or "naturalist-back-v1",
        preferred_version=_value(source, "back_template_version") or "1.0.0",
    )
    capture_country = _value(source, "capture_country")
    range_mode, range_regions, local_markers = _range_mode(species_name, kingdom_key, capture_country)
    family_key = (_value(source, "sub_category") or "").strip().lower() or None
    environment_key = str(payload["biome"] or "").strip().lower() or None
    wildex_id = _value(source, "wildex_id")
    dex_id = _value(source, "dex_id")
    card_number = wildex_id or str(dex_id or "").split("-")[-1] or str(_value(source, "id") or "")

    _merge_template_parts(
        kingdom_key=kingdom_key,
        side_name="front",
        template=front_template,
        family_key=family_key,
        environment_key=environment_key,
    )
    _merge_template_parts(
        kingdom_key=kingdom_key,
        side_name="back",
        template=back_template,
        family_key=family_key,
        environment_key=environment_key,
    )

    return {
        "card_id": _value(source, "id"),
        "wildex_id": wildex_id,
        "species_name": species_name,
        "scientific_name": scientific_name,
        "common_name": payload["common_name"],
        "kingdom": kingdom_key.title(),
        "group": _value(source, "group_code"),
        "dex_id": dex_id,
        "card_number": card_number,
        "rarity": payload["rarity"],
        "threat_level": payload["threat_level"],
        "aggression": payload["aggression"],
        "region": _value(source, "region"),
        "length_text": payload["length_text"],
        "habitat_text": payload["habitat_text"],
        "diet_text": payload["diet"],
        "info_text": payload["flavor_text"],
        "fact_text": payload["fact_snippets"][0] if payload["fact_snippets"] else "",
        "image_url": payload["primary_image_url"],
        "original_image_url": payload["original_image_url"] or _original_image(source),
        "sound_url": payload["sound_url"],
        "captured_at": _value(source, "captured_at"),
        "taxon_id": _value(source, "taxon_id"),
        "inat_url": f"https://www.inaturalist.org/taxa/{int(_value(source, 'taxon_id'))}" if _value(source, "taxon_id") and str(_value(source, "taxon_id")).isdigit() else None,
        "qr_url": f"/cards/{int(_value(source, 'id'))}/inat-qr.png" if _value(source, "id") else None,
        "hp": payload["stats"]["hp"],
        "atk": payload["stats"]["atk"],
        "def": payload["stats"]["def"],
        "spd": payload["stats"]["spd"],
        "type_label": payload["type_label"],
        "biome": payload["biome"],
        "biome_bonus": payload["biome_bonus"],
        "strength_name": payload["strength_name"],
        "strength_effect": payload["strength_effect"],
        "weakness_name": payload["weakness_name"],
        "weakness_effect": payload["weakness_effect"],
        "abilities": payload["moves"],
        "environment_triggers": payload["slot_content"]["environment_panel"]["rows"],
        "range_mode": range_mode,
        "range_regions": range_regions,
        "local_markers": local_markers,
        "evolution_chain_id": _value(source, "evolution_chain_id"),
        "evolution_stage": _value(source, "evolution_stage"),
        "theme_class": theme["theme_class"],
        "accent": theme["accent"],
        "accent_dark": theme["accent_dark"],
        "banner_text": payload["banner_text"],
        "slot_content": payload["slot_content"],
        "render_hints": payload["render_hints"],
        "front_template": front_template,
        "back_template": back_template,
        "confidence": _value(source, "confidence"),
        "provisional": _value(source, "provisional"),
        "rank": _value(source, "rank"),
    }


def apply_render_fields(target, render_data: dict) -> None:
    target.rarity_display = render_data.get("rarity")
    target.threat_level = render_data.get("threat_level")
    target.aggression = render_data.get("aggression")
    target.biome = render_data.get("biome")
    target.biome_bonus = render_data.get("biome_bonus")
    target.strength_name = render_data.get("strength_name")
    target.strength_effect = render_data.get("strength_effect")
    target.weakness_name = render_data.get("weakness_name")
    target.weakness_effect = render_data.get("weakness_effect")
    if getattr(target, "original_image_url", None) is None:
        target.original_image_url = render_data.get("original_image_url")
    if getattr(target, "primary_card_image_url", None) is None:
        target.primary_card_image_url = render_data.get("image_url")
    if getattr(target, "image_url", None) is None:
        target.image_url = render_data.get("image_url")
    target.front_template_name = render_data.get("front_template", {}).get("name")
    target.front_template_version = render_data.get("front_template", {}).get("version")
    target.back_template_name = render_data.get("back_template", {}).get("name")
    target.back_template_version = render_data.get("back_template", {}).get("version")
    if getattr(target, "sound_url", None) is None:
        target.sound_url = render_data.get("sound_url")
