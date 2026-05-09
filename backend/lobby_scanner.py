"""One-shot OCR reader for the brawler-selection grid.

The bot's `WindowController` is heavyweight (boots ADB + scrcpy, ~3-5s),
so this module keeps a single instance alive across calls and rebuilds
it only if the device disconnects. The bot owns its own WC while
running, so scanning is refused during an active session to avoid racing
on the shared frame queue.

OCR pipeline mirrors what `lobby_automation.select_brawler` already
proved works: resize the frame to 65% (compact glyphs read cleaner),
strip spaces/dashes/dots, lowercase. Brawler names are matched against
`brawlers_info.json` keys via difflib so OCR typos like "DYNANIKE" still
hit "dynamike".
"""

from __future__ import annotations

import difflib
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2


class _ScanError(Exception):
    pass


# Highest plausible per-brawler trophy count. Real top-tier brawlers can sit
# above 3000, so the cap is set generously — above this is almost certainly
# OCR concatenating two adjacent numbers (e.g. rank+trophy bleed) or pulling
# digits from a neighbouring tile. Values above this get treated as "no read"
# so they neither persist nor display.
MAX_TROPHIES_SANITY = 5400


# OCR variants of the "BRAWLERS TO BE UNLOCKED" header that marks the end
# of the unlocked section. Paging past it is pointless — the target brawler
# can't be below this line if it isn't already in our unlocked set.
_LOCKED_SECTION_KEYWORDS = frozenset({
    "tobeunlocked", "brawlerstobeunlocked", "tobkunlocked",
    "tobeunlockea", "brawlerstobe", "tobeunlock", "beunlocked",
    "availableonthe", "starrroad", "availableon",
})


# Hardcoded OCR → canonical brawler key. EasyOCR consistently confuses a few
# glyph pairs (I/1/l, O/0, r/n, c/e) on the compact grid font. These misreads
# land just below the fuzzy-ratio cutoff, so catching them explicitly is the
# cheapest accuracy boost available. Lifted from NorphyOG's
# lobby_automation.resolve_ocr_typos.
_OCR_TYPO_MAP = {
    # Shelly
    "shey": "shelly", "shlly": "shelly",
    # Larry & Lawrie (twin brawler, OCR splits name with symbols)
    "larryslawrie": "larry", "larry8lawrie": "larry",
    "larry6lawrie": "larry", "larryelawrie": "larry",
    "larryalawrie": "larry", "larrydlawrie": "larry",
    "larry": "larry", "lawrie": "larry",
    # Meeple
    "meepie": "meeple", "meeplo": "meeple", "meepla": "meeple",
    "meepl": "meeple", "meple": "meeple", "meople": "meeple",
    "meep1e": "meeple",
    # El Primo (leading E/I confusion)
    "eprimo": "elprimo", "eiprimo": "elprimo",
    "eiprmio": "elprimo", "eilprimo": "elprimo",
    # Colt / Bull short-name misreads
    "coif": "colt", "buli": "bull",
    # Rico (l/1/0/q/r confusion on short name)
    "rlco": "rico", "rco": "rico", "rieo": "rico", "ric0": "rico",
    "ricq": "rico", "r1co": "rico", "rlc0": "rico",
}


class LobbyScanner:
    """Lazy WindowController + brawler-grid OCR."""

    IDLE_TTL_SEC = 120.0
    OCR_RESIZE = 0.65
    NAME_MATCH_RATIO = 0.72  # difflib SequenceMatcher cutoff

    def __init__(self) -> None:
        self._wc = None
        self._lock = threading.Lock()
        self._last_use = 0.0

    def _ensure_wc(self):
        from window_controller import WindowController  # heavy import

        if self._wc is not None and (time.time() - self._last_use) > self.IDLE_TTL_SEC:
            self._close_wc()
        if self._wc is None:
            self._wc = WindowController()
        return self._wc

    def _close_wc(self) -> None:
        try:
            if self._wc is not None:
                self._wc.close()
        except Exception:
            pass
        self._wc = None

    def shutdown(self) -> None:
        with self._lock:
            self._close_wc()

    # ------------------------------------------------------------------
    def _ocr_current_frame(self, known_lower):
        from utils import reader

        with self._lock:
            wc = self._ensure_wc()
            try:
                frame = wc.screenshot()
            except Exception as exc:
                self._close_wc()
                raise _ScanError(f"screenshot failed: {exc}") from exc
            self._last_use = time.time()

        small = cv2.resize(
            frame,
            (int(frame.shape[1] * self.OCR_RESIZE), int(frame.shape[0] * self.OCR_RESIZE)),
            interpolation=cv2.INTER_AREA,
        )
        try:
            results = reader.readtext(small)
        except Exception as exc:
            raise _ScanError(f"OCR failed: {exc}") from exc

        name_boxes, number_boxes, raw_text = _classify(results)
        tiles = _pair_tiles(name_boxes, number_boxes, known_lower, self.NAME_MATCH_RATIO)
        return frame, tiles, raw_text

    def _swipe_grid(self, direction: str, count: int = 1, duration: float = 0.6) -> None:
        with self._lock:
            wc = self._ensure_wc()
            wr = wc.width_ratio
            hr = wc.height_ratio
        for _ in range(count):
            try:
                if direction == "up":
                    wc.swipe(int(1700 * wr), int(900 * hr),
                             int(1700 * wr), int(650 * hr), duration=duration)
                else:
                    wc.swipe(int(1700 * wr), int(350 * hr),
                             int(1700 * wr), int(900 * hr), duration=duration)
                time.sleep(0.3)
            except Exception:
                pass

    def scan(self, target_brawler: Optional[str] = None) -> Dict[str, Any]:
        from utils import load_brawlers_info
        from stage_manager import StageManager

        try:
            known = list((load_brawlers_info() or {}).keys())
        except Exception:
            known = []
        known_lower = [k.lower() for k in known]

        frame, tiles, raw_text = self._ocr_current_frame(known_lower)

        match = None
        if target_brawler:
            match = _resolve_match(tiles, target_brawler, self.NAME_MATCH_RATIO)
            # Target wasn't on the visible page — page through the whole grid.
            # Reset to top, then swipe up one row at a time, OCRing each frame
            # until the target tile shows up (or we run out of pages).
            if not match:
                self._swipe_grid("down", count=5, duration=0.5)
                stall = 0
                for _ in range(20):
                    frame, tiles, raw_text = self._ocr_current_frame(known_lower)
                    match = _resolve_match(tiles, target_brawler, self.NAME_MATCH_RATIO)
                    if match:
                        break
                    # Hit the "BRAWLERS TO BE UNLOCKED" header → target isn't
                    # in the unlocked section. Stop paging; don't waste 20
                    # swipes through the locked grid.
                    if _is_locked_section(raw_text):
                        break
                    seen = sum(1 for t in tiles if t.get("matched_known"))
                    if seen == 0:
                        stall += 1
                        if stall >= 3:
                            break
                    else:
                        stall = 0
                    self._swipe_grid("up", count=1, duration=0.7)
            if match:
                m = dict(match)
                if m.get("trophies_raw") is not None:
                    v = StageManager.validate_trophies(str(m["trophies_raw"]))
                    m["trophies"] = v if v is not False else None
                if m.get("streak_raw") is not None:
                    v = StageManager.validate_trophies(str(m["streak_raw"]))
                    m["streak"] = v if v is not False else None
                # Streak digits sit in a small font near the flame icon and
                # often get lost in the 65% OCR pass. Do a focused full-res
                # OCR of the streak zone (with a 2× upscale) to recover them.
                if m.get("trophies") is not None and m.get("streak") in (None, 0):
                    try:
                        rescued = _rescue_streak(frame, m, self.OCR_RESIZE)
                        if rescued is not None:
                            tval = m.get("trophies") or 0
                            if 0 < rescued <= 200 and (tval == 0 or rescued <= tval):
                                m["streak"] = rescued
                                m["streak_raw"] = str(rescued)
                                m["streak_source"] = "fullres-rescue"
                    except Exception:
                        pass
                match = m

        return {
            "tiles": tiles,
            "match": match,
            "raw_text": raw_text,
            "frame_size": [int(frame.shape[1]), int(frame.shape[0])],
        }


# ──────────────────────────────────────────────────────────────────────
# OCR post-processing
# ──────────────────────────────────────────────────────────────────────
def _bbox_center(bbox) -> Tuple[float, float]:
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return (sum(xs) / 4.0, sum(ys) / 4.0)


def _bbox_top(bbox) -> float:
    return min(p[1] for p in bbox)


def _clean_name(text: str) -> str:
    out = text.lower()
    for ch in [" ", "-", ".", "&", "_", "'", "!", "*"]:
        out = out.replace(ch, "")
    # Known OCR misreads → canonical key before fuzzy matching runs.
    return _OCR_TYPO_MAP.get(out, out)


def _is_locked_section(raw_text: List[str]) -> bool:
    """True if the OCR output contains the locked-section header."""
    if not raw_text:
        return False
    combined = "".join(_clean_name(t) for t in raw_text)
    return any(kw in combined for kw in _LOCKED_SECTION_KEYWORDS)


def _classify(results) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    name_boxes: List[Dict[str, Any]] = []
    number_boxes: List[Dict[str, Any]] = []
    raw_text: List[str] = []
    for item in results:
        bbox, text, conf = item
        clean = (text or "").strip()
        if not clean:
            continue
        raw_text.append(clean)
        cx, cy = _bbox_center(bbox)
        top = _bbox_top(bbox)
        digits = "".join(c for c in clean if c.isdigit())
        letters = "".join(c for c in clean if c.isalpha())
        # If the token is predominantly digits (e.g. "S496" where 'S' is a
        # mis-OCR'd '5'), recover the number by substituting the usual glyph
        # confusions. Guard with `digits >= letters` to avoid treating
        # brawler names like "NANI" or "COLT" as numbers.
        if digits and letters and len(digits) >= len(letters) and conf >= 0.15:
            subs = clean.replace("O", "0").replace("o", "0")
            subs = subs.replace("l", "1").replace("I", "1")
            subs = subs.replace("S", "5").replace("s", "5")
            subs = subs.replace("B", "8").replace("b", "6")
            sub_digits = "".join(c for c in subs if c.isdigit())
            if sub_digits and sub_digits != digits:
                digits = sub_digits
                letters = ""  # reclassify as pure-number below
        if digits and not letters:
            number_boxes.append({"text": digits, "cx": cx, "cy": cy, "top": top, "conf": conf})
            # Rank-badge concat: OCR sometimes glues the rank digit onto the
            # trophy number (e.g. rank 2 + 217 trophies → "2217"). Emit the
            # suffix as an *alternate* candidate at the same coords; pairing
            # later prefers 3-digit trophies when both are equally close.
            if len(digits) >= 4 and digits[0] in "123456789":
                try:
                    full = int(digits)
                except ValueError:
                    full = 0
                if full >= 1000:
                    suffix = digits[1:].lstrip("0") or "0"
                    try:
                        s_val = int(suffix)
                    except ValueError:
                        s_val = -1
                    if 10 <= s_val <= 999:
                        number_boxes.append({
                            "text": suffix, "cx": cx, "cy": cy, "top": top,
                            "conf": conf, "alt_of_concat": True,
                        })
        elif letters and len(letters) >= 2:
            name_boxes.append({
                "raw": clean,
                "key": _clean_name(letters),
                "cx": cx, "cy": cy, "top": top, "conf": conf,
            })
    return name_boxes, number_boxes, raw_text


def _cutoff_for(name_key: str, base_cutoff: float) -> float:
    """Tighten the fuzzy cutoff for short names, loosen it for long ones.

    Short brawlers (BULL/POCO/8BIT) only have 3–4 characters; a 0.72 cutoff
    accepts any 1-char edit as a match — way too permissive. Long names
    (DYNAMIKE/JACKY/CARL) can absorb a typo or two without ambiguity.
    """
    n = len(name_key)
    if n <= 4:
        return max(base_cutoff, 0.80)
    if n >= 7:
        return min(base_cutoff, 0.65)
    return base_cutoff


def _best_known(name_key: str, known_lower: List[str], cutoff: float) -> Optional[str]:
    if not known_lower:
        return None
    if name_key in known_lower:
        return name_key
    # Substring hit first: if OCR appended garbage ("BUZZLT", "SHELLYB") or
    # chopped the name ("DYNA" for DYNAMIKE), catch it without fuzzy math.
    # Only trust substring for ≥3-char candidates to avoid 'LT' → 'COLT'.
    if len(name_key) >= 3:
        for cand in known_lower:
            if name_key in cand or (len(cand) >= 3 and cand in name_key):
                return cand
    effective_cutoff = _cutoff_for(name_key, cutoff)
    matches = difflib.get_close_matches(name_key, known_lower, n=1, cutoff=effective_cutoff)
    return matches[0] if matches else None


def _pair_tiles(
    name_boxes: List[Dict[str, Any]],
    number_boxes: List[Dict[str, Any]],
    known_lower: List[str],
    cutoff: float,
) -> List[Dict[str, Any]]:
    tiles: List[Dict[str, Any]] = []
    used_numbers = set()
    for nb in name_boxes:
        canonical = _best_known(nb["key"], known_lower, cutoff)
        cands = []
        for i, num in enumerate(number_boxes):
            if i in used_numbers:
                continue
            if num["cy"] >= nb["top"]:
                continue
            dx = num["cx"] - nb["cx"]
            dy = nb["top"] - num["cy"]
            # 65% downscaled coords → tile is roughly 390×220px;
            # trophy badge is centred ~80-160px above the name.
            # dy capped at 200 so cropped neighbour-tile trophies above the
            # first row (e.g. "5496"/"7104"/"2614" floating well above any
            # name) can't leak into this tile's pairing.
            if abs(dx) > 220 or dy > 200:
                continue
            cands.append((abs(dx), dy, i, num))
        # Prefer candidates that look like trophy counts over candidates that
        # look like rank+trophy concatenations: 3-digit values sort ahead of
        # 4+ digit siblings at similar distance. This lets the suffix emitted
        # by `_classify` win when it's a likelier trophy.
        def _trophy_score(c):
            dxv, dyv, _idx, numv = c
            txt = numv.get("text") or ""
            digit_penalty = 40 if len(txt) >= 4 else 0
            return (dxv + digit_penalty, dyv)
        cands.sort(key=_trophy_score)
        trophy = None
        streak_text: Optional[str] = None
        if cands:
            _, _, t_idx, t_num = cands[0]
            used_numbers.add(t_idx)
            trophy = t_num
            # Mark any sibling boxes at the same coords used too (the
            # rank-concat alternate, or the original if the alt won).
            for j, num in enumerate(number_boxes):
                if j == t_idx or j in used_numbers:
                    continue
                if abs(num["cx"] - t_num["cx"]) < 1 and abs(num["cy"] - t_num["cy"]) < 1:
                    used_numbers.add(j)
            # Streak floats outside the trophy badge: just to the right, at
            # roughly the same Y. EasyOCR likes to split "15" into "1" + "5",
            # so collect every digit-box in the streak zone and concat by X.
            # Bounds (in 65%-downscaled px): 30 < dx < 230, |dy| <= 40 — wide
            # enough to catch a split number but tight enough to reject the
            # neighbouring tile's trophy badge (~400px away).
            streak_parts = []
            for _, _, i, num in cands[1:]:
                if i in used_numbers:
                    continue
                dx_n = num["cx"] - trophy["cx"]
                if 30 < dx_n < 230 and abs(num["cy"] - trophy["cy"]) <= 40:
                    streak_parts.append((num["cx"], num["text"], i))
            streak_parts.sort(key=lambda p: p[0])
            for _, _, i in streak_parts:
                used_numbers.add(i)
            if streak_parts:
                streak_text = "".join(p[1] for p in streak_parts)
            # Sanity: streak has to be a small positive int, can't exceed the
            # brawler's own trophies. Anything else is a misread (e.g. the
            # adjacent tile's trophy bled into our zone).
            if streak_text:
                try:
                    sval = int(streak_text)
                    tval = int(trophy["text"]) if trophy["text"].isdigit() else None
                    if sval <= 0 or sval > 200 or (tval is not None and sval > tval):
                        streak_text = None
                except ValueError:
                    streak_text = None
        tiles.append({
            "name": canonical.upper() if canonical else nb["raw"].upper(),
            "key": canonical or nb["key"],
            "matched_known": canonical is not None,
            "ocr_raw": nb["raw"],
            "trophies_raw": trophy["text"] if trophy else None,
            "streak_raw":   streak_text,
            # downscaled (65%) coords used by the rescue pass to project a
            # crop region onto the original full-resolution frame.
            "_trophy_cx_65": trophy["cx"] if trophy else None,
            "_trophy_cy_65": trophy["cy"] if trophy else None,
        })
    return tiles


def _rescue_streak(frame, match: Dict[str, Any], ocr_resize: float) -> Optional[int]:
    """Re-OCR the small streak number at full resolution.

    The trophy badge centre is known in 65%-downscaled coords; map it back
    to the original frame, crop a strip just to the right of the badge,
    upscale 2×, and ask EasyOCR for digits. Returns an int or None.
    """
    from utils import reader

    cx_65 = match.get("_trophy_cx_65")
    cy_65 = match.get("_trophy_cy_65")
    if cx_65 is None or cy_65 is None:
        return None
    inv = 1.0 / ocr_resize
    h, w = frame.shape[:2]
    cx = int(cx_65 * inv)
    cy = int(cy_65 * inv)
    # Streak floats outside the trophy badge: just to the right, slightly
    # above the badge centre. In 1920×1080-equiv coords:
    #   ~50px right of badge centre … ~360px right
    #   ~80px above centre … ~80px below
    x1 = max(0, cx + 30)
    x2 = min(w, cx + 360)
    y1 = max(0, cy - 90)
    y2 = min(h, cy + 90)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    crop = cv2.resize(crop, (crop.shape[1] * 2, crop.shape[0] * 2), interpolation=cv2.INTER_CUBIC)
    # The DefaultEasyOCR wrapper drops kwargs; reach the underlying Reader
    # so we can constrain detection to digits only — big accuracy boost on
    # tiny "15" / "6" badges that easily get misread as letters otherwise.
    try:
        results = reader.reader.readtext(crop, allowlist="0123456789")
    except Exception:
        results = reader.readtext(crop)
    parts = []
    for bbox, text, _conf in results:
        digits = "".join(c for c in (text or "") if c.isdigit())
        if not digits:
            continue
        cx_p, _ = _bbox_center(bbox)
        parts.append((cx_p, digits))
    if not parts:
        return None
    parts.sort(key=lambda p: p[0])
    joined = "".join(p[1] for p in parts)
    try:
        return int(joined) if joined else None
    except ValueError:
        return None


def _resolve_match(
    tiles: List[Dict[str, Any]],
    target_brawler: str,
    cutoff: float,
) -> Optional[Dict[str, Any]]:
    target_key = _clean_name(target_brawler)
    # Prefer exact key hit
    for t in tiles:
        if t.get("key") == target_key:
            return t
    # Substring hit (handles OCR over-reads like "BUzZ LT" or "8BITO") before
    # fuzzy matching — if the canonical name is fully contained in the OCR
    # token (or vice versa for ≥3-char names), that's a cleaner signal than
    # SequenceMatcher ratio.
    if len(target_key) >= 3:
        for t in tiles:
            k = t.get("key") or ""
            if not k:
                continue
            if target_key in k or (len(k) >= 3 and k in target_key):
                return t
    # Fall back to fuzzy across whatever OCR coughed up
    keys = [t["key"] for t in tiles]
    effective_cutoff = _cutoff_for(target_key, cutoff)
    closest = difflib.get_close_matches(target_key, keys, n=1, cutoff=effective_cutoff)
    if not closest:
        return None
    return next((t for t in tiles if t["key"] == closest[0]), None)


def _scan_all(
    self,
    max_iters: int = 80,
    stall_rounds: int = 3,
    progress_cb=None,
) -> Dict[str, Dict[str, Any]]:
    """Swipe through the brawler-selection grid and OCR every tile."""
    from utils import reader, load_brawlers_info
    from stage_manager import StageManager

    try:
        known = list((load_brawlers_info() or {}).keys())
    except Exception:
        known = []
    known_lower = [k.lower() for k in known]

    def _report(phase: str, **extra: Any) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb({"phase": phase, **extra})
        except Exception:
            pass

    with self._lock:
        wc = self._ensure_wc()
        # WindowController populates width_ratio/height_ratio inside screenshot()
        # after the first frame arrives, so prime it before reading the ratios —
        # otherwise wr/hr are None and the swipe math blows up with
        # "unsupported operand type(s) for *: 'int' and 'NoneType'".
        try:
            wc.screenshot()
        except Exception as exc:
            self._close_wc()
            raise _ScanError(f"initial screenshot failed: {exc}") from exc
        wr = wc.width_ratio
        hr = wc.height_ratio

        _report("reset")
        try:
            for _ in range(5):
                wc.swipe(int(1700 * wr), int(350 * hr),
                         int(1700 * wr), int(900 * hr), duration=0.5)
                time.sleep(0.25)
        except Exception as exc:
            self._close_wc()
            raise _ScanError(f"scroll reset failed: {exc}") from exc

        results: Dict[str, Dict[str, Any]] = {}
        stall = 0
        last_new_iter = 0
        iteration = 0
        for iteration in range(max_iters):
            try:
                frame = wc.screenshot()
            except Exception as exc:
                self._close_wc()
                raise _ScanError(f"screenshot failed: {exc}") from exc
            self._last_use = time.time()

            small = cv2.resize(
                frame,
                (int(frame.shape[1] * self.OCR_RESIZE),
                 int(frame.shape[0] * self.OCR_RESIZE)),
                interpolation=cv2.INTER_AREA,
            )
            try:
                ocr = reader.readtext(small)
            except Exception as exc:
                raise _ScanError(f"OCR failed: {exc}") from exc

            name_boxes, number_boxes, raw_text = _classify(ocr)
            tiles = _pair_tiles(name_boxes, number_boxes, known_lower, self.NAME_MATCH_RATIO)
            reached_locked = _is_locked_section(raw_text)

            new_this_round = 0
            for tile in tiles:
                if not tile.get("matched_known"):
                    continue
                key = tile["key"]
                traw = tile.get("trophies_raw")
                sraw = tile.get("streak_raw")
                tval = StageManager.validate_trophies(str(traw)) if traw else False
                sval = StageManager.validate_trophies(str(sraw)) if sraw else False
                tval = tval if tval is not False else None
                sval = sval if sval is not False else None
                # Reject impossible trophy reads instead of persisting them.
                if tval is not None and tval > MAX_TROPHIES_SANITY:
                    tval = None

                if tval is not None and (sval is None or sval == 0):
                    try:
                        rescued = _rescue_streak(
                            frame,
                            {**tile, "trophies": tval, "streak": sval},
                            self.OCR_RESIZE,
                        )
                        if rescued and 0 < rescued <= 200 and rescued <= tval:
                            sval = rescued
                    except Exception:
                        pass

                prev = results.get(key)
                if prev and prev.get("trophies") is not None and tval is None:
                    continue
                record = {
                    "trophies": tval,
                    "streak": sval or 0,
                    "scanned_at": time.time(),
                }
                if prev != record:
                    if key not in results:
                        new_this_round += 1
                    results[key] = record

            _report("page", iteration=iteration, total=len(results), new=new_this_round)
            if new_this_round > 0:
                stall = 0
                last_new_iter = iteration
            else:
                stall += 1
            if stall >= stall_rounds:
                break
            # Processed this page; if we've hit the locked-section header, stop.
            if reached_locked:
                _report("locked_section_reached", iteration=iteration)
                break

            try:
                wc.swipe(int(1700 * wr), int(900 * hr),
                         int(1700 * wr), int(650 * hr), duration=0.7)
                time.sleep(0.4)
            except Exception:
                pass

        _report("done", total=len(results), iterations=iteration + 1, last_new=last_new_iter)
        return results


LobbyScanner.scan_all = _scan_all
SCANNER = LobbyScanner()
