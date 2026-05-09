"""Per-emulator instance manager.

The web server stays single-process; each emulator runs as a separate
``python main.py --instance N`` subprocess. This module owns the registry of
instances on disk plus the live ``Popen`` handles, and exposes the operations
the FastAPI routes need (list, create, delete, start, stop, status, tail
logs). Per-instance disk layout:

    instances/<id>/cfg/                  # provisioned config copy
    instances/<id>/state/registry.json   # name, emulator, port (set on create)
    instances/<id>/state/session.json    # brawler queue (written on start)
    instances/<id>/state/heartbeat.json  # ts, current_brawler, queued (subprocess)
    instances/<id>/logs/                 # log files written by the subprocess

Instance IDs are integers ≥ 1 to keep them stable across renames and friendly
for the existing ``--instance N`` CLI flag in main.py.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTANCES_DIR = REPO_ROOT / "instances"
GLOBAL_CFG = REPO_ROOT / "cfg"

_HEARTBEAT_FRESH_SEC = 30  # status flips to "stale" past this


def _instance_root(instance_id: int) -> Path:
    return INSTANCES_DIR / str(int(instance_id))


def _state_dir(instance_id: int) -> Path:
    p = _instance_root(instance_id) / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _logs_dir(instance_id: int) -> Path:
    p = _instance_root(instance_id) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


class InstanceManager:
    """In-memory registry of running instance subprocesses + on-disk metadata.

    Thread-safe: the web server may receive concurrent /start and /stop calls,
    and the heartbeat reader runs from the FastAPI request thread.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._procs: Dict[int, subprocess.Popen] = {}
        self._last_session: Dict[int, List[Dict[str, Any]]] = {}
        # Per-instance crash-restart bookkeeping. Tracks last attempt time so we
        # don't re-spawn a process that's failing fast (e.g., bad config).
        self._last_restart_attempt: Dict[int, float] = {}
        self._restart_backoff: Dict[int, float] = {}
        self._consecutive_crashes: Dict[int, int] = {}
        # Set by stop()/delete()/restart_emulator() so the watchdog doesn't
        # immediately re-spawn an instance the user just asked to halt.
        self._user_stopped: set = set()
        INSTANCES_DIR.mkdir(exist_ok=True)
        self._stop_watchdog = threading.Event()
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="instance-watchdog", daemon=True
        )
        self._watchdog.start()

    # ---- discovery / listing -------------------------------------------
    def list_instances(self) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[Dict[str, Any]] = []
            if not INSTANCES_DIR.is_dir():
                return results
            for child in sorted(INSTANCES_DIR.iterdir()):
                if not child.is_dir():
                    continue
                try:
                    iid = int(child.name)
                except ValueError:
                    continue
                results.append(self._snapshot(iid))
            return results

    def _snapshot(self, instance_id: int) -> Dict[str, Any]:
        meta = _read_json(_state_dir(instance_id) / "registry.json") or {}
        heartbeat = _read_json(_state_dir(instance_id) / "heartbeat.json") or {}
        session = _read_json(_state_dir(instance_id) / "dashboard_session.json") or {}
        proc = self._procs.get(instance_id)
        alive = bool(proc and proc.poll() is None)
        last_beat = float(heartbeat.get("ts") or 0)
        age = time.time() - last_beat if last_beat else None
        if alive:
            if last_beat == 0:
                status = "starting"
            elif age is not None and age <= _HEARTBEAT_FRESH_SEC:
                status = "running"
            else:
                status = "stale"
        else:
            # CTRL_BREAK_EVENT on Windows leaves exit_code 0xC000013A /
            # 3221225786 (or signed -1073741510). That's a clean stop, not a
            # crash — the user (or watchdog/restart) sent the signal.
            CTRL_BREAK_EXITS = (3221225786, -1073741510)
            if (proc is not None
                    and proc.returncode not in (None, 0)
                    and proc.returncode not in CTRL_BREAK_EXITS
                    and instance_id not in self._user_stopped):
                status = "crashed"
            elif meta:
                status = "stopped"
            else:
                status = "uninitialized"
        # Pretty session summary so the UI doesn't have to fetch /session
        # for every card just to render the "Shelly → 1500" label.
        brawlers = session.get("brawlers_data") or []
        session_summary = None
        if brawlers:
            head = brawlers[0]
            target = head.get("push_until")
            current = head.get("trophies") if head.get("type") == "trophies" else head.get("wins")
            session_summary = {
                "brawler": head.get("brawler"),
                "type": head.get("type") or "trophies",
                "current": current or 0,
                "target": target or 0,
                "queue_length": len(brawlers),
            }
        # Metrics published by pyla_main into the heartbeat file. Surface
        # them alongside heartbeat so the UI's instance card has enough data
        # to draw the IPS sparkline + W/L counters without a second fetch.
        ips = heartbeat.get("ips")
        ips_history = heartbeat.get("ips_history") or []
        started_at = heartbeat.get("started_at")
        uptime_sec = (time.time() - started_at) if (alive and started_at) else None
        session_wins = heartbeat.get("session_wins")
        session_losses = heartbeat.get("session_losses")
        session_battles = heartbeat.get("session_battles")
        win_rate = heartbeat.get("win_rate")
        trophies_delta = heartbeat.get("trophies_delta")
        metrics = {
            "ips": ips,
            "battles": session_battles,
            "wins": session_wins,
            "losses": session_losses,
            "trophies_delta": trophies_delta,
            "win_rate": win_rate,
            "uptime_sec": round(uptime_sec, 1) if uptime_sec is not None else None,
        }
        return {
            "id": instance_id,
            "name": meta.get("name") or f"Instance {instance_id}",
            "emulator": meta.get("emulator") or "",
            "port": meta.get("port") or 0,
            "auto_restart": bool(meta.get("auto_restart")),
            "status": status,
            "pid": proc.pid if proc and alive else None,
            "exit_code": proc.returncode if proc and not alive else None,
            "session": session_summary,
            "metrics": metrics,
            # Convenience: bot subprocess emits ``started_at`` directly into
            # heartbeat, expose it at instance-level too so the UI doesn't
            # need to dig into heartbeat for uptime.
            "started_at": started_at,
            "heartbeat": {
                "ts": last_beat or None,
                "age_sec": round(age, 1) if age is not None else None,
                "current_brawler": heartbeat.get("current_brawler"),
                "brawlers_left": heartbeat.get("brawlers_left"),
                "current_state": heartbeat.get("current_state"),
                "ips": ips,
                "ips_history": ips_history,
                "actions_per_sec": ips,  # alias the design mock uses
            },
        }

    def get(self, instance_id: int) -> Dict[str, Any]:
        return self._snapshot(int(instance_id))

    # ---- create / delete -----------------------------------------------
    def create(
        self,
        name: str = "",
        emulator: str = "LDPlayer",
        port: int = 0,
        copy_from: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            existing_ids = {
                int(c.name) for c in INSTANCES_DIR.iterdir()
                if c.is_dir() and c.name.isdigit()
            }
            new_id = (max(existing_ids) + 1) if existing_ids else 1

            target_cfg = _instance_root(new_id) / "cfg"
            target_cfg.parent.mkdir(parents=True, exist_ok=True)
            if copy_from is not None and (_instance_root(copy_from) / "cfg").is_dir():
                shutil.copytree(_instance_root(copy_from) / "cfg", target_cfg)
            elif GLOBAL_CFG.is_dir():
                shutil.copytree(GLOBAL_CFG, target_cfg)
            else:
                target_cfg.mkdir(parents=True, exist_ok=True)

            # Stamp the per-instance general_config with the chosen port so the
            # bot's WindowController picks the right emulator without further
            # human editing.
            self._patch_general_config(new_id, emulator=emulator, port=port)

            # LDPlayer convention: port = 5555 + 2 * index. Store the inferred
            # index so restart_emulator() can call ldconsole quit/launch.
            ld_index = None
            if emulator == "LDPlayer" and int(port) >= 5555 and (int(port) - 5555) % 2 == 0:
                ld_index = (int(port) - 5555) // 2
            registry = {
                "id": new_id,
                "name": name or f"Instance {new_id}",
                "emulator": emulator,
                "port": int(port),
                "ld_index": ld_index,
                "created_at": time.time(),
            }
            _atomic_write_json(_state_dir(new_id) / "registry.json", registry)
            # Seed empty stat files (match_log/match_history/brawler_stats etc.)
            # so the per-instance bot has somewhere to append from match #1
            # AND the UI's stats / brawlers panes don't render "no data".
            try:
                from utils import bootstrap_stat_files
                bootstrap_stat_files(str(target_cfg))
            except Exception as exc:
                print(f"create(): bootstrap_stat_files failed for instance {new_id}: {exc}")

            # Per-instance Brawl Stars API config: keep ONLY player_tag (the
            # field that legitimately differs per emulator). The token and
            # developer credentials live in the global cfg only — this
            # avoids the user typing the same eyJ0eXAi… token into every
            # instance's Cfg modal.
            try:
                import toml
                api_path = target_cfg / "brawl_stars_api.toml"
                if api_path.is_file():
                    data = toml.loads(api_path.read_text(encoding="utf-8-sig")) or {}
                    slim = {"player_tag": str(data.get("player_tag") or "").strip() or "#YOURTAG"}
                    api_path.write_text(toml.dumps(slim), encoding="utf-8")
            except Exception as exc:
                print(f"create(): could not slim brawl_stars_api.toml for instance {new_id}: {exc}")
            return self._snapshot(new_id)

    # ---- per-instance saved session ------------------------------------
    def get_session(self, instance_id: int) -> Optional[Dict[str, Any]]:
        """Saved Dashboard-style session for this instance, or None."""
        return _read_json(_state_dir(int(instance_id)) / "dashboard_session.json")

    def put_session(self, instance_id: int, session: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a Dashboard-style session for later starts. The session is
        a list of brawler entries identical to what /api/start accepts."""
        if not isinstance(session, list) or not session:
            raise ValueError("session must be a non-empty list of brawler entries")
        sanitized = []
        for entry in session:
            if not isinstance(entry, dict):
                raise ValueError("every session entry must be an object")
            cleaned = dict(entry)
            cleaned.pop("run_for_minutes", None)
            sanitized.append(cleaned)
        _atomic_write_json(_state_dir(int(instance_id)) / "dashboard_session.json",
                           {"brawlers_data": sanitized, "saved_at": time.time()})
        return {"brawlers_data": sanitized}

    def clear_session(self, instance_id: int) -> bool:
        target = _state_dir(int(instance_id)) / "dashboard_session.json"
        if target.is_file():
            target.unlink()
            return True
        return False

    def set_auto_restart(self, instance_id: int, enabled: bool) -> Dict[str, Any]:
        """Toggle the manager's watchdog auto-restart for this instance.

        Stored on the registry so it survives backend restarts. The watchdog
        thread re-reads the flag each tick.
        """
        path = _state_dir(int(instance_id)) / "registry.json"
        meta = _read_json(path) or {}
        meta["auto_restart"] = bool(enabled)
        _atomic_write_json(path, meta)
        return self._snapshot(int(instance_id))

    def rename(self, instance_id: int, new_name: str) -> Dict[str, Any]:
        """Update the human label shown on the instance card. The numeric id
        and on-disk paths are unchanged so saved sessions / heartbeat / logs
        keep working."""
        iid = int(instance_id)
        clean = (new_name or "").strip()
        if not clean:
            raise ValueError("name must not be empty")
        if len(clean) > 64:
            clean = clean[:64]
        # Refuse to rename an instance that doesn't exist on disk yet — both
        # the cfg/ dir and an existing registry.json are valid signals. Without
        # this check, ``_state_dir(iid)`` happily mkdir's the missing instance
        # root, leaving a phantom registry.json behind that the UI lists as a
        # ghost instance.
        root = _instance_root(iid)
        registry = _read_json(root / "state" / "registry.json")
        if not (root / "cfg").is_dir() and registry is None:
            raise LookupError(f"instance {iid} does not exist")
        path = _state_dir(iid) / "registry.json"
        meta = _read_json(path) or {}
        meta["name"] = clean
        _atomic_write_json(path, meta)
        return self._snapshot(iid)

    def cfg_path(self, instance_id: int, file_name: str) -> Path:
        """Resolve a per-instance cfg file path (used by API/webhook helpers)."""
        return _instance_root(int(instance_id)) / "cfg" / file_name

    def _patch_general_config(self, instance_id: int, emulator: str, port: int) -> None:
        """Write ``current_emulator`` and ``emulator_port`` into the instance's
        general_config.toml. Best-effort: if toml is missing or broken we just
        leave the user to edit it manually."""
        try:
            import toml
        except Exception:
            return
        cfg_path = _instance_root(instance_id) / "cfg" / "general_config.toml"
        if not cfg_path.is_file():
            return
        try:
            data = toml.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        if emulator:
            data["current_emulator"] = emulator
        if int(port) > 0:
            data["emulator_port"] = int(port)
        try:
            cfg_path.write_text(toml.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def delete(self, instance_id: int) -> bool:
        with self._lock:
            self.stop(instance_id)
            root = _instance_root(instance_id)
            if not root.is_dir():
                return False
            shutil.rmtree(root, ignore_errors=True)
            self._procs.pop(instance_id, None)
            return True

    # ---- lifecycle ------------------------------------------------------
    def start(self, instance_id: int, brawlers_data: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        with self._lock:
            iid = int(instance_id)
            existing = self._procs.get(iid)
            if existing and existing.poll() is None:
                raise RuntimeError(f"instance {iid} is already running (pid {existing.pid})")
            root = _instance_root(iid)
            if not (root / "cfg").is_dir():
                raise RuntimeError(f"instance {iid} not provisioned (no cfg dir)")

            # Resolve which brawlers to send: explicit arg wins, otherwise
            # use this instance's saved session (per-instance individual
            # session feature). Without either we can't start.
            if brawlers_data is None:
                stored = self.get_session(iid) or {}
                brawlers_data = stored.get("brawlers_data") or []
            if not isinstance(brawlers_data, list) or not brawlers_data:
                raise RuntimeError(
                    f"instance {iid} has no session: pass brawlers_data or save one via PUT /api/instances/{iid}/session"
                )
            self._last_session[iid] = list(brawlers_data)
            # Explicit start clears the user-stopped flag so the watchdog can
            # auto-restart on a future crash.
            self._user_stopped.discard(iid)

            # Write the brawler queue the subprocess will consume on boot.
            session = {
                "brawlers_data": brawlers_data,
                "started_at": time.time(),
            }
            _atomic_write_json(_state_dir(iid) / "session.json", session)
            # Reset heartbeat so the snapshot doesn't show stale data from a
            # previous run.
            _atomic_write_json(_state_dir(iid) / "heartbeat.json", {"ts": 0})

            log_path = _logs_dir(iid) / f"manager_{int(time.time())}.log"
            log_handle = open(log_path, "ab", buffering=0)

            cmd = [sys.executable, "-u", "main.py", "--instance", str(iid)]
            # CREATE_NEW_PROCESS_GROUP on Windows so we can ctrl-break-style
            # signal it; on POSIX, start_new_session does the same job.
            kwargs: Dict[str, Any] = {
                "cwd": str(REPO_ROOT),
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True

            proc = subprocess.Popen(cmd, **kwargs)
            self._procs[iid] = proc
            return self._snapshot(iid)

    def stop(self, instance_id: int, timeout: float = 8.0) -> bool:
        with self._lock:
            iid = int(instance_id)
            proc = self._procs.get(iid)
            # Mark as user-stopped even when there's no live proc so a stale
            # watchdog tick doesn't try to restart on the next pass.
            self._user_stopped.add(iid)
            if proc is None or proc.poll() is not None:
                return False
            try:
                if os.name == "nt":
                    # CTRL_BREAK is the only signal the new process group will
                    # accept while still letting Python's atexit handlers run.
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    pass
            return True

    def restart_emulator(self, instance_id: int) -> Dict[str, Any]:
        """Force-restart the underlying emulator VM (LDPlayer only for now).

        Returns a dict with ``ok``, ``message``, ``ld_index``. When the bot
        process is currently running it's stopped first so it can re-attach
        to the freshly-booted emulator on the next start.
        """
        iid = int(instance_id)
        meta = _read_json(_state_dir(iid) / "registry.json") or {}
        ld_index = meta.get("ld_index")
        if meta.get("emulator") != "LDPlayer" or ld_index is None:
            return {"ok": False, "message": "restart_emulator currently only supports LDPlayer instances with a known ld_index"}
        # Stop the bot first so it doesn't fight the emulator restart.
        self.stop(iid)
        ok, message = restart_ldplayer_instance(int(ld_index))
        return {"ok": ok, "message": message, "ld_index": ld_index}

    # ---- watchdog -------------------------------------------------------
    def shutdown(self) -> None:
        """Stop the watchdog thread (called on server shutdown)."""
        self._stop_watchdog.set()

    def _watchdog_loop(self) -> None:
        """Re-spawn instances that crashed *if* their auto_restart flag is set.

        Backoff doubles after each failed attempt up to 5 minutes, so a
        misconfigured instance that crashes immediately doesn't burn CPU.
        Reset to 5s once the instance survives 60s.
        """
        BASE_DELAY = 5.0
        MAX_DELAY = 300.0
        STABILITY_WINDOW = 60.0
        # After this many crashes in a row we assume the emulator VM itself is
        # wedged (frozen LDPlayer, ADB unresponsive) and try restarting *it*
        # via ldconsole before re-spawning the bot. Resets to 0 on a stable
        # run.
        EMULATOR_RESTART_THRESHOLD = 3
        while not self._stop_watchdog.wait(10.0):
            try:
                with self._lock:
                    for iid, proc in list(self._procs.items()):
                        if proc is None or proc.poll() is None:
                            started = self._last_restart_attempt.get(iid, 0)
                            if started and time.time() - started > STABILITY_WINDOW:
                                self._restart_backoff[iid] = BASE_DELAY
                                self._consecutive_crashes[iid] = 0
                            continue
                        meta = _read_json(_state_dir(iid) / "registry.json") or {}
                        if not bool(meta.get("auto_restart")):
                            continue
                        # User explicitly stopped this instance — respect that
                        # until they hit Start again.
                        if iid in self._user_stopped:
                            continue
                        last = self._last_restart_attempt.get(iid, 0)
                        delay = self._restart_backoff.get(iid, BASE_DELAY)
                        if time.time() - last < delay:
                            continue
                        last_session = self._last_session.get(iid)
                        if last_session is None:
                            stored = self.get_session(iid) or {}
                            last_session = stored.get("brawlers_data")
                        if not last_session:
                            continue
                        crashes = self._consecutive_crashes.get(iid, 0) + 1
                        self._consecutive_crashes[iid] = crashes
                        print(f"[watchdog] instance {iid} crashed (exit={proc.returncode}, streak={crashes}); auto-restart in {delay:.0f}s")
                        self._procs.pop(iid, None)
                        # Escalation: if the bot keeps dying immediately the
                        # emulator itself is probably frozen. Kick it via
                        # ldconsole and reset the streak.
                        if (crashes >= EMULATOR_RESTART_THRESHOLD
                                and meta.get("emulator") == "LDPlayer"
                                and meta.get("ld_index") is not None):
                            print(f"[watchdog] instance {iid}: {crashes} crashes in a row → restarting LDPlayer VM #{meta.get('ld_index')}")
                            ok, message = restart_ldplayer_instance(int(meta["ld_index"]))
                            print(f"[watchdog] LDPlayer restart: ok={ok} msg={message}")
                            self._consecutive_crashes[iid] = 0
                            # Give LDPlayer ~25s to boot Android before re-spawning the bot.
                            time.sleep(25.0)
                        try:
                            self.start(iid, last_session)
                            self._last_restart_attempt[iid] = time.time()
                            self._restart_backoff[iid] = min(MAX_DELAY, max(delay * 2.0, BASE_DELAY))
                        except Exception as exc:
                            print(f"[watchdog] auto-restart of instance {iid} failed: {exc}")
                            self._restart_backoff[iid] = min(MAX_DELAY, max(delay * 2.0, BASE_DELAY))
                            self._last_restart_attempt[iid] = time.time()
            except Exception as exc:
                print(f"[watchdog] tick error: {exc}")

    # ---- logs -----------------------------------------------------------
    def list_logs(self, instance_id: int) -> List[str]:
        d = _logs_dir(int(instance_id))
        return sorted(p.name for p in d.glob("*.log"))

    def tail_log(self, instance_id: int, lines: int = 200, file: Optional[str] = None) -> List[str]:
        d = _logs_dir(int(instance_id))
        if file:
            target = d / file
        else:
            files = sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
            if not files:
                return []
            target = files[-1]
        if not target.is_file():
            return []
        try:
            content = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        if lines and lines > 0:
            content = content[-int(lines):]
        return content


MANAGER = InstanceManager()


# ---------------------------------------------------------------------------
# LDPlayer auto-discovery
#
# LDPlayer ships ``ldconsole.exe`` (and an older ``dnconsole.exe``) which can
# enumerate the installed VMs. ``ldconsole list2`` prints
#   index,name,top_window_handle,bind_window_handle,android_started,pid,vbox_pid
# and the ADB port is implied by the index: 5555 + 2*N. We surface this so the
# UI's "Add Instance" wizard can offer "Detect emulators" instead of forcing
# the user to type ports they don't remember.
# ---------------------------------------------------------------------------
def _build_ldconsole_candidates() -> List[str]:
    """LDPlayer can land on any drive — generate candidate paths for every
    fixed/local drive plus the historical Program Files locations on C:."""
    paths: List[str] = []
    drives: List[str] = []
    if os.name == "nt":
        for letter in "CDEFGHIJ":
            root = f"{letter}:\\"
            if os.path.isdir(root):
                drives.append(letter)
    else:
        drives.append("")
    rel_subpaths = [
        r"LDPlayer\LDPlayer9",
        r"LDPlayer\LDPlayer4.0",
        r"Program Files\LDPlayer\LDPlayer9",
        r"Program Files\LDPlayer\LDPlayer4.0",
        r"Program Files (x86)\LDPlayer\LDPlayer9",
        r"Program Files (x86)\LDPlayer\LDPlayer4.0",
    ]
    for drive in drives:
        prefix = f"{drive}:\\" if drive else "/"
        for sub in rel_subpaths:
            for exe in ("ldconsole.exe", "dnconsole.exe"):
                paths.append(os.path.join(prefix, sub, exe))
    return paths


_LDCONSOLE_CANDIDATE_PATHS = _build_ldconsole_candidates()


def _find_ldconsole() -> Optional[str]:
    """Return the first existing ldconsole.exe / dnconsole.exe path, or None."""
    # Allow the user to pin an explicit path via the global cfg so we don't
    # have to keep extending the candidate list every time LDPlayer ships a
    # new install layout.
    try:
        import toml
        cfg_file = REPO_ROOT / "cfg" / "general_config.toml"
        if cfg_file.is_file():
            data = toml.loads(cfg_file.read_text(encoding="utf-8-sig"))
            override = str(data.get("ldplayer_console_path", "")).strip()
            if override and Path(override).is_file():
                return override
    except Exception:
        pass
    for p in _LDCONSOLE_CANDIDATE_PATHS:
        if Path(p).is_file():
            return p
    return None


def _ld_port_for_index(index: int) -> int:
    """LDPlayer convention: instance 0 → 5555, 1 → 5557, 2 → 5559, …"""
    return 5555 + 2 * int(index)


def discover_ldplayer_instances(timeout: float = 4.0) -> Dict[str, Any]:
    """Run ``ldconsole list2`` and return parsed instance metadata.

    Returns a dict with:
        ``console``: path to the console used (or None when not found)
        ``instances``: list of {index, name, port, running}

    Falls back to ``[]`` for instances if the console is missing or the call
    times out — the UI shows that to the user as "no LDPlayer detected" and
    they can still create an instance manually.
    """
    console = _find_ldconsole()
    if not console:
        return {"console": None, "instances": [], "error": "ldconsole.exe not found"}
    try:
        result = subprocess.run(
            [console, "list2"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return {"console": console, "instances": [], "error": "ldconsole list2 timed out"}
    except Exception as exc:
        return {"console": console, "instances": [], "error": f"ldconsole call failed: {exc}"}

    instances: List[Dict[str, Any]] = []
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        name = parts[1] or f"LDPlayer-{idx}"
        try:
            android_started = int(parts[4]) == 1
        except ValueError:
            android_started = False
        instances.append({
            "index": idx,
            "name": name,
            "port": _ld_port_for_index(idx),
            "running": android_started,
        })
    return {"console": console, "instances": instances}


def restart_ldplayer_instance(index: int, timeout: float = 8.0) -> Tuple[bool, str]:
    """``ldconsole quit`` + ``ldconsole launch`` to recover a wedged emulator.

    Returns (ok, message). The caller (recovery state machine) escalates from
    soft reconnect → restart_ldplayer_instance → process exit.
    """
    console = _find_ldconsole()
    if not console:
        return False, "ldconsole.exe not found"
    try:
        subprocess.run(
            [console, "quit", "--index", str(int(index))],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as exc:
        return False, f"quit failed: {exc}"
    # Brief pause so LDPlayer's housekeeping finishes before we relaunch.
    time.sleep(1.5)
    try:
        subprocess.Popen(
            [console, "launch", "--index", str(int(index))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as exc:
        return False, f"launch failed: {exc}"
    return True, f"LDPlayer instance {index} restart issued"
