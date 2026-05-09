"""Regression for the live multi-instance bug: bot wins matches without ever
firing E because ``super_pixels_minimum=2400`` was calibrated against a
1920×1080 reference frame, but scrcpy with default ``scrcpy_max_width = 960``
delivers ~960×540 frames. Same ROI rect on a 1/4-area frame contains ~1/4
of the yellow pixels, so the count physically can't exceed the threshold.

Live evidence (Colt, instance 2, 2 matches won): 917 super_yellow checks,
max 1030, threshold 2400, 0 supers fired. After fix: 1/298 fired in the
first ~100s with threshold scaled to 604.

The fix lives on ``Play._ability_threshold`` and is exercised by every
``check_if_*_ready`` site. We test the scaling helper directly by stubbing
the WindowController's wr/hr ratios — pulling in real Play would drag scrcpy
+ onnxruntime into the unit-test env.
"""

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _FakeWC:
    def __init__(self, wr, hr):
        self.width_ratio = wr
        self.height_ratio = hr


class _PlayShim:
    """Just enough of Play to call _ability_threshold without ML imports."""
    # Bind the method by name from the real class via direct source extraction
    # — we want the live behaviour, not a copy.
    def __init__(self, wr, hr):
        self.window_controller = _FakeWC(wr, hr)


def _bind_ability_threshold():
    """Pull the production ``_ability_threshold`` impl out of play.py without
    importing the whole module (which would require onnxruntime + cv2)."""
    src = (REPO_ROOT / "play.py").read_text(encoding="utf-8")
    # Locate the helper definition
    start = src.index("def _ability_threshold(")
    # Walk forward to the first def/class at the same indent — that's the end
    end = src.index("\n    def ", start + 1)
    fn_src = src[start:end]
    # Strip the leading 4 spaces so it's a top-level function
    fn_src = "\n".join(line[4:] if line.startswith("    ") else line
                        for line in fn_src.splitlines())
    ns = {}
    exec(fn_src, ns)
    return ns["_ability_threshold"]


_ability_threshold = _bind_ability_threshold()
_PlayShim._ability_threshold = _ability_threshold


class AbilityThresholdScalingTests(unittest.TestCase):
    def test_native_resolution_unchanged(self):
        # 1920×1080 native -> wr=hr=1 -> threshold unchanged
        p = _PlayShim(1.0, 1.0)
        self.assertAlmostEqual(p._ability_threshold(2400), 2400.0)

    def test_scrcpy_960_540_scales_to_quarter(self):
        # The bug we found live: scrcpy_max_width=960 on 1920×1080 source
        # yields wr=hr=0.5 -> 0.25 area -> threshold goes 2400 -> 600.
        p = _PlayShim(0.5, 0.5)
        self.assertAlmostEqual(p._ability_threshold(2400), 600.0)
        self.assertAlmostEqual(p._ability_threshold(1300), 325.0)
        self.assertAlmostEqual(p._ability_threshold(2000), 500.0)

    def test_intermediate_scale_640(self):
        # scrcpy_max_width=1280 -> wr=hr~0.667 -> 0.444 area scaling
        p = _PlayShim(0.667, 0.667)
        scaled = p._ability_threshold(2400)
        self.assertAlmostEqual(scaled, 2400 * (0.667 ** 2), places=1)

    def test_above_native_capped_at_one(self):
        # If someone runs at 2400×1360 (some LDPlayer tablet profiles do —
        # we saw exactly this in the user's earlier game screenshots),
        # wr*hr ≈ 1.58. We DON'T want the threshold inflated 1.58x — that
        # would mean a real READY button on a high-res capture wouldn't fire.
        # The cap at 1.0 keeps the original behaviour.
        p = _PlayShim(1.25, 1.26)
        self.assertAlmostEqual(p._ability_threshold(2400), 2400.0)

    def test_pre_init_none_treated_as_one(self):
        # WindowController.width_ratio is None until the first scrcpy frame.
        # If a Play.check_if_*_ready ever races ahead of init, the helper
        # must NOT crash with TypeError; it should fall back to base.
        p = _PlayShim(None, None)
        # max(0.25, min(1.0, 1.0 * 1.0)) = 1.0 -> base threshold
        self.assertEqual(p._ability_threshold(2400), 2400.0)

    def test_floor_prevents_absurdly_low_threshold(self):
        # Pathological tiny scale -> floor at 0.25 of base, so the bot can
        # still in theory fire if the (also-tiny) ROI holds enough pixels.
        p = _PlayShim(0.1, 0.1)
        self.assertEqual(p._ability_threshold(2400), 2400 * 0.25)


if __name__ == "__main__":
    unittest.main()
