import math
import unittest

from play import Play


class CombatAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.movement = object.__new__(Play)
        self.movement._strafe_started_at = 0.0
        self.movement._strafe_side = 1
        self.movement.strafe_interval = 1.0
        self.movement.projectile_speed_px_s = 900.0

    def test_strafe_angle_flips_after_interval(self):
        first = self.movement.get_strafe_angle(0, 10.0)
        second = self.movement.get_strafe_angle(0, 11.2)
        self.assertEqual(first, 90)
        self.assertEqual(second, 270)

    def test_lead_shot_falls_back_to_direct_when_unsolvable(self):
        angle = self.movement.lead_shot_angle((0, 0), (100, 0), (3000, 0), projectile_speed_px_s=100)
        self.assertAlmostEqual(angle, 0.0)

    def test_lead_shot_aims_ahead_of_moving_target(self):
        angle = self.movement.lead_shot_angle((0, 0), (900, 0), (0, 300), projectile_speed_px_s=900)
        self.assertGreater(angle, 0.0)
        self.assertLess(angle, 45.0)
        self.assertFalse(math.isnan(angle))


if __name__ == "__main__":
    unittest.main()
