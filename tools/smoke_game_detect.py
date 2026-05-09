"""Run the production in-game detection stack against pre-captured screenshots
from TestScreenshot/Game/. No emulator / scrcpy / window_controller needed —
loads the ONNX models directly and calls the same HSV pixel-counters that
``Play.check_if_super_ready`` / gadget / hypercharge use.

For each frame, reports:
  * YOLO detections on mainInGameModel: count of enemy / teammate / player
    bounding boxes and their centers (so we can verify the bot would 'see'
    the training dummies as enemies)
  * Wall-detector classes on tileDetector: walls / bushes inside the frame
  * HSV pixel counts in each ability ROI (super yellow, gadget green,
    hypercharge purple) and the boolean ready/not-ready verdict the bot
    would compute, comparing against thresholds in cfg/bot_config.toml

Annotates each frame and writes to TestScreenshot/Game/_annotated/.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from utils import count_hsv_pixels, load_toml_as_dict
from detect import Detect

GAME_DIR = ROOT / "TestScreenshot" / "Game"
OUT_DIR = GAME_DIR / "_annotated"
OUT_DIR.mkdir(exist_ok=True)

BASE_W, BASE_H = 1920, 1080  # window_controller's brawl_stars_width / _height

bot = load_toml_as_dict("cfg/bot_config.toml")
lobby = load_toml_as_dict("cfg/lobby_config.toml")

SUPER_ROI = lobby["pixel_counter_crop_area"]["super"]
GADGET_ROI = lobby["pixel_counter_crop_area"]["gadget"]
HYPER_ROI = lobby["pixel_counter_crop_area"]["hypercharge"]

SUPER_MIN = bot["super_pixels_minimum"]
GADGET_MIN = bot["gadget_pixels_minimum"]
HYPER_MIN = bot["hypercharge_pixels_minimum"]

ENT_CONF = float(bot["entity_detection_confidence"])
WALL_CONF = float(bot["wall_detection_confidence"])
WALL_CLASSES = bot["wall_model_classes"]

# Same loader the bot uses
print("Loading mainInGameModel.onnx + tileDetector.onnx ...")
ent = Detect(str(ROOT / "models" / "mainInGameModel.onnx"),
             classes=["enemy", "teammate", "player"])
tile = Detect(str(ROOT / "models" / "tileDetector.onnx"), classes=WALL_CLASSES)
print("OK\n")


def scale_roi(roi, w, h):
    wr = w / BASE_W
    hr = h / BASE_H
    return [int(roi[0] * wr), int(roi[1] * hr),
            int(roi[2] * wr), int(roi[3] * hr)]


def super_roi_padded(roi, w, h):
    """Production check_if_super_ready pads ROI by 80*min(wr,hr) on each side."""
    wr = w / BASE_W
    hr = h / BASE_H
    pad = int(80 * min(wr, hr))
    return [max(0, int(roi[0] * wr) - pad),
            max(0, int(roi[1] * hr) - pad),
            min(w, int(roi[2] * wr) + pad),
            min(h, int(roi[3] * hr) + pad)]


def annotate(img, ent_results, wall_results, ability_states):
    out = img.copy()
    color_map = {"enemy": (0, 0, 255), "teammate": (255, 200, 0),
                 "player": (0, 255, 80)}
    for cls, boxes in ent_results.items():
        c = color_map.get(cls, (200, 200, 200))
        for b in boxes:
            cv2.rectangle(out, (b[0], b[1]), (b[2], b[3]), c, 4)
            cv2.putText(out, cls, (b[0], max(20, b[1] - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, c, 2)
    for cls, boxes in (wall_results or {}).items():
        c = (140, 140, 140) if cls == "wall" else (50, 200, 50)
        for b in boxes:
            cv2.rectangle(out, (b[0], b[1]), (b[2], b[3]), c, 2)
    for label, (roi, count, thr, ready) in ability_states.items():
        c = (0, 255, 0) if ready else (0, 0, 255)
        cv2.rectangle(out, (roi[0], roi[1]), (roi[2], roi[3]), c, 3)
        cv2.putText(out, f"{label}: {count}/{thr} {'READY' if ready else '-'}",
                    (roi[0], max(30, roi[1] - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, c, 2)
    return out


def process(p: Path):
    img = cv2.imread(str(p))
    if img is None:
        print(f"[skip] could not read {p.name}")
        return
    h, w = img.shape[:2]
    print(f"\n=== {p.name} ({w}x{h}) ===")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # YOLO entity detection (player / enemy / teammate)
    ent_results = ent.detect_objects(rgb, conf_tresh=ENT_CONF)
    enemy_n = len(ent_results.get("enemy", []))
    team_n = len(ent_results.get("teammate", []))
    player_n = len(ent_results.get("player", []))
    print(f"  YOLO entities  enemy={enemy_n}  teammate={team_n}  player={player_n}")
    for cls, boxes in ent_results.items():
        for b in boxes:
            cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
            print(f"    {cls:<8} center=({cx:>4},{cy:>4})  bbox={b}")

    # Tile detector (walls / bushes)
    wall_results = tile.detect_objects(rgb, conf_tresh=WALL_CONF)
    if wall_results:
        for cls in WALL_CLASSES:
            n = len(wall_results.get(cls, []))
            if n:
                print(f"  Tile detector  {cls}={n}")

    # Ability HSV checks — exact same code paths as Play.check_if_*_ready
    abilities = {}

    sx1, sy1, sx2, sy2 = super_roi_padded(SUPER_ROI, w, h)
    super_crop = rgb[sy1:sy2, sx1:sx2]
    super_yellow = count_hsv_pixels(super_crop, (17, 170, 200), (27, 255, 255))
    super_ready = super_yellow > SUPER_MIN
    abilities["SUPER (yellow)"] = ([sx1, sy1, sx2, sy2], super_yellow, SUPER_MIN, super_ready)

    gx1, gy1, gx2, gy2 = scale_roi(GADGET_ROI, w, h)
    gadget_crop = rgb[gy1:gy2, gx1:gx2]
    gadget_green = count_hsv_pixels(gadget_crop, (57, 219, 165), (62, 255, 255))
    gadget_ready = gadget_green > GADGET_MIN
    abilities["GADGET (green)"] = ([gx1, gy1, gx2, gy2], gadget_green, GADGET_MIN, gadget_ready)

    hx1, hy1, hx2, hy2 = scale_roi(HYPER_ROI, w, h)
    hyper_crop = rgb[hy1:hy2, hx1:hx2]
    hyper_purple = count_hsv_pixels(hyper_crop, (137, 158, 159), (179, 255, 255))
    hyper_ready = hyper_purple > HYPER_MIN
    abilities["HYPER (purple)"] = ([hx1, hy1, hx2, hy2], hyper_purple, HYPER_MIN, hyper_ready)

    for label, (roi, count, thr, ready) in abilities.items():
        verdict = "READY" if ready else "not-ready"
        print(f"  {label:<18} ROI={roi}  hsv_pixels={count:>5}  threshold={thr}  -> {verdict}")

    annotated = annotate(img, ent_results, wall_results, abilities)
    out_path = OUT_DIR / p.name
    cv2.imwrite(str(out_path), annotated)
    print(f"  -> annotated: {out_path}")


def main():
    shots = sorted(p for p in GAME_DIR.iterdir()
                   if p.suffix.lower() in (".png", ".jpg", ".jpeg")
                   and not p.name.startswith("_"))
    print(f"Found {len(shots)} screenshots")
    for s in shots:
        process(s)
    print(f"\nAnnotated frames -> {OUT_DIR}")


if __name__ == "__main__":
    main()
