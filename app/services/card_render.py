from __future__ import annotations

from dataclasses import asdict, is_dataclass

from app.services.card_assets import select_context_asset
from app.services.card_templates import select_template

RARITY_VALUES = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "very_rare": "Legendary",
    "legendary": "Legendary",
    "mythic": "Mythic",
    "cryptic": "Cryptic",
    "extinct": "Extinct",
}

THEMES = {
    "reptile": {
        "theme_class": "theme-reptile",
        "accent": "#8a4d2f",
        "accent_dark": "#5c3321",
        "banner_text": "DRAGON",
        "type_label": "Reptile",
        "biome": "Rocky Desert",
        "biome_bonus": "+20% defence in arid zones",
        "strength_name": "Desert",
        "strength_effect": "+20% defence in arid zones",
        "weakness_name": "Cold Rain",
        "weakness_effect": "Reduced mobility and warmth in wet conditions",
    },
    "mammal": {
        "theme_class": "theme-mammal",
        "accent": "#6f5938",
        "accent_dark": "#4d3c24",
        "banner_text": "PAW",
        "type_label": "Mammal",
        "biome": "Grassland",
        "biome_bonus": "+20% damage in arid zones",
        "strength_name": "Desert",
        "strength_effect": "+20% damage in arid zones",
        "weakness_name": "Heavy Rain",
        "weakness_effect": "Reduced mobility and dodge in wet conditions",
    },
    "fish": {
        "theme_class": "theme-fish",
        "accent": "#3a7687",
        "accent_dark": "#244b57",
        "banner_text": "FISH",
        "type_label": "Marine",
        "biome": "Ocean Current",
        "biome_bonus": "+20% speed in open water",
        "strength_name": "Open Water",
        "strength_effect": "+20% speed in marine zones",
        "weakness_name": "Shallow Heat",
        "weakness_effect": "Reduced endurance in warm shallow water",
    },
    "bird": {
        "theme_class": "theme-bird",
        "accent": "#7b8795",
        "accent_dark": "#56606b",
        "banner_text": "WING",
        "type_label": "Bird",
        "biome": "Sky / Cliff",
        "biome_bonus": "+20% speed in open air",
        "strength_name": "High Wind",
        "strength_effect": "+20% scouting in elevated terrain",
        "weakness_name": "Dense Brush",
        "weakness_effect": "Reduced maneuvering in enclosed canopy",
    },
    "insect": {
        "theme_class": "theme-insect",
        "accent": "#8b7a34",
        "accent_dark": "#625523",
        "banner_text": "INSECT",
        "type_label": "Insect",
        "biome": "Brushland",
        "biome_bonus": "+20% evasion in dense foliage",
        "strength_name": "Camouflage",
        "strength_effect": "+20% evasion in natural cover",
        "weakness_name": "Cold Snap",
        "weakness_effect": "Reduced activity in low temperatures",
    },
    "plant": {
        "theme_class": "theme-plant",
        "accent": "#4c7f4f",
        "accent_dark": "#305533",
        "banner_text": "LEAF",
        "type_label": "Plant",
        "biome": "Botanical Habitat",
        "biome_bonus": "+20% resilience in native soil",
        "strength_name": "Rooted Soil",
        "strength_effect": "+20% resilience in stable ground",
        "weakness_name": "Transplant Shock",
        "weakness_effect": "Reduced vitality outside native habitat",
    },
}


def _value(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _stats(source) -> dict:
    stats = _value(source, "stats") or {}
    if is_dataclass(stats):
        return asdict(stats)
    return stats


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


def _rarity(source) -> str:
    display = str(_value(source, "rarity_display") or "").strip()
    if display in {"Common", "Uncommon", "Rare", "Legendary", "Mythic", "Cryptic", "Extinct"}:
        return display
    return RARITY_VALUES.get(str(_value(source, "rarity_tier") or "").strip().lower(), "Common")


def _stored_or(default, source, key):
    value = _value(source, key)
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


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


def _threat_level(attack: int, hp: int) -> str:
    score = attack * 0.65 + hp * 0.35
    if score >= 82:
        return "Extreme"
    if score >= 62:
        return "High"
    if score >= 38:
        return "Medium"
    return "Low"


def _aggression(attack: int, speed: int) -> str:
    score = attack * 0.7 + speed * 0.3
    if score >= 82:
        return "Very High"
    if score >= 62:
        return "High"
    if score >= 38:
        return "Medium"
    return "Low"


def _length_text(name: str, kingdom: str) -> str:
    lowered = name.lower()
    if "ring-tailed dragon" in lowered:
        return "8-10 inches (20-25 cm)"
    if "red kangaroo" in lowered:
        return "1.0-1.6 m body length"
    if "great white shark" in lowered:
        return "3.5-6.0 m"
    if "bald eagle" in lowered:
        return "70-102 cm body length"
    if "mantis" in lowered:
        return "6-10 cm"
    if "pitcher plant" in lowered:
        return "Pitchers to 30 cm"
    return "Field size varies by species"


def _habitat_text(name: str, kingdom: str, capture_country: str | None) -> str:
    lowered = name.lower()
    if "ring-tailed dragon" in lowered:
        return "Rocky terrain of arid Australian outback"
    if "red kangaroo" in lowered:
        return "Arid plains and open woodland"
    if "great white shark" in lowered:
        return "Coastal shelf waters and offshore marine zones"
    if "bald eagle" in lowered:
        return "Large lakes, coasts, and river systems"
    if "mantis" in lowered:
        return "Shrubland, gardens, and dry grassland"
    if "pitcher plant" in lowered:
        return "Humid wetlands and nutrient-poor ground"
    return f"Native habitat{f' in {capture_country}' if capture_country else ''}"


def _diet_text(name: str, kingdom: str) -> str:
    lowered = name.lower()
    if "ring-tailed dragon" in lowered:
        return "Insects and small invertebrates"
    if "red kangaroo" in lowered:
        return "Grasses and low vegetation"
    if "great white shark" in lowered:
        return "Fish, rays, and marine mammals"
    if "bald eagle" in lowered:
        return "Fish, birds, and carrion"
    if "mantis" in lowered:
        return "Insects and small arthropods"
    if "pitcher plant" in lowered:
        return "Insects trapped in pitcher fluid"
    return "Diet varies by species"


def _abilities(name: str, kingdom: str) -> list[str]:
    lowered = name.lower()
    if "ring-tailed dragon" in lowered:
        return ["Flatten Body", "Band-tail Decoy"]
    if "red kangaroo" in lowered:
        return ["Powerful Kick", "Hop Away"]
    if "great white shark" in lowered:
        return ["Burst Rush", "Ambush Bite"]
    if "bald eagle" in lowered:
        return ["High Scan", "Dive Strike"]
    if "mantis" in lowered:
        return ["Ambush Grab", "Leaf Stillness"]
    if "pitcher plant" in lowered:
        return ["Pitfall Trap", "Digestive Pool"]
    return ["Field Adaptation", "Territory Sense"]


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


def build_card_payload(source) -> dict:
    stats = _stats(source)
    species_name = _value(source, "species_name") or _value(source, "common_name") or _value(source, "scientific_name") or "Unknown"
    scientific_name = _value(source, "scientific_name") or "Unknown"
    kingdom_key = _kingdom(_value(source, "category"), _value(source, "sub_category"), _value(source, "iconic_taxon"))
    theme = THEMES[kingdom_key]
    speed = int(stats.get("speed", 50) or 50)
    attack = int(stats.get("attack", 50) or 50)
    defence = int(stats.get("defence", 50) or 50)
    hp = int(stats.get("hp", 50) or 50)
    rarity = _rarity(source)
    capture_country = _value(source, "capture_country")
    threat_level = _stored_or(_threat_level(attack, hp), source, "threat_level")
    aggression = _stored_or(_aggression(attack, speed), source, "aggression")
    biome = _stored_or(theme["biome"], source, "biome")
    biome_bonus = _stored_or(theme["biome_bonus"], source, "biome_bonus")
    strength_name = _stored_or(theme["strength_name"], source, "strength_name")
    strength_effect = _stored_or(theme["strength_effect"], source, "strength_effect")
    weakness_name = _stored_or(theme["weakness_name"], source, "weakness_name")
    weakness_effect = _stored_or(theme["weakness_effect"], source, "weakness_effect")
    abilities = _abilities(species_name, kingdom_key)
    fact_text = (_value(source, "wikipedia_summary") or "").strip() or (
        f"{species_name} has {int(_value(source, 'observations_count') or 0):,} recorded observations."
        if _value(source, "observations_count") else
        f"{species_name} has a confirmed WildEx entry."
    )
    return {
        "card_title": species_name,
        "scientific_name": scientific_name,
        "common_name": species_name,
        "rarity": rarity,
        "diet": _diet_text(species_name, kingdom_key),
        "habitat_text": _habitat_text(species_name, kingdom_key, capture_country),
        "flavor_text": _value(source, "blurb") or f"{species_name} is logged as a WildEx field record.",
        "fact_snippets": [fact_text],
        "stats": {
            "hp": hp,
            "atk": attack,
            "def": defence,
            "spd": speed,
            "stamina_regen": int(stats.get("stamina_regen", 50) or 50),
        },
        "moves": abilities,
        "threat_level": threat_level,
        "aggression": aggression,
        "biome": biome,
        "biome_bonus": biome_bonus,
        "strength_name": strength_name,
        "strength_effect": strength_effect,
        "weakness_name": weakness_name,
        "weakness_effect": weakness_effect,
        "type_label": theme["type_label"],
        "banner_text": theme["banner_text"],
        "length_text": _length_text(species_name, kingdom_key),
        "original_image_url": _original_image(source),
        "primary_image_url": _primary_image(source),
        "sound_url": _value(source, "sound_url"),
        "slot_content": {
            "number_badge": {"text": str(_value(source, "dex_id") or "").split("-")[-1] or str(_value(source, "id") or "")},
            "title_banner": {"text": "WILDEX"},
            "kingdom_badge": {"text": theme["banner_text"]},
            "name_plate": {"title": species_name, "subtitle": scientific_name},
            "scientific_name_line": {"text": scientific_name},
            "creature_art": {"image_url": _primary_image(source)},
            "info_panel": {
                "rows": [
                    {"label": "Common Name", "value": species_name},
                    {"label": "Scientific Name", "value": scientific_name},
                    {"label": "Length", "value": _length_text(species_name, kingdom_key)},
                    {"label": "Habitat", "value": _habitat_text(species_name, kingdom_key, capture_country)},
                    {"label": "Diet", "value": _diet_text(species_name, kingdom_key)},
                ]
            },
            "info_banner": {"text": "INFO"},
            "info_text": {"text": _value(source, "blurb") or f"{species_name} is logged as a WildEx field record."},
            "fact_banner": {"text": "FACT"},
            "fact_text": {"text": fact_text},
            "status_panel": {
                "rows": [
                    {"label": "Rarity", "value": rarity},
                    {"label": "Threat", "value": threat_level},
                    {"label": "Aggression", "value": aggression},
                ]
            },
            "map_panel": {"mode": "range"},
            "strength_box": {"title": strength_name, "text": strength_effect},
            "weakness_box": {"title": weakness_name, "text": weakness_effect},
            "stat_panel": {"rows": [{"label": "HP", "value": hp}, {"label": "ATK", "value": attack}, {"label": "DEF", "value": defence}, {"label": "SPD", "value": speed}]},
            "type_panel": {"title": theme["type_label"], "text": biome_bonus},
            "abilities_panel": {"rows": abilities},
            "environment_panel": {"rows": [f"Gains advantage in {str(biome).lower()} terrain", f"Vulnerable to {str(weakness_name).lower()} conditions"]},
            "call_button": {"label": "Play Call", "enabled": bool(_value(source, "sound_url"))},
            "bottom_strip": {"items": [f"Rarity: {rarity}", f"Threat Level: {threat_level}", f"Aggression: {aggression}"]},
        },
        "render_hints": {
            "theme": kingdom_key,
            "icon_family": (_value(source, "sub_category") or kingdom_key or "").lower(),
            "layout_variant": "master-front-back",
        },
    }


def build_render_card(source) -> dict:
    payload = build_card_payload(source)
    stats = _stats(source)
    species_name = payload["card_title"]
    scientific_name = payload["scientific_name"]
    kingdom_key = _kingdom(_value(source, "category"), _value(source, "sub_category"), _value(source, "iconic_taxon"))
    theme = THEMES[kingdom_key]
    front_template = select_template(
        kingdom=kingdom_key,
        side="front",
        preferred_name=_value(source, "front_template_name"),
        preferred_version=_value(source, "front_template_version"),
    )
    back_template = select_template(
        kingdom=kingdom_key,
        side="back",
        preferred_name=_value(source, "back_template_name"),
        preferred_version=_value(source, "back_template_version"),
    )
    speed = payload["stats"]["spd"]
    attack = payload["stats"]["atk"]
    defence = payload["stats"]["def"]
    hp = payload["stats"]["hp"]
    rarity = payload["rarity"]
    capture_country = _value(source, "capture_country")
    range_mode, range_regions, local_markers = _range_mode(species_name, kingdom_key, capture_country)
    threat_level = payload["threat_level"]
    aggression = payload["aggression"]
    biome = payload["biome"]
    biome_bonus = payload["biome_bonus"]
    strength_name = payload["strength_name"]
    strength_effect = payload["strength_effect"]
    weakness_name = payload["weakness_name"]
    weakness_effect = payload["weakness_effect"]
    family_key = (_value(source, "sub_category") or "").strip().lower() or None
    environment_key = str(biome or "").strip().lower() or None

    def merge_template_parts(selection, side_name: str) -> list[dict]:
        parts = [dict(item) for item in (selection.parts or [])]
        assigned_slots = {item.get("slot_name") for item in parts}
        for slot_name in ("family_icon", "species_icon", "special_badge", "map_frame"):
            if slot_name in assigned_slots:
                continue
            dynamic_asset = select_context_asset(
                asset_type="icon" if "icon" in slot_name or "badge" in slot_name else "map_asset",
                template_part=slot_name,
                side=side_name,
                kingdom=kingdom_key,
                family=family_key,
                environment=environment_key,
            )
            if dynamic_asset is None:
                continue
            parts.append({
                "id": dynamic_asset.id,
                "asset_id": dynamic_asset.id,
                "slot_name": slot_name,
                "asset_url": dynamic_asset.asset_url,
                "asset_type": dynamic_asset.asset_type,
                "template_part": dynamic_asset.template_part,
                "mime_type": dynamic_asset.mime_type,
                "name": dynamic_asset.name,
                "slug": dynamic_asset.slug,
                "version": dynamic_asset.version,
                "sort_order": dynamic_asset.sort_order,
                "active": dynamic_asset.active,
            })
        return sorted(parts, key=lambda item: (int(item.get("sort_order") or 100), item.get("slot_name") or ""))

    return {
        "species_name": species_name,
        "scientific_name": scientific_name,
        "common_name": species_name,
        "kingdom": kingdom_key.title(),
        "group": _value(source, "group_code"),
        "dex_id": _value(source, "dex_id"),
        "card_number": (str(_value(source, "dex_id") or "").split("-")[-1] or str(_value(source, "id") or "")),
        "rarity": rarity,
        "threat_level": threat_level,
        "aggression": aggression,
        "length_text": payload["length_text"],
        "habitat_text": payload["habitat_text"],
        "diet_text": payload["diet"],
        "info_text": payload["flavor_text"],
        "fact_text": payload["fact_snippets"][0] if payload["fact_snippets"] else "",
        "image_url": _primary_image(source),
        "original_image_url": _original_image(source),
        "sound_url": payload["sound_url"],
        "hp": hp,
        "atk": attack,
        "def": defence,
        "spd": speed,
        "type_label": payload["type_label"],
        "biome": biome,
        "biome_bonus": biome_bonus,
        "strength_name": strength_name,
        "strength_effect": strength_effect,
        "weakness_name": weakness_name,
        "weakness_effect": weakness_effect,
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
        "front_template": {
            "id": front_template.id,
            "name": front_template.name,
            "version": front_template.version,
            "asset_url": front_template.asset_url,
            "label": front_template.label,
            "slug": front_template.slug,
            "layout_key": front_template.layout_key,
            "parts": merge_template_parts(front_template, "front"),
        },
        "back_template": {
            "id": back_template.id,
            "name": back_template.name,
            "version": back_template.version,
            "asset_url": back_template.asset_url,
            "label": back_template.label,
            "slug": back_template.slug,
            "layout_key": back_template.layout_key,
            "parts": merge_template_parts(back_template, "back"),
        },
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
