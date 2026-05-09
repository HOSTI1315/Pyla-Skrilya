import unittest
from unittest.mock import patch

import cv2
import numpy as np

from stage_manager import StageManager
from state_finder import is_in_prestige_reward


class DummyTrophyObserver:
    def __init__(self):
        self.current_trophies = 0
        self.current_wins = 0
        self.win_streak = 0

    def change_trophies(self, trophies):
        self.current_trophies = trophies


class DummyLobbyAutomation:
    def __init__(self):
        self.lowest_selected = False

    def select_lowest_trophy_brawler(self):
        self.lowest_selected = True


class DummyWindowController:
    width_ratio = 1.0
    height_ratio = 1.0

    def __init__(self):
        self.clicks = []
        self.presses = []
        self.keys_released = []

    def keys_up(self, keys):
        self.keys_released.append(keys)

    def click(self, x, y):
        self.clicks.append((x, y))

    def press_key(self, key):
        self.presses.append(key)

    def screenshot(self):
        return np.zeros((1080, 1920, 3), dtype=np.uint8)


class PrestigeRewardTests(unittest.TestCase):
    def test_prestige_reward_detector_requires_green_next_and_purple_badge(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        green = cv2.cvtColor(
            np.full((1, 1, 3), (60, 220, 220), dtype=np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0, 0]
        purple = cv2.cvtColor(
            np.full((1, 1, 3), (140, 180, 180), dtype=np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0, 0]
        image[930:1030, 1240:1580] = green
        image[180:700, 1120:1700] = purple
        image[940:975, 1360:1460] = (255, 255, 255)
        self.assertTrue(is_in_prestige_reward(image))

    def test_prestige_reward_detector_rejects_match_noise_without_next_text(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        green = cv2.cvtColor(
            np.full((1, 1, 3), (60, 220, 220), dtype=np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0, 0]
        purple = cv2.cvtColor(
            np.full((1, 1, 3), (140, 180, 180), dtype=np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0, 0]
        image[930:1030, 1240:1580] = green
        image[180:700, 1120:1700] = purple
        self.assertFalse(is_in_prestige_reward(image))

    def test_prestige_reward_advances_queue_and_selects_lowest(self):
        manager = object.__new__(StageManager)
        manager.brawlers_pick_data = [
            {"brawler": "gray", "trophies": 990, "push_until": 1000, "wins": 0, "win_streak": 0},
            {"brawler": "shelly", "trophies": 20, "push_until": 1000, "wins": 0, "win_streak": 0},
        ]
        manager.Trophy_observer = DummyTrophyObserver()
        manager.Lobby_automation = DummyLobbyAutomation()
        manager.window_controller = DummyWindowController()

        with patch("stage_manager.is_in_prestige_reward", return_value=True), \
                patch("stage_manager.get_state", return_value="lobby"), \
                patch("stage_manager.save_brawler_data"):
            manager.handle_prestige_reward()

        self.assertEqual(manager.brawlers_pick_data[0]["brawler"], "shelly")
        self.assertEqual(manager.Trophy_observer.current_trophies, 20)
        self.assertTrue(manager.Lobby_automation.lowest_selected)
        self.assertIn((1410, 990), manager.window_controller.clicks)


if __name__ == "__main__":
    unittest.main()
