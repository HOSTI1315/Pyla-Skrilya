"""Threaded bot runner — reuses the logic from main.py.Main() but adds
cooperative stop / pause and redirects stdout into AppState.
"""

from __future__ import annotations

import asyncio
import io
import re
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from backend.state import STATE
from backend import watchdog as _wd

_ANSI_RE = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")


class _TeeStream(io.TextIOBase):
    """Fan writes to the original stream AND AppState log bus."""

    def __init__(self, original) -> None:
        self._original = original
        self._buf = ""

    def write(self, text: str) -> int:
        try:
            self._original.write(text)
        except Exception:
            pass
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if not line.strip():
                continue
            color = None
            m = _ANSI_RE.search(line)
            if m:
                r, g, b = map(int, m.groups())
                color = f"#{r:02x}{g:02x}{b:02x}"
            STATE.push_log(line, color=color)
        return len(text)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass


class BotRunner:
    """Owns the bot thread and exposes start/stop/pause/resume."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._lock = threading.Lock()
        self._tee_out: Optional[_TeeStream] = None
        self._tee_err: Optional[_TeeStream] = None
        # attribute read/written by play.main(frame, brawler, self)
        self.state: Optional[str] = None
        self._watchdog_tripped = threading.Event()
        self._reconnect_limiter: Optional[_wd.ReconnectLimiter] = None
        self._last_session_config: Optional[List[Dict[str, Any]]] = None
        # Snapshot of starting trophies/wins per brawler captured at start().
        # The session config dict gets mutated in-place by stage_manager after
        # every match (trophies → CURRENT, wins → CURRENT) — that mutation
        # would otherwise make ``cfg0['trophies']`` track current and the
        # milestone card would render with start == current. We freeze the
        # original values per brawler key here once.
        self._initial_brawler_trophies: Dict[str, int] = {}
        self._initial_brawler_wins: Dict[str, int] = {}
        self._auto_restart_on_watchdog = False

    # public ------------------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, session_config: List[Dict[str, Any]]) -> None:
        with self._lock:
            # if a previous run is still tearing down, give it a moment
            if self._thread is not None and self._thread.is_alive() and self._stop.is_set():
                self._thread.join(timeout=5.0)
            if self.is_running():
                raise RuntimeError("Bot is already running")
            self._stop.clear()
            self._pause.clear()
            self._watchdog_tripped.clear()
            self._last_session_config = session_config
            # Snapshot start values per brawler (see attribute comment in __init__).
            self._initial_brawler_trophies = {
                str(entry.get("brawler", "")).lower():
                    int(entry.get("trophies") or 0)
                for entry in (session_config or [])
                if entry.get("brawler")
            }
            self._initial_brawler_wins = {
                str(entry.get("brawler", "")).lower():
                    int(entry.get("wins") or 0)
                for entry in (session_config or [])
                if entry.get("brawler")
            }
            STATE.set_status("starting")
            STATE.reset_session()
            self._install_tee()
            self._thread = threading.Thread(
                target=self._run,
                args=(session_config,),
                name="PylaBotThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        # Manual stop: clear the last-session so the watchdog post-hook
        # in _run's finally block won't auto-restart the bot.
        self._last_session_config = None
        self._watchdog_tripped.clear()
        self._stop.set()
        self._pause.clear()
        STATE.set_status("stopping")
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
        _wd.stop_watchdog()

    def pause(self) -> None:
        if not self.is_running():
            return
        self._pause.set()
        STATE.set_status("paused")

    def resume(self) -> None:
        if not self.is_running():
            return
        self._pause.clear()
        STATE.set_status("running")

    # internals ---------------------------------------------------------
    def _install_tee(self) -> None:
        if self._tee_out is None:
            self._tee_out = _TeeStream(sys.stdout)
            sys.stdout = self._tee_out  # type: ignore[assignment]
        if self._tee_err is None:
            self._tee_err = _TeeStream(sys.stderr)
            sys.stderr = self._tee_err  # type: ignore[assignment]

    def _run(self, session_config: List[Dict[str, Any]]) -> None:
        # Session-log accounting. These are read in the `finally` block, so
        # initialise here — an early import failure would otherwise leave the
        # reason resolution touching unbound names.
        session_start_ts = time.time()
        exit_reason = "unknown"
        try:
            # import lazily so we don't pay the cost of loading ML deps until
            # the user actually clicks Start.
            import window_controller  # noqa: F401
            from lobby_automation import LobbyAutomation
            from play import Play
            from stage_manager import StageManager
            from state_finder import get_state
            from time_management import TimeManagement
            from utils import load_toml_as_dict, cprint, save_brawler_data
            from window_controller import WindowController

            save_brawler_data(session_config)

            wc = WindowController()
            STATE.set_device(True, getattr(wc, "device_name", "emulator"))

            models = [
                "./models/mainInGameModel.onnx",
                "./models/tileDetector.onnx",
            ]
            play = Play(*models, wc)
            time_mgr = TimeManagement()
            lobby = LobbyAutomation(wc)
            stage_mgr = StageManager(session_config, lobby, wc)

            if session_config[0].get("automatically_pick"):
                print("Picking brawler automatically")
                lobby.select_brawler(session_config[0]["brawler"])

            play.current_brawler = session_config[0]["brawler"]
            STATE.set_current_brawler(session_config[0]["brawler"])

            stage_mgr.Trophy_observer.win_streak = session_config[0]["win_streak"]
            stage_mgr.Trophy_observer.current_trophies = session_config[0]["trophies"]
            stage_mgr.Trophy_observer.current_wins = (
                session_config[0]["wins"] if session_config[0]["wins"] != "" else 0
            )
            # Baseline match_history so session stats (games/wins/losses/draws
            # /net_trophies) are deltas from session start, not lifetime totals.
            obs_init = stage_mgr.Trophy_observer
            _mh_total_init = (obs_init.match_history or {}).get("total", {}) or {}
            base_wins    = int(_mh_total_init.get("victory", 0) or 0)
            base_losses  = int(_mh_total_init.get("defeat",  0) or 0)
            base_draws   = int(_mh_total_init.get("draw",    0) or 0)
            base_trophies = int(obs_init.current_trophies or 0)
            session_started_at = time.time()
            trophy_curve: List[int] = [base_trophies]
            trophy_curve_ts: List[float] = [session_started_at]
            STATE.update_stats(
                trophies=base_trophies,
                wins=0,
                losses=0,
                draws=0,
                games=0,
                net_trophies=0,
                win_streak=int(obs_init.win_streak or 0),
                trophy_curve=list(trophy_curve),
                trophy_curve_ts=list(trophy_curve_ts),
                started_at=session_started_at,
            )
            last_snap: Dict[str, Any] = {}

            no_detections_action_threshold = 60 * 8
            general = load_toml_as_dict("cfg/general_config.toml")
            try:
                max_ips = int(general.get("max_ips", 0)) or None
            except ValueError:
                max_ips = None
            visual_debug = general.get("visual_debug", "no") == "yes"
            run_for_minutes = int(general.get("run_for_minutes", 0))

            watchdog_enabled = general.get("watchdog_enabled", "yes") == "yes"
            try:
                watchdog_timeout_s = float(general.get("watchdog_timeout_s", 120) or 120)
            except (TypeError, ValueError):
                watchdog_timeout_s = 120.0
            try:
                watchdog_poll_s = float(general.get("watchdog_poll_s", 30) or 30)
            except (TypeError, ValueError):
                watchdog_poll_s = 30.0
            try:
                max_reconnects = int(general.get("max_reconnects_per_window", 3) or 3)
            except (TypeError, ValueError):
                max_reconnects = 3
            try:
                reconnect_window_s = float(general.get("reconnect_window_s", 300) or 300)
            except (TypeError, ValueError):
                reconnect_window_s = 300.0
            self._reconnect_limiter = _wd.ReconnectLimiter(max_reconnects, reconnect_window_s)

            # Discord milestone intervals (0 disables that milestone type).
            # Re-read each iteration (bypassing utils.cached_toml) so the
            # user can change thresholds in the UI without restarting the bot.
            def _read_milestone_intervals() -> tuple[int, int]:
                try:
                    import toml as _toml
                    with open("cfg/general_config.toml", "r", encoding="utf-8") as _f:
                        _cfg = _toml.load(_f) or {}
                except Exception:
                    return 0, 0
                try:
                    w = int(_cfg.get("discord_milestone_wins_interval", 0) or 0)
                except (TypeError, ValueError):
                    w = 0
                try:
                    g = int(_cfg.get("discord_milestone_games_interval", 0) or 0)
                except (TypeError, ValueError):
                    g = 0
                return w, g

            ms_wins_interval, ms_games_interval = _read_milestone_intervals()
            last_ms_wins_bucket = 0
            last_ms_games_bucket = 0
            print(
                f"[milestone] loaded intervals: wins={ms_wins_interval}, "
                f"games={ms_games_interval} (0 = disabled)"
            )

            def _on_watchdog_timeout(elapsed: float) -> None:
                STATE.push_log(
                    f"[watchdog] no heartbeat for {elapsed:.0f}s — stopping bot for restart",
                    level="warn",
                )
                self._watchdog_tripped.set()
                self._stop.set()

            if watchdog_enabled:
                _wd.bump()
                _wd.start_watchdog(
                    timeout_s=watchdog_timeout_s,
                    on_timeout=_on_watchdog_timeout,
                    poll_interval=watchdog_poll_s,
                )

            start_time = time.time()
            in_cooldown = False
            cooldown_start = 0.0
            cooldown_duration = 3 * 60

            STATE.set_status("running")
            cprint("Session started", "#34D399")

            s_time = time.time()
            counter = 0
            while not self._stop.is_set():
                if watchdog_enabled:
                    _wd.bump()
                # pause loop
                while self._pause.is_set() and not self._stop.is_set():
                    if watchdog_enabled:
                        _wd.bump()
                    time.sleep(0.1)
                if self._stop.is_set():
                    break

                frame_start = time.perf_counter() if max_ips else None

                if run_for_minutes > 0 and not in_cooldown:
                    elapsed = (time.time() - start_time) / 60
                    if elapsed >= run_for_minutes:
                        cprint(
                            f"timer is done, {run_for_minutes} is over. continuing for 3 minutes if in game",
                            "#AAE5A4",
                        )
                        in_cooldown = True
                        cooldown_start = time.time()
                        stage_mgr.states["lobby"] = lambda: 0

                if in_cooldown and time.time() - cooldown_start >= cooldown_duration:
                    cprint("stopping bot fully", "#AAE5A4")
                    exit_reason = "finished"
                    break

                if abs(s_time - time.time()) > 1:
                    elapsed = time.time() - s_time
                    if elapsed > 0 and not visual_debug:
                        ips = counter / elapsed
                        STATE.set_ips(ips)
                        print(f"{ips:.2f} IPS")
                    s_time = time.time()
                    counter = 0

                try:
                    frame = wc.screenshot()
                except Exception as exc:
                    print(f"[runner] screenshot failed: {exc}")
                    time.sleep(0.5)
                    continue

                _, last_ft = wc.get_latest_frame()
                if last_ft > 0 and (time.time() - last_ft) > wc.FRAME_STALE_TIMEOUT:
                    play.window_controller.keys_up(list("wasd"))
                    print("Stale frame detected -- restarting the game.")
                    wc.restart_brawl_stars()

                # inline manage_time_tasks so stop flag cuts in quickly
                if time_mgr.state_check():
                    state = get_state(frame)
                    self.state = state
                    if state != "match":
                        play.time_since_last_proceeding = time.time()
                    try:
                        stage_mgr.do_state(state, None)
                    except SystemExit:
                        # stage_manager calls sys.exit(0) when the target is
                        # reached with no more brawlers queued. Surface it to
                        # the UI as a clean stop instead of dying silently.
                        cprint("Target reached — stopping bot", "#AAE5A4")
                        exit_reason = "finished"
                        break
                    except Exception as exc:
                        tb = traceback.format_exc()
                        print(f"[runner] stage_mgr.do_state('{state}') failed: {exc}\n{tb}")
                        exit_reason = "crashed"
                        break

                if time_mgr.no_detections_check():
                    for _key, value in play.time_since_detections.items():
                        if time.time() - value > no_detections_action_threshold:
                            wc.restart_brawl_stars()
                            play.time_since_detections["player"] = time.time()
                            play.time_since_detections["enemy"] = time.time()

                if time_mgr.idle_check():
                    lobby.check_for_idle(frame)

                brawler = stage_mgr.brawlers_pick_data[0]["brawler"]
                try:
                    play.main(frame, brawler, self)
                except Exception as exc:
                    print(f"[runner] play.main error: {exc}")

                # surface trophy observer changes to the UI. Match counts are
                # deltas from session start so the dashboard shows *this run*,
                # not lifetime history.
                try:
                    obs = stage_mgr.Trophy_observer
                    mh_total = (obs.match_history or {}).get("total", {}) or {}
                    cur_v  = int(mh_total.get("victory", 0) or 0)
                    cur_d  = int(mh_total.get("defeat",  0) or 0)
                    cur_dr = int(mh_total.get("draw",    0) or 0)
                    sess_v  = max(0, cur_v  - base_wins)
                    sess_d  = max(0, cur_d  - base_losses)
                    sess_dr = max(0, cur_dr - base_draws)
                    cur_trophies = int(obs.current_trophies or 0)
                    if cur_trophies != trophy_curve[-1]:
                        trophy_curve.append(cur_trophies)
                        trophy_curve_ts.append(time.time())
                        if len(trophy_curve) > 200:
                            del trophy_curve[: len(trophy_curve) - 200]
                            del trophy_curve_ts[: len(trophy_curve_ts) - 200]
                    snap = {
                        "wins":         sess_v,
                        "losses":       sess_d,
                        "draws":        sess_dr,
                        "games":        sess_v + sess_d + sess_dr,
                        "trophies":     cur_trophies,
                        "net_trophies": cur_trophies - base_trophies,
                        "win_streak":   int(obs.win_streak or 0),
                        "trophy_curve": list(trophy_curve),
                        "trophy_curve_ts": list(trophy_curve_ts),
                        "started_at":   session_started_at,
                    }
                    if snap != last_snap:
                        STATE.update_stats(**snap)
                        last_snap = snap

                    # Discord milestone notifications — fire when the
                    # session crosses a wins/games interval boundary. Intervals
                    # are re-read from disk here so UI changes take effect
                    # without a bot restart.
                    ms_wins_interval, ms_games_interval = _read_milestone_intervals()
                    if ms_wins_interval > 0 and sess_v > 0:
                        bucket = sess_v // ms_wins_interval
                        if bucket > last_ms_wins_bucket:
                            last_ms_wins_bucket = bucket
                            print(
                                f"[milestone] firing wins milestone: "
                                f"sess_v={sess_v}, bucket={bucket}, "
                                f"interval={ms_wins_interval}"
                            )
                            self._fire_milestone_notify(
                                wc, brawler, snap,
                                label=f"{bucket * ms_wins_interval} session wins",
                            )
                    if ms_games_interval > 0 and snap["games"] > 0:
                        bucket = snap["games"] // ms_games_interval
                        if bucket > last_ms_games_bucket:
                            last_ms_games_bucket = bucket
                            print(
                                f"[milestone] firing games milestone: "
                                f"games={snap['games']}, bucket={bucket}, "
                                f"interval={ms_games_interval}"
                            )
                            self._fire_milestone_notify(
                                wc, brawler, snap,
                                label=f"{bucket * ms_games_interval} session matches",
                            )
                except Exception as exc:
                    print(f"[runner] stats/milestone block failed: {exc}")

                counter += 1

                if max_ips and frame_start is not None:
                    target_period = 1 / max_ips
                    work_time = time.perf_counter() - frame_start
                    if work_time < target_period:
                        time.sleep(target_period - work_time)

            # Loop fell through cleanly. If a more specific exit_reason was
            # already set (finished/crashed), keep it; otherwise this is a
            # natural stop (e.g. _stop flag set externally).
            if exit_reason == "unknown":
                exit_reason = "finished"
            cprint("Bot stopped", "#AAE5A4")
        except Exception as exc:
            exit_reason = "crashed"
            tb = traceback.format_exc()
            STATE.push_log(f"[runner] fatal: {exc}\n{tb}", level="warn")
            STATE.set_status("error")
            try:
                from utils import notify_user
                shot = None
                try:
                    _wc = locals().get("wc")
                    if _wc is not None:
                        shot, _ = _wc.get_latest_frame()
                except Exception:
                    shot = None
                notify_user(
                    "error",
                    screenshot=shot,
                    live_summary={"error": str(exc)[:200]},
                )
            except Exception:
                pass
            return
        finally:
            try:
                wc  # type: ignore[name-defined]
                wc.keys_up(list("wasd"))  # type: ignore[name-defined]
                wc.close()  # type: ignore[name-defined]
            except Exception:
                pass
            self._log_session_end(session_start_ts, exit_reason)
            STATE.set_status("idle")
            self._stop.clear()
            self._pause.clear()
            if self._watchdog_tripped.is_set():
                self._watchdog_tripped.clear()
                self._maybe_auto_restart()

    def _log_session_end(self, start_ts: float, exit_reason: str) -> None:
        """Write a single line to cfg/sessions.jsonl summarising this run.

        Reason resolution: watchdog trumps user_stopped trumps exit_reason.
        Stats are deltas from session-start baselines so the entry reflects
        only this run, not lifetime totals.
        """
        if self._watchdog_tripped.is_set():
            reason = "watchdog"
        elif self._last_session_config is None:
            # `stop()` clears _last_session_config — that path means user-driven
            reason = "user_stopped"
        else:
            reason = exit_reason or "unknown"

        wins = losses = draws = 0
        trophy_delta = 0
        try:
            snap = STATE.snapshot().get("stats") or {}
            wins = int(snap.get("wins") or 0)
            losses = int(snap.get("losses") or 0)
            draws = int(snap.get("draws") or 0)
            trophy_delta = int(snap.get("net_trophies") or 0)
        except Exception:
            pass

        try:
            from sessions import log_session
            log_session(
                start_ts=start_ts,
                end_ts=time.time(),
                wins=wins,
                losses=losses,
                draws=draws,
                trophy_delta=trophy_delta,
                reason=reason,
            )
        except Exception as e:
            print(f"[runner] failed to log session: {e}")

    def _fire_milestone_notify(self, wc, brawler: str, snap: Dict[str, Any], label: str) -> None:
        """Fire a milestone Discord notification in a background thread so
        the bot loop never blocks on network I/O."""
        try:
            from utils import has_notification_webhook
            if not has_notification_webhook():
                print(f"[milestone] skipping '{label}' — no personal_webhook configured")
                return
        except Exception as e:
            print(f"[milestone] webhook check failed: {e}")
            return

        try:
            shot, _ = wc.get_latest_frame()
        except Exception:
            shot = None

        games = int(snap.get("games") or 0)
        wins = int(snap.get("wins") or 0)
        losses = int(snap.get("losses") or 0)
        draws = int(snap.get("draws") or 0)
        wr = (wins / games * 100) if games > 0 else 0.0

        cfg0 = (self._last_session_config or [{}])[0]
        goal_type = cfg0.get("type") or "trophies"
        goal_target = int(cfg0.get("push_until") or 0)
        # cfg0['trophies'] is overwritten by stage_manager on every match —
        # use the frozen snapshot taken in start() so the milestone card's
        # bar fills correctly (e.g. user typed 1000, current is 1162 ->
        # bar should treat 1000 as start, not 1162).
        head_key = str(cfg0.get("brawler") or brawler or "").lower()
        start_trophies = self._initial_brawler_trophies.get(
            head_key, int(cfg0.get("trophies") or 0))

        summary = {
            "brawler": brawler,
            "brawler_key": str(brawler or "").lower(),
            "trophies": snap.get("trophies"),
            "session_trophy_delta": snap.get("net_trophies", 0),
            "session_matches": games,
            "session_victories": wins,
            "session_defeats": losses,
            "session_draws": draws,
            "session_winrate": wr,
            "win_streak": snap.get("win_streak", 0),
            "milestone_label": label,
            "trophy_curve": list(snap.get("trophy_curve") or []),
            "started_at": snap.get("started_at"),
            "goal_type": goal_type,
            "goal_target": goal_target,
            "session_start_trophies": start_trophies,
        }

        def _send():
            try:
                from utils import notify_user
                ok = notify_user(
                    "milestone_reached",
                    screenshot=shot,
                    subject=brawler,
                    live_summary=summary,
                )
                if ok:
                    print(f"[milestone] webhook posted: '{label}' for {brawler}")
                else:
                    print(f"[milestone] webhook returned false for '{label}' — check webhook URL / Discord response")
            except Exception as e:
                print(f"[runner] milestone webhook failed: {e}")

        threading.Thread(target=_send, daemon=True, name="PylaMilestoneNotify").start()

    def _maybe_auto_restart(self) -> None:
        """Relaunch the bot thread after a watchdog trip, honouring the
        rolling-window reconnect limiter so we don't loop forever."""
        cfg = self._last_session_config
        limiter = self._reconnect_limiter
        if cfg is None or limiter is None:
            return
        if not limiter.record_and_check():
            STATE.push_log(
                f"[watchdog] reconnect limit exceeded "
                f"({limiter.max} in {int(limiter.window)}s) — staying idle",
                level="warn",
            )
            STATE.set_status("error")
            return
        STATE.push_log("[watchdog] auto-restarting bot thread", level="info")

        def _relaunch():
            time.sleep(2.0)
            try:
                self.start(cfg)
            except Exception as e:
                STATE.push_log(f"[watchdog] auto-restart failed: {e}", level="warn")

        threading.Thread(target=_relaunch, daemon=True, name="PylaAutoRestart").start()


RUNNER = BotRunner()
