import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from app.database import Base, engine, SessionLocal
from app.models import Card, User
from app.services.quests import (
    ensure_builtin_quests,
    grant_xp,
    process_discovery_event,
    get_user_progression,
)
from app.services.spatial_map import (
    fuzz_coordinates,
    get_explore_map_data,
    _distance_km,
)


class TestQuestsAndSpatial(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        unique_email = f"test_quest_{uuid.uuid4().hex[:8]}@example.com"
        self.user = User(email=unique_email, password_hash="hash")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        try:
            user_id = self.user.id
            self.db.rollback()
            from app.models import UserBadge, UserQuestProgress, UserProgression
            self.db.query(UserBadge).filter(UserBadge.user_id == user_id).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(UserQuestProgress).filter(UserQuestProgress.user_id == user_id).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(UserProgression).filter(UserProgression.user_id == user_id).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(Card).filter(Card.owner_id == user_id).delete(synchronize_session=False)
            self.db.commit()
            self.db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def test_coordinate_fuzzer_rare_vs_common(self):
        # Rare species should be fuzzed by ~1 to 5 km
        lat, lon = -33.8688, 151.2093
        f_lat, f_lon, is_fuzzed = fuzz_coordinates(lat, lon, rarity_tier="rare")

        self.assertTrue(is_fuzzed)
        dist_km = _distance_km(lat, lon, f_lat, f_lon)
        self.assertGreaterEqual(dist_km, 0.5)
        self.assertLessEqual(dist_km, 10.0)

        # Common species should have minor or zero fuzzing
        c_lat, c_lon, c_fuzzed = fuzz_coordinates(lat, lon, rarity_tier="common")
        self.assertFalse(c_fuzzed)
        c_dist_km = _distance_km(lat, lon, c_lat, c_lon)
        self.assertLess(c_dist_km, 0.5)

    def test_quest_generation_and_xp_grant(self):
        quests = ensure_builtin_quests(self.db)
        self.assertGreaterEqual(len(quests), 3)

        prog, badges = grant_xp(self.db, self.user.id, 600)
        self.assertEqual(prog.level, 3)
        self.assertEqual(prog.xp, 600)

    def test_discovery_event_quest_and_badge_progress(self):
        card = Card(
            owner_id=self.user.id,
            species_name="Bald Eagle",
            scientific_name="Haliaeetus leucocephalus",
            category="bird",
            sub_category="bird",
            rarity_tier="rare",
            latitude=-33.8688,
            longitude=151.2093,
        )
        self.db.add(card)
        self.db.commit()
        self.db.refresh(card)

        result = process_discovery_event(
            self.db,
            user_id=self.user.id,
            card=card,
            is_new_species=True,
            is_region_unlock=False,
        )

        self.assertGreater(result["xp_gained"], 200)
        self.assertIn("first_discovery", result["new_badges"])
        self.assertIn("rare_hunter", result["new_badges"])

    def test_spatial_map_explore_payload(self):
        card = Card(
            owner_id=self.user.id,
            species_name="Red Kangaroo",
            scientific_name="Macropus rufus",
            rarity_tier="common",
            latitude=-33.8700,
            longitude=151.2100,
        )
        self.db.add(card)
        self.db.commit()

        explore_data = get_explore_map_data(
            self.db,
            user_id=self.user.id,
            user_lat=-33.8688,
            user_lon=151.2093,
        )

        self.assertIn("public_markers", explore_data)
        self.assertIn("user_private_markers", explore_data)
        self.assertGreaterEqual(len(explore_data["public_markers"]), 1)
        self.assertGreaterEqual(len(explore_data["user_private_markers"]), 1)


if __name__ == "__main__":
    unittest.main()
