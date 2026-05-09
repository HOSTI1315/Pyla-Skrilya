"""Shared pub/sub state used by the bot thread and the FastAPI/WebSocket layer."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _classify(raw: str) -> str:
    low = raw.lower()
    if any(k in low for k in ("error", "traceback", "exception", "failed")):
        return "warn"
    if any(k in low for k in ("warn", "stale", "stuck", "retry")):
        return "warn"
    if any(k in low for k in ("victory", "win", "won ", " +", "ok", "done")):
        return "ok"
    if any(k in low for k in ("tap(", "move(", "press", "attack", "super", "joystick")):
        return "action"
    return "info"


class AppState:
    """Thread-safe bus between the bot thread and all WebSocket clients."""

    def __init__(self, max_log_lines: int = 500) -> None:
        self._lock = threading.Lock()
        self._log: Deque[Dict[str, Any]] = deque(maxlen=max_log_lines)
        self._status: str = "idle"  # idle | starting | running | paused | stopping | error
        self._stats: Dict[str, Any] = {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "trophies": 0,
            "net_trophies": 0,
            "win_streak": 0,
            "started_at": 0.0,
        }
        self._device: Dict[str, Any] = {"connected": False, "name": "—"}
        self._ips: float = 0.0
        self._current_brawler: Optional[str] = None
        self._subscribers: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # event-loop binding ------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # snapshot ----------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "stats": dict(self._stats),
                "device": dict(self._device),
                "ips": self._ips,
                "current_brawler": self._current_brawler,
                "log_tail": list(self._log)[-120:],
            }

    # mutations ---------------------------------------------------------
    def set_status(self, status: str) -> None:
        with self._lock:
            if self._status == status:
                return
            self._status = status
        self._broadcast({"type": "status", "status": status})

    def set_device(self, connected: bool, name: str) -> None:
        with self._lock:
            self._device = {"connected": connected, "name": name}
        self._broadcast({"type": "device", "device": {"connected": connected, "name": name}})

    def set_current_brawler(self, brawler: Optional[str]) -> None:
        with self._lock:
            self._current_brawler = brawler
        self._broadcast({"type": "brawler", "brawler": brawler})

    def set_ips(self, ips: float) -> None:
        with self._lock:
            self._ips = round(ips, 2)
        self._broadcast({"type": "ips", "ips": self._ips})

    def update_stats(self, **kwargs: Any) -> None:
        with self._lock:
            self._stats.update(kwargs)
            snap = dict(self._stats)
        self._broadcast({"type": "stats", "stats": snap})

    def reset_session(self) -> None:
        with self._lock:
            self._stats = {
                "games": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "trophies": self._stats.get("trophies", 0),
                "net_trophies": 0,
                "win_streak": 0,
                "started_at": time.time(),
            }
            snap = dict(self._stats)
        self._broadcast({"type": "stats", "stats": snap})

    def push_log(self, text: str, level: Optional[str] = None, color: Optional[str] = None) -> None:
        clean = _ANSI_RE.sub("", text).rstrip()
        if not clean:
            return
        lvl = level or _classify(clean)
        entry = {
            "t": time.strftime("%H:%M:%S"),
            "lvl": lvl,
            "msg": clean,
        }
        if color and _HEX_RE.match(color.lstrip("#")):
            entry["color"] = "#" + color.lstrip("#")
        with self._lock:
            self._log.append(entry)
        self._broadcast({"type": "log", "line": entry})

    # pub/sub -----------------------------------------------------------
    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass

    def _broadcast(self, message: Dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, message)
            except RuntimeError:
                # loop closed
                continue
            except asyncio.QueueFull:
                continue


STATE = AppState()
