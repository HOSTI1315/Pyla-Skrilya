import unittest
from unittest.mock import patch

from stage_manager import StageManager


class DummyTrophyObserver:
    def __init__(self, trophies):
        self.current_trophies = trophies
        self.current_wins = 0
        self.win_streak = 0
        self.changed_to = None

    def change_trophies(self, value):
        self.changed_to = value
        self.current_trophies = value


class DummyWindowController:
    def __init__(self):
        self.pressed = []
        self.keys_released = []

    def screenshot(self):
        return None

    def keys_up(self, keys):
        self.keys_released.extend(keys)

    def press_key(self, key):
        self.pressed.append(key)


class DummyLobbyAutomation:
    def __init__(self):
        self.lowest_calls = 0
        self.named_calls = []

    def select_lowest_trophy_brawler(self):
        self.lowest_calls += 1

    def select_brawler(self, name):
        self.named_calls.append(name)


class PushAllTargetSwitchTest(unittest.TestCase):
    def make_manager(self, target):
        manager = object.__new__(StageManager)
        manager.brawlers_pick_data = [
            {
                "brawler": "first",
                "push_until": target,
                "trophies": target,
                "wins": 0,
                "type": "trophies",
                "automatically_pick": False,
                "win_streak": 0,
                "selection_method": "lowest_trophies",
            },
            {
                "brawler": "second",
                "push_until": target,
                "trophies": 0,
                "wins": 0,
                "type": "trophies",
                "automatically_pick": True,
                "win_streak": 0,
                "selection_method": "lowest_trophies",
            },
        ]
        manager.started_trophies_by_brawler = {"first": target, "second": 0}
        manager.Trophy_observer = DummyTrophyObserver(target)
        manager.window_controller = DummyWindowController()
        manager.Lobby_automation = DummyLobbyAutomation()
        manager.send_webhook_notification = lambda *args, **kwargs: None
        return manager

    @patch("stage_manager.time.sleep", return_value=None)
    @patch("stage_manager.get_state", return_value="lobby")
    def test_push_all_targets_switch_by_lowest_trophy_sort(self, *_):
        for target in (250, 500, 750, 1000):
            with self.subTest(target=target):
                manager = self.make_manager(target)

                manager.start_game()

                self.assertEqual(manager.brawlers_pick_data[0]["brawler"], "second")
                self.assertEqual(manager.Trophy_observer.changed_to, 0)
                self.assertEqual(manager.Lobby_automation.lowest_calls, 1)
                self.assertEqual(manager.Lobby_automation.named_calls, [])
                self.assertIn("Q", manager.window_controller.pressed)


if __name__ == "__main__":
    unittest.main()
