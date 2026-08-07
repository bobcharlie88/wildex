import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base, engine, SessionLocal
from app.models import BattleMatch, Card, CardProtection, User
from app.services.battle_engine import (
    calculate_biome_modifiers,
    coin_flip_select_arena,
    evaluate_roster_diversity_penalty,
    execute_losers_tax_transfer,
    register_match_forfeiture,
    simulate_3v3_battle,
)


class TestBattleEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        u1_email = f"p1_{uuid.uuid4().hex[:8]}@example.com"
        u2_email = f"p2_{uuid.uuid4().hex[:8]}@example.com"
        self.p1 = User(email=u1_email, password_hash="hash")
        self.p2 = User(email=u2_email, password_hash="hash")
        self.db.add_all([self.p1, self.p2])
        self.db.commit()
        self.db.refresh(self.p1)
        self.db.refresh(self.p2)

    def tearDown(self):
        try:
            p1_id = self.p1.id
            p2_id = self.p2.id
            self.db.rollback()
            self.db.query(CardProtection).filter(CardProtection.user_id.in_([p1_id, p2_id])).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(BattleMatch).filter(BattleMatch.player1_id.in_([p1_id, p2_id])).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(Card).filter(Card.owner_id.in_([p1_id, p2_id])).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(User).filter(User.id.in_([p1_id, p2_id])).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def test_coin_flip_select_arena(self):
        arena, seed = coin_flip_select_arena()
        self.assertIsNotNone(arena)
        self.assertIsNotNone(seed)
        arena2, _ = coin_flip_select_arena(seed)
        self.assertEqual(arena, arena2)

    def test_biome_modifiers_native_vs_hostile(self):
        marine_card = Card(
            species_name="Great White Shark",
            category="fish",
            sub_category="marine",
            iconic_taxon="actinopterygii",
            speed=80,
            attack=90,
            defence=60,
            hp=85,
        )
        # Marine card in Marine arena (Native Buff)
        marine_mods = calculate_biome_modifiers(marine_card, "Marine")
        self.assertGreater(marine_mods["spd"], 80)
        self.assertGreater(marine_mods["def"], 60)

        # Marine card in Desert arena (Hostile Debuff)
        desert_mods = calculate_biome_modifiers(marine_card, "Desert")
        self.assertLess(desert_mods["spd"], 80)
        self.assertLess(desert_mods["def"], 60)

    def test_mono_roster_diversity_penalty(self):
        c1 = Card(species_name="Shark 1", category="fish", sub_category="marine")
        c2 = Card(species_name="Shark 2", category="fish", sub_category="marine")
        c3 = Card(species_name="Shark 3", category="fish", sub_category="marine")

        penalty = evaluate_roster_diversity_penalty([c1, c2, c3], "Desert")
        self.assertEqual(penalty, 0.80)

        # Diverse roster
        c4 = Card(species_name="Eagle", category="bird", sub_category="bird")
        diversity_penalty = evaluate_roster_diversity_penalty([c1, c2, c4], "Desert")
        self.assertEqual(diversity_penalty, 1.0)

    def test_3v3_combat_simulation(self):
        p1_cards = [
            Card(species_name="Kangaroo", category="mammal", speed=70, attack=75, defence=50, hp=80),
            Card(species_name="Eagle", category="bird", speed=85, attack=70, defence=45, hp=65),
            Card(species_name="Dragon", category="reptile", speed=60, attack=65, defence=70, hp=75),
        ]
        p2_cards = [
            Card(species_name="Small Beetle", category="insect", speed=30, attack=25, defence=20, hp=30),
            Card(species_name="Small Ant", category="insect", speed=25, attack=20, defence=15, hp=25),
            Card(species_name="Small Fly", category="insect", speed=35, attack=15, defence=10, hp=20),
        ]

        result = simulate_3v3_battle(p1_cards, p2_cards, "Grassland")
        self.assertEqual(result["winner_player"], 1)
        self.assertGreater(len(result["combat_log"]), 3)

    def test_losers_tax_card_transfer_and_protection(self):
        loser_card = Card(
            owner_id=self.p2.id,
            species_name="Ring-tailed Dragon",
            scientific_name="Draco annulatus",
            rarity_tier="rare",
            rarity_display="Rare",
        )
        self.db.add(loser_card)
        self.db.commit()
        self.db.refresh(loser_card)

        # Protect card
        prot = CardProtection(user_id=self.p2.id, card_id=loser_card.id, is_protected=True)
        self.db.add(prot)
        self.db.commit()

        # Should fail due to protection
        with self.assertRaises(ValueError):
            execute_losers_tax_transfer(self.db, winner_id=self.p1.id, loser_id=self.p2.id, target_card_id=loser_card.id)

        # Unprotect card
        prot.is_protected = False
        self.db.commit()

        # Transfer succeeds
        transferred = execute_losers_tax_transfer(self.db, winner_id=self.p1.id, loser_id=self.p2.id, target_card_id=loser_card.id)
        self.assertEqual(transferred.owner_id, self.p1.id)

    def test_match_forfeiture_anti_cheat(self):
        match = BattleMatch(
            match_code=f"TEST-{uuid.uuid4().hex[:6]}",
            player1_id=self.p1.id,
            player2_id=self.p2.id,
            status="in_progress",
            arena_biome="Forest",
        )
        self.db.add(match)
        self.db.commit()

        forfeited = register_match_forfeiture(self.db, match_code=match.match_code, forfeiting_player_id=self.p1.id)
        self.assertEqual(forfeited.status, "forfeit")
        self.assertEqual(forfeited.winner_id, self.p2.id)


if __name__ == "__main__":
    unittest.main()
