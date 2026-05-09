import unittest
from unittest.mock import patch

from gui.select_brawler import SelectBrawler


class PushAll1kSelectionTest(unittest.TestCase):
    def test_ocr_match_accepts_close_brawler_name(self):
        brawler = SelectBrawler._match_brawler_from_ocr_texts(["M1NA"], ["meg", "mina", "ziggy"])

        self.assertEqual(brawler, "mina")

    def test_selected_game_brawler_moves_to_front_and_flags_update(self):
        data = [
            {"brawler": "meg", "automatically_pick": False, "trophies": 0},
            {"brawler": "mina", "automatically_pick": True, "trophies": 0},
            {"brawler": "ziggy", "automatically_pick": True, "trophies": 0},
        ]

        reordered = SelectBrawler._move_brawler_to_front(data, "mina")

        self.assertEqual(reordered[0]["brawler"], "mina")
        self.assertFalse(reordered[0]["automatically_pick"])
        self.assertTrue(reordered[1]["automatically_pick"])
        self.assertTrue(reordered[2]["automatically_pick"])

    def test_push_all_target_filters_and_sets_target_amount(self):
        obj = object.__new__(SelectBrawler)
        obj.brawlers = ["shelly", "colt", "meg"]
        player_data = {
            "brawlers": [
                {"name": "Shelly", "trophies": 249},
                {"name": "Colt", "trophies": 500},
                {"name": "Meg", "trophies": 750},
            ]
        }

        with patch("gui.select_brawler.load_brawl_stars_api_config", return_value={
            "api_token": "token",
            "player_tag": "TAG",
            "timeout_seconds": 15,
        }), patch("gui.select_brawler.fetch_brawl_stars_player", return_value=player_data):
            data = SelectBrawler.get_push_all_data(obj, 500)

        self.assertEqual([row["brawler"] for row in data], ["shelly"])
        self.assertEqual(data[0]["push_until"], 500)
        self.assertFalse(data[0]["automatically_pick"])
        self.assertEqual(data[0]["selection_method"], "lowest_trophies")


if __name__ == "__main__":
    unittest.main()
