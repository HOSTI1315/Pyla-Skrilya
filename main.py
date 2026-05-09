"""PylaAI entry point.

Default:  launches the FastAPI server + React UI at http://127.0.0.1:8765
Legacy:   `py -3.11 main.py --legacy` falls back to the Tk login -> Hub flow.
Instance: `py -3.11 main.py --instance N` runs a single bot against the
          emulator configured in ``instances/N/cfg/``. Spawned by the
          backend instance-manager when the user starts an instance from the
          web UI; can also be run by hand for debugging.
"""

import argparse
import asyncio
import gc
import os
import platform
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _early_parse_instance():
    """Pull ``--instance N`` and ``--setup-instances N`` out of sys.argv before
    any module-load TOML reads happen.

    Returns ``(instance_id_or_None, setup_count_or_None)``. We can't use
    argparse here because it would also swallow flags meant for the chosen
    sub-command (server / legacy / instance), so we hand-roll a tiny scan and
    leave argv intact for the real ``main()`` parser to handle later.
    """
    instance_id = None
    setup_count = None
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--instance" and i + 1 < len(argv):
            try:
                instance_id = int(argv[i + 1])
            except (TypeError, ValueError):
                pass
        elif arg.startswith("--instance="):
            try:
                instance_id = int(arg.split("=", 1)[1])
            except (TypeError, ValueError):
                pass
        elif arg == "--setup-instances" and i + 1 < len(argv):
            try:
                setup_count = int(argv[i + 1])
            except (TypeError, ValueError):
                pass
        elif arg.startswith("--setup-instances="):
            try:
                setup_count = int(arg.split("=", 1)[1])
            except (TypeError, ValueError):
                pass
    return instance_id, setup_count


_INSTANCE_ID, _SETUP_COUNT = _early_parse_instance()
if _INSTANCE_ID is not None:
    # Switch CONFIG_DIR before any module-load TOML reads fire (lobby_automation,
    # play, state_finder, window_controller all read configs at import time).
    from utils import set_config_dir as _set_config_dir
    _instance_cfg = os.path.join("instances", str(_INSTANCE_ID), "cfg")
    if not os.path.isdir(_instance_cfg):
        sys.stderr.write(
            f"[PylaAI] Instance {_INSTANCE_ID} not provisioned: missing {_instance_cfg}.\n"
            f"         Run: python main.py --setup-instances <N>\n"
        )
        sys.exit(2)
    _set_config_dir(_instance_cfg)

from logger_setup import setup_logging_if_enabled

setup_logging_if_enabled(instance_id=_INSTANCE_ID)

import cv2

import window_controller
from lobby_automation import LobbyAutomation
from play import Play
from runtime_control import RuntimeControlWindow
from stage_manager import StageManager
from state_finder import get_state
from time_management import TimeManagement
from utils import (
    api_base_url,
    async_notify_user,
    check_version,
    cprint,
    current_wall_model_is_latest,
    extract_text_strings,
    get_brawler_list,
    get_latest_version,
    get_latest_wall_model_file,
    load_toml_as_dict,
    update_missing_brawlers_info,
    update_wall_model_classes,
)
from window_controller import WindowController

if platform.architecture()[0] != "64bit":
    print("\nWARNING: PylaAI is running on 32-bit Python.")
    print("If IPS is very low, run python tools/performance_check.py to verify ONNX and emulator frame speed.")
    print(f"Current Python: {sys.executable}")

pyla_version = load_toml_as_dict("./cfg/general_config.toml")['pyla_version']


def parse_max_ips(value):
    """Normalise the max_ips general_config value.

    Returns None for "unlimited" (0, empty, missing, or non-numeric). Returns
    a positive int when the user wants to cap the loop.
    """
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


def _boot_checks():
    all_brawlers = get_brawler_list()
    if api_base_url != "localhost":
        update_missing_brawlers_info(all_brawlers)
        check_version()
        update_wall_model_classes()
        if not current_wall_model_is_latest():
            print("New Wall detection model found, downloading... (this might take a few minutes depending on your internet speed)")
            get_latest_wall_model_file()
    return all_brawlers


# Multi-emulator: per-instance live metrics published by pyla_main into this
# shared dict. The heartbeat thread (see run_instance_bot) reads it every 5s
# and atomic-writes ``instances/<N>/state/heartbeat.json``. Manager reads that
# file in _snapshot() and exposes it through /api/instances. The UI's
# instance card renders the IPS sparkline + W/L counters from these values.
_INSTANCE_HEARTBEAT_STATE: dict = {}


def _publish_instance_heartbeat(payload: dict) -> None:
    """Best-effort merge of new metrics into the shared heartbeat dict.
    No-op when running standalone (single-instance mode) — the dict just sits
    unused. Pyla_main calls this from its hot loop every ~1-2 seconds."""
    try:
        _INSTANCE_HEARTBEAT_STATE.update(payload)
    except Exception:
        pass


def pyla_main(data):
    """Legacy hot loop: exact upstream Main with adaptive_brain + watchdogs."""

    class Main:

        def __init__(self):
            self.window_controller = WindowController()
            self.Play = Play(*self.load_models(), self.window_controller)
            self.Time_management = TimeManagement()
            self.lobby_automator = LobbyAutomation(self.window_controller)
            self.Stage_manager = StageManager(data, self.lobby_automator, self.window_controller)
            self.Stage_manager.adaptive_brain.apply_to_play(self.Play)
            self.states_requiring_data = ["lobby"]
            if data[0]['automatically_pick']:
                # Honor selection_method on the FIRST pick too — Push All
                # queues every entry with selection_method='lowest_trophies'
                # so the bot can survive an OCR miss on the named brawler
                # (e.g. ``colt`` not visible after 22 scroll attempts because
                # the icon is locked / renamed). Without this, the very first
                # __init__ call always went through select_brawler(name) and
                # crashed before stage_manager could fall back. Match the
                # post-target switching path in stage_manager.start_game.
                selection_method = data[0].get("selection_method", "named_brawler")
                print(f"Picking brawler automatically (method={selection_method})")
                if selection_method == "lowest_trophies":
                    self.lobby_automator.select_lowest_trophy_brawler()
                else:
                    try:
                        self.lobby_automator.select_brawler(data[0]['brawler'])
                    except ValueError as exc:
                        # Don't crash the whole bot run because the very first
                        # named pick missed — the queue still has work to do
                        # and the next start_game tick will retry / advance.
                        print(f"select_brawler failed on first pick: {exc}; "
                              f"falling back to lowest-trophies slot")
                        self.lobby_automator.select_lowest_trophy_brawler()
            self.Play.current_brawler = data[0]['brawler']
            self.no_detections_action_threshold = 60 * 8
            self.initialize_stage_manager()
            self.state = None
            general_config = load_toml_as_dict("cfg/general_config.toml")
            self.max_ips = parse_max_ips(general_config.get('max_ips'))
            print(
                "Performance config:",
                f"max_ips={self.max_ips or 'auto'}",
                f"scrcpy_max_fps={general_config.get('scrcpy_max_fps', 'default')}",
                f"scrcpy_max_width={general_config.get('scrcpy_max_width', 'default')}",
                f"onnx_cpu_threads={general_config.get('onnx_cpu_threads', 'auto')}",
            )
            self.visual_debug = general_config.get('visual_debug', 'no') == "yes"
            self.run_for_minutes = int(general_config.get('run_for_minutes', 0))
            self.start_time = time.time()
            self.time_to_stop = False
            self.in_cooldown = False
            self.cooldown_start_time = 0
            self.cooldown_duration = 3 * 60
            self.match_ready_at = 0.0
            self.match_warmup_seconds = float(load_toml_as_dict("cfg/bot_config.toml").get("match_warmup_seconds", 4.0))
            time_thresholds = load_toml_as_dict("cfg/time_tresholds.toml")
            self.started_at = time.time()
            self.low_ips_startup_grace_seconds = float(time_thresholds.get("low_ips_startup_grace_seconds", 120))
            self.low_ips_match_grace_seconds = float(time_thresholds.get("low_ips_match_grace_seconds", 20))
            self.visual_freeze_check_interval = float(time_thresholds.get("visual_freeze_check_interval", 1.0))
            self.visual_freeze_restart_seconds = float(time_thresholds.get("visual_freeze_restart", 45.0))
            self.visual_freeze_diff_threshold = float(time_thresholds.get("visual_freeze_diff_threshold", 0.35))
            self.last_visual_freeze_check = 0.0
            self.last_visual_change_time = time.time()
            self.last_visual_sample = None
            self.lobby_start_retry_interval = float(time_thresholds.get("lobby_start_retry", 8.0))
            self.lobby_stuck_restart_seconds = float(time_thresholds.get("lobby_stuck_restart", 120.0))
            self.lobby_entered_at = None
            self.last_lobby_start_press = 0.0
            self.last_stale_feed_recovery = 0.0
            self.stale_feed_recovery_attempts = 0
            self.last_stale_feed_message = 0.0
            self.low_ips_threshold = float(time_thresholds.get("low_ips_recovery_threshold", 4.0))
            self.low_ips_recovery_seconds = float(time_thresholds.get("low_ips_recovery_seconds", 35.0))
            self.low_ips_recovery_cooldown = float(time_thresholds.get("low_ips_recovery_cooldown", 20.0))
            self.low_ips_app_restart_after = int(time_thresholds.get("low_ips_app_restart_after", 2))
            self.low_ips_emulator_restart_after = int(time_thresholds.get("low_ips_emulator_restart_after", 4))
            self.low_ips_since = None
            self.last_low_ips_recovery = 0.0
            self.low_ips_recovery_attempts = 0
            self.last_disconnect_check = 0.0
            self.disconnect_reload_attempts = 0
            self.last_processed_frame_id = -1
            self.ips_ema = None
            self.low_frame_fps_warning_time = 0.0
            self.disconnect_ocr_interval = 6.0
            self.control_window = RuntimeControlWindow()
            self.control_window.start()
            self.was_paused = False
            self.pause_started_at = None
            # Discord milestone tracking — same intervals the legacy in-process
            # bot_runner uses, but applied here so the multi-instance subprocess
            # also fires the rich "Milestone Reached" card with chart through
            # ``notify_user("milestone_reached", ...)``. Buckets start at -1 so
            # the very first crossing fires immediately.
            self._ms_wins_bucket = -1
            self._ms_games_bucket = -1
            # ── Snapshot of "session start" trophies / wins per brawler ──
            # stage_manager mutates ``brawlers_pick_data[0]['trophies']``
            # after every match (line 315 in stage_manager.py). That makes
            # the live ``head['trophies']`` track CURRENT, not the value the
            # user originally typed in the session goal. We freeze the
            # initial values here, keyed by brawler name, so the milestone
            # webhook can report a real start-of-session baseline that
            # matches what the user filled into the dashboard form.
            self._initial_brawler_trophies = {
                str(entry.get("brawler", "")).lower():
                    int(entry.get("trophies") or 0)
                for entry in (data or [])
                if entry.get("brawler")
            }
            self._initial_brawler_wins = {
                str(entry.get("brawler", "")).lower():
                    int(entry.get("wins") or 0)
                for entry in (data or [])
                if entry.get("brawler")
            }

        def initialize_stage_manager(self):
            self.Stage_manager.Trophy_observer.win_streak = data[0]['win_streak']
            self.Stage_manager.Trophy_observer.current_trophies = data[0]['trophies']
            self.Stage_manager.Trophy_observer.current_wins = data[0]['wins'] if data[0]['wins'] != "" else 0

        @staticmethod
        def load_models():
            folder_path = "./models/"
            model_names = ['mainInGameModel.onnx', 'tileDetector.onnx']
            return [folder_path + name for name in model_names]

        def restart_brawl_stars(self):
            self.window_controller.restart_brawl_stars()
            self.window_controller.restart_scrcpy_client()
            self.reset_visual_freeze_watchdog()
            self.reset_low_ips_watchdog(recovered=False)
            gc.collect()
            self.lobby_entered_at = None
            self.last_lobby_start_press = 0.0
            self.last_processed_frame_id = -1
            self.Play.time_since_detections["player"] = time.time()
            self.Play.time_since_detections["enemy"] = time.time()
            opened_package = self.window_controller.foreground_package(timeout=4)
            if opened_package and opened_package != window_controller.BRAWL_STARS_PACKAGE:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    screenshot = self.window_controller.screenshot()
                    loop.run_until_complete(async_notify_user(
                        "bot_is_stuck",
                        screenshot,
                        details={
                            "reason": "Brawl Stars did not stay in the foreground after recovery.",
                            "state": self.state or "unknown",
                            "emulator": getattr(self.window_controller, "selected_emulator", "unknown"),
                            "adb_device": getattr(getattr(self.window_controller, "device", None), "serial", ""),
                        },
                    ))
                finally:
                    loop.close()
                print("Bot got stuck. User notified. Shutting down.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.close()
                sys.exit(1)

        def _maybe_fire_milestone(self, head, tro, session_wins, session_battles,
                                  session_losses, current_trophies, initial_trophies,
                                  win_rate):
            """Fire ``notify_user('milestone_reached', ...)`` when session_wins
            or session_battles cross an interval boundary configured in
            cfg/general_config.toml. This brings the rich Milestone Card
            (chart + KPI grid) to multi-instance bot subprocesses, which only
            had the simple match embed before. The legacy in-process
            ``backend/bot_runner.py`` already does the same against its
            STATE.snapshot — this is the per-instance equivalent.
            """
            try:
                cfg = load_toml_as_dict("cfg/general_config.toml")
            except Exception:
                return
            try:
                ms_wins = int(cfg.get("discord_milestone_wins_interval", 0) or 0)
            except (TypeError, ValueError):
                ms_wins = 0
            try:
                ms_games = int(cfg.get("discord_milestone_games_interval", 0) or 0)
            except (TypeError, ValueError):
                ms_games = 0
            if ms_wins <= 0 and ms_games <= 0:
                return

            triggers = []
            if ms_wins > 0 and session_wins > 0:
                bucket = session_wins // ms_wins
                if bucket > self._ms_wins_bucket:
                    self._ms_wins_bucket = bucket
                    triggers.append(f"{bucket * ms_wins} session wins")
            if ms_games > 0 and session_battles > 0:
                bucket = session_battles // ms_games
                if bucket > self._ms_games_bucket:
                    self._ms_games_bucket = bucket
                    triggers.append(f"{bucket * ms_games} session matches")

            if not triggers:
                return

            try:
                from utils import has_notification_webhook, notify_user
                if not has_notification_webhook():
                    return
            except Exception:
                return

            brawler = head.get("brawler") or "—"
            queue = getattr(self.Stage_manager, "brawlers_pick_data", []) or []
            cfg0 = queue[0] if queue else {}
            wr_pct = round(win_rate * 100, 1) if win_rate is not None else 0.0
            try:
                shot = self.window_controller.screenshot()
            except Exception:
                shot = None
            summary = {
                "brawler": brawler,
                "brawler_key": str(brawler).lower(),
                "trophies": current_trophies,
                "session_trophy_delta": current_trophies - initial_trophies,
                "session_matches": session_battles,
                "session_victories": session_wins,
                "session_defeats": session_losses,
                "session_draws": max(0, session_battles - session_wins - session_losses),
                "session_winrate": wr_pct,
                "win_streak": int(getattr(tro, "win_streak", 0) or 0),
                "goal_type": cfg0.get("type") or "trophies",
                "goal_target": int(cfg0.get("push_until") or 0),
                "session_start_trophies": initial_trophies,
                "started_at": getattr(self, "started_at", None),
            }

            def _send_one(label):
                try:
                    summary["milestone_label"] = label
                    notify_user("milestone_reached", screenshot=shot,
                                subject=brawler, live_summary=dict(summary))
                except Exception as e:
                    print(f"[milestone] webhook failed: {e}")

            import threading as _threading
            for label in triggers:
                _threading.Thread(target=_send_one, args=(label,),
                                  daemon=True, name="PylaInstMilestone").start()

        def reset_visual_freeze_watchdog(self):
            self.last_visual_sample = None
            self.last_visual_freeze_check = 0.0
            self.last_visual_change_time = time.time()

        def reset_low_ips_watchdog(self, recovered=True):
            self.low_ips_since = None
            self.ips_ema = None
            if recovered:
                self.low_ips_recovery_attempts = 0

        def recover_low_ips(self, current_ips):
            now = time.time()
            if now - self.started_at < self.low_ips_startup_grace_seconds:
                return False
            if self.state == "match" and now - self.match_ready_at < self.low_ips_match_grace_seconds:
                return False
            if current_ips >= self.low_ips_threshold:
                if self.low_ips_since is not None:
                    print(f"IPS recovered to {current_ips:.2f}; clearing low-IPS watchdog.")
                self.reset_low_ips_watchdog(recovered=True)
                return False

            _, last_frame_time = self.window_controller.get_latest_frame()
            frame_age = now - last_frame_time if last_frame_time else 999.0
            if self.low_ips_since is None:
                self.low_ips_since = now
                return False

            low_for = now - self.low_ips_since
            if low_for < self.low_ips_recovery_seconds:
                return False
            if now - self.last_low_ips_recovery < self.low_ips_recovery_cooldown:
                return False

            self.last_low_ips_recovery = now
            self.low_ips_recovery_attempts += 1
            self.window_controller.keys_up(list("wasd"))
            print(
                f"IPS stayed low ({current_ips:.2f}, frame age {frame_age:.1f}s) "
                f"for {low_for:.1f}s; recovery attempt {self.low_ips_recovery_attempts}."
            )

            if self.low_ips_recovery_attempts >= self.low_ips_emulator_restart_after:
                if frame_age <= 5:
                    print(
                        "Low IPS is still happening but scrcpy frames are fresh; "
                        "skipping emulator restart and restarting Brawl Stars/scrcpy instead."
                    )
                    self.restart_brawl_stars()
                    self.low_ips_recovery_attempts = max(
                        self.low_ips_app_restart_after,
                        self.low_ips_emulator_restart_after - 1,
                    )
                else:
                    print("Low IPS did not recover after app/scrcpy restarts; restarting emulator profile.")
                    if self.window_controller.restart_emulator_profile():
                        self.low_ips_recovery_attempts = 0
                    else:
                        print("Emulator restart was not available; keeping bot alive and retrying scrcpy recovery.")
                        self.window_controller.restart_scrcpy_client()
                        self.low_ips_recovery_attempts = max(
                            self.low_ips_app_restart_after,
                            self.low_ips_emulator_restart_after - 1,
                        )
            elif self.low_ips_recovery_attempts >= self.low_ips_app_restart_after:
                print("Low IPS persisted; restarting Brawl Stars and scrcpy.")
                self.restart_brawl_stars()
            else:
                print("Low IPS detected; restarting scrcpy feed.")
                self.window_controller.restart_scrcpy_client()

            self.last_processed_frame_id = -1
            self.low_ips_since = now
            self.ips_ema = None
            gc.collect()
            return True

        def handle_visual_freeze(self, frame):
            if self.state != "match":
                self.reset_visual_freeze_watchdog()
                return False

            now = time.time()
            if now < self.match_ready_at or now - self.last_visual_freeze_check < self.visual_freeze_check_interval:
                return False
            self.last_visual_freeze_check = now

            sample = cv2.resize(frame, (96, 54), interpolation=cv2.INTER_AREA)
            sample = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)
            if self.last_visual_sample is None:
                self.last_visual_sample = sample
                self.last_visual_change_time = now
                return False

            diff = float(cv2.absdiff(sample, self.last_visual_sample).mean())
            self.last_visual_sample = sample
            if diff >= self.visual_freeze_diff_threshold:
                self.last_visual_change_time = now
                return False

            frozen_for = now - self.last_visual_change_time
            if frozen_for < self.visual_freeze_restart_seconds:
                return False

            print(
                f"Match image did not change for {frozen_for:.1f}s "
                f"(diff {diff:.3f}); restarting Brawl Stars and scrcpy."
            )
            self.window_controller.keys_up(list("wasd"))
            self.restart_brawl_stars()
            return True

        def handle_lobby_watchdog(self, state):
            now = time.time()
            if state != "lobby" or self.in_cooldown:
                if state != "lobby":
                    self.lobby_entered_at = None
                return False

            if self.lobby_entered_at is None:
                self.lobby_entered_at = now

            if now - self.last_lobby_start_press >= self.lobby_start_retry_interval:
                print("Lobby watchdog: pressing start again.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.press_key("Q")
                self.last_lobby_start_press = now

            lobby_age = now - self.lobby_entered_at
            if lobby_age < self.lobby_stuck_restart_seconds:
                return False

            print(f"Lobby did not enter a match for {lobby_age:.1f}s; restarting Brawl Stars.")
            self.restart_brawl_stars()
            return True

        def manage_time_tasks(self, frame):
            if self.handle_disconnect_screen(frame):
                return

            if self.Time_management.state_check():
                state = get_state(frame)
                previous_state = self.state
                self.state = state
                if state != "match":
                    self.Play.time_since_last_proceeding = time.time()
                if previous_state == "match" and state != "match":
                    self.Play.reset_match_control_state()
                    self.Stage_manager.adaptive_brain.apply_to_play(self.Play)
                elif previous_state != "match" and state == "match":
                    self.Play.reset_match_control_state()
                    self.match_ready_at = time.time() + self.match_warmup_seconds
                frame_data = None
                self.Stage_manager.do_state(state, frame_data)
                self.handle_lobby_watchdog(state)

            if self.Time_management.no_detections_check():
                frame_data = self.Play.time_since_detections
                for key, value in frame_data.items():
                    if time.time() - value > self.no_detections_action_threshold:
                        self.restart_brawl_stars()

            if self.Time_management.idle_check():
                self.lobby_automator.check_for_idle(frame)

        def handle_disconnect_screen(self, frame):
            if time.time() - self.last_disconnect_check < self.disconnect_ocr_interval:
                return False
            self.last_disconnect_check = time.time()

            h, w = frame.shape[:2]
            dialog_crop = frame[int(h * 0.32):int(h * 0.62), int(w * 0.24):int(w * 0.76)]
            dialog_mean = float(dialog_crop.mean())
            dialog_std = float(dialog_crop.std())
            dialog_hsv = cv2.cvtColor(dialog_crop, cv2.COLOR_RGB2HSV)
            dialog_saturation = float(dialog_hsv[:, :, 1].mean())
            if dialog_mean > 90 or dialog_std > 75 or dialog_saturation > 85:
                return False

            center_crop = frame[int(h * 0.22):int(h * 0.55), int(w * 0.15):int(w * 0.70)]
            try:
                text = " ".join(extract_text_strings(center_crop))
            except Exception as e:
                print(f"Could not OCR disconnect screen: {e}")
                return False

            if (
                    "reload" not in text
                    and "disconnect" not in text
                    and "disconnected" not in text
                    and "idle" not in text
            ):
                return False

            self.disconnect_reload_attempts += 1
            self.window_controller.keys_up(list("wasd"))
            print(f"Disconnect/reload screen detected, recovery attempt {self.disconnect_reload_attempts}.")
            if self.disconnect_reload_attempts >= 3:
                print("Reload did not clear disconnect screen; restarting Brawl Stars.")
                self.restart_brawl_stars()
                self.disconnect_reload_attempts = 0
            else:
                self.window_controller.click(550, 450, already_include_ratio=False)
                time.sleep(3)
            return True

        def handle_stale_scrcpy_feed(self, frame_time=None):
            now = time.time()
            stale_age = now - frame_time if frame_time else 0
            age_text = f"{stale_age:.1f}s old" if frame_time else "missing"
            self.Play.window_controller.keys_up(list("wasd"))

            if now - self.last_stale_feed_recovery < 5:
                if now - self.last_stale_feed_message > 2:
                    remaining = 5 - (now - self.last_stale_feed_recovery)
                    print(f"Scrcpy frame is still {age_text}; retrying recovery in {remaining:.1f}s.")
                    self.last_stale_feed_message = now
                return

            self.last_stale_feed_recovery = now
            self.stale_feed_recovery_attempts += 1

            if self.stale_feed_recovery_attempts >= 3 or stale_age > 45:
                print("Scrcpy feed is still frozen; restarting Brawl Stars and scrcpy.")
                self.restart_brawl_stars()
                self.stale_feed_recovery_attempts = 0
            else:
                print(f"Scrcpy frame is {age_text}; restarting scrcpy feed.")
                self.window_controller.restart_scrcpy_client()

        def handle_pause_control(self):
            if not self.control_window.is_paused():
                if self.was_paused:
                    paused_for = time.time() - self.pause_started_at if self.pause_started_at else 0
                    self.start_time += paused_for
                    self.Play.time_since_detections["player"] = time.time()
                    self.Play.time_since_detections["enemy"] = time.time()
                    self.Play.time_since_player_last_found = time.time()
                    self.Play.time_since_last_proceeding = time.time()
                    self.last_processed_frame_id = -1
                    self.was_paused = False
                    self.pause_started_at = None
                    print("Bot resumed.")
                return False

            if not self.was_paused:
                self.window_controller.keys_up(list("wasd"))
                self.Play.reset_match_control_state()
                self.was_paused = True
                self.pause_started_at = time.time()
                print("Bot paused.")
            time.sleep(0.1)
            return True

        def main(self):
            s_time = time.time()
            c = 0
            while True:
                if self.handle_pause_control():
                    s_time = time.time()
                    c = 0
                    continue
                if self.max_ips:
                    frame_start = time.perf_counter()
                if self.run_for_minutes > 0 and not self.in_cooldown:
                    elapsed_time = (time.time() - self.start_time) / 60
                    if elapsed_time >= self.run_for_minutes:
                        if self.state != "match":
                            cprint(f"timer is done, {self.run_for_minutes} minutes are over and bot is not in game. stopping bot fully", "#AAE5A4")
                            break
                        cprint(f"timer is done, {self.run_for_minutes} is over. continuing for 3 minutes if in game", "#AAE5A4")
                        self.in_cooldown = True
                        self.cooldown_start_time = time.time()
                        self.Stage_manager.states['lobby'] = lambda: 0

                if self.in_cooldown:
                    if time.time() - self.cooldown_start_time >= self.cooldown_duration:
                        cprint("stopping bot fully", "#AAE5A4")
                        break

                if abs(s_time - time.time()) > 1:
                    elapsed = time.time() - s_time
                    if elapsed > 0 and not self.visual_debug:
                        current_ips = c / elapsed
                        self.ips_ema = current_ips if self.ips_ema is None else (self.ips_ema * 0.75 + current_ips * 0.25)
                        print(f"{self.ips_ema:.2f} IPS")
                        # Publish per-instance live metrics so the UI's
                        # instance card can render IPS/W-L/etc. The dict is
                        # ignored when running standalone (no instance flag).
                        try:
                            tro = getattr(self.Stage_manager, "Trophy_observer", None)
                            queue = getattr(self.Stage_manager, "brawlers_pick_data", []) or []
                            head = queue[0] if queue else {}
                            wins = int(getattr(tro, "current_wins", 0) or 0)
                            current_trophies = int(getattr(tro, "current_trophies", 0) or 0)
                            # ``head['trophies']`` and ``head['wins']`` are
                            # mutated by stage_manager after every match —
                            # so they always equal CURRENT, not session start.
                            # Use the snapshot we took in __init__ instead so
                            # ``trophies_delta`` reflects real session growth.
                            head_key = str(head.get("brawler") or "").lower()
                            initial_trophies = self._initial_brawler_trophies.get(
                                head_key, int(head.get("trophies") or 0))
                            initial_wins = self._initial_brawler_wins.get(
                                head_key, int(head.get("wins") or 0))
                            session_wins = max(0, wins - initial_wins)
                            session_battles = max(session_wins, int(getattr(tro, "session_battles", session_wins) or session_wins))
                            session_losses = max(0, session_battles - session_wins)
                            win_rate = (session_wins / session_battles) if session_battles > 0 else None
                            _publish_instance_heartbeat({
                                "ips": round(self.ips_ema, 2),
                                "current_brawler": head.get("brawler"),
                                "brawlers_left": max(0, len(queue) - 1),
                                "current_state": self.state,
                                "win_streak": int(getattr(tro, "win_streak", 0) or 0),
                                "session_wins": session_wins,
                                "session_battles": session_battles,
                                "session_losses": session_losses,
                                "trophies_delta": current_trophies - initial_trophies,
                                "win_rate": round(win_rate, 3) if win_rate is not None else None,
                                "current_trophies": current_trophies,
                            })
                            # Discord milestone — fire when session_wins or
                            # session_battles cross an interval boundary. Same
                            # cfg keys + helper as bot_runner's in-process path
                            # so a friend's setup behaves identically whether
                            # they run via legacy /api/start or per-instance.
                            self._maybe_fire_milestone(
                                head, tro, session_wins, session_battles,
                                session_losses, current_trophies, initial_trophies,
                                win_rate,
                            )
                        except Exception:
                            # Never let metric collection kill the bot loop.
                            pass
                        if self.recover_low_ips(self.ips_ema):
                            s_time = time.time()
                            c = 0
                            continue
                        if self.ips_ema is not None and self.ips_ema < 3 and time.time() - self.low_frame_fps_warning_time > 20:
                            _, last_frame_time = self.window_controller.get_latest_frame()
                            frame_age = time.time() - last_frame_time if last_frame_time else 0
                            print(
                                "Low IPS with low CPU usually means the emulator/scrcpy feed is slow. "
                                f"Latest frame age: {frame_age:.1f}s. "
                                "Run: python tools/performance_check.py"
                            )
                            self.low_frame_fps_warning_time = time.time()
                    s_time = time.time()
                    c = 0

                try:
                    frame = self.window_controller.screenshot()
                except ConnectionError as e:
                    print(f"{e} Recovering scrcpy feed.")
                    self.handle_stale_scrcpy_feed()
                    continue

                _, last_ft = self.window_controller.get_latest_frame()
                if last_ft > 0 and (time.time() - last_ft) > self.window_controller.FRAME_STALE_TIMEOUT:
                    self.handle_stale_scrcpy_feed(last_ft)
                    continue

                self.stale_feed_recovery_attempts = 0

                frame_id = self.window_controller.get_latest_frame_id()
                if frame_id == self.last_processed_frame_id:
                    time.sleep(0.01)
                    continue
                self.last_processed_frame_id = frame_id

                self.manage_time_tasks(frame)

                if self.handle_visual_freeze(frame):
                    continue

                if self.state != "match":
                    self.window_controller.keys_up(list("wasd"))
                    time.sleep(0.02)
                    continue

                if self.state == "match" and time.time() < self.match_ready_at:
                    self.window_controller.keys_up(list("wasd"))
                    time.sleep(0.05)
                    continue

                brawler = self.Stage_manager.brawlers_pick_data[0]['brawler']
                self.Play.main(frame, brawler, self)
                c += 1

                if self.max_ips:
                    target_period = 1 / self.max_ips
                    work_time = time.perf_counter() - frame_start
                    if work_time < target_period:
                        time.sleep(target_period - work_time)

            self.control_window.close()

    Main().main()


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn
    from backend.server import app

    _boot_checks()

    url = f"http://{host}:{port}"
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()

    print(f"[PylaAI] UI + API -> {url}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def run_legacy() -> None:
    from gui.hub import Hub
    from gui.login import login
    from gui.main import App
    from gui.select_brawler import SelectBrawler

    all_brawlers = _boot_checks()
    app = App(login, SelectBrawler, pyla_main, all_brawlers, Hub)
    app.start(pyla_version, get_latest_version)


def write_crash_log(error):
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    crash_path = log_dir / "startup_crash.log"
    crash_path.write_text(
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        encoding="utf-8",
    )
    print(f"Pyla crashed during startup. Crash log saved to: {crash_path.resolve()}")
    print(traceback.format_exc())


def main() -> None:
    parser = argparse.ArgumentParser(description="PylaAI launcher")
    parser.add_argument("--legacy", action="store_true", help="use the old Tkinter flow")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--instance", type=int, default=None,
        help="run a single bot against instances/<N>/cfg/ (no UI/server)",
    )
    parser.add_argument(
        "--setup-instances", type=int, default=None, metavar="N",
        help="provision instances/1..N/cfg/ from the current cfg/ dir and exit",
    )
    args = parser.parse_args()

    if args.setup_instances is not None:
        provision_instances(int(args.setup_instances))
        return

    if args.instance is not None:
        # CONFIG_DIR has already been switched in the early parse above.
        run_instance_bot(int(args.instance))
        return

    if args.legacy:
        run_legacy()
    else:
        run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


def provision_instances(count: int) -> None:
    """Copy ``cfg/`` into ``instances/1..count/cfg/`` (skips already-provisioned).

    Idempotent: existing instance dirs are kept as-is so user edits don't get
    clobbered. Prints a summary so the user knows what to do next.
    """
    import shutil

    if count < 1:
        print(f"[provision] count must be >= 1, got {count}")
        return
    base = Path("instances")
    base.mkdir(exist_ok=True)
    src = Path("cfg")
    if not src.is_dir():
        print(f"[provision] source cfg/ not found at {src.resolve()}; aborting")
        return
    for i in range(1, count + 1):
        target = base / str(i) / "cfg"
        if target.is_dir():
            print(f"[provision] instance {i}: {target} already exists, skipping")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, target)
        print(f"[provision] instance {i}: created {target}")
    print(
        f"[provision] done. Run individual instances with: "
        f"python main.py --instance <N>"
    )


def run_instance_bot(instance_id: int) -> None:
    """Headless single-instance bot loop. Reads brawler queue from
    ``instances/<id>/state/session.json`` (written by the backend manager when
    the user starts an instance from the web UI).
    """
    import json

    state_dir = Path("instances") / str(instance_id) / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    session_path = state_dir / "session.json"
    if not session_path.is_file():
        sys.stderr.write(
            f"[instance {instance_id}] no session.json at {session_path}; "
            f"cannot start without a brawler queue.\n"
        )
        sys.exit(3)
    try:
        session = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"[instance {instance_id}] session.json unreadable: {exc}\n")
        sys.exit(3)

    brawlers_data = session.get("brawlers_data") or session
    if not isinstance(brawlers_data, list) or not brawlers_data:
        sys.stderr.write(f"[instance {instance_id}] empty brawlers_data in session.json\n")
        sys.exit(3)

    # Heartbeat: even if the bot's hot loop never calls save_brawler_data
    # (e.g. it spends a long time fighting a single brawler), the manager
    # needs a fresh ts to keep the UI badge from flipping to "stale".
    # The pyla_main loop publishes its live metrics by mutating
    # ``_INSTANCE_HEARTBEAT_STATE`` (see below). The heartbeat thread reads
    # that dict, stamps ts, and atomic-writes the JSON the manager reads.
    heartbeat_path = state_dir / "heartbeat.json"
    stop_heartbeat = threading.Event()
    _INSTANCE_HEARTBEAT_STATE.clear()
    _INSTANCE_HEARTBEAT_STATE.update({
        "started_at": time.time(),
        "ips_history": [],
    })

    def _heartbeat_loop() -> None:
        IPS_HISTORY_LIMIT = 30
        while not stop_heartbeat.is_set():
            try:
                snapshot = dict(_INSTANCE_HEARTBEAT_STATE)
                ips = snapshot.get("ips")
                if ips is not None:
                    history = list(snapshot.get("ips_history") or [])
                    history.append(round(float(ips), 2))
                    if len(history) > IPS_HISTORY_LIMIT:
                        history = history[-IPS_HISTORY_LIMIT:]
                    snapshot["ips_history"] = history
                    _INSTANCE_HEARTBEAT_STATE["ips_history"] = history
                snapshot["ts"] = time.time()
                tmp = heartbeat_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(snapshot), encoding="utf-8")
                tmp.replace(heartbeat_path)
            except Exception:
                pass
            stop_heartbeat.wait(5.0)

    threading.Thread(target=_heartbeat_loop, name="instance-heartbeat", daemon=True).start()

    print(f"[instance {instance_id}] starting bot with {len(brawlers_data)} brawlers queued")
    try:
        _boot_checks()
        pyla_main(brawlers_data)
    finally:
        stop_heartbeat.set()


if __name__ == "__main__":
    sys.path.append(os.path.abspath("."))
    try:
        main()
    except Exception as e:
        write_crash_log(e)
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
        raise
