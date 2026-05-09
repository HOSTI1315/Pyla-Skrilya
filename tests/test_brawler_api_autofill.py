import unittest
from unittest.mock import patch

from gui.select_brawler import SelectBrawler
import utils
from utils import get_config_player_tag


class BrawlerApiAutofillTest(unittest.TestCase):
    def test_trophy_lookup_uses_normalized_brawler_name(self):
        selector = object.__new__(SelectBrawler)
        selector.api_trophies_by_brawler = {"8-bit": 731, "sprout": 642}
        selector.api_trophies_by_normalized_brawler = None

        self.assertEqual(selector.get_api_trophies_for_brawler("8 Bit"), 731)
        self.assertEqual(selector.get_api_trophies_for_brawler("SPROUT"), 642)

    def test_player_tag_selection(self):
        config = {
            "player_tag": "#AAAA",
        }

        self.assertEqual(get_config_player_tag(config), "#AAAA")

    def test_keeps_placeholder_when_no_player_tag_is_configured(self):
        config = {
            "player_tag": "#YOURTAG",
        }

        self.assertEqual(get_config_player_tag(config), "#YOURTAG")

    def test_failed_auto_refresh_does_not_mark_refresh_done(self):
        utils._brawl_stars_api_refresh_done = False
        config = {
            "auto_refresh_token": True,
            "developer_email": "",
            "developer_password": "",
        }

        with self.assertRaises(ValueError):
            utils.refresh_brawl_stars_api_token_if_enabled(config)

        self.assertFalse(utils._brawl_stars_api_refresh_done)

    @patch("utils.refresh_brawl_stars_api_token_if_enabled")
    def test_api_config_is_reloaded_fresh(self, mock_refresh):
        mock_refresh.side_effect = lambda config, file_path: config
        path = "cfg/test_brawl_stars_api_autofill.toml"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write('api_token = ""\nplayer_tag = "#FIRST"\nauto_refresh_token = false\n')
            self.assertEqual(utils.load_brawl_stars_api_config(path)["player_tag"], "#FIRST")

            with open(path, "w", encoding="utf-8") as f:
                f.write('api_token = ""\nplayer_tag = "#SECOND"\nauto_refresh_token = false\n')
            self.assertEqual(utils.load_brawl_stars_api_config(path)["player_tag"], "#SECOND")
        finally:
            import os
            utils.clear_toml_cache(path)
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
