"""Run the same OCR -> normalize -> canonical pipeline that
``LobbyAutomation.select_brawler`` uses, but offline against pre-captured
screenshots. Reveals OCR misses without needing a live emulator.

For each screenshot:
  * OCR with the same scale-down factor (cfg/general_config.toml :
    ocr_scale_down_factor, default 0.65) and grid-only crop (left 78% of
    width — same crop as production).
  * Print every detected token, its normalized form, the canonical brawler
    key the matcher resolved (or '-' for none), and bbox center.
  * Then test target='colt' lookup specifically for the dnplayer_ap8mddQGqt
    screenshot (the one COLT is visible in).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
from utils import extract_text_and_positions, load_brawlers_info
from lobby_automation import LobbyAutomation

SHOTS_DIR = ROOT / "LobbyBrawlerTets"
OCR_SCALE = 0.65

known_keys = [LobbyAutomation.normalize_ocr_name(k) for k in (load_brawlers_info() or {}).keys()]
print(f"loaded {len(known_keys)} known brawler keys")
print()


def _grid_crop(img):
    h, w = img.shape[:2]
    gx2 = max(int(w * 0.78), 1)
    return img[:, :gx2]


def _process(path: Path, target: str | None = None):
    img = cv2.imread(str(path))
    if img is None:
        print(f"[{path.name}] could not read")
        return
    crop = _grid_crop(img)
    small = cv2.resize(crop,
                       (max(1, int(crop.shape[1] * OCR_SCALE)),
                        max(1, int(crop.shape[0] * OCR_SCALE))),
                       interpolation=cv2.INTER_AREA)
    results = extract_text_and_positions(small)
    print(f"--- {path.name} (crop {crop.shape[1]}x{crop.shape[0]} -> {small.shape[1]}x{small.shape[0]}) ---")
    print(f"OCR token count: {len(results)}")
    canonical_hits = {}
    for raw, box in results.items():
        cleaned = LobbyAutomation.resolve_ocr_typos(LobbyAutomation.normalize_ocr_name(raw))
        canon = LobbyAutomation._canonical_brawler(cleaned, known_keys)
        cx, cy = box.get('center', (None, None))
        marker = f" -> {canon}" if canon else ""
        print(f"  '{raw}'  norm='{cleaned}'  center=({cx},{cy}){marker}")
        if canon:
            canonical_hits.setdefault(canon, []).append((raw, cx, cy))
    if target:
        target_key = LobbyAutomation.normalize_ocr_name(target)
        hit = canonical_hits.get(target_key)
        verdict = "FOUND" if hit else "MISSED"
        print(f"  >>> target='{target}' -> {verdict}: {hit}")
    print()
    return canonical_hits


# 1) Walk all screenshots
shots = sorted(SHOTS_DIR.glob("*"))
all_hits = {}
for s in shots:
    if s.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        continue
    hits = _process(s)
    if hits:
        all_hits[s.name] = hits

# 2) Specifically test 'colt' lookup on the screenshot we know contains it
colt_shot = SHOTS_DIR / "dnplayer_ap8mddQGqt.png"
print("=" * 60)
print("Specific colt lookup:")
_process(colt_shot, target="colt")

# 3) Cross-screenshot summary: which brawlers got recognized somewhere?
print("=" * 60)
print("Cross-shot canonical recognition summary:")
seen = set()
for shot, hits in all_hits.items():
    for canon in hits:
        seen.add(canon)
print(f"  recognized {len(seen)} distinct brawler keys across {len(all_hits)} screenshots")
print(f"  recognized: {sorted(seen)}")
