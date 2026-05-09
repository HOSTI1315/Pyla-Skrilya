import unittest
from unittest.mock import patch

import numpy as np

from stage_manager import StageManager


class DummyWindowController:
    def __init__(self):
        self.presses = []

    def screenshot(self):
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def press_key(self, key, delay=0.005, touch_up=True, touch_down=True):
        self.presses.append((key, delay))


class StarDropHandlingTests(unittest.TestCase):
    def make_manager(self):
        manager = object.__new__(StageManager)
        manager.window_controller = DummyWindowController()
        manager.long_press_star_drop = "no"
        return manager

    def test_angelic_star_drop_forces_long_press(self):
        manager = self.make_manager()
        with patch("stage_manager.get_star_drop_type", return_value="angelic"):
            manager.click_star_drop()
        self.assertEqual(manager.window_controller.presses, [("Q", 10)])

    def test_demonic_star_drop_forces_long_press(self):
        manager = self.make_manager()
        with patch("stage_manager.get_star_drop_type", return_value="demonic"):
            manager.click_star_drop()
        self.assertEqual(manager.window_controller.presses, [("Q", 10)])

    def test_standard_star_drop_fast_taps(self):
        manager = self.make_manager()
        with patch("stage_manager.get_star_drop_type", return_value="standard"), patch("stage_manager.time.sleep"):
            manager.click_star_drop()
        self.assertEqual(len(manager.window_controller.presses), 5)
        self.assertTrue(all(press == ("Q", 0.005) for press in manager.window_controller.presses))


if __name__ == "__main__":
    unittest.main()
