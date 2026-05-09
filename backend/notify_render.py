"""PIL renderer for Discord notification cards.

Produces a 1200×630 PNG matching the `CardVariantA` design from
`New UI and Discord Noting/discord-card.jsx` — split layout with a
left info panel (brawler glyph, session report label, goal, stat pills,
duration/streak footer) and a right chart panel (net trophies, peak,
trend chart).

Usage:
    from backend.notify_render import render_milestone_card_a
    payload = {
        "brawler": {"name": "Shelly", "color": "#F8B733"},
        "mode":    {"name": "Gem Grab", "color": "#B45EE8"},  # optional
        "goal":    {"type": "trophies", "current": 423, "target": 500, "start": 380},
        "stats":   {"games": 47, "wins": 28, "losses": 19, "winRate": 60,
                    "netTrophies": 43, "duration": "3h 12m", "winStreak": 4},
        "curve":   [380, 384, ...],
    }
    png_bytes = render_milestone_card_a(payload)
"""

from __future__ import annotations

import io
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ── Design tokens (mirror DC_COLORS in discord-card.jsx) ────────────
COLORS = {
    "bg0":     (11, 13, 16),
    "bg1":     (18, 21, 26),
    "bg2":     (24, 28, 35),
    "bg3":     (32, 37, 46),
    "fg":      (230, 232, 236),
    "fg2":     (185, 190, 200),
    "muted":   (138, 143, 152),
    "accent":  (248, 183, 51),
    "accent2": (124, 92, 255),
    "green":   (52, 211, 153),
    "red":     (248, 113, 113),
    "stroke":  (255, 255, 255, 20),   # ~0.08 alpha
    "stroke2": (255, 255, 255, 36),   # ~0.14 alpha
}


# ── Font loading ────────────────────────────────────────────────────
# The design calls for Space Grotesk, but it's not shipped with Windows.
# Fall back through Segoe UI Variable → Segoe UI Semibold/Bold → default.
_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

# Designer fix #10: drop SpaceGrotesk-*.ttf into ``assets/fonts/`` (or rooted
# next to this file) and the renderer will pick them up first. Without those
# files the geometry of digits like "1" and "5" diverges noticeably from the
# JSX preview because Segoe UI / Arial draw them with different metrics.
# Files come from https://fonts.google.com/specimen/Space+Grotesk
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts")


def _font_paths(*names: str) -> List[str]:
    out: List[str] = []
    for n in names:
        out.append(os.path.join(_FONT_DIR, n))
    return out


_CANDIDATES = {
    "regular": [
        *_font_paths("SpaceGrotesk-Regular.ttf"),
        "SpaceGrotesk-Regular.ttf",
        r"C:\Windows\Fonts\SegUIVar.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ],
    "medium": [
        *_font_paths("SpaceGrotesk-Medium.ttf"),
        "SpaceGrotesk-Medium.ttf",
        r"C:\Windows\Fonts\seguisb.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ],
    "semibold": [
        *_font_paths("SpaceGrotesk-SemiBold.ttf"),
        "SpaceGrotesk-SemiBold.ttf",
        r"C:\Windows\Fonts\seguisb.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ],
    "bold": [
        *_font_paths("SpaceGrotesk-Bold.ttf"),
        "SpaceGrotesk-Bold.ttf",
        r"C:\Windows\Fonts\seguibl.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ],
    "mono": [
        *_font_paths("JetBrainsMono-Regular.ttf"),
        "JetBrainsMono-Regular.ttf",
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
        r"C:\Windows\Fonts\cour.ttf",
    ],
}


def _get_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    cache_key = (weight, size)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]
    for name in _CANDIDATES.get(weight, _CANDIDATES["regular"]):
        try:
            f = ImageFont.truetype(name, size)
            _FONT_CACHE[cache_key] = f
            return f
        except (OSError, IOError):
            continue
    # Last-resort: PIL's bitmap default (fixed tiny size, ignores `size`).
    f = ImageFont.load_default()
    _FONT_CACHE[cache_key] = f
    return f


# ── Helpers ─────────────────────────────────────────────────────────
def _hex_to_rgb(hex_color: str, fallback: Tuple[int, int, int] = (248, 183, 51)) -> Tuple[int, int, int]:
    if not hex_color:
        return fallback
    s = hex_color.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return fallback
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return fallback


def _blend(bg: Tuple[int, int, int], fg: Tuple[int, int, int, int]) -> Tuple[int, int, int]:
    a = fg[3] / 255.0
    return (
        int(bg[0] * (1 - a) + fg[0] * a),
        int(bg[1] * (1 - a) + fg[1] * a),
        int(bg[2] * (1 - a) + fg[2] * a),
    )


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l
    except AttributeError:
        return int(font.getlength(text))


def _text_height(font: ImageFont.FreeTypeFont) -> int:
    try:
        asc, desc = font.getmetrics()
        return asc + desc
    except Exception:
        return font.size


def _catmull_rom_points(pts: Sequence[Tuple[float, float]], samples_per_seg: int = 16,
                         tension: float = 0.5) -> List[Tuple[float, float]]:
    """Bake a catmull-rom spline into a dense polyline for PIL drawing.

    Matches the JS in discord-card.jsx so the PNG and the in-browser preview
    look identical.
    """
    if len(pts) < 2:
        return list(pts)
    out: List[Tuple[float, float]] = [pts[0]]
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else pts[i + 1]
        cp1x = p1[0] + (p2[0] - p0[0]) / 6 * tension * 2
        cp1y = p1[1] + (p2[1] - p0[1]) / 6 * tension * 2
        cp2x = p2[0] - (p3[0] - p1[0]) / 6 * tension * 2
        cp2y = p2[1] - (p3[1] - p1[1]) / 6 * tension * 2
        for s in range(1, samples_per_seg + 1):
            t = s / samples_per_seg
            omt = 1 - t
            x = (omt ** 3) * p1[0] + 3 * (omt ** 2) * t * cp1x + 3 * omt * (t ** 2) * cp2x + (t ** 3) * p2[0]
            y = (omt ** 3) * p1[1] + 3 * (omt ** 2) * t * cp1y + 3 * omt * (t ** 2) * cp2y + (t ** 3) * p2[1]
            out.append((x, y))
    return out


def _rounded_rect(base: Image.Image, xy: Tuple[float, float, float, float],
                   radius: int, fill: Optional[Tuple[int, int, int]] = None,
                   outline: Optional[Tuple[int, int, int, int]] = None,
                   width: int = 1) -> None:
    """Draw a rounded rect on base (supports RGBA outline for soft strokes)."""
    x0, y0, x1, y1 = xy
    draw = ImageDraw.Draw(base, "RGBA")
    if fill is not None:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill)
    if outline is not None:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=outline, width=width)


# ── Gradient helpers ───────────────────────────────────────────────
def _radial_gradient_layer(size: Tuple[int, int], center: Tuple[float, float],
                            radius: float, color: Tuple[int, int, int],
                            max_alpha: float = 0.15) -> Image.Image:
    """Generate a radial-gradient RGBA layer: color at center, transparent at radius.

    Uses a simple quadratic falloff to match the CSS radial-gradient() feel.
    The layer is downscaled-then-upscaled to stay cheap (a fine gradient at
    1200×630 would be slow in pure Python).
    """
    w, h = size
    scale = 6  # downsample factor — good trade-off between speed and quality
    sw, sh = max(1, w // scale), max(1, h // scale)
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    px = layer.load()
    cx, cy = center[0] / scale, center[1] / scale
    r_sc = max(1.0, radius / scale)
    alpha_cap = int(max_alpha * 255)
    for y in range(sh):
        dy = (y - cy)
        for x in range(sw):
            dx = (x - cx)
            d = math.hypot(dx, dy) / r_sc
            if d >= 1.0:
                continue
            a = (1.0 - d) ** 2
            px[x, y] = (color[0], color[1], color[2], int(alpha_cap * a))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.5))
    return layer.resize((w, h), Image.BILINEAR)


def _linear_gradient_v(size: Tuple[int, int], color_top: Tuple[int, int, int, int],
                        color_bot: Tuple[int, int, int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(color_top[0] * (1 - t) + color_bot[0] * t)
        g = int(color_top[1] * (1 - t) + color_bot[1] * t)
        b = int(color_top[2] * (1 - t) + color_bot[2] * t)
        a = int(color_top[3] * (1 - t) + color_bot[3] * t)
        for x in range(w):
            px[x, y] = (r, g, b, a)
    return img


# ── Chart drawing ──────────────────────────────────────────────────
def _draw_trend_chart(layer: Image.Image, box: Tuple[int, int, int, int],
                       curve: Sequence[float], color: Tuple[int, int, int],
                       show_dots: bool = True) -> None:
    """Draw a smoothed trend chart into `box` (x0,y0,x1,y1) on an RGBA layer."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 4 or h <= 4 or len(curve) < 2:
        return
    pad = 4
    lo = min(curve)
    hi = max(curve)
    rng = max(1.0, hi - lo)
    pts: List[Tuple[float, float]] = []
    for i, v in enumerate(curve):
        px = x0 + pad + (i / (len(curve) - 1)) * (w - 2 * pad)
        py = y0 + pad + (1 - (v - lo) / rng) * (h - 2 * pad)
        pts.append((px, py))
    line_pts = _catmull_rom_points(pts, samples_per_seg=14, tension=0.5)

    # Area fill — vertical gradient color → transparent, clipped to the polygon.
    fill_mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(fill_mask)
    poly = [(p[0] - x0, p[1] - y0) for p in line_pts]
    poly.append((line_pts[-1][0] - x0, h - pad))
    poly.append((line_pts[0][0] - x0, h - pad))
    md.polygon(poly, fill=255)
    gradient = _linear_gradient_v(
        (w, h),
        color_top=(color[0], color[1], color[2], int(0.35 * 255)),
        color_bot=(color[0], color[1], color[2], 0),
    )
    gradient.putalpha(Image.eval(gradient.split()[-1], lambda a: a).point(
        lambda _: 0).point(lambda _: 0))  # reset alpha, we'll compose with mask
    # Simpler path: recompose gradient directly with mask
    gradient = _linear_gradient_v(
        (w, h),
        color_top=(color[0], color[1], color[2], int(0.35 * 255)),
        color_bot=(color[0], color[1], color[2], 0),
    )
    alpha = gradient.split()[-1]
    alpha = Image.eval(alpha, lambda a: a).resize((w, h))
    combined_alpha = Image.new("L", (w, h))
    combined_alpha.paste(alpha, (0, 0), mask=fill_mask)
    fill_img = Image.new("RGBA", (w, h), (color[0], color[1], color[2], 0))
    fill_img.putalpha(combined_alpha)
    layer.alpha_composite(fill_img, dest=(x0, y0))

    # Line on top — draw with antialiasing via supersampling trick: draw
    # twice at integer coords, PIL's line already smooths well enough.
    draw = ImageDraw.Draw(layer, "RGBA")
    draw.line([(p[0], p[1]) for p in line_pts],
              fill=(color[0], color[1], color[2], 255), width=3, joint="curve")

    if show_dots:
        for idx in (0, len(pts) - 1):
            cx, cy = pts[idx]
            r_out = 5
            draw.ellipse((cx - r_out, cy - r_out, cx + r_out, cy + r_out),
                         fill=COLORS["bg1"])
            draw.ellipse((cx - 3.5, cy - 3.5, cx + 3.5, cy + 3.5),
                         fill=(color[0], color[1], color[2], 255))


# ── Brawler glyph ──────────────────────────────────────────────────
def _draw_brawler_glyph(layer: Image.Image, top_left: Tuple[int, int], size: int,
                         initial: str, color: Tuple[int, int, int]) -> None:
    x, y = top_left

    # Designer fix #8: drop a soft color shadow under the glyph to lift it
    # off the dark background (mirrors `boxShadow: 0 8px 24px -8px ${color}55`
    # from the JSX). Done before the glyph itself so it sits behind.
    shadow_pad = 24
    shadow = Image.new("RGBA", (size + shadow_pad * 2, size + shadow_pad * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rounded_rectangle(
        (shadow_pad, shadow_pad, shadow_pad + size - 1, shadow_pad + size - 1),
        radius=int(size * 0.22),
        fill=(color[0], color[1], color[2], int(0.33 * 255)),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=12))
    layer.alpha_composite(shadow, dest=(x - shadow_pad, y - shadow_pad + 8))

    radius = int(size * 0.22)
    glyph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Designer fix #6: gradient stop is supposed to be the brawler color
    # blended onto bg0 at 67% alpha (the "AA" hex suffix in the original
    # CSS). Old code multiplied RGB channels by 0.67 which is a different
    # operation — gives a muddy grey instead of the warm "fading" look.
    darker = _blend(COLORS["bg0"], (color[0], color[1], color[2], int(0.67 * 255)))
    # Build diagonal gradient by compositing a vertical gradient rotated 45°.
    grad = _linear_gradient_v((size * 2, size * 2),
                              color_top=(color[0], color[1], color[2], 255),
                              color_bot=(darker[0], darker[1], darker[2], 255))
    grad = grad.rotate(-45, resample=Image.BILINEAR, expand=False)
    grad = grad.crop(((size * 2 - size) // 2, (size * 2 - size) // 2,
                      (size * 2 + size) // 2, (size * 2 + size) // 2))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    glyph.paste(grad, (0, 0), mask)
    # Subtle outer ring (simulates "0 0 0 2px rgba(255,255,255,0.08)").
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(ring, "RGBA").rounded_rectangle(
        (1, 1, size - 2, size - 2), radius=radius, outline=(255, 255, 255, 24), width=2,
    )
    glyph.alpha_composite(ring)
    # Glyph letter
    gd = ImageDraw.Draw(glyph, "RGBA")
    font = _get_font("bold", int(size * 0.5))
    letter = (initial or "?").upper()
    tw = _text_width(gd, letter, font)
    th = _text_height(font)
    gd.text(((size - tw) // 2, (size - th) // 2 - int(size * 0.04)),
            letter, font=font, fill=(255, 255, 255, 255))
    layer.alpha_composite(glyph, dest=(x, y))


# ── Stat pill ──────────────────────────────────────────────────────
def _draw_pill(layer: Image.Image, xy: Tuple[int, int, int, int],
                label: str, value: str, accent: Tuple[int, int, int] = COLORS["fg"]) -> None:
    """Render one GAMES / WINS / WINRATE pill.

    All visual knobs live at the top of the function and the LABEL / VALUE
    Y offsets are independent — moving one never moves the other.

        ┌────────────────────────┐  <- y0 (pill top)
        │   GAMES   ← LABEL_Y     │
        │   258     ← VALUE_Y     │
        └────────────────────────┘  <- y1 (pill bot)

    LABEL_Y and VALUE_Y are absolute pixel offsets from the pill's top
    edge. Smaller value = higher inside the pill.
    """
    x0, y0, x1, y1 = xy

    # ─── INTERNAL KNOBS ───────────────────────────────────────────────
    PILL_RADIUS    = 10                   # ← corner roundness
    PILL_BG        = COLORS["bg2"]        # ← background fill colour
    PILL_BORDER    = COLORS["stroke"]     # ← outline colour

    PILL_PAD_X     = 14                   # ← horizontal padding for both texts

    # Independent vertical offsets (from pill TOP edge, in px).
    # Smaller = higher. Each knob ONLY moves its own line.
    LABEL_Y        = 4                    # ← Y of "GAMES" / "WINS" / "WINRATE"
    VALUE_Y        = 22                   # ← Y of the number "258" / "140" / "54%"

    LABEL_SIZE     = 13                   # ← font size of LABEL
    VALUE_SIZE     = 22                   # ← font size of VALUE
    LABEL_WEIGHT   = "semibold"           # ← regular | medium | semibold | bold
    VALUE_WEIGHT   = "bold"
    LABEL_COLOR    = COLORS["muted"]      # ← LABEL text colour
    LABEL_UPPER    = True                 # ← True → "GAMES"; False → "Games"
    # ──────────────────────────────────────────────────────────────────

    _rounded_rect(layer, (x0, y0, x1, y1), radius=PILL_RADIUS,
                  fill=PILL_BG, outline=PILL_BORDER, width=1)
    draw = ImageDraw.Draw(layer, "RGBA")

    lbl_font = _get_font(LABEL_WEIGHT, LABEL_SIZE)
    val_font = _get_font(VALUE_WEIGHT, VALUE_SIZE)

    label_text = label.upper() if LABEL_UPPER else label
    draw.text((x0 + PILL_PAD_X, y0 + LABEL_Y), label_text, font=lbl_font, fill=LABEL_COLOR)
    draw.text((x0 + PILL_PAD_X, y0 + VALUE_Y), value, font=val_font, fill=accent)


# ── Progress bar ───────────────────────────────────────────────────
def _draw_progress_bar(layer: Image.Image, xy: Tuple[int, int, int, int],
                        pct: float, color: Tuple[int, int, int]) -> None:
    x0, y0, x1, y1 = xy
    h = y1 - y0
    _rounded_rect(layer, (x0, y0, x1, y1), radius=h // 2, fill=COLORS["bg3"])
    fill_w = max(0, min(1, pct / 100.0)) * (x1 - x0)
    if fill_w > 2:
        # Horizontal gradient color → color*0.8 (emulates the CSS CC suffix).
        grad_w = max(1, int(fill_w))
        grad_img = Image.new("RGBA", (grad_w, h), (0, 0, 0, 0))
        gp = grad_img.load()
        for xi in range(grad_w):
            t = xi / max(1, grad_w - 1)
            r = int(color[0] * (1 - 0.2 * t))
            g = int(color[1] * (1 - 0.2 * t))
            b = int(color[2] * (1 - 0.2 * t))
            for yi in range(h):
                gp[xi, yi] = (r, g, b, 255)
        grad_mask = Image.new("L", (grad_w, h), 0)
        ImageDraw.Draw(grad_mask).rounded_rectangle(
            (0, 0, grad_w - 1, h - 1), radius=h // 2, fill=255,
        )
        grad_img.putalpha(grad_mask)
        # Soft glow
        glow = Image.new("RGBA", (grad_w + 20, h + 20), (0, 0, 0, 0))
        glow.paste(grad_img, (10, 10), grad_img)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
        # Reduce glow alpha
        glow_alpha = glow.split()[-1].point(lambda a: int(a * 0.4))
        glow.putalpha(glow_alpha)
        layer.alpha_composite(glow, dest=(x0 - 10, y0 - 10))
        layer.alpha_composite(grad_img, dest=(x0, y0))


# ── Main entry point ───────────────────────────────────────────────
def render_milestone_card_a(payload: Dict[str, Any]) -> bytes:
    """Render CardVariantA (split layout) to PNG bytes at 1200×630."""
    W, H = 1200, 630
    brawler = payload.get("brawler") or {}
    mode = payload.get("mode") or {}
    goal = payload.get("goal") or {}
    stats = payload.get("stats") or {}
    curve = payload.get("curve") or []

    b_name = str(brawler.get("name") or "—")
    b_color = _hex_to_rgb(brawler.get("color"), COLORS["accent"])
    m_name = str(mode.get("name") or "")
    m_color = _hex_to_rgb(mode.get("color"), COLORS["accent2"])

    g_type = goal.get("type") or "trophies"
    g_cur = int(goal.get("current") or 0)
    g_tgt = int(goal.get("target") or max(g_cur, 1))
    g_start = int(goal.get("start") if goal.get("start") is not None else g_cur)

    # ─── PROGRESS PERCENT MODE ──────────────────────────────────────
    # "session"  → (cur - start) / (target - start) — how far we got in
    #              the current session. If start ≈ current (small delta),
    #              the bar will look almost empty. This is the legacy
    #              behaviour and matches the JSX preview.
    # "absolute" → cur / target — how close to the trophy ceiling
    #              regardless of when the session started. Always shows
    #              a meaningful fill if cur > 0.
    # ───────────────────────────────────────────────────────────────
    PROGRESS_MODE = "session"   # ← "absolute" (cur/target) | "session" (delta)
    if PROGRESS_MODE == "absolute":
        pct = max(0, min(100, round(g_cur / g_tgt * 100))) if g_tgt > 0 else 0
    elif g_tgt > g_start:
        pct = max(0, min(100, round((g_cur - g_start) / (g_tgt - g_start) * 100)))
    else:
        pct = 100 if g_cur >= g_tgt else 0

    net = int(stats.get("netTrophies") or 0)
    net_str = f"{'+' if net >= 0 else ''}{net}"
    net_color = COLORS["green"] if net >= 0 else COLORS["red"]
    trend_color = net_color

    # Make sure we always have enough points for the chart.
    if len(curve) < 2:
        if curve:
            curve = [curve[0], curve[0]]
        else:
            curve = [g_start, g_cur]

    # ── Base canvas ──
    canvas = Image.new("RGB", (W, H), COLORS["bg0"])
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Radial gradients (brawler color top-left, mode color bottom-right).
    layer.alpha_composite(
        _radial_gradient_layer((W, H), center=(W * 0.15, H * -0.10),
                               radius=900, color=b_color, max_alpha=0.13),
    )
    layer.alpha_composite(
        _radial_gradient_layer((W, H), center=(W * 1.10, H * 1.10),
                               radius=800, color=m_color, max_alpha=0.10),
    )

    # Subtle 48px grid (3% white). Cheap: draw lines on a small overlay.
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    grid_alpha = 8  # ~3%
    for x in range(0, W, 48):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, grid_alpha))
    for y in range(0, H, 48):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, grid_alpha))
    layer.alpha_composite(grid)

    canvas = Image.alpha_composite(canvas.convert("RGBA"), layer)
    work = canvas  # work on RGBA for layering clarity

    # ── LEFT panel (540px, 44px padding top) ──
    LEFT_W = 540
    PAD = 40
    PAD_TOP = 44
    x = PAD
    y = PAD_TOP
    left_content_right = LEFT_W - PAD   # right edge of content after padding

    # Brawler glyph + header text
    glyph_size = 88
    _draw_brawler_glyph(work, (x, y), glyph_size, b_name[:1] or "?", b_color)

    text_x = x + glyph_size + 22
    draw = ImageDraw.Draw(work, "RGBA")

    # "Session Report" label
    lbl_font = _get_font("semibold", 13)
    draw.text((text_x, y + 2), "SESSION REPORT", font=lbl_font, fill=COLORS["muted"])

    # Brawler name — big
    name_font = _get_font("bold", 36)
    # Truncate if too wide to avoid overlapping the right panel.
    max_name_w = LEFT_W - text_x - PAD + x
    name_text = b_name
    while _text_width(draw, name_text, name_font) > max_name_w and len(name_text) > 3:
        name_text = name_text[:-1]
    if name_text != b_name:
        name_text = name_text[:-1] + "…"
    draw.text((text_x, y + 18), name_text, font=name_font, fill=COLORS["fg"])

    # Mode pill (inline below the name)
    if m_name:
        mp_font = _get_font("medium", 13)
        mp_text = m_name
        mp_text_w = _text_width(draw, mp_text, mp_font)
        mp_x0 = text_x
        mp_y0 = y + 64
        mp_w = mp_text_w + 20
        mp_h = 24
        # Background
        _rounded_rect(work, (mp_x0, mp_y0, mp_x0 + mp_w, mp_y0 + mp_h),
                      radius=6, fill=COLORS["bg2"], outline=COLORS["stroke"], width=1)
        # Left colored stripe (3px)
        bar = Image.new("RGBA", (3, mp_h - 2), (m_color[0], m_color[1], m_color[2], 255))
        mask = Image.new("L", (3, mp_h - 2), 255)
        work.paste(bar, (mp_x0, mp_y0 + 1), mask)
        draw.text((mp_x0 + 10, mp_y0 + 4), mp_text, font=mp_font, fill=COLORS["fg2"])

    # ── Goal section ──
    goal_y = y + 120
    # ─── GOAL LABEL "GOAL · TROPHIES" ───────────────────────────────
    GOAL_LABEL_X     = x
    GOAL_LABEL_Y     = goal_y
    GOAL_LABEL_SIZE  = 12
    GOAL_LABEL_WT    = "semibold"
    GOAL_LABEL_COLOR = COLORS["muted"]
    draw.text((GOAL_LABEL_X, GOAL_LABEL_Y),
              f"GOAL · {'TROPHIES' if g_type == 'trophies' else 'WINS'}",
              font=_get_font(GOAL_LABEL_WT, GOAL_LABEL_SIZE), fill=GOAL_LABEL_COLOR)

    # ─── "77%" PERCENT LABEL ────────────────────────────────────────
    # Right-aligned to PCT_RIGHT. Move PCT_Y up/down independently of
    # the GOAL label.
    PCT_RIGHT = left_content_right    # ← right edge (anchor)
    PCT_Y     = goal_y - -48                # ← Y (top-left of glyph row)
    PCT_SIZE  = 12                    # ← font size
    PCT_WT    = "mono"                # ← regular | medium | semibold | bold | mono
    PCT_COLOR = COLORS["muted"]       # ← color
    pct_text = f"{pct}%"
    pct_font = _get_font(PCT_WT, PCT_SIZE)
    pct_w = _text_width(draw, pct_text, pct_font)
    draw.text((PCT_RIGHT - pct_w, PCT_Y), pct_text,
              font=pct_font, fill=PCT_COLOR)

    # Current → target line — all glyphs share a baseline so the mix of
    # font sizes doesn't look "staircase". anchor="ls" pins the baseline
    # at baseline_y regardless of font size.
    big_font = _get_font("bold", 44)
    mid_font = _get_font("semibold", 28)
    arrow_font = _get_font("medium", 22)
    # Designer fix #3: 44pt font with lineHeight:1 has ascender ≈32-34, not 42.
    # Old +42 pushed the number too far down from the "ЦЕЛЬ · ТРОФЕИ" label.
    gly_y = goal_y + 22
    baseline_y = gly_y + 32
    cur_text = str(g_cur)
    tgt_text = str(g_tgt)
    draw.text((x, baseline_y), cur_text, font=big_font,
              fill=COLORS["fg"], anchor="ls")
    cur_w = _text_width(draw, cur_text, big_font)
    arrow_x = x + cur_w + 14
    draw.text((arrow_x, baseline_y), "→", font=arrow_font,
              fill=COLORS["muted"], anchor="ls")
    arrow_w = _text_width(draw, "→", arrow_font)
    tgt_x = arrow_x + arrow_w + 10
    draw.text((tgt_x, baseline_y), tgt_text, font=mid_font,
              fill=COLORS["fg2"], anchor="ls")
    tgt_w = _text_width(draw, tgt_text, mid_font)
    icon = "🏆" if g_type == "trophies" else "🏅"
    try:
        emoji_font = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", 24)
    except OSError:
        emoji_font = _get_font("medium", 24)
    draw.text((tgt_x + tgt_w + 10, baseline_y), icon, font=emoji_font,
              fill=COLORS["fg"], embedded_color=True, anchor="ls")

    # ─── PROGRESS BAR ───────────────────────────────────────────────
    PB_X_LEFT  = x                     # ← X левого края
    PB_X_RIGHT = left_content_right    # ← X правого края (полная ширина)
    PB_Y       = baseline_y + 14       # ← Y top (зазор от числа)
    PB_HEIGHT  = 6                     # ← толщина полоски в px
    PB_COLOR   = b_color               # ← цвет заливки (по умолчанию = цвет бравлера)
    # ────────────────────────────────────────────────────────────────
    _draw_progress_bar(work, (PB_X_LEFT, PB_Y, PB_X_RIGHT, PB_Y + PB_HEIGHT),
                       pct, PB_COLOR)

    # ── Stat pills (3-up) ──────────────────────────────────────────
    # Block of 3 stat pills along the bottom of the left panel.
    #
    # Two layers of knobs:
    #   1. ROW knobs — apply to the whole row (vertical position, gap,
    #      uniform height). Auto-equal widths between PILLS_LEFT…PILLS_RIGHT.
    #   2. PER-PILL knobs — overrides for individual pills (size, color,
    #      label/value text). Set ``"x": N`` or ``"w": N`` to override
    #      auto-layout for one pill; leave them out for default behaviour.
    # ─────────────────────────────────────────────────────────────────
    games = int(stats.get("games") or 0)
    wins = int(stats.get("wins") or 0)
    wr = stats.get("winRate")
    wr_text = f"{int(wr) if isinstance(wr, (int, float)) else 0}%"

    # ─── ROW KNOBS ───────────────────────────────────────────────────
    PILLS_Y       = H - 130             # ← вертикальная позиция всего ряда
    PILLS_LEFT    = x                   # ← X левого края 1-й плашки
    PILLS_RIGHT   = LEFT_W - PAD        # ← X правого края 3-й плашки
    PILLS_GAP     = 10                  # ← зазор между плашками
    PILLS_HEIGHT  = 58                  # ← высота плашек (общая для всех)
    # ─────────────────────────────────────────────────────────────────

    # ─── PER-PILL CONFIG ─────────────────────────────────────────────
    # Each entry: label, value, color. Optional "x" / "w" / "y" / "h"
    # override the auto-layout for that single pill — leave out to use
    # the row-wide defaults above.
    #
    # Want WINRATE wider? -> {"label": "WINRATE", ..., "w": 180}
    # Want WINS shifted up by 4px? -> {"label": "WINS", ..., "y": PILLS_Y - 4}
    # Want only GAMES + WINS (no WINRATE)? -> remove the third entry.
    # ─────────────────────────────────────────────────────────────────
    pill_specs = [
        {"label": "GAMES",   "value": str(games), "color": COLORS["fg"]},
        {"label": "WINS",    "value": str(wins),  "color": COLORS["green"]},
        {"label": "WINRATE", "value": wr_text,    "color": COLORS["fg"]},
    ]

    # Auto-equal widths across the row, accounting for gaps.
    n = max(1, len(pill_specs))
    auto_pill_w = (PILLS_RIGHT - PILLS_LEFT - (n - 1) * PILLS_GAP) // n
    cursor_x = PILLS_LEFT
    for spec in pill_specs:
        px = spec.get("x", cursor_x)
        pw = spec.get("w", auto_pill_w)
        py = spec.get("y", PILLS_Y)
        ph = spec.get("h", PILLS_HEIGHT)
        _draw_pill(work, (px, py, px + pw, py + ph),
                   spec["label"], spec["value"], accent=spec["color"])
        # Advance cursor based on this pill's actual width — so a wider
        # pill pushes the next ones right; a manually-positioned pill
        # (x= override) doesn't disturb the cursor.
        if "x" not in spec:
            cursor_x += pw + PILLS_GAP
    # Convenience aliases for the streak-footer block below — it still
    # references pill positioning to know where to anchor its baseline.
    pills_y = PILLS_Y
    pill_h = PILLS_HEIGHT

    # Duration / streak footer
    footer_y = pills_y + pill_h + 15
    dur_font = _get_font("medium", 13)
    # Designer fix #4: dot was at footer_y+7..+13 (lower than text), now
    # vertically centered against the text glyph. Text height ~17 for 13pt
    # → midpoint ≈ 8 from top. Center the 6px dot around (footer_y+3 + 8).
    dot_h = _text_height(dur_font)
    dot_cy = footer_y + 3 + dot_h // 2
    draw.ellipse((x, dot_cy - 3, x + 6, dot_cy + 3), fill=COLORS["accent"])
    dur_label = "Session: "
    draw.text((x + 14, footer_y + 3), dur_label, font=dur_font, fill=COLORS["muted"])
    lbl_w = _text_width(draw, dur_label, dur_font)
    dur_val = str(stats.get("duration") or "—")
    draw.text((x + 14 + lbl_w, footer_y + 3), dur_val,
              font=_get_font("semibold", 13), fill=COLORS["fg"])
    streak = int(stats.get("winStreak") or 0)
    if streak > 0:
        # ──────────────────────────────────────────────────────────────
        # Win-streak block — explicit knobs so changing one doesn't
        # silently shift the other across cards.
        #
        # Old code right-aligned the entire "🔥 N win streak" string. That
        # made the fire position depend on the digit width — "3" vs "7"
        # differ by 1-3 px in most fonts, so the fire visibly jumped
        # between cards.
        #
        # Now: TEXT is right-anchored to the panel's right edge (always
        # ends at the same X), and the fire sits LEFT of the text with a
        # fixed gap. Changing fire size or Y doesn't move the text;
        # changing text font doesn't move the fire's pivot.
        # ──────────────────────────────────────────────────────────────
        FIRE_SIZE  = 14            # ← emoji glyph size
        FIRE_Y     = footer_y + 8  # ← fire vertical offset (relative to footer)
        FIRE_GAP   = 4             # ← px gap between fire and the digit
        TEXT_Y     = footer_y + 3  # ← text vertical offset
        TEXT_RIGHT = left_content_right   # ← text's right edge (anchor='rt')

        try:
            emoji_small = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", FIRE_SIZE)
        except OSError:
            emoji_small = dur_font

        streak_text = f"{streak} win streak"
        text_w = _text_width(draw, streak_text, dur_font)
        # Text — right-aligned to TEXT_RIGHT so its end never moves.
        draw.text((TEXT_RIGHT - text_w, TEXT_Y), streak_text,
                  font=dur_font, fill=COLORS["fg2"])
        # Fire — sits to the LEFT of the text by FIRE_GAP. Its X is
        # derived from text_w (one source of truth), but the gap stays
        # constant regardless of digit width.
        fire_w = _text_width(draw, "🔥", emoji_small)
        fire_x = TEXT_RIGHT - text_w - FIRE_GAP - fire_w
        draw.text((fire_x, FIRE_Y), "🔥",
                  font=emoji_small, fill=COLORS["fg2"], embedded_color=True)

    # ── RIGHT panel (chart half) ──
    RX = LEFT_W
    RIGHT_PAD_L = 20
    RIGHT_PAD_R = 40
    rx0 = RX + RIGHT_PAD_L
    rx1 = W - RIGHT_PAD_R
    ry = PAD_TOP

    # ── TROPHY TREND header (label + big net number + trophy emoji) ───
    # Three independent rows of knobs:
    #   1. LABEL  — "TROPHY TREND" caption above the number
    #   2. NUMBER — the big "+1162" / "-48"
    #   3. TROPHY — the 🏆 / 🏅 emoji to the right of the number
    #
    # Each block has its own X / Y / size knobs — moving one never
    # cascades into the others. NUMBER and TROPHY use ``anchor="ls"``
    # (bottom-left) so the values are baselines, not top-left corners
    # — this is what keeps the emoji flush with the digits regardless
    # of font size.
    # ─────────────────────────────────────────────────────────────────

    # ─── LABEL "TROPHY TREND" ─────────────────────────────────────────
    LABEL_TEXT  = "TROPHY TREND"
    LABEL_X     = rx0                  # ← X (left edge of right panel)
    LABEL_Y     = ry + 2               # ← Y (top-left of caption)
    LABEL_SIZE  = 13                   # ← font size
    LABEL_WT    = "semibold"           # ← weight
    LABEL_COLOR = COLORS["muted"]
    draw.text((LABEL_X, LABEL_Y), LABEL_TEXT,
              font=_get_font(LABEL_WT, LABEL_SIZE), fill=LABEL_COLOR)

    # ─── NUMBER "+1162" ──────────────────────────────────────────────
    NUMBER_X        = rx0              # ← X (left edge of digits)
    NUMBER_BASELINE = ry + 66          # ← Y of glyph baseline (smaller=higher)
    NUMBER_SIZE     = 54               # ← font size
    NUMBER_WT       = "bold"           # ← weight
    NUMBER_COLOR    = net_color        # ← auto: green if net>=0, red if <0
    net_font = _get_font(NUMBER_WT, NUMBER_SIZE)
    draw.text((NUMBER_X, NUMBER_BASELINE), net_str,
              font=net_font, fill=NUMBER_COLOR, anchor="ls")
    net_w = _text_width(draw, net_str, net_font)

    # ─── TROPHY 🏆 emoji ─────────────────────────────────────────────
    TROPHY_GAP      = 12               # ← gap between number and emoji
    TROPHY_BASELINE = NUMBER_BASELINE  # ← Y baseline (default: same as number)
    TROPHY_SIZE     = 32               # ← emoji font size
    TROPHY_X        = NUMBER_X + net_w + TROPHY_GAP
    try:
        trophy_font = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", TROPHY_SIZE)
    except OSError:
        trophy_font = _get_font("medium", TROPHY_SIZE)
    draw.text((TROPHY_X, TROPHY_BASELINE), "🏆",
              font=trophy_font, fill=COLORS["fg"],
              embedded_color=True, anchor="ls")

    # Re-export for code below that references net_baseline (chart card pos).
    net_baseline = NUMBER_BASELINE

    # Peak (right-aligned). Designer fix #7: in JSX, PEAK label and value
    # are stacked tightly (marginTop: 2). Old layout pinned the value to
    # net_baseline, putting it 60+ px below PEAK. Now the value sits right
    # under its label.
    peak_val = max(curve) if curve else g_cur
    peak_label = "PEAK"
    pkl_font = _get_font("semibold", 11)
    pkv_font = _get_font("semibold", 18)
    pkl_w = _text_width(draw, peak_label, pkl_font)
    draw.text((rx1 - pkl_w, ry + 2), peak_label, font=pkl_font, fill=COLORS["muted"])
    pkl_h = _text_height(pkl_font)
    pkv_text = str(peak_val)
    pkv_w = _text_width(draw, pkv_text, pkv_font)
    draw.text((rx1 - pkv_w, ry + 2 + pkl_h + 2), pkv_text,
              font=pkv_font, fill=COLORS["fg"])

    # Chart card
    chart_y0 = ry + 98
    chart_y1 = H - PAD
    _rounded_rect(work, (rx0, chart_y0, rx1, chart_y1), radius=14,
                  fill=COLORS["bg1"], outline=COLORS["stroke"], width=1)

    # Start / Now tiny header inside the card
    inner_pad = 14
    cap_font = _get_font("medium", 11)
    start_text = f"Start · {g_start}"
    now_text = f"Now · {g_cur}"
    draw.text((rx0 + inner_pad, chart_y0 + inner_pad - 2),
              start_text, font=cap_font, fill=COLORS["muted"])
    now_w = _text_width(draw, now_text, cap_font)
    draw.text((rx1 - inner_pad - now_w, chart_y0 + inner_pad - 2),
              now_text, font=cap_font, fill=COLORS["muted"])

    # Chart itself
    chart_box = (
        rx0 + inner_pad,
        chart_y0 + inner_pad + 16,
        rx1 - inner_pad,
        chart_y1 - inner_pad,
    )
    _draw_trend_chart(work, chart_box, [float(v) for v in curve],
                      color=trend_color, show_dots=True)

    out = io.BytesIO()
    work.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


__all__ = ["render_milestone_card_a"]
