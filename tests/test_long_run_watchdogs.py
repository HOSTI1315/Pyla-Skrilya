import unittest
from unittest.mock import patch

from window_controller import WindowController, _foreground_package_from_text


class LongRunWatchdogTests(unittest.TestCase):
    def test_foreground_package_parser_handles_current_focus(self):
        text = "mCurrentFocus=Window{123 u0 com.supercell.brawlstars/com.supercell.titan.GameApp}"
        self.assertEqual(_foreground_package_from_text(text), "com.supercell.brawlstars")

    def test_foreground_package_parser_handles_focused_app(self):
        text = "mFocusedApp=ActivityRecord{123 u0 com.android.launcher/.Launcher t1}"
        self.assertEqual(_foreground_package_from_text(text), "com.android.launcher")

    @patch("window_controller.time.time")
    def test_emulator_restart_respects_cooldown(self, mock_time):
        controller = object.__new__(WindowController)
        controller.last_emulator_restart_time = 100.0
        controller.emulator_restart_cooldown = 180.0
        mock_time.return_value = 150.0

        self.assertFalse(controller.restart_emulator_profile())

    @patch.object(WindowController, "launch_saved_emulator_profile", return_value=False)
    @patch.object(WindowController, "keys_up")
    @patch("window_controller.time.time")
    def test_emulator_restart_failure_does_not_raise(self, mock_time, _mock_keys_up, _mock_launch):
        controller = object.__new__(WindowController)
        controller.selected_emulator = "LDPlayer"
        controller.emulator_profile_index = 0
        controller.configured_serial = "emulator-5554"
        controller.scrcpy_client = None
        controller.last_emulator_restart_time = 0.0
        controller.emulator_restart_cooldown = 180.0
        mock_time.return_value = 300.0

        self.assertFalse(controller.restart_emulator_profile())


if __name__ == "__main__":
    unittest.main()
