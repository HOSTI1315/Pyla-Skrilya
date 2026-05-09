"""Heartbeat watchdog + frame-flow verification.

Adapted from myddxyz/brawlindustry for PylaAI's web-server context:
the watchdog requests a bot-thread restart via callback instead of
calling os._exit (the FastAPI process must stay alive to serve the UI).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

_last_heartbeat = time.time()
_heartbeat_lock = threading.Lock()
_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop = threading.Event()


def bump() -> None:
    global _last_heartbeat
    with _heartbeat_lock:
        _last_heartbeat = time.time()


def seconds_since_heartbeat() -> float:
    with _heartbeat_lock:
        return time.time() - _last_heartbeat


def start_watchdog(
    timeout_s: float,
    on_timeout: Callable[[float], None],
    poll_interval: float = 30.0,
) -> threading.Thread:
    """Launch (or re-launch) the watchdog thread.

    On stale heartbeat, calls on_timeout(elapsed_seconds). The callback
    is expected to request a bot-thread restart — the watchdog itself
    does NOT exit the process.
    """
    global _watchdog_thread
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return _watchdog_thread

    _watchdog_stop.clear()
    bump()

    def _loop():
        while not _watchdog_stop.is_set():
            if _watchdog_stop.wait(poll_interval):
                break
            elapsed = seconds_since_heartbeat()
            if elapsed > timeout_s:
                log.error(
                    f"WATCHDOG: no heartbeat for {elapsed:.0f}s "
                    f"(> {timeout_s:.0f}s) — requesting bot restart"
                )
                try:
                    on_timeout(elapsed)
                except Exception as e:
                    log.exception(f"watchdog on_timeout callback failed: {e}")
                # Reset so we don't spam restart requests every poll
                bump()

    t = threading.Thread(target=_loop, daemon=True, name="watchdog")
    t.start()
    _watchdog_thread = t
    return t


def stop_watchdog() -> None:
    _watchdog_stop.set()


def verify_frames_flowing(
    get_frame_time: Callable[[], float],
    timeout_s: float = 12.0,
) -> bool:
    """Verify SUSTAINED frame flow, not just one cached frame.

    Phase A: wait for any fresh frame timestamp (proves scrcpy connected).
    Phase B: drain 4s so cached/burst frames stop.
    Phase C: confirm NEW frames are still arriving (emulator truly alive).

    `get_frame_time()` must return a monotonic-ish float (our WC exposes
    `last_frame_time`). A frozen emulator typically delivers one cached
    frame then stops — Phase C catches this.
    """
    initial_ts = get_frame_time() or 0.0
    deadline = time.time() + timeout_s

    # Phase A — wait for a newer frame
    while time.time() < deadline:
        bump()
        time.sleep(0.5)
        if (get_frame_time() or 0.0) > initial_ts:
            break
    else:
        return False

    # Phase B — drain cached frames
    drain_until = min(time.time() + 4.0, deadline)
    while time.time() < drain_until:
        bump()
        time.sleep(0.5)

    if time.time() >= deadline:
        return False

    # Phase C — confirm frames still arriving
    checkpoint_ts = get_frame_time() or 0.0
    while time.time() < deadline:
        bump()
        time.sleep(0.5)
        if (get_frame_time() or 0.0) > checkpoint_ts:
            return True

    return False


class ReconnectLimiter:
    """Rolling-window counter. If too many reconnects in window_s, caller
    should escalate (stop bot, flag UI) instead of looping forever."""

    def __init__(self, max_in_window: int, window_s: float):
        self.max = max_in_window
        self.window = window_s
        self.events: list[float] = []
        self._lock = threading.Lock()

    def record_and_check(self) -> bool:
        """Record a reconnect. Returns True if under the limit, False if exceeded."""
        now = time.time()
        with self._lock:
            self.events = [t for t in self.events if now - t <= self.window]
            self.events.append(now)
            return len(self.events) <= self.max

    def reset(self) -> None:
        with self._lock:
            self.events.clear()
