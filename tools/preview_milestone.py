"""Live preview server for backend/notify_render.py.

Open http://127.0.0.1:8780 in your browser. Every change to notify_render.py
auto-rerenders the 4 sample cards (the page polls a tiny ``/mtime`` endpoint
every 500ms and bumps a cache-buster on the images when the file changes).

No setup beyond running this script — uvicorn + FastAPI are already deps.

Run:
    py -3.11 tools/preview_milestone.py
"""
from __future__ import annotations

import importlib
import io
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# Lazy import so we can reload it on every render
import backend.notify_render as nr

NR_PATH = ROOT / "backend" / "notify_render.py"


def _curve(start: int, end: int, n: int, jitter: float = 6.0) -> list[float]:
    rng = random.Random(start * 7 + end * 13 + n)
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        s = 1 / (1 + math.exp(-6 * (t - 0.5)))
        base = start + (end - start) * s
        out.append(round(base + rng.uniform(-jitter, jitter), 1))
    out[0] = float(start)
    out[-1] = float(end)
    return out


SAMPLES = [
    {
        "name": "01 · brock high trophy (chart from your screenshot)",
        "payload": {
            "brawler": {"name": "brock", "color": "#7CD3FF"},
            "mode": {"name": "Brawl Ball", "color": "#B45EE8"},
            "goal": {"type": "trophies", "current": 1162, "target": 1500, "start": 0},
            "stats": {"games": 258, "wins": 140, "losses": 110, "winRate": 54,
                      "netTrophies": 1162, "duration": "7h 58m", "winStreak": 3},
            "curve": _curve(0, 1162, 80),
        },
    },
    {
        "name": "02 · Shelly mid-session",
        "payload": {
            "brawler": {"name": "Shelly", "color": "#F8B733"},
            "mode": {"name": "Gem Grab", "color": "#B45EE8"},
            "goal": {"type": "trophies", "current": 423, "target": 500, "start": 380},
            "stats": {"games": 47, "wins": 28, "losses": 19, "winRate": 60,
                      "netTrophies": 43, "duration": "3h 12m", "winStreak": 4},
            "curve": _curve(380, 423, 38, jitter=2.0),
        },
    },
    {
        "name": "03 · EMZ losing streak (red, 0% bar, no streak)",
        "payload": {
            "brawler": {"name": "EMZ", "color": "#E85D75"},
            "mode": {"name": "Showdown", "color": "#5FAD56"},
            "goal": {"type": "trophies", "current": 712, "target": 800, "start": 760},
            "stats": {"games": 18, "wins": 4, "losses": 14, "winRate": 22,
                      "netTrophies": -48, "duration": "1h 04m", "winStreak": 0},
            "curve": _curve(760, 712, 18, jitter=4.0),
        },
    },
    {
        "name": "04 · Colt wins-mode goal (medal icon)",
        "payload": {
            "brawler": {"name": "Colt", "color": "#FF8B59"},
            "goal": {"type": "wins", "current": 140, "target": 200, "start": 0},
            "stats": {"games": 256, "wins": 140, "losses": 116, "winRate": 55,
                      "netTrophies": 287, "duration": "5h 33m", "winStreak": 7},
            "curve": _curve(0, 287, 60, jitter=8.0),
        },
    },
]


app = FastAPI(title="PylaAI · milestone card preview")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    rows = "\n".join(
        f'''
        <div class="tile">
          <h3>{s["name"]}</h3>
          <img id="img{i}" src="/render/{i}?t=0" alt=""/>
        </div>
        '''
        for i, s in enumerate(SAMPLES)
    )
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>PylaAI · milestone card preview</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 18px;
    background: #0b0d10; color: #e6e8ec;
    font: 13px/1.4 -apple-system, "Segoe UI", system-ui, sans-serif;
  }}
  header {{
    display: flex; align-items: center; gap: 14px;
    padding: 8px 4px 16px;
    border-bottom: 1px solid #1c2028; margin-bottom: 16px;
  }}
  header h1 {{ margin: 0; font-size: 16px; font-weight: 600; }}
  header .mtime {{ opacity: 0.55; font-family: "JetBrains Mono", Consolas, monospace; }}
  header .pulse {{
    width: 8px; height: 8px; border-radius: 50%;
    background: #34d399; box-shadow: 0 0 0 0 rgba(52,211,153,0.55);
    animation: pulse 1.4s infinite;
  }}
  @keyframes pulse {{
    0%   {{ box-shadow: 0 0 0 0 rgba(52,211,153,0.55); }}
    70%  {{ box-shadow: 0 0 0 10px rgba(52,211,153,0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(52,211,153,0); }}
  }}
  .grid {{
    display: grid; grid-template-columns: repeat(2, 1fr);
    gap: 14px; max-width: 2540px; margin: 0 auto;
  }}
  @media (max-width: 1300px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .tile {{
    background: #12151a; border: 1px solid #1c2028;
    border-radius: 12px; padding: 12px;
  }}
  .tile h3 {{
    margin: 0 0 10px; font-size: 12px; font-weight: 500;
    color: #8a8f98; text-transform: uppercase; letter-spacing: 0.04em;
  }}
  .tile img {{
    width: 100%; height: auto; display: block;
    border-radius: 8px; background: #000;
  }}
  .err {{ color: #f87171; padding: 8px 0; }}
</style>
</head><body>
<header>
  <span class="pulse"></span>
  <h1>milestone card · live preview</h1>
  <span class="mtime" id="mtime">watching…</span>
  <span style="opacity:.5; margin-left:auto;">
    edit <code>backend/notify_render.py</code> · auto-refresh on save
  </span>
</header>
<div class="grid">{rows}</div>
<script>
  let lastMtime = 0;
  async function poll() {{
    try {{
      const r = await fetch('/mtime', {{cache: 'no-store'}});
      const j = await r.json();
      document.getElementById('mtime').textContent =
          'mtime ' + new Date(j.mtime * 1000).toLocaleTimeString();
      if (j.mtime > lastMtime) {{
        lastMtime = j.mtime;
        const t = Date.now();
        document.querySelectorAll('img').forEach((img, i) => {{
          img.src = '/render/' + i + '?t=' + t;
        }});
      }}
    }} catch (e) {{
      document.getElementById('mtime').textContent = 'fetch error';
    }}
    setTimeout(poll, 500);
  }}
  poll();
</script>
</body></html>
"""
    return HTMLResponse(html)


@app.get("/mtime")
def mtime() -> JSONResponse:
    try:
        return JSONResponse({"mtime": NR_PATH.stat().st_mtime})
    except OSError:
        return JSONResponse({"mtime": 0})


@app.get("/render/{idx}")
def render(idx: int) -> Response:
    if idx < 0 or idx >= len(SAMPLES):
        return Response("bad index", status_code=404)
    # Reimport notify_render every call so source edits land without
    # restarting uvicorn. Catches syntax errors and shows them as text.
    try:
        importlib.reload(nr)
        png = nr.render_milestone_card_a(SAMPLES[idx]["payload"])
        return Response(png, media_type="image/png")
    except Exception as exc:
        # Render the error onto a tiny placeholder PNG so the page can
        # display "what broke" instead of a dead image icon.
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1200, 200), (40, 12, 12))
        d = ImageDraw.Draw(img)
        msg = f"{type(exc).__name__}: {exc}"
        d.text((20, 20), msg[:1900], fill=(248, 113, 113))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png", status_code=500)


if __name__ == "__main__":
    print("=" * 60)
    print("  preview_milestone.py — open http://127.0.0.1:8780")
    print("  edit backend/notify_render.py and save — page auto-refreshes")
    print("  Ctrl+C to stop")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8780, log_level="warning")
