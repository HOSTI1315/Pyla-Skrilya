"""FastAPI server: REST + WebSocket + static frontend."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.bot_runner import RUNNER
from backend.instance_manager import MANAGER, discover_ldplayer_instances
from backend.state import STATE

REPO_ROOT = Path(__file__).resolve().parent.parent
CFG_DIR = REPO_ROOT / "cfg"
ICON_DIR = REPO_ROOT / "api" / "assets" / "brawler_icons"
UI_DIR = REPO_ROOT / "web_ui"

CONFIG_FILES = {
    "general": CFG_DIR / "general_config.toml",
    "bot": CFG_DIR / "bot_config.toml",
    "lobby": CFG_DIR / "lobby_config.toml",
    "time": CFG_DIR / "time_tresholds.toml",
    "match_history": CFG_DIR / "match_history.toml",
    "brawl_stars_api": CFG_DIR / "brawl_stars_api.toml",
    "webhook": CFG_DIR / "webhook_config.toml",
}
PLAYSTYLES_DIR = CFG_DIR.parent / "playstyles"
BRAWL_STARS_API_FILE = CFG_DIR / "brawl_stars_api.toml"
BRAWLER_STATS_FILE = CFG_DIR / "brawler_stats.toml"

# --- lazy utils import so the server can boot without ML deps first ---
def _utils():
    from utils import load_toml_as_dict, save_dict_as_toml, cprint  # noqa: F401
    return load_toml_as_dict, save_dict_as_toml


def _read_match_log(limit=None, brawler=None, gamemode=None):
    from utils import read_match_log
    return read_match_log(limit=limit, brawler=brawler, gamemode=gamemode)


def _load_toml_fresh(path):
    """Read a toml file off disk, bypassing utils.cached_toml.

    The bot writes match_history.toml mid-run; the cache in utils does not
    invalidate across the relative/absolute path the backend uses, so reading
    via the cached helper returns stale data. This always hits disk.
    """
    import toml
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return toml.load(f) or {}
    except Exception:
        return {}


def _ru_names():
    try:
        from gui.brawler_names_ru import RU_NAMES, display_name
        return RU_NAMES, display_name
    except Exception:
        return {}, lambda k: (k or "").upper()


# ──────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="PylaAI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    STATE.bind_loop(asyncio.get_running_loop())
    # First-run defaults: seed empty match_log / match_history / brawler_stats
    # so the web UI doesn't display "no data" forever on a fresh install. Real
    # bot writes append on top of these. Touch every per-instance cfg dir too
    # so a friend's instance starts with valid stat files.
    from utils import bootstrap_stat_files
    bootstrap_stat_files(str(CFG_DIR))
    inst_root = REPO_ROOT / "instances"
    if inst_root.is_dir():
        for sub in inst_root.iterdir():
            inst_cfg = sub / "cfg"
            if inst_cfg.is_dir():
                bootstrap_stat_files(str(inst_cfg))


# ──────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────
class SessionConfig(BaseModel):
    brawler: str
    type: str = "trophies"          # "trophies" | "wins"
    push_until: int = 1000
    trophies: int = 0
    wins: int = 0
    win_streak: int = 0
    automatically_pick: bool = True
    run_for_minutes: Optional[int] = None


class ConfigPatch(BaseModel):
    values: Dict[str, Any]


# ──────────────────────────────────────────────────────────────────────
# Brawlers / icons
# ──────────────────────────────────────────────────────────────────────
def _resolve_cfg_root(instance_id: Optional[int]) -> Path:
    """Pick the cfg dir to read from. None / 0 -> global; N -> per-instance.

    Falls back to global cfg if the per-instance dir doesn't exist so a stale
    instance_id query param doesn't 500 the page.
    """
    if instance_id is None or int(instance_id) <= 0:
        return CFG_DIR
    inst_cfg = REPO_ROOT / "instances" / str(int(instance_id)) / "cfg"
    return inst_cfg if inst_cfg.is_dir() else CFG_DIR


@app.get("/api/brawlers")
def get_brawlers(instance_id: Optional[int] = None) -> Dict[str, Any]:
    """Brawler roster + per-brawler stats.

    instance_id=None / 0 -> reads global cfg/.
    instance_id=N        -> reads instances/N/cfg/ for trophies, history, scan stamps.
                            brawlers_info.json + icons stay global (they don't change
                            per-account).
    """
    cfg_root = _resolve_cfg_root(instance_id)
    # brawlers_info.json is account-agnostic — keep it global.
    info_path = CFG_DIR / "brawlers_info.json"
    if not info_path.exists():
        return {"brawlers": []}
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    history = _load_toml_fresh(cfg_root / "match_history.toml")
    stats_path = cfg_root / "brawler_stats.toml"
    stats = _load_toml_fresh(stats_path) if stats_path.exists() else {}
    _, display_name = _ru_names()
    # Same upper bound as the scanner uses to reject obviously wrong OCR reads
    # (e.g. `lumi: 5496` left over from a botched scan). Anything above this is
    # surfaced as 0 so the UI shows "no data" instead of a fake number.
    from backend.lobby_scanner import MAX_TROPHIES_SANITY
    out: List[Dict[str, Any]] = []
    for key, val in info.items():
        icon_exists = (ICON_DIR / f"{key}.png").exists()
        h = history.get(key) or {}
        v = int(h.get("victory", 0) or 0)
        d = int(h.get("defeat", 0) or 0)
        dr = int(h.get("draw", 0) or 0)
        games = v + d + dr
        wr = round(v / games * 100) if games else 0
        s = stats.get(key) or {}
        raw_trophies = int(s.get("trophies") or 0)
        trophies = raw_trophies if 0 <= raw_trophies <= MAX_TROPHIES_SANITY else 0
        out.append(
            {
                "id": key,
                "key": key,
                "name_en": key.upper(),
                "name": display_name(key),
                "icon_url": f"/icons/{key}.png" if icon_exists else None,
                "safe_range": val.get("safe_range"),
                "attack_range": val.get("attack_range"),
                "super_type": val.get("super_type"),
                "super_range": val.get("super_range"),
                "trophies": trophies,
                "streak": int(s.get("streak") or 0),
                "scanned_at": s.get("scanned_at") or None,
                "games": games,
                "wins": v,
                "losses": d,
                "draws": dr,
                "wr": wr,
            }
        )
    out.sort(key=lambda b: b["name"])
    return {"brawlers": out}


@app.get("/icons/{brawler}.png")
def get_icon(brawler: str) -> FileResponse:
    path = ICON_DIR / f"{brawler}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="icon not found")
    return FileResponse(path)


# ──────────────────────────────────────────────────────────────────────
# Config read / write
# ──────────────────────────────────────────────────────────────────────
@app.get("/api/config/{name}")
def read_config(name: str) -> Dict[str, Any]:
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config '{name}'")
    load_toml_as_dict, _ = _utils()
    path = str(CONFIG_FILES[name])
    return load_toml_as_dict(path)


@app.put("/api/config/{name}")
def write_config(name: str, patch: ConfigPatch) -> Dict[str, Any]:
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config '{name}'")
    load_toml_as_dict, save_dict_as_toml = _utils()
    path = str(CONFIG_FILES[name])
    current = dict(load_toml_as_dict(path))
    current.update(patch.values)
    save_dict_as_toml(current, path)
    return {"ok": True, "config": current}


# ──────────────────────────────────────────────────────────────────────
# Performance profiles — applies known-good settings to general+bot configs
# ──────────────────────────────────────────────────────────────────────
class PerformanceProfileRequest(BaseModel):
    profile: str = "balanced"


@app.get("/api/performance-profile/list")
def list_performance_profiles() -> Dict[str, Any]:
    from performance_profile import PERFORMANCE_PROFILES
    profiles = []
    for key, data in PERFORMANCE_PROFILES.items():
        profiles.append({
            "key": key,
            "description": data.get("description", ""),
            "general_keys": data.get("general_config", {}),
            "bot_keys": data.get("bot_config", {}),
        })
    return {"profiles": profiles}


@app.post("/api/performance-profile/apply")
def apply_perf_profile(req: PerformanceProfileRequest) -> Dict[str, Any]:
    from performance_profile import apply_performance_profile
    if RUNNER.is_running():
        raise HTTPException(status_code=409, detail="bot is running — stop the session first")
    try:
        result = apply_performance_profile(req.profile, save=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "ok": True,
        "profile": result["profile"],
        "description": result["description"],
        "changed_general_keys": result["changed_general_keys"],
        "changed_bot_keys": result["changed_bot_keys"],
    }


# ──────────────────────────────────────────────────────────────────────
# Playstyles — list / upload / delete / read-source for the .pyla files in
# `playstyles/`. Files are runtime-imported Python so we treat them as user
# scripts: any user with access to the UI can already run code on this host.
# We still defend against path traversal (basename only) and broken headers.
# ──────────────────────────────────────────────────────────────────────
PLAYSTYLE_DEFAULT = "default.pyla"
PLAYSTYLE_MAX_BYTES = 256 * 1024  # 256 KB is plenty for the longest playstyle


def _playstyle_path(file_name: str) -> Path:
    """Resolve <file_name> inside PLAYSTYLES_DIR or raise HTTPException."""
    if not file_name or not isinstance(file_name, str):
        raise HTTPException(status_code=400, detail="missing file name")
    base = os.path.basename(file_name).strip()
    if base != file_name or base in ("", ".", "..") or "/" in base or "\\" in base:
        raise HTTPException(status_code=400, detail="invalid file name")
    if not base.lower().endswith(".pyla"):
        raise HTTPException(status_code=400, detail="must be a .pyla file")
    return PLAYSTYLES_DIR / base


def _playstyle_meta(path: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "file": path.name,
        "name": path.stem,
        "description": "",
        "is_default": path.name == PLAYSTYLE_DEFAULT,
    }
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return meta
    try:
        st = path.stat()
        meta["size"] = st.st_size
        meta["mtime"] = int(st.st_mtime)
    except OSError:
        pass
    try:
        start = text.find("{")
        end = text.find("}", start)
        if start != -1 and end != -1:
            header = json.loads(text[start:end + 1])
            if isinstance(header, dict):
                meta["name"] = str(header.get("name", meta["name"]))
                meta["description"] = str(header.get("description", ""))
                if header.get("author"):
                    meta["author"] = str(header["author"])
                if header.get("version"):
                    meta["version"] = str(header["version"])
    except (ValueError, json.JSONDecodeError):
        meta["header_error"] = "could not parse JSON header"
    return meta


@app.get("/api/playstyles/list")
def list_playstyles() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    if not PLAYSTYLES_DIR.exists():
        return {"playstyles": items}
    for path in sorted(PLAYSTYLES_DIR.glob("*.pyla")):
        items.append(_playstyle_meta(path))
    return {"playstyles": items}


@app.get("/api/playstyles/source")
def read_playstyle_source(file: str) -> Dict[str, Any]:
    """Return the text of a .pyla file so the UI can preview it before applying.

    Used by the "view source" button. Refuses oversize files.
    """
    path = _playstyle_path(file)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{file} not found")
    try:
        st = path.stat()
        if st.st_size > PLAYSTYLE_MAX_BYTES:
            raise HTTPException(status_code=413, detail="playstyle file too large to preview")
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not read playstyle: {e}")
    return {"file": path.name, "size": st.st_size, "text": text, "meta": _playstyle_meta(path)}


@app.post("/api/playstyles/upload")
async def upload_playstyle(file: UploadFile = File(...), overwrite: bool = False) -> Dict[str, Any]:
    """Upload a .pyla file into playstyles/.

    The runtime imports these as Python — the file is *executable code*. The UI
    is expected to warn the user. Server-side guards: basename only, .pyla
    extension, size cap, valid JSON header (description must exist).
    """
    target = _playstyle_path(file.filename or "")
    body = await file.read()
    if len(body) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if len(body) > PLAYSTYLE_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {PLAYSTYLE_MAX_BYTES // 1024} KB cap")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="playstyle must be UTF-8 text")

    # Validate that the leading line is a parseable JSON header — that's how
    # the runtime locates name/description/etc.
    first_line = text.splitlines()[0] if text else ""
    try:
        header = json.loads(first_line)
        if not isinstance(header, dict) or not header.get("name"):
            raise ValueError("header must be a JSON object with at least a 'name' field")
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid playstyle header: {e}")

    if target.exists() and not overwrite:
        raise HTTPException(status_code=409, detail=f"{target.name} already exists — pass overwrite=true to replace")
    if target.name == PLAYSTYLE_DEFAULT and not overwrite:
        # Allow updating default only with explicit overwrite — typical usage
        # is "I tweaked default.pyla locally and want to push my version."
        raise HTTPException(status_code=409, detail="cannot replace default.pyla without overwrite=true")

    PLAYSTYLES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(body)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not save playstyle: {e}")

    return {"ok": True, "file": target.name, "meta": _playstyle_meta(target), "overwritten": True if overwrite else False}


@app.delete("/api/playstyles/{file}")
def delete_playstyle(file: str) -> Dict[str, Any]:
    """Delete a user-uploaded playstyle. Refuses to delete default.pyla and the
    currently-selected playstyle (so the runtime never points at a missing file).
    """
    path = _playstyle_path(file)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{file} not found")
    if path.name == PLAYSTYLE_DEFAULT:
        raise HTTPException(status_code=400, detail="default.pyla is protected and cannot be deleted")
    # Refuse if it's the active selection.
    try:
        load_toml_as_dict, _ = _utils()
        bot_cfg = load_toml_as_dict(str(CONFIG_FILES["bot"]))
        active = str(bot_cfg.get("current_playstyle", "")).strip()
        if active == path.name:
            raise HTTPException(
                status_code=409,
                detail=f"{path.name} is currently active — switch to another playstyle first",
            )
    except HTTPException:
        raise
    except Exception:
        # If we can't read the config, fall through and allow delete; the bot
        # would error on its own restart, which is the same outcome.
        pass
    try:
        path.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not delete playstyle: {e}")
    return {"ok": True, "file": path.name}


# ──────────────────────────────────────────────────────────────────────
# Match history / state / control
# ──────────────────────────────────────────────────────────────────────
@app.get("/api/match-history")
def match_history(
    limit: int = 200,
    brawler: Optional[str] = None,
    gamemode: Optional[str] = None,
) -> Dict[str, Any]:
    """Return per-match entries from cfg/match_log.jsonl (newest first)."""
    capped = max(0, min(int(limit or 0), 3000))
    entries = _read_match_log(limit=capped, brawler=brawler, gamemode=gamemode)
    _, display_name = _ru_names()
    for entry in entries:
        key = entry.get("brawler") or ""
        entry["brawler_name"] = display_name(key)
    return {"entries": entries, "count": len(entries)}


@app.get("/api/sessions")
def sessions(limit: int = 20) -> Dict[str, Any]:
    """Return the most recent bot-run sessions, newest first."""
    from sessions import recent_sessions
    capped = max(0, min(int(limit or 0), 1000))
    entries = recent_sessions(n=capped)
    return {"entries": entries, "count": len(entries)}


def _enumerate_cfg_roots(instance_id: Optional[int], aggregate: bool) -> List[Path]:
    """Decide which cfg dirs the stats endpoint should pull from.

    aggregate=True (default for fresh callers): walks global ``cfg/`` PLUS
        every ``instances/N/cfg/`` so the Stats page reflects multi-emulator
        farming.
    aggregate=False:
        instance_id=None / 0 -> global only (legacy single-instance behaviour)
        instance_id=N        -> just that instance
    """
    roots: List[Path] = []
    if instance_id is not None and int(instance_id) > 0:
        ic = REPO_ROOT / "instances" / str(int(instance_id)) / "cfg"
        if ic.is_dir():
            return [ic]
        return [CFG_DIR]
    if aggregate:
        if CFG_DIR.is_dir():
            roots.append(CFG_DIR)
        inst_root = REPO_ROOT / "instances"
        if inst_root.is_dir():
            for sub in sorted(inst_root.iterdir()):
                ic = sub / "cfg"
                if ic.is_dir():
                    roots.append(ic)
        return roots or [CFG_DIR]
    return [CFG_DIR]


def _read_match_log_at(path: Path) -> List[Dict[str, Any]]:
    """Read one specific match_log.jsonl, newest first. Used by aggregation
    so we can sum entries from every cfg root explicitly."""
    if not path.is_file():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except (ValueError, TypeError):
                    continue
    except OSError:
        return []
    entries.reverse()
    return entries


@app.get("/api/stats")
def stats(instance_id: Optional[int] = None, aggregate: bool = True) -> Dict[str, Any]:
    """Aggregate real match history for the Stats / Modes / Dashboard pages.

    Query params:
      instance_id=N : pin to one instance's cfg (overrides aggregate)
      aggregate=true (default) : merge global cfg/ + every instances/N/cfg/
      aggregate=false : just global cfg/

    match_history.toml stores {brawler: {victory, defeat, draw}} + a 'total'
    entry. Anything not present yields zero / empty arrays.
    """
    cfg_roots = _enumerate_cfg_roots(instance_id, aggregate)
    _, display_name = _ru_names()

    # Merge match_history.toml across roots (sum buckets per brawler).
    hist: Dict[str, Dict[str, int]] = {}
    for root in cfg_roots:
        h = _load_toml_fresh(root / "match_history.toml")
        for key, row in h.items():
            if not isinstance(row, dict):
                continue
            slot = hist.setdefault(key, {"victory": 0, "defeat": 0, "draw": 0})
            for bucket in ("victory", "defeat", "draw"):
                try:
                    slot[bucket] += int(row.get(bucket, 0) or 0)
                except (TypeError, ValueError):
                    pass

    # Concatenate every match_log.jsonl across roots, newest first.
    log_entries: List[Dict[str, Any]] = []
    for root in cfg_roots:
        log_entries.extend(_read_match_log_at(root / "match_log.jsonl"))
    log_entries.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    # source breakdown so the UI can show "X / Y instances contributing"
    sources = [str(r.relative_to(REPO_ROOT) if r.is_absolute() else r) for r in cfg_roots]

    trophies_gained = 0
    trophies_lost = 0
    per_brawler_trophies: Dict[str, Dict[str, int]] = {}
    for e in log_entries:
        try:
            d = int(e.get("delta") or 0)
        except (TypeError, ValueError):
            d = 0
        if d > 0:
            trophies_gained += d
        elif d < 0:
            trophies_lost += -d
        bk = (e.get("brawler") or "").strip()
        if bk:
            row = per_brawler_trophies.setdefault(bk, {"gained": 0, "lost": 0})
            if d > 0:
                row["gained"] += d
            elif d < 0:
                row["lost"] += -d

    brawler_perf: List[Dict[str, Any]] = []
    for key, row in hist.items():
        if key == "total" or not isinstance(row, dict):
            continue
        v = int(row.get("victory", 0) or 0)
        d = int(row.get("defeat", 0) or 0)
        dr = int(row.get("draw", 0) or 0)
        games = v + d + dr
        if games <= 0:
            continue
        tr = per_brawler_trophies.get(key) or {"gained": 0, "lost": 0}
        brawler_perf.append({
            "key": key,
            "name": display_name(key),
            "games": games,
            "wins": v,
            "losses": d,
            "draws": dr,
            "wr": round(v / games * 100) if games else 0,
            "trophies_gained": tr["gained"],
            "trophies_lost": tr["lost"],
            "trophies_net": tr["gained"] - tr["lost"],
        })
    brawler_perf.sort(key=lambda x: x["games"], reverse=True)

    total = hist.get("total") or {}
    total_v = int(total.get("victory", 0) or 0)
    total_d = int(total.get("defeat", 0) or 0)
    total_dr = int(total.get("draw", 0) or 0)
    total_games = total_v + total_d + total_dr

    mode_buckets: Dict[str, Dict[str, int]] = {}
    for e in log_entries:
        mode = (e.get("gamemode") or "").strip() or "unknown"
        bucket = e.get("bucket")
        if bucket not in ("victory", "defeat", "draw"):
            continue
        row = mode_buckets.setdefault(mode, {"victory": 0, "defeat": 0, "draw": 0})
        row[bucket] += 1

    mode_performance: List[Dict[str, Any]] = []
    for mode, row in mode_buckets.items():
        v = row["victory"]
        d = row["defeat"]
        dr = row["draw"]
        games = v + d + dr
        if games <= 0:
            continue
        mode_performance.append({
            "mode": mode,
            "games": games,
            "wins": v,
            "losses": d,
            "draws": dr,
            "wr": round(v / games * 100),
        })
    mode_performance.sort(key=lambda x: x["games"], reverse=True)

    recent_form: List[str] = []
    for e in log_entries[:20]:
        b = e.get("bucket")
        if b == "victory":
            recent_form.append("W")
        elif b == "defeat":
            recent_form.append("L")
        elif b == "draw":
            recent_form.append("D")

    # Cumulative trophy curve across the whole match log (oldest -> newest).
    # We only have deltas, so the curve is relative — starts at 0 and tracks
    # the running net. Downsampled to ~200 points so the SVG stays light even
    # with the full 3000-entry log.
    running = 0
    trophy_curve_total: List[int] = [0]
    for e in reversed(log_entries):
        try:
            d = int(e.get("delta") or 0)
        except (TypeError, ValueError):
            d = 0
        running += d
        trophy_curve_total.append(running)
    if len(trophy_curve_total) > 200:
        step = len(trophy_curve_total) / 200
        trophy_curve_total = (
            [trophy_curve_total[int(i * step)] for i in range(200)]
            + [trophy_curve_total[-1]]
        )

    return {
        "brawler_performance": brawler_perf,
        "mode_performance": mode_performance,
        "recent_form": recent_form,
        "recent_matches": log_entries[:10],
        "trophy_curve_total": trophy_curve_total,
        "sources": sources,
        "totals": {
            "games": total_games,
            "wins": total_v,
            "losses": total_d,
            "draws": total_dr,
            "wr": round(total_v / total_games * 100) if total_games else 0,
            "trophies_gained": trophies_gained,
            "trophies_lost": trophies_lost,
            "trophies_net": trophies_gained - trophies_lost,
        },
    }


@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    return STATE.snapshot()


@app.post("/api/start")
def start_bot(payload: List[SessionConfig]) -> Dict[str, Any]:
    if not payload:
        raise HTTPException(status_code=400, detail="payload must contain at least one brawler entry")

    # stage_manager.start_game exits the process when current >= target, so
    # reject obviously broken payloads up-front instead of letting the bot
    # connect, pick the brawler, and die on the first lobby check.
    head = payload[0]
    current = head.trophies if head.type == "trophies" else head.wins
    if head.push_until <= 0:
        raise HTTPException(status_code=400, detail="push_until must be greater than 0")
    if current >= head.push_until:
        raise HTTPException(
            status_code=400,
            detail=f"current {head.type} ({current}) already >= target ({head.push_until})",
        )

    # run_for_minutes is a global setting read from general_config.toml by the bot.
    # Mirror the legacy Tk flow where the timer input writes this before start.
    run_for = payload[0].run_for_minutes
    if run_for is not None:
        try:
            load_toml_as_dict, save_dict_as_toml = _utils()
            cfg = dict(load_toml_as_dict(str(CONFIG_FILES["general"])))
            cfg["run_for_minutes"] = int(run_for)
            save_dict_as_toml(cfg, str(CONFIG_FILES["general"]))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to persist run_for_minutes: {exc}")

    # Strip the transient `run_for_minutes` field so bot_runner.save_brawler_data
    # writes a shape identical to the legacy select_brawler.py payload.
    items = []
    for item in payload:
        d = item.model_dump()
        d.pop("run_for_minutes", None)
        items.append(d)

    try:
        RUNNER.start(items)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "state": STATE.snapshot()}


@app.post("/api/stop")
def stop_bot() -> Dict[str, Any]:
    RUNNER.stop()
    return {"ok": True}


@app.post("/api/pause")
def pause_bot() -> Dict[str, Any]:
    RUNNER.pause()
    return {"ok": True}


@app.post("/api/resume")
def resume_bot() -> Dict[str, Any]:
    RUNNER.resume()
    return {"ok": True}


@app.post("/api/log")
def inject_log(entry: Dict[str, Any]) -> Dict[str, Any]:
    STATE.push_log(entry.get("msg", ""), level=entry.get("lvl"))
    return {"ok": True}


# ──────────────────────────────────────────────────────────────────────
# Instances (multi-emulator) — each instance is a separate ``python main.py
# --instance N`` subprocess; the legacy /api/start aliases the in-process
# RUNNER, /api/instances/* drives the subprocess pool.
# ──────────────────────────────────────────────────────────────────────
class InstanceCreate(BaseModel):
    name: str = ""
    emulator: str = "LDPlayer"
    port: int = 0
    copy_from: Optional[int] = None


@app.get("/api/instances")
def list_instances() -> Dict[str, Any]:
    return {"instances": MANAGER.list_instances()}


@app.post("/api/instances")
def create_instance(payload: InstanceCreate) -> Dict[str, Any]:
    snap = MANAGER.create(
        name=payload.name,
        emulator=payload.emulator,
        port=int(payload.port or 0),
        copy_from=payload.copy_from,
    )
    return snap


@app.delete("/api/instances/{instance_id}")
def delete_instance(instance_id: int) -> Dict[str, Any]:
    ok = MANAGER.delete(instance_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"instance {instance_id} not found")
    return {"ok": True}


@app.get("/api/instances/{instance_id}")
def get_instance(instance_id: int) -> Dict[str, Any]:
    snap = MANAGER.get(instance_id)
    if snap.get("status") == "uninitialized":
        raise HTTPException(status_code=404, detail=f"instance {instance_id} not found")
    return snap


@app.post("/api/instances/{instance_id}/start")
def start_instance(instance_id: int, payload: List[SessionConfig]) -> Dict[str, Any]:
    items: Optional[List[Dict[str, Any]]] = None
    if payload:
        head = payload[0]
        current = head.trophies if head.type == "trophies" else head.wins
        if head.push_until <= 0:
            raise HTTPException(status_code=400, detail="push_until must be greater than 0")
        if current >= head.push_until:
            raise HTTPException(
                status_code=400,
                detail=f"current {head.type} ({current}) already >= target ({head.push_until})",
            )
        items = []
        for item in payload:
            d = item.model_dump()
            d.pop("run_for_minutes", None)
            items.append(d)
    try:
        # items=None → manager loads this instance's saved session
        # (per-instance individual session feature).
        snap = MANAGER.start(instance_id, items)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return snap


@app.post("/api/instances/{instance_id}/stop")
def stop_instance(instance_id: int) -> Dict[str, Any]:
    stopped = MANAGER.stop(instance_id)
    return {"ok": True, "stopped": stopped}


@app.get("/api/instances/{instance_id}/logs")
def instance_logs(instance_id: int, lines: int = 200, file: Optional[str] = None) -> Dict[str, Any]:
    return {
        "files": MANAGER.list_logs(instance_id),
        "tail": MANAGER.tail_log(instance_id, lines=lines, file=file),
    }


@app.websocket("/api/instances/{instance_id}/logs/stream")
async def instance_logs_stream(websocket: WebSocket, instance_id: int) -> None:
    """Live log tail. Sends initial 200-line backfill, then streams new lines
    as they appear. Reopens the underlying file when it rotates (a fresh
    ``manager_<ts>.log`` is created on every start)."""
    from backend.instance_manager import _logs_dir
    await websocket.accept()
    try:
        backfill = MANAGER.tail_log(instance_id, lines=200)
        for line in backfill:
            await websocket.send_json({"line": line, "backfill": True})

        current_path: Optional[Path] = None
        fh = None
        try:
            while True:
                # Pick the latest file each loop so a freshly-spawned bot's
                # log gets streamed without the user closing/reopening.
                files = sorted((_logs_dir(instance_id)).glob("*.log"),
                               key=lambda p: p.stat().st_mtime if p.exists() else 0)
                latest = files[-1] if files else None
                if latest != current_path:
                    if fh is not None:
                        try: fh.close()
                        except Exception: pass
                        fh = None
                    current_path = latest
                    if current_path is not None:
                        try:
                            fh = open(current_path, "r", encoding="utf-8", errors="replace")
                            fh.seek(0, os.SEEK_END)  # only stream new lines
                        except Exception:
                            fh = None

                if fh is not None:
                    while True:
                        line = fh.readline()
                        if not line:
                            break
                        await websocket.send_json({"line": line.rstrip("\n"), "backfill": False})

                await asyncio.sleep(0.5)
        finally:
            if fh is not None:
                try: fh.close()
                except Exception: pass
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({"error": str(exc)})
        except Exception:
            pass


# ── Per-instance config editor ────────────────────────────────────────
@app.get("/api/instances/{instance_id}/config/{section}")
def get_instance_config(instance_id: int, section: str) -> Dict[str, Any]:
    """Read one of the per-instance toml files. ``section`` matches the same
    keys CONFIG_FILES uses for the global editor (general, bot, time, …)."""
    if section not in CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"unknown config section: {section}")
    inst_root = REPO_ROOT / "instances" / str(int(instance_id)) / "cfg"
    if not inst_root.is_dir():
        raise HTTPException(status_code=404, detail=f"instance {instance_id} has no cfg dir")
    fname = CONFIG_FILES[section].name
    target = inst_root / fname
    if not target.is_file():
        return {"section": section, "values": {}}
    import toml
    try:
        return {"section": section, "values": toml.loads(target.read_text(encoding="utf-8-sig"))}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"could not read {target}: {exc}")


@app.put("/api/instances/{instance_id}/config/{section}")
def put_instance_config(instance_id: int, section: str, payload: ConfigPatch) -> Dict[str, Any]:
    """Merge-write per-instance config. Mirrors the global PUT /api/config/X
    semantics so the UI can reuse the same form shape."""
    if section not in CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"unknown config section: {section}")
    inst_root = REPO_ROOT / "instances" / str(int(instance_id)) / "cfg"
    if not inst_root.is_dir():
        raise HTTPException(status_code=404, detail=f"instance {instance_id} has no cfg dir")
    fname = CONFIG_FILES[section].name
    target = inst_root / fname
    import toml
    existing = {}
    if target.is_file():
        try:
            existing = toml.loads(target.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            existing = {}
    existing.update(payload.values or {})
    target.write_text(toml.dumps(existing), encoding="utf-8")
    return {"section": section, "values": existing}


@app.post("/api/instances/{instance_id}/restart_emulator")
def restart_instance_emulator(instance_id: int) -> Dict[str, Any]:
    return MANAGER.restart_emulator(instance_id)


# ── Per-instance saved session (so each emulator can run a different brawler)
class InstanceSession(BaseModel):
    session: List[SessionConfig]


@app.get("/api/instances/{instance_id}/session")
def get_instance_session(instance_id: int) -> Dict[str, Any]:
    s = MANAGER.get_session(instance_id) or {}
    return {"brawlers_data": s.get("brawlers_data") or [], "saved_at": s.get("saved_at")}


@app.put("/api/instances/{instance_id}/session")
def put_instance_session(instance_id: int, payload: InstanceSession) -> Dict[str, Any]:
    items = []
    for item in payload.session:
        d = item.model_dump()
        d.pop("run_for_minutes", None)
        items.append(d)
    try:
        return MANAGER.put_session(instance_id, items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/instances/{instance_id}/session")
def clear_instance_session(instance_id: int) -> Dict[str, Any]:
    return {"ok": MANAGER.clear_session(instance_id)}


class AutoRestartToggle(BaseModel):
    enabled: bool


@app.put("/api/instances/{instance_id}/auto_restart")
def set_instance_auto_restart(instance_id: int, payload: AutoRestartToggle) -> Dict[str, Any]:
    return MANAGER.set_auto_restart(instance_id, payload.enabled)


# ── Per-instance display label (e.g. "HOSTI", "Farm 2") ──────────────
class InstanceRename(BaseModel):
    name: str


@app.put("/api/instances/{instance_id}/name")
def rename_instance(instance_id: int, payload: InstanceRename) -> Dict[str, Any]:
    try:
        return MANAGER.rename(instance_id, payload.name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Per-instance Push All ────────────────────────────────────────────
# Reads THIS instance's brawl_stars_api.toml (token + player_tag), fetches
# trophies, builds the same lowest-trophies queue as /api/push-all, and starts
# the instance subprocess. Each emulator can target a different account.
class InstancePushAllRequest(BaseModel):
    target_trophies: int = 1000


def _resolve_brawl_stars_api_cfg(instance_cfg_path: Optional[Path]) -> Dict[str, Any]:
    """Build the active Brawl Stars API config for a per-instance call.

    Policy (driven by user's UX feedback): the API token + dev_email/password
    + auto_refresh flags live ONLY in the global cfg/brawl_stars_api.toml —
    one app-wide token shared across every emulator. The per-instance file
    only overrides ``player_tag`` so each emulator can target a different
    account. If the per-instance file omits ``player_tag``, fall back to the
    global one.
    """
    from utils import load_brawl_stars_api_config

    global_cfg = load_brawl_stars_api_config(str(BRAWL_STARS_API_FILE))
    if instance_cfg_path is None or not instance_cfg_path.is_file():
        return dict(global_cfg)

    import toml as _toml
    try:
        per_instance = _toml.loads(instance_cfg_path.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        per_instance = {}

    merged = dict(global_cfg)
    inst_tag = str(per_instance.get("player_tag") or "").strip()
    if inst_tag and inst_tag.upper() != "#YOURTAG":
        merged["player_tag"] = inst_tag
    return merged


def _build_push_all_payload(api_cfg_path: Path, target: int) -> List[Dict[str, Any]]:
    """Shared helper: query Brawl Stars API and return a sorted-ascending
    session payload of brawlers below ``target``."""
    from utils import fetch_brawl_stars_player, normalize_brawler_name

    info_path = CFG_DIR / "brawlers_info.json"
    if not info_path.exists():
        raise HTTPException(status_code=500, detail="brawlers_info.json not found")
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    known = {normalize_brawler_name(k): k for k in info.keys()}

    cfg = _resolve_brawl_stars_api_cfg(api_cfg_path)
    try:
        player = fetch_brawl_stars_player(
            cfg.get("api_token", "").strip(),
            cfg.get("player_tag", "").strip(),
            int(cfg.get("timeout_seconds", 15)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Brawl Stars API failed: {exc}")

    rows: List[tuple] = []
    for index, api_brawler in enumerate(player.get("brawlers", [])):
        key = known.get(normalize_brawler_name(api_brawler.get("name", "")))
        if not key:
            continue
        trophies = int(api_brawler.get("trophies", 0))
        if trophies < target:
            rows.append((trophies, index, key))
    rows.sort(key=lambda r: (r[0], r[1]))

    payload: List[Dict[str, Any]] = []
    for trophies, _, key in rows:
        payload.append({
            "brawler": key,
            "type": "trophies",
            "push_until": target,
            "trophies": trophies,
            "wins": 0,
            "win_streak": 0,
            "automatically_pick": True,
            "selection_method": "lowest_trophies",
        })
    return payload


@app.post("/api/instances/{instance_id}/push_all")
def push_all_instance(instance_id: int, payload_req: Optional[InstancePushAllRequest] = None) -> Dict[str, Any]:
    target = int(payload_req.target_trophies) if payload_req else 1000
    if target <= 0:
        raise HTTPException(status_code=400, detail="target_trophies must be > 0")

    api_cfg = MANAGER.cfg_path(instance_id, "brawl_stars_api.toml")
    if not api_cfg.is_file():
        raise HTTPException(status_code=404, detail=f"instance {instance_id} has no brawl_stars_api.toml")

    items = _build_push_all_payload(api_cfg, target)
    if not items:
        raise HTTPException(status_code=400, detail=f"no brawlers below {target} trophies")

    # Persist as the instance's saved session so the watchdog/auto-restart
    # path also has something to resume into.
    MANAGER.put_session(instance_id, items)
    try:
        snap = MANAGER.start(instance_id, items)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "ok": True,
        "count": len(items),
        "target_trophies": target,
        "instance": snap,
    }


# ── Per-instance webhook test ────────────────────────────────────────
# Sends a test embed using the *instance's* webhook_config.toml (and falls back
# to the shared one if the per-instance file is empty). Lets the user verify
# notifications work from each emulator without waiting for a real match.
@app.post("/api/instances/{instance_id}/webhook/test")
def webhook_test_instance(instance_id: int) -> Dict[str, Any]:
    webhook_cfg = MANAGER.cfg_path(instance_id, "webhook_config.toml")
    if not webhook_cfg.is_file():
        raise HTTPException(status_code=404, detail=f"instance {instance_id} has no webhook_config.toml")

    # Read the per-instance webhook url directly so we don't have to flip the
    # global CONFIG_DIR (which would race with a running bot subprocess).
    import toml as _toml
    try:
        cfg = _toml.loads(webhook_cfg.read_text(encoding="utf-8-sig")) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to parse webhook_config.toml: {exc}")

    url = str(cfg.get("webhook_url") or "").strip()
    used_global = False
    if not url:
        # Per-instance URL empty → fall back to the global ``personal_webhook``
        # in cfg/general_config.toml. This matches the runtime path:
        # discord_notifier.load_webhook_settings already does the same fallback,
        # so the test reflects what real notifications would do.
        try:
            import toml as _toml
            gen = _toml.loads((CFG_DIR / "general_config.toml").read_text(encoding="utf-8-sig")) or {}
            url = str(gen.get("personal_webhook") or "").strip()
            used_global = bool(url)
        except Exception:
            url = ""
    if not url:
        raise HTTPException(status_code=400, detail="webhook_url is empty for this instance and no global personal_webhook is set")

    import asyncio as _asyncio
    import aiohttp
    from datetime import datetime, timezone

    async def _send() -> None:
        # Plain JSON post — avoids needing the discord lib's stateful Webhook
        # object for a quick test ping. Embed shape mirrors discord_notifier.
        body = {
            "username": str(cfg.get("username") or "PylaAI"),
            "embeds": [{
                "title": f"PylaAI · instance #{instance_id}",
                "description": ("Webhook test from the per-instance Cfg modal "
                                + ("(via global webhook)." if used_global
                                   else "(via instance-specific webhook).")),
                "color": 0x9B59B6,
                "footer": {"text": "PylaAI OP xxz"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, timeout=15) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"discord returned {resp.status}: {text[:200]}")

    try:
        _asyncio.run(_send())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"webhook test failed: {exc}")
    return {"ok": True, "instance_id": instance_id, "used_global": used_global}


# ── Aggregated dashboard view across all instances ───────────────────
# Path is `instances-dashboard` (not `instances/dashboard`) to avoid
# colliding with /api/instances/{instance_id} — FastAPI route order would
# otherwise try to parse "dashboard" as an int and 422 the request.
@app.get("/api/instances-dashboard")
def instances_dashboard() -> Dict[str, Any]:
    """Sum metrics across every instance for the Dashboard's "Сессия" panel.

    Combines per-instance heartbeats (battles / wins / losses / trophies_delta)
    so the global summary reflects every running emulator, not just the legacy
    in-process bot. Average match time is derived from total uptime / battles
    where data is available.
    """
    instances = MANAGER.list_instances()
    totals = {
        "instances_total": len(instances),
        "instances_running": 0,
        "battles": 0,
        "wins": 0,
        "losses": 0,
        "trophies_delta": 0,
        "uptime_sec": 0.0,
        "ips_sum": 0.0,
        "ips_count": 0,
    }
    per_instance: List[Dict[str, Any]] = []
    for inst in instances:
        m = inst.get("metrics") or {}
        if inst.get("status") in ("running", "starting", "stale"):
            totals["instances_running"] += 1
        battles = int(m.get("battles") or 0)
        wins = int(m.get("wins") or 0)
        losses = int(m.get("losses") or 0)
        delta = int(m.get("trophies_delta") or 0)
        uptime = float(m.get("uptime_sec") or 0.0)
        ips = m.get("ips")
        totals["battles"] += battles
        totals["wins"] += wins
        totals["losses"] += losses
        totals["trophies_delta"] += delta
        totals["uptime_sec"] += uptime
        if ips is not None:
            totals["ips_sum"] += float(ips)
            totals["ips_count"] += 1
        per_instance.append({
            "id": inst.get("id"),
            "name": inst.get("name"),
            "status": inst.get("status"),
            "battles": battles,
            "wins": wins,
            "losses": losses,
            "trophies_delta": delta,
            "uptime_sec": uptime,
            "ips": ips,
            "win_rate": m.get("win_rate"),
            "current_brawler": (inst.get("heartbeat") or {}).get("current_brawler"),
        })
    avg_match_sec = (totals["uptime_sec"] / totals["battles"]) if totals["battles"] else None
    win_rate = (totals["wins"] / totals["battles"]) if totals["battles"] else None
    avg_ips = (totals["ips_sum"] / totals["ips_count"]) if totals["ips_count"] else None
    return {
        "totals": {
            "instances_total": totals["instances_total"],
            "instances_running": totals["instances_running"],
            "battles": totals["battles"],
            "wins": totals["wins"],
            "losses": totals["losses"],
            "trophies_delta": totals["trophies_delta"],
            "uptime_sec": round(totals["uptime_sec"], 1),
            "avg_match_sec": round(avg_match_sec, 1) if avg_match_sec else None,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "avg_ips": round(avg_ips, 2) if avg_ips is not None else None,
        },
        "instances": per_instance,
    }


# ── Broadcast: drive every instance from one Dashboard ────────────────
class StartAllPayload(BaseModel):
    # When ``session`` is omitted (None), each instance uses its own saved
    # session from PUT /api/instances/{id}/session. That powers the
    # "per-instance individual sessions" UX where each emulator pushes a
    # different brawler.
    session: Optional[List[SessionConfig]] = None
    instance_ids: Optional[List[int]] = None  # None == every instance


@app.post("/api/instances/start_all")
def start_all_instances(payload: StartAllPayload) -> Dict[str, Any]:
    items: Optional[List[Dict[str, Any]]] = None
    if payload.session:
        items = []
        for item in payload.session:
            d = item.model_dump()
            d.pop("run_for_minutes", None)
            items.append(d)

    targets = payload.instance_ids
    if targets is None:
        targets = [int(inst["id"]) for inst in MANAGER.list_instances()]
    started, skipped, errors = [], [], []
    for iid in targets:
        try:
            snap = MANAGER.start(int(iid), items)  # items=None → per-instance session
            started.append(snap)
        except RuntimeError as exc:
            msg = str(exc)
            if "already running" in msg:
                skipped.append({"id": iid, "reason": msg})
            else:
                errors.append({"id": iid, "error": msg})
        except Exception as exc:
            errors.append({"id": iid, "error": str(exc)})
    return {"started": started, "skipped": skipped, "errors": errors}


@app.post("/api/instances/stop_all")
def stop_all_instances(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    targets = (payload or {}).get("instance_ids")
    if targets is None:
        targets = [int(inst["id"]) for inst in MANAGER.list_instances()]
    stopped = []
    for iid in targets:
        try:
            ok = MANAGER.stop(int(iid))
            stopped.append({"id": iid, "stopped": bool(ok)})
        except Exception as exc:
            stopped.append({"id": iid, "stopped": False, "error": str(exc)})
    return {"results": stopped}


# ── Emulator auto-discovery (LDPlayer first, MuMu later) ──────────────
@app.get("/api/emulators/discover")
def emulators_discover(emulator: str = "LDPlayer") -> Dict[str, Any]:
    if emulator.lower() in ("ldplayer", "ld"):
        return discover_ldplayer_instances()
    # Stub for future MuMu / BlueStacks discovery; UI handles empty list.
    return {"console": None, "instances": [], "error": f"discovery for {emulator} not implemented yet"}


# ──────────────────────────────────────────────────────────────────────
# One-shot OCR scan of the brawler-selection grid
# ──────────────────────────────────────────────────────────────────────
class ScanRequest(BaseModel):
    brawler: Optional[str] = None


@app.get("/api/brawl-stars-api/trophies")
def brawl_stars_api_trophies() -> Dict[str, Any]:
    """Fetch per-brawler trophy counts from the official Brawl Stars API.

    Uses cfg/brawl_stars_api.toml (api_token + player_tag, optional auto_refresh).
    Returns `{ok, trophies: {brawler_key: int}}`. 502 if the API call fails so
    the UI can surface a readable error.
    """
    from utils import (
        fetch_brawl_stars_player,
        load_brawl_stars_api_config,
        normalize_brawler_name,
    )

    info_path = CFG_DIR / "brawlers_info.json"
    if not info_path.exists():
        raise HTTPException(status_code=500, detail="brawlers_info.json not found")
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    known = {normalize_brawler_name(k): k for k in info.keys()}

    try:
        cfg = load_brawl_stars_api_config(str(BRAWL_STARS_API_FILE))
        player = fetch_brawl_stars_player(
            cfg.get("api_token", "").strip(),
            cfg.get("player_tag", "").strip(),
            int(cfg.get("timeout_seconds", 15)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Brawl Stars API failed: {exc}")

    trophies: Dict[str, int] = {}
    for api_brawler in player.get("brawlers", []):
        key = known.get(normalize_brawler_name(api_brawler.get("name", "")))
        if key:
            trophies[key] = int(api_brawler.get("trophies", 0))
    return {"ok": True, "trophies": trophies}


@app.post("/api/brawl-stars-api/sync-all")
def brawl_stars_api_sync_all() -> Dict[str, Any]:
    """Pull every brawler's trophy count from the Brawl Stars API and persist.

    Mirrors what the brawler-goal modal does on per-brawler selection, but for
    the whole roster — writes into ``cfg/brawler_stats.toml`` so the Brawlers
    page picks the values up on its next refresh. Streak is preserved from
    whatever was there (the API doesn't expose per-brawler win streak).
    """
    if RUNNER.is_running():
        raise HTTPException(
            status_code=409,
            detail="bot is running — stop the session before syncing",
        )
    from utils import (
        fetch_brawl_stars_player,
        load_brawl_stars_api_config,
        normalize_brawler_name,
    )

    import time as _time
    started = _time.time()

    info_path = CFG_DIR / "brawlers_info.json"
    if not info_path.exists():
        raise HTTPException(status_code=500, detail="brawlers_info.json not found")
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    known = {normalize_brawler_name(k): k for k in info.keys()}

    try:
        cfg = load_brawl_stars_api_config(str(BRAWL_STARS_API_FILE))
        player = fetch_brawl_stars_player(
            cfg.get("api_token", "").strip(),
            cfg.get("player_tag", "").strip(),
            int(cfg.get("timeout_seconds", 15)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Brawl Stars API failed: {exc}")

    trophies: Dict[str, int] = {}
    for api_brawler in player.get("brawlers", []):
        key = known.get(normalize_brawler_name(api_brawler.get("name", "")))
        if key:
            trophies[key] = int(api_brawler.get("trophies", 0))

    load_toml_as_dict, save_dict_as_toml = _utils()
    existing: Dict[str, Any] = {}
    if BRAWLER_STATS_FILE.exists():
        try:
            existing = dict(load_toml_as_dict(str(BRAWLER_STATS_FILE)) or {})
        except Exception:
            existing = {}

    merged = dict(existing)
    now = _time.time()
    for key, t in trophies.items():
        prev = dict(merged.get(key) or {})
        prev["trophies"] = int(t)
        if prev.get("streak") is None:
            prev["streak"] = 0
        prev["scanned_at"] = now
        merged[key] = prev

    try:
        save_dict_as_toml(merged, str(BRAWLER_STATS_FILE))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to persist stats: {exc}")

    return {
        "ok": True,
        "count": len(trophies),
        "duration": round(_time.time() - started, 2),
        "trophies": trophies,
    }


class PushAllRequest(BaseModel):
    target_trophies: int = 1000


@app.post("/api/push-all")
@app.post("/api/push-all-1k")
def push_all(payload_req: Optional[PushAllRequest] = None) -> Dict[str, Any]:
    """Build a session payload for every brawler below `target_trophies` and start the bot.

    Mirrors the desktop `SelectBrawler.push_all_1k` flow but with a configurable
    threshold: query the Brawl Stars API, keep brawlers below `target_trophies`,
    sort by current trophies ascending, hand the list to the runner. First entry
    has `automatically_pick=True` so lobby_automation picks it in-lobby.

    `/api/push-all-1k` is kept as an alias for older clients (defaults to 1000).
    """
    if RUNNER.is_running():
        raise HTTPException(status_code=409, detail="bot is running — stop the session first")

    target = int(payload_req.target_trophies) if payload_req else 1000
    if target <= 0:
        raise HTTPException(status_code=400, detail="target_trophies must be > 0")

    from utils import (
        fetch_brawl_stars_player,
        load_brawl_stars_api_config,
        normalize_brawler_name,
    )

    info_path = CFG_DIR / "brawlers_info.json"
    if not info_path.exists():
        raise HTTPException(status_code=500, detail="brawlers_info.json not found")
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    known = {normalize_brawler_name(k): k for k in info.keys()}

    try:
        cfg = load_brawl_stars_api_config(str(BRAWL_STARS_API_FILE))
        player = fetch_brawl_stars_player(
            cfg.get("api_token", "").strip(),
            cfg.get("player_tag", "").strip(),
            int(cfg.get("timeout_seconds", 15)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Brawl Stars API failed: {exc}")

    rows: List[tuple] = []
    for index, api_brawler in enumerate(player.get("brawlers", [])):
        key = known.get(normalize_brawler_name(api_brawler.get("name", "")))
        if not key:
            continue
        trophies = int(api_brawler.get("trophies", 0))
        if trophies < target:
            rows.append((trophies, index, key))
    rows.sort(key=lambda r: (r[0], r[1]))

    if not rows:
        raise HTTPException(status_code=400, detail=f"no brawlers below {target} trophies")

    # selection_method="lowest_trophies" makes the lobby auto-pick grab whichever
    # slot is currently lowest in-game. This is more robust than name-based
    # selection: name OCR can misread, the API trophies can be stale, and the
    # user's intent for "push all" is "always be playing whatever is lowest".
    # Web flow always uses automatically_pick=True (no human in the loop).
    payload: List[Dict[str, Any]] = []
    for trophies, _, key in rows:
        payload.append({
            "brawler": key,
            "type": "trophies",
            "push_until": target,
            "trophies": trophies,
            "wins": 0,
            "win_streak": 0,
            "automatically_pick": True,
            "selection_method": "lowest_trophies",
        })

    try:
        RUNNER.start(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {"ok": True, "count": len(payload), "target_trophies": target, "payload": payload, "state": STATE.snapshot()}


@app.post("/api/scan-brawler")
def scan_brawler(payload: Optional[ScanRequest] = None) -> Dict[str, Any]:
    """Read trophies + streak off the brawler-selection screen via EasyOCR.

    Refuses while the bot is running — bot owns the WindowController and
    we don't want two threads racing on `screenshot()`.
    """
    if RUNNER.is_running():
        raise HTTPException(
            status_code=409,
            detail="bot is running — stop the session before scanning",
        )
    from backend.lobby_scanner import SCANNER, _ScanError
    target = payload.brawler if payload else None
    try:
        result = SCANNER.scan(target_brawler=target)
    except _ScanError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scan failed: {exc}")
    return {"ok": True, **result}


@app.post("/api/scan-all-brawlers")
def scan_all_brawlers() -> Dict[str, Any]:
    """Page through the entire brawler grid via OCR and persist trophies/streak.

    Refuses while the bot is running. Merges results on top of any existing
    brawler_stats.toml so a brawler that didn't get re-scanned keeps its
    last known values.
    """
    if RUNNER.is_running():
        raise HTTPException(
            status_code=409,
            detail="bot is running — stop the session before scanning",
        )
    from backend.lobby_scanner import SCANNER, _ScanError

    import time as _time
    started = _time.time()
    try:
        results = SCANNER.scan_all()
    except _ScanError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scan failed: {exc}")

    load_toml_as_dict, save_dict_as_toml = _utils()
    existing: Dict[str, Any] = {}
    if BRAWLER_STATS_FILE.exists():
        try:
            existing = dict(load_toml_as_dict(str(BRAWLER_STATS_FILE)) or {})
        except Exception:
            existing = {}

    merged = dict(existing)
    for key, rec in (results or {}).items():
        prev = dict(merged.get(key) or {})
        # Don't overwrite a good prior trophy reading with None.
        t = rec.get("trophies")
        s = rec.get("streak")
        if t is None and prev.get("trophies") is not None:
            t = prev.get("trophies")
        if s is None and prev.get("streak") is not None:
            s = prev.get("streak")
        prev.update({
            "trophies": int(t) if t is not None else 0,
            "streak": int(s) if s is not None else 0,
            "scanned_at": float(rec.get("scanned_at") or _time.time()),
        })
        merged[key] = prev

    try:
        save_dict_as_toml(merged, str(BRAWLER_STATS_FILE))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to persist stats: {exc}")

    return {
        "ok": True,
        "count": len(results or {}),
        "duration": round(_time.time() - started, 2),
        "results": results,
    }


# ──────────────────────────────────────────────────────────────────────
# WebSocket stream
# ──────────────────────────────────────────────────────────────────────
@app.websocket("/api/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    queue = await STATE.subscribe()
    try:
        await ws.send_json({"type": "snapshot", "snapshot": STATE.snapshot()})
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        await STATE.unsubscribe(queue)


# ──────────────────────────────────────────────────────────────────────
# Static frontend
# ──────────────────────────────────────────────────────────────────────
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
else:
    @app.get("/")
    def _no_ui() -> JSONResponse:  # pragma: no cover
        return JSONResponse({"error": "web_ui folder not found"}, status_code=500)
