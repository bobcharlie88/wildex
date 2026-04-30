from __future__ import annotations

import json

from app.models import Card
from app.services.card_render import build_render_card
from app.utils.media_urls import media_url_for_client

_RARITY_DISPLAY = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "very_rare": "Legendary",
}


def card_to_dict(c: Card) -> dict:
    primary_image_url = c.primary_card_image_url or c.image_url
    original_image_url = c.original_image_url or primary_image_url
    client_primary_image_url = media_url_for_client(primary_image_url)
    client_original_image_url = media_url_for_client(original_image_url)
    if c.render_card_json and c.render_status == "ready":
        render_card = json.loads(c.render_card_json)
        render_card["image_url"] = client_primary_image_url
        render_card["original_image_url"] = client_original_image_url
        slot_content = render_card.setdefault("slot_content", {})
        creature_art = slot_content.setdefault("creature_art", {})
        creature_art["image_url"] = client_primary_image_url
        if c.wildex_id:
            render_card["wildex_id"] = c.wildex_id
            render_card["card_number"] = c.wildex_id
            number_badge = slot_content.setdefault("number_badge", {})
            number_badge["text"] = c.wildex_id
    else:
        render_card = build_render_card(c)
        render_card["image_url"] = media_url_for_client(render_card.get("image_url"))
        render_card["original_image_url"] = media_url_for_client(render_card.get("original_image_url"))
        render_card.setdefault("slot_content", {}).setdefault("creature_art", {})["image_url"] = render_card["image_url"]
    return {
        "id":                   c.id,
        "wildex_id":            c.wildex_id,
        "species_name":         c.species_name,
        "scientific_name":      c.scientific_name,
        "rank":                 c.rank,
        "confidence":           round(c.confidence, 4) if c.confidence else None,
        "provisional":          c.provisional,
        "rarity_tier":          c.rarity_tier,
        "rarity_display":       c.rarity_display or _RARITY_DISPLAY.get(c.rarity_tier or "", "Unknown"),
        "invasive_at_location": c.invasive_at_location,
        "iconic_taxon":         c.iconic_taxon,
        "conservation_status":  c.conservation_status,
        "observations_count":   c.observations_count,
        "taxon_id":             c.taxon_id,
        "gbif_key":             c.gbif_key,
        "category":             c.category,
        "sub_category":         c.sub_category,
        "blurb":                c.blurb,
        "stats": {
            "speed":         c.speed,
            "attack":        c.attack,
            "defence":       c.defence,
            "hp":            c.hp,
            "stamina_regen": c.stamina_regen,
        },
        "threat_level":          c.threat_level,
        "aggression":            c.aggression,
        "biome":                 c.biome,
        "biome_bonus":           c.biome_bonus,
        "strength_name":         c.strength_name,
        "strength_effect":       c.strength_effect,
        "weakness_name":         c.weakness_name,
        "weakness_effect":       c.weakness_effect,
        "sound_url":             c.sound_url,
        "captured_at":           c.captured_at.isoformat() if c.captured_at else None,
        "latitude":              c.latitude,
        "longitude":             c.longitude,
        "capture_country":       c.capture_country,
        "original_image_url":    client_original_image_url,
        "primary_card_image_url": client_primary_image_url,
        "image_url":             client_primary_image_url,
        "stored_original_image_url": original_image_url,
        "stored_primary_card_image_url": primary_image_url,
        "supporting_image_urls": [media_url_for_client(url) for url in (json.loads(c.supporting_image_urls) if c.supporting_image_urls else [])],
        "card_payload":          json.loads(c.card_payload_json) if c.card_payload_json else None,
        "card_payload_version":  c.card_payload_version,
        "render_status":         c.render_status,
        "front_template_name":   c.front_template_name,
        "front_template_version": c.front_template_version,
        "front_template_id":     c.front_template_id,
        "back_template_name":    c.back_template_name,
        "back_template_version": c.back_template_version,
        "back_template_id":      c.back_template_id,
        "dex_id":                c.dex_id,
        "discovery_state":       c.discovery_state,
        "region":                c.region,
        "kingdom":               c.kingdom,
        "group_code":            c.group_code,
        "evolution_chain_id":    c.evolution_chain_id,
        "evolution_stage":       c.evolution_stage,
        "render_card":           render_card,
    }
