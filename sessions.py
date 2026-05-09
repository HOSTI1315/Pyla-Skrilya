"""Per-session bot run log at cfg/sessions.jsonl.

One JSON object per line, written when a bot run terminates:
    {"start": 1712345678.9, "end": 1712350000.0, "duration_s": 4321.1,
     "wins": 12, "losses": 4, "draws": 0,
     "trophy_delta": 87, "matches": 16,
     "reason": "user_stopped"}

`reason` is one of: user_stopped, crashed, finished, watchdog, unknown.
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Dict, Optional


SESSIONS_PATH = "./cfg/sessions.jsonl"
SESSIONS_MAX_ENTRIES = 1000


def log_session(
    start_ts: float,
    end_ts: float,
    wins: int,
    losses: int,
    draws: int,
    reason: str,
    trophy_delta: int = 0,
    matches: Optional[int] = None,
    path: str = SESSIONS_PATH,
    max_entries: int = SESSIONS_MAX_ENTRIES,
) -> bool:
    entry = {
        "start": float(start_ts),
        "end": float(end_ts),
        "duration_s": float(max(0.0, end_ts - start_ts)),
        "wins": int(wins or 0),
        "losses": int(losses or 0),
        "draws": int(draws or 0),
        "matches": int(matches if matches is not None else (wins + losses + draws)),
        "trophy_delta": int(trophy_delta or 0),
        "reason": reason or "unknown",
    }
    try:
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return False

    existing: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = [raw.strip() for raw in f if raw.strip()]
        except OSError:
            existing = []
    existing.append(line)
    if len(existing) > max_entries:
        existing = existing[-max_entries:]

    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            for raw in existing:
                f.write(raw + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def load_sessions(path: str = SESSIONS_PATH) -> List[Dict]:
    """Return all session entries in chronological order (oldest first)."""
    if not os.path.exists(path):
        return []
    out: List[Dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except (ValueError, TypeError):
                    continue
    except OSError:
        return []
    return out


def recent_sessions(n: int = 20, path: str = SESSIONS_PATH) -> List[Dict]:
    """Return the n most recent sessions, newest first."""
    sessions = load_sessions(path)
    if n is None or n < 0:
        return list(reversed(sessions))
    return list(reversed(sessions[-n:]))


def format_duration(seconds: float) -> str:
    s = int(max(0, seconds or 0))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"
