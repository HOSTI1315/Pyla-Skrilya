"""Render a few sample milestone cards to disk so you can preview the designer
fixes. Saves to ``TestScreenshot/_milestone_samples/`` (created on demand).

Run: python tools/render_milestone_samples.py
"""
from __future__ import annotations

import os
import sys
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.notify_render import render_milestone_card_a

OUT_DIR = ROOT / "TestScreenshot" / "_milestone_samples"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _curve(start: int, end: int, n: int, jitter: float = 6.0) -> list[float]:
    """Smooth-ish growth curve so the chart actually has shape."""
    rng = random.Random(start * 7 + end * 13 + n)
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        # Slight S-curve so growth feels organic.
        s = 1 / (1 + math.exp(-6 * (t - 0.5)))
        base = start + (end - start) * s
        out.append(round(base + rng.uniform(-jitter, jitter), 1))
    out[0] = float(start)
    out[-1] = float(end)
    return out


SAMPLES = [
    # 1) Brock-style high-trophy push (mirrors the screenshot user shared).
    {
        "name": "01_brock_high_trophy",
        "payload": {
            "brawler": {"name": "brock", "color": "#7CD3FF"},
            "mode": {"name": "Brawl Ball", "color": "#B45EE8"},
            "goal": {"type": "trophies", "current": 1162, "target": 1500, "start": 0},
            "stats": {
                "games": 258, "wins": 140, "losses": 110, "winRate": 54,
                "netTrophies": 1162, "duration": "7h 58m", "winStreak": 3,
            },
            "curve": _curve(0, 1162, 80),
        },
    },
    # 2) Shelly mid-progress with mode pill — reasonable session.
    {
        "name": "02_shelly_in_range",
        "payload": {
            "brawler": {"name": "Shelly", "color": "#F8B733"},
            "mode": {"name": "Gem Grab", "color": "#B45EE8"},
            "goal": {"type": "trophies", "current": 423, "target": 500, "start": 380},
            "stats": {
                "games": 47, "wins": 28, "losses": 19, "winRate": 60,
                "netTrophies": 43, "duration": "3h 12m", "winStreak": 4,
            },
            "curve": _curve(380, 423, 38, jitter=2.0),
        },
    },
    # 3) Negative session — red net, downward chart, no streak.
    {
        "name": "03_emz_losing_streak",
        "payload": {
            "brawler": {"name": "EMZ", "color": "#E85D75"},
            "mode": {"name": "Showdown", "color": "#5FAD56"},
            "goal": {"type": "trophies", "current": 712, "target": 800, "start": 760},
            "stats": {
                "games": 18, "wins": 4, "losses": 14, "winRate": 22,
                "netTrophies": -48, "duration": "1h 04m", "winStreak": 0,
            },
            "curve": _curve(760, 712, 18, jitter=4.0),
        },
    },
    # 4) Wins-mode goal (no trophy curve, flat games).
    {
        "name": "04_colt_session_wins",
        "payload": {
            "brawler": {"name": "Colt", "color": "#FF8B59"},
            "goal": {"type": "wins", "current": 140, "target": 200, "start": 0},
            "stats": {
                "games": 256, "wins": 140, "losses": 116, "winRate": 55,
                "netTrophies": 287, "duration": "5h 33m", "winStreak": 7,
            },
            "curve": _curve(0, 287, 60, jitter=8.0),
        },
    },
]


for sample in SAMPLES:
    out_path = OUT_DIR / f"{sample['name']}.png"
    print(f"Rendering {out_path.name} ...", end=" ", flush=True)
    png = render_milestone_card_a(sample["payload"])
    out_path.write_bytes(png)
    print(f"OK ({len(png)//1024} KB)")

print(f"\nSaved {len(SAMPLES)} cards to {OUT_DIR}")
