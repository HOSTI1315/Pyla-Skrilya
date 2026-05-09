"""Regression tests for ``LobbyAutomation.names_match`` length-ratio gate.

A real-screenshot bug found during multi-instance Push All testing: locked
brawler cards display the caption ``Available on the STARR ROAD`` which OCR
returns as the token ``availableonthe`` (14 chars). Without a length-ratio
gate, the substring rule matched ``leon`` (4 chars, present at positions 7-10
of ``ab|leon|the``) — and the bot would happily click that locked-card text
thinking it was the LEON tile. Mid-match the bot then tries to start a game
with whichever character actually got selected, leading to a crash or wrong
brawler.

These tests pin both the new false-negative-prevention (rejecting noise) AND
the legitimate near-miss matches (so OCR clipping like ``darry`` -> ``darryl``
keeps working).
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lobby_automation import LobbyAutomation


class NamesMatchLengthRatioTests(unittest.TestCase):
    def test_locked_card_caption_does_not_match_short_brawler(self):
        # The exact OCR token captured from screenshots/dnplayer_S6wAEGW2UY.png
        self.assertFalse(LobbyAutomation.names_match("availableonthe", "leon"))
        self.assertFalse(LobbyAutomation.names_match("availableon", "leon"))
        self.assertFalse(LobbyAutomation.names_match("availableonte", "leon"))

    def test_starr_road_does_not_match_tara(self):
        # 'starrroad' (9 chars) vs 'tara' (4) — without the gate the substring
        # rule would also let "starr" match because it contains 'tara' fragments.
        # Length ratio 9/4 = 2.25 > 1.5 should reject.
        self.assertFalse(LobbyAutomation.names_match("availablestarrroad", "tara"))

    def test_brawlers_to_be_unlocked_does_not_match(self):
        # 'brawlerstobeunlocked' contains 'unlocked' which... shouldn't match
        # any brawler. Just verify the noise token doesn't accidentally match
        # something short like 'lou' or 'rt'.
        self.assertFalse(LobbyAutomation.names_match("brawlerstobeunlocked", "lou"))
        self.assertFalse(LobbyAutomation.names_match("brawlerstobeunlocked", "rt"))

    def test_legitimate_ocr_clipping_still_matches(self):
        # OCR misses one trailing char — should still resolve.
        self.assertTrue(LobbyAutomation.names_match("darry", "darryl"))
        # OCR adds one extra char — should still resolve.
        self.assertTrue(LobbyAutomation.names_match("pearrl", "pearl"))
        # Same-length swaps go through the edit-distance path.
        self.assertTrue(LobbyAutomation.names_match("shey", "shelly")
                        or LobbyAutomation.resolve_ocr_typos("shey") == "shelly")

    def test_exact_match_always_works(self):
        for name in ("colt", "shelly", "leon", "el primo", "8bit", "bo"):
            normalized = LobbyAutomation.normalize_ocr_name(name)
            self.assertTrue(LobbyAutomation.names_match(normalized, normalized))

    def test_short_target_inside_long_token_now_rejected(self):
        # General principle: a 4-char target inside a 9+-char token shouldn't
        # match unless edit distance is small (it isn't here).
        self.assertFalse(LobbyAutomation.names_match("starroadunlock", "leon"))
        # But 5-char inside 6-char is still legit (1.2 ratio).
        self.assertTrue(LobbyAutomation.names_match("buzzz", "buzz"))


if __name__ == "__main__":
    unittest.main()
