"""Regression tests for the Showdown trio-grouping fix.

The old code only blended in teammate-pull when the teammate was farther than
``teammate_combat_regroup_distance`` (650px by default) AND an enemy was visible
yet outside attack range. In trio Showdown that combination almost never holds,
so the bot effectively ignored its teammate the whole match. The fix makes the
pull a continuous ramp and falls back to ``follow_teammate`` when every visible
enemy is unhittable.
"""

import unittest

from play import Play


def make_movement():
    m = object.__new__(Play)
    m.teammate_follow_min_distance = 180.0
    m.teammate_follow_max_distance = 520.0
    m.teammate_combat_regroup_distance = 650.0
    m.teammate_combat_bias = 0.5
    return m


class CombatTeammatePullTests(unittest.TestCase):
    def test_no_pull_when_teammate_within_follow_max(self):
        m = make_movement()
        for d in (0, 100, 300, 519, 520):
            mode, pull = m._compute_combat_teammate_pull(d)
            self.assertEqual(mode, "none", f"distance={d}px should not pull")
            self.assertEqual(pull, 0.0)

    def test_continuous_ramp_between_follow_max_and_regroup(self):
        m = make_movement()
        # Just past follow_max — almost zero pull
        mode, low = m._compute_combat_teammate_pull(530)
        self.assertEqual(mode, "blend")
        self.assertLess(low, 0.1)
        # Mid-ramp — somewhere around half of bias
        mode, mid = m._compute_combat_teammate_pull(585)
        self.assertEqual(mode, "blend")
        self.assertGreater(mid, low)
        # At regroup — full bias
        mode, high = m._compute_combat_teammate_pull(650)
        self.assertEqual(mode, "blend")
        self.assertAlmostEqual(high, 0.5, places=2)

    def test_panic_override_when_teammate_far_enough(self):
        m = make_movement()
        # panic = regroup * 1.4 = 910px
        mode, pull = m._compute_combat_teammate_pull(910)
        self.assertEqual(mode, "panic")
        self.assertEqual(pull, 1.0)

        mode, pull = m._compute_combat_teammate_pull(1500)
        self.assertEqual(mode, "panic")

    def test_user_disabled_grouping_via_bias_zero(self):
        # If a user really wants the old "ignore teammates" behaviour they can
        # set teammate_combat_bias to 0 — the helper must respect that.
        m = make_movement()
        m.teammate_combat_bias = 0.0
        mode, pull = m._compute_combat_teammate_pull(600)
        self.assertEqual(mode, "none")
        self.assertEqual(pull, 0.0)


class FindClosestEnemyHittableOnlyTests(unittest.TestCase):
    """Showdown caller asks find_closest_enemy to ignore unhittable enemies so
    the no-enemy / follow-teammate branch can fire."""

    def _make(self, hittable_for):
        m = object.__new__(Play)

        def get_enemy_pos(enemy):
            return enemy

        def get_distance(a, b):
            return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

        def is_enemy_hittable(player_pos, enemy_pos, walls, skill_type):
            return enemy_pos in hittable_for

        m.get_enemy_pos = get_enemy_pos
        m.get_distance = get_distance
        m.is_enemy_hittable = is_enemy_hittable
        return m

    def test_returns_none_when_no_hittable_and_flag_set(self):
        unhittable = (800, 0)
        m = self._make(hittable_for=set())
        coords, dist = m.find_closest_enemy(
            [unhittable], (0, 0), [], "attack", prefer_hittable_only=True
        )
        self.assertIsNone(coords)
        self.assertIsNone(dist)

    def test_falls_back_to_unhittable_when_flag_unset(self):
        # Default (3v3 / non-showdown) behaviour preserved.
        unhittable = (800, 0)
        m = self._make(hittable_for=set())
        coords, dist = m.find_closest_enemy([unhittable], (0, 0), [], "attack")
        self.assertEqual(coords, unhittable)
        self.assertAlmostEqual(dist, 800.0, places=2)

    def test_hittable_wins_even_with_flag(self):
        hit = (300, 0)
        miss = (200, 0)
        m = self._make(hittable_for={hit})
        coords, dist = m.find_closest_enemy(
            [miss, hit], (0, 0), [], "attack", prefer_hittable_only=True
        )
        self.assertEqual(coords, hit)


if __name__ == "__main__":
    unittest.main()
