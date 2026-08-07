import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.cards.builder import build_card_payload, _rarity
from app.services.cards.renderer import build_render_card, apply_render_fields
from app.utils.card_serializer import card_to_dict
from app.models import Card


class TestCardRendererPipeline(unittest.TestCase):

    def test_rarity_normalization(self):
        cases = [
            ("very_rare", "Legendary"),
            ("Very_Rare", "Legendary"),
            ("legendary", "Legendary"),
            ("Legendary", "Legendary"),
            ("common", "Common"),
            ("Rare", "Rare"),
            ("cryptic", "Cryptic"),
            ("extinct", "Extinct"),
        ]
        for input_val, expected in cases:
            source = {"rarity_tier": input_val}
            self.assertEqual(_rarity(source), expected, f"Failed for tier {input_val}")

            source_disp = {"rarity_display": input_val}
            self.assertEqual(_rarity(source_disp), expected, f"Failed for display {input_val}")

    def test_custom_user_photo_and_stats_payload(self):
        source = {
            "id": 99,
            "species_name": "Test Wildlife Creature",
            "scientific_name": "Creaturus testus",
            "rarity_tier": "very_rare",
            "original_image_url": "/uploads/user_photo_orig.jpg",
            "primary_card_image_url": "/uploads/user_photo_card.jpg",
            "image_url": "/uploads/user_photo_primary.jpg",
            "category": "animal",
            "sub_category": "reptile",
            "stats": {
                "speed": 88,
                "attack": 92,
                "defence": 74,
                "hp": 85,
                "stamina_regen": 60,
            },
        }

        payload = build_card_payload(source)
        self.assertEqual(payload["card_title"], "Test Wildlife Creature")
        self.assertEqual(payload["rarity"], "Legendary")
        self.assertEqual(payload["primary_image_url"], "/uploads/user_photo_card.jpg")

        render_card = build_render_card(source)
        self.assertEqual(render_card["rarity"], "Legendary")
        self.assertEqual(render_card["hp"], 85)
        self.assertEqual(render_card["atk"], 92)
        self.assertEqual(render_card["def"], 74)
        self.assertEqual(render_card["spd"], 88)
        self.assertEqual(render_card["original_image_url"], "/uploads/user_photo_orig.jpg")

    def test_apply_render_fields_and_serialization(self):
        c = Card(
            id=1,
            species_name="Emu",
            scientific_name="Dromaius novaehollandiae",
            rarity_tier="common",
            speed=65,
            attack=55,
            defence=45,
            hp=70,
            stamina_regen=80,
            original_image_url="/uploads/emu.jpg",
            primary_card_image_url="/uploads/emu.jpg",
            image_url="/uploads/emu.jpg",
        )
        render_data = build_render_card(c)
        apply_render_fields(c, render_data)

        self.assertEqual(c.rarity_display, "Common")
        self.assertEqual(c.original_image_url, "/uploads/emu.jpg")

        serialized = card_to_dict(c)
        self.assertEqual(serialized["species_name"], "Emu")
        self.assertIn("render_card", serialized)
        self.assertEqual(serialized["render_card"]["hp"], 70)


if __name__ == "__main__":
    unittest.main()
