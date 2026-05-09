import unittest

import cv2
import numpy as np

from play import Movement, Play


class FakeWindow:
    width_ratio = 1.0
    height_ratio = 1.0


class SuperUsageTests(unittest.TestCase):
    def test_short_super_range_holds_until_enemy_in_range(self):
        # Enemy is past super_range but within attack_range → don't waste the
        # super on a likely fall-short. Bot's approach logic closes the gap
        # and the next tick fires the super in-range.
        self.assertFalse(
            Movement.should_use_super_on_enemy(
                "meg",
                "damage",
                enemy_distance=450,
                attack_range=576,
                super_range=277,
                enemy_hittable=True,
            )
        )

    def test_in_super_range_fires_super(self):
        self.assertTrue(
            Movement.should_use_super_on_enemy(
                "meg",
                "damage",
                enemy_distance=200,
                attack_range=576,
                super_range=277,
                enemy_hittable=True,
            )
        )

    def test_unhittable_never_fires(self):
        self.assertFalse(
            Movement.should_use_super_on_enemy(
                "meg",
                "damage",
                enemy_distance=100,
                attack_range=576,
                super_range=277,
                enemy_hittable=False,
            )
        )

    def test_spawnable_super_ignores_distance(self):
        # Penny / Mr.P — drop spawn anywhere we can.
        self.assertTrue(
            Movement.should_use_super_on_enemy(
                "penny",
                "spawnable",
                enemy_distance=9999,
                attack_range=500,
                super_range=300,
                enemy_hittable=True,
            )
        )

    def test_stu_charge_super_uses_extended_range(self):
        # Stu's super is meant to chain past super_range — keep that branch.
        self.assertTrue(
            Movement.should_use_super_on_enemy(
                "stu",
                "charge",
                enemy_distance=700,
                attack_range=500,
                super_range=300,
                enemy_hittable=True,
            )
        )

    def test_super_ready_detection_allows_button_layout_drift(self):
        play = Play.__new__(Play)
        play.window_controller = FakeWindow()
        play.super_crop_area = [1460, 830, 1560, 930]
        play.super_pixels_minimum = 2400

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cv2.circle(frame, (1580, 950), 52, (255, 170, 0), -1)

        self.assertTrue(play.check_if_super_ready(frame))


if __name__ == "__main__":
    unittest.main()
