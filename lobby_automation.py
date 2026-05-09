from difflib import SequenceMatcher
import time

import cv2
import numpy as np

from typization import BrawlerName
from utils import (
    extract_text_and_positions,
    count_hsv_pixels,
    load_toml_as_dict,
    find_template_center,
    load_brawlers_info,
)

debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"
gray_pixels_treshold = load_toml_as_dict("./cfg/bot_config.toml")['idle_pixels_minimum']
class LobbyAutomation:

    def __init__(self, window_controller):
        self.coords_cfg = load_toml_as_dict("./cfg/lobby_config.toml")
        self.window_controller = window_controller

    def check_for_idle(self, frame):
        general_config = load_toml_as_dict("cfg/general_config.toml")
        bot_config = load_toml_as_dict("./cfg/bot_config.toml")
        debug_enabled = str(general_config.get("super_debug", "no")).lower() in ("yes", "true", "1")
        gray_pixels_threshold = bot_config.get("idle_pixels_minimum", gray_pixels_treshold)
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        # Tight ROI centered on the Idle Disconnect dialog body, so we don't
        # pick up dark gameplay pixels outside the box. V range is wide enough
        # to cover both LDPlayer (bright overlay, V~82) and MuMu (dark overlay, V~28).
        x_start, x_end = int(700 * wr), int(1220 * wr)
        y_start, y_end = int(470 * hr), int(620 * hr)
        gray_pixels = count_hsv_pixels(frame[y_start:y_end, x_start:x_end], (0, 0, 18), (10, 20, 100))
        if debug_enabled: print(f"gray pixels (if > {gray_pixels_threshold} then bot will try to unidle) :", gray_pixels)
        if gray_pixels > gray_pixels_threshold:
            self.window_controller.click(int(535 * wr), int(615 * hr))

    def select_brawler(self, brawler):
        self.window_controller.screenshot()
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        general_config = load_toml_as_dict("cfg/general_config.toml")
        debug_enabled = str(general_config.get("super_debug", "no")).lower() in ("yes", "true", "1")
        try:
            ocr_scale = float(general_config.get("ocr_scale_down_factor", 0.65))
        except (TypeError, ValueError):
            ocr_scale = 0.65
        ocr_scale = max(0.35, min(1.0, ocr_scale))
        # Right-side OCR crop. The old hard-coded 0.78 was tuned for an older
        # client where a giant "currently selected brawler" preview occupied
        # the right ~22% of the screen. Modern Brawl Stars + LDPlayer 9 at
        # 1920x1080 has no preview pane: the third grid column starts at
        # x ≈ 1500-1700, so 0.78 cuts the right column off entirely (Tick,
        # Jacky, Crow, etc. become invisible to OCR -> ValueError after 22
        # scroll attempts -> bot crash). Configurable via
        # general_config.toml::lobby_ocr_right_crop, default 0.97 keeps the
        # safety margin small enough to filter the rightmost UI furniture
        # while preserving the third brawler column.
        try:
            right_crop = float(general_config.get("lobby_ocr_right_crop", 0.97))
        except (TypeError, ValueError):
            right_crop = 0.97
        right_crop = max(0.5, min(1.0, right_crop))
        target_key = self.normalize_ocr_name(brawler)

        try:
            known_keys = [self.normalize_ocr_name(k) for k in (load_brawlers_info() or {}).keys()]
        except Exception:
            known_keys = []
        if target_key and target_key not in known_keys:
            known_keys.append(target_key)

        bx, by = self.coords_cfg['lobby']['brawler_btn']
        self.window_controller.click(bx * wr, by * hr)
        time.sleep(1.0)

        # Anchor the grid order with "Least Trophies": the dropdown coords are
        # the same ones select_lowest_trophy_brawler uses, so any drift would
        # already break Push All. Sorting also avoids matching the big
        # currently-selected brawler label that sits in the right-hand panel.
        self.window_controller.click(int(1210 * wr), int(45 * hr))
        time.sleep(0.45)
        self.window_controller.click(int(1210 * wr), int(426 * hr))
        time.sleep(0.9)

        # Reset the scroll position to the top of the sorted grid.
        for _ in range(3):
            self.window_controller.swipe(int(1700 * wr), int(350 * hr),
                                         int(1700 * wr), int(900 * hr), duration=0.4)
            time.sleep(0.15)

        found_brawler = False
        for attempt in range(22):
            screenshot_full = self.window_controller.screenshot()
            h, w = screenshot_full.shape[:2]
            # See lobby_ocr_right_crop comment up top for why this is configurable.
            gx2 = max(int(w * right_crop), 1)
            crop = screenshot_full[:, :gx2]
            small = cv2.resize(
                crop,
                (max(1, int(crop.shape[1] * ocr_scale)),
                 max(1, int(crop.shape[0] * ocr_scale))),
                interpolation=cv2.INTER_AREA,
            )
            if debug_enabled: print(f"select_brawler attempt {attempt}: running OCR on grid crop...")
            results = extract_text_and_positions(small)
            if debug_enabled:
                print(f"OCR detected on attempt {attempt}: {list(results.keys())}")

            match_box = None
            match_label = None
            for raw_name, box in results.items():
                cleaned = self.resolve_ocr_typos(self.normalize_ocr_name(raw_name))
                canonical = self._canonical_brawler(cleaned, known_keys)
                if canonical == target_key:
                    match_box = box
                    match_label = raw_name
                    break
            if match_box is not None:
                cx_small, cy_small = match_box['center']
                click_x = int(cx_small / ocr_scale)
                click_y = int(cy_small / ocr_scale)
                click_y = max(0, min(screenshot_full.shape[0] - 1, click_y))
                self.window_controller.click(click_x, click_y)
                print(f"Found brawler '{brawler}' (OCR: '{match_label}') tapping ({click_x}, {click_y}).")
                time.sleep(0.7)
                sx, sy = self.coords_cfg['lobby']['select_btn']
                self.window_controller.click(sx, sy, already_include_ratio=False)
                time.sleep(0.5)
                print(f"Selected brawler '{brawler}'")
                found_brawler = True
                break

            self.window_controller.swipe(int(1700 * wr), int(900 * hr),
                                         int(1700 * wr), int(550 * hr), duration=0.45)
            time.sleep(0.3)

        if not found_brawler:
            print(f"WARNING: Brawler '{brawler}' was not found after 22 scroll attempts. "
                  f"The bot will continue with the currently selected brawler.")
            raise ValueError(f"Brawler '{brawler}' could not be found in the brawler selection menu.")

    @classmethod
    def _canonical_brawler(cls, ocr_name, known_keys):
        """Return the known-brawler key that best matches an OCR-detected string,
        or None when nothing crosses the match threshold. Canonicalising via the
        full known list (not just the requested target) lets misreads like
        ``shey`` → ``shelly`` or ``[eon`` → ``leon`` resolve before we compare
        against the target, which is where the old target-only matcher missed."""
        if not ocr_name or not known_keys:
            return None
        if ocr_name in known_keys:
            return ocr_name
        best = None
        best_score = 0.0
        for cand in known_keys:
            if not cls.names_match(ocr_name, cand):
                continue
            score = cls.name_match_score(ocr_name, cand)
            if score > best_score:
                best_score = score
                best = cand
        return best

    def select_lowest_trophy_brawler(self):
        # Force a screenshot first so window_controller.width_ratio /
        # height_ratio get populated. Without this the ``int(x * wr)`` math
        # below blows up with a ``TypeError: int * NoneType`` when called as
        # the very first lobby action of a fresh bot run — which is exactly
        # what Push All does (selection_method='lowest_trophies' on the head
        # entry routes through Main.__init__ -> here directly, never having
        # touched select_brawler that does the same screenshot priming).
        self.window_controller.screenshot()
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio

        def tap(x, y, wait=0.6):
            self.window_controller.click(int(x * wr), int(y * hr))
            time.sleep(wait)

        print("Selecting next brawler by sorting lowest trophies.")
        tap(128, 500, 1.4)   # left Brawlers button in lobby
        tap(1210, 45, 0.6)   # sort dropdown
        tap(1210, 426, 1.0)  # Least Trophies
        tap(422, 359, 1.0)   # first brawler card after sorting
        tap(260, 991, 1.0)   # Select

    @staticmethod
    def resolve_ocr_typos(potential_brawler_name: str) -> str:
        """
        Matches well known 'typos' from OCR to the correct brawler's name
        or returns the original string
        """

        matched_typo: str | None = {
            'shey': BrawlerName.Shelly.value,
            'shlly': BrawlerName.Shelly.value,
            'larryslawrie': BrawlerName.Larry.value,
            '[eon': BrawlerName.Leon.value,
        }.get(potential_brawler_name, None)

        return matched_typo or potential_brawler_name

    @staticmethod
    def normalize_ocr_name(value: str) -> str:
        normalized = str(value).lower()
        for symbol in [' ', '-', '.', "&", "'", "`", "_"]:
            normalized = normalized.replace(symbol, "")
        return normalized

    @staticmethod
    def bounded_edit_distance(left: str, right: str, limit: int) -> int:
        if abs(len(left) - len(right)) > limit:
            return limit + 1
        previous = list(range(len(right) + 1))
        for i, left_char in enumerate(left, 1):
            current = [i]
            best = current[0]
            for j, right_char in enumerate(right, 1):
                cost = 0 if left_char == right_char else 1
                value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
                current.append(value)
                best = min(best, value)
            if best > limit:
                return limit + 1
            previous = current
        return previous[-1]

    @classmethod
    def names_match(cls, detected_name: str, target_name: str) -> bool:
        if detected_name == target_name:
            return True
        # Substring rule: require the *shorter* side to be at least 3 chars so
        # an OCR fragment like "l" or "bo" doesn't match every brawler whose
        # name happens to contain that letter ("bull", "bo[nnie]", etc.).
        # ALSO require the lengths to be within ~1.5x of each other — without
        # this, short brawler names get spuriously matched inside long UI
        # noise tokens. Real-screenshot regression: "available on the"
        # (14 chars) contains the substring "leon" (positions 7-10 of
        # "ab|leon|the"), and the bot would happily click that locked-card
        # caption thinking it was the LEON brawler tile. Length-ratio gate
        # rejects 14/4 = 3.5 > 1.5; keeps legitimate near-misses like
        # "darry" -> "darryl" (5/6 = 1.2) intact.
        if (len(target_name) >= 4
                and len(detected_name) >= 3
                and (target_name in detected_name or detected_name in target_name)):
            longer = max(len(target_name), len(detected_name))
            shorter = min(len(target_name), len(detected_name))
            if longer <= shorter * 1.5:
                return True
        # Edit-distance fallback also gates by minimum detected length so that
        # 1- or 2-character OCR junk can't masquerade as a near-match.
        if len(detected_name) < 3:
            return False
        limit = 1 if len(target_name) <= 5 else 2
        if cls.bounded_edit_distance(detected_name, target_name, limit) <= limit:
            return True
        return SequenceMatcher(None, detected_name, target_name).ratio() >= 0.84

    @classmethod
    def name_match_score(cls, detected_name: str, target_name: str) -> float:
        if detected_name == target_name:
            return 2.0
        ratio = SequenceMatcher(None, detected_name, target_name).ratio()
        distance = cls.bounded_edit_distance(detected_name, target_name, 3)
        return ratio - (distance * 0.05)
