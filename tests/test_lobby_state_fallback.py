import unittest

import cv2
import numpy as np

from state_finder import is_lobby_play_button_visible


class LobbyStateFallbackTests(unittest.TestCase):
    def test_detects_lobby_by_large_yellow_play_button(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        yellow_bgr = cv2.cvtColor(
            np.full((1, 1, 3), (28, 230, 245), dtype=np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0, 0]
        image[850:1020, 1300:1820] = yellow_bgr

        self.assertTrue(is_lobby_play_button_visible(image))

    def test_rejects_small_yellow_noise(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        yellow_bgr = cv2.cvtColor(
            np.full((1, 1, 3), (28, 230, 245), dtype=np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0, 0]
        image[900:930, 1300:1360] = yellow_bgr

        self.assertFalse(is_lobby_play_button_visible(image))


if __name__ == "__main__":
    unittest.main()
