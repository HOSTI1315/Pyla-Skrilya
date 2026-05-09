"""Run the production LobbyAutomation OCR pipeline against a single live
screenshot from a chosen LDPlayer instance via ADB. Read-only — never clicks
the emulator, never starts a bot. Perfect for verifying detection / matcher
without burning a real match.

Usage::

    python tools/smoke_live_detect.py --serial emulator-5554
    python tools/smoke_live_detect.py --serial emulator-5556 --target colt
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2

from utils import extract_text_and_positions, load_brawlers_info
from lobby_automation import LobbyAutomation

ADB_CANDIDATES = [
    ROOT / "adb.exe",
    Path("D:/LDPlayer/LDPlayer9/adb.exe"),
    Path("C:/Program Files/Android/platform-tools/adb.exe"),
]


def find_adb() -> str:
    for cand in ADB_CANDIDATES:
        if Path(cand).is_file():
            return str(cand)
    return "adb"


def grab(serial: str) -> bytes:
    adb = find_adb()
    res = subprocess.run([adb, "-s", serial, "exec-out", "screencap", "-p"],
                         capture_output=True, timeout=10)
    if res.returncode != 0:
        raise RuntimeError(f"adb screencap failed: {res.stderr.decode(errors='replace')}")
    return res.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default="emulator-5554",
                    help="adb device id (emulator-5554 = LDPlayer #0)")
    ap.add_argument("--target", default=None,
                    help="optional brawler name to look up (mimics Push All target)")
    ap.add_argument("--scale", type=float, default=0.65,
                    help="ocr_scale_down_factor (matches general_config.toml default)")
    ap.add_argument("--right-crop", type=float, default=0.97,
                    help="lobby_ocr_right_crop, fraction of width to keep (default 0.97 — modern client has no right preview pane)")
    ap.add_argument("--save", default=None, help="optional path to save the captured PNG")
    args = ap.parse_args()

    print(f"-- ADB grab from {args.serial} --")
    png_bytes = grab(args.serial)
    tmp = Path(tempfile.gettempdir()) / f"_live_{int(time.time())}.png"
    tmp.write_bytes(png_bytes)
    if args.save:
        Path(args.save).write_bytes(png_bytes)
        print(f"   saved -> {args.save}")
    img = cv2.imread(str(tmp))
    h, w = img.shape[:2]
    print(f"   image {w}x{h}, {len(png_bytes)//1024}KB")

    # Same crop production uses (configurable via lobby_ocr_right_crop)
    gx2 = max(int(w * args.right_crop), 1)
    crop = img[:, :gx2]
    small = cv2.resize(crop,
                       (max(1, int(crop.shape[1] * args.scale)),
                        max(1, int(crop.shape[0] * args.scale))),
                       interpolation=cv2.INTER_AREA)
    print(f"   crop {crop.shape[1]}x{crop.shape[0]} -> ocr {small.shape[1]}x{small.shape[0]}")

    known_keys = [LobbyAutomation.normalize_ocr_name(k)
                  for k in (load_brawlers_info() or {}).keys()]

    print("\n-- OCR pass --")
    t0 = time.time()
    results = extract_text_and_positions(small)
    dt = time.time() - t0
    print(f"  {len(results)} tokens in {dt:.1f}s")

    canonical_hits = {}
    print("\n-- Token resolution --")
    for raw, box in results.items():
        cleaned = LobbyAutomation.resolve_ocr_typos(LobbyAutomation.normalize_ocr_name(raw))
        canon = LobbyAutomation._canonical_brawler(cleaned, known_keys)
        cx, cy = box.get("center", (None, None))
        # Map back to real (un-scaled) click coords like select_brawler does.
        click_x = int(cx / args.scale) if cx is not None else None
        click_y = int(cy / args.scale) if cy is not None else None
        marker = f" -> {canon}" if canon else ""
        print(f"  '{raw}'  norm='{cleaned}'  click=({click_x},{click_y}){marker}")
        if canon:
            canonical_hits.setdefault(canon, []).append((raw, click_x, click_y))

    print(f"\n-- Recognized brawlers ({len(canonical_hits)}) --")
    for canon, hits in sorted(canonical_hits.items()):
        print(f"  {canon}: {hits}")

    if args.target:
        target_key = LobbyAutomation.normalize_ocr_name(args.target)
        hit = canonical_hits.get(target_key)
        verdict = "FOUND" if hit else "NOT FOUND on this frame"
        print(f"\n-- Target lookup: '{args.target}' -> {verdict} --")
        if hit:
            print(f"   would click at: {hit[0][1]},{hit[0][2]}")


if __name__ == "__main__":
    main()
