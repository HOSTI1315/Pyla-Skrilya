"""Tests for backend/instance_manager.py and the per-instance hooks added
to utils (save_brawler_data + set_config_dir)."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _TempCwd:
    """Run a test inside a fresh temporary directory and restore cwd after."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pyla_inst_test_"))
        self._old_cwd = Path.cwd()

    def __enter__(self):
        os.chdir(self.tmp)
        # Provide a fake "global" cfg so create() has something to copy.
        (self.tmp / "cfg").mkdir()
        # Include every key window_controller / utils read at module-load
        # time so unrelated tests can still ``import window_controller`` after
        # us. Otherwise a missing key blows up the next test's import (the
        # cwd swap leaks the fake cfg into module loading).
        (self.tmp / "cfg" / "general_config.toml").write_text(
            'pyla_version = "test"\n'
            'emulator_port = 0\n'
            'current_emulator = "LDPlayer"\n'
            'api_base_url = "default"\n'
            'brawl_stars_package = "com.supercell.brawlstars"\n'
            'super_debug = "no"\n'
            'visual_debug = "no"\n'
            'cpu_or_gpu = "cpu"\n',
            encoding="utf-8",
        )
        return self.tmp

    def __exit__(self, *exc):
        # Reset CONFIG_DIR back to default — tests that called set_config_dir()
        # would otherwise leave it pointing at a now-deleted instances/N/cfg
        # path and break the next test's window_controller import.
        try:
            import utils
            utils.set_config_dir("cfg")
        except Exception:
            pass
        os.chdir(self._old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)


class InstanceManagerTests(unittest.TestCase):
    def setUp(self):
        # Reload the module fresh so REPO_ROOT/INSTANCES_DIR re-resolve to cwd.
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base: Path):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_create_assigns_sequential_ids_and_writes_registry(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            a = mgr.create(name="Slot A", emulator="LDPlayer", port=5555)
            b = mgr.create(name="Slot B", emulator="MuMu", port=16384)
            self.assertEqual(a["id"], 1)
            self.assertEqual(b["id"], 2)
            self.assertEqual(a["name"], "Slot A")
            self.assertEqual(b["emulator"], "MuMu")
            self.assertTrue((base / "instances" / "1" / "cfg" / "general_config.toml").is_file())

            # Per-instance general_config got patched with the chosen port/emulator.
            import toml
            cfg1 = toml.loads(
                (base / "instances" / "1" / "cfg" / "general_config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(cfg1.get("emulator_port"), 5555)
            self.assertEqual(cfg1.get("current_emulator"), "LDPlayer")

    def test_list_returns_all_dirs_with_status(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.create(name="B", emulator="LDPlayer", port=5557)
            entries = mgr.list_instances()
            self.assertEqual([e["id"] for e in entries], [1, 2])
            for e in entries:
                # No process started → status is "stopped".
                self.assertEqual(e["status"], "stopped")
                self.assertIsNone(e["pid"])

    def test_delete_removes_dir(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            self.assertTrue(mgr.delete(1))
            self.assertFalse((base / "instances" / "1").exists())

    def test_start_writes_session_and_marks_starting(self):
        # We don't actually want to spawn the bot — fake out subprocess.Popen
        # so the test stays hermetic.
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)

            import backend.instance_manager as im

            class _FakeProc:
                def __init__(self, *a, **k):
                    self.pid = 99999
                    self.returncode = None
                def poll(self):
                    return None  # still "running"
                def wait(self, timeout=None):
                    return 0

            real_popen = im.subprocess.Popen
            im.subprocess.Popen = lambda *a, **k: _FakeProc()
            try:
                snap = mgr.start(1, [{"brawler": "shelly", "type": "trophies", "push_until": 1000}])
                self.assertEqual(snap["status"], "starting")  # alive but no heartbeat yet
                self.assertEqual(snap["pid"], 99999)
                session = json.loads(
                    (base / "instances" / "1" / "state" / "session.json").read_text(encoding="utf-8")
                )
                self.assertEqual(session["brawlers_data"][0]["brawler"], "shelly")
            finally:
                im.subprocess.Popen = real_popen

    def test_start_refuses_double_start(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            import backend.instance_manager as im

            class _FakeProc:
                pid = 99
                returncode = None
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0

            real_popen = im.subprocess.Popen
            im.subprocess.Popen = lambda *a, **k: _FakeProc()
            try:
                mgr.start(1, [{"brawler": "x", "type": "trophies", "push_until": 1}])
                with self.assertRaises(RuntimeError):
                    mgr.start(1, [{"brawler": "x", "type": "trophies", "push_until": 1}])
            finally:
                im.subprocess.Popen = real_popen

    def test_status_running_when_heartbeat_fresh(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            import backend.instance_manager as im

            class _FakeProc:
                pid = 1234
                returncode = None
                def poll(self):
                    return None

            real_popen = im.subprocess.Popen
            im.subprocess.Popen = lambda *a, **k: _FakeProc()
            try:
                mgr.start(1, [{"brawler": "shelly", "type": "trophies", "push_until": 1000}])
                # Pretend the subprocess wrote a fresh heartbeat.
                heartbeat = base / "instances" / "1" / "state" / "heartbeat.json"
                heartbeat.write_text(
                    json.dumps({"ts": time.time(), "current_brawler": "shelly", "brawlers_left": 0}),
                    encoding="utf-8",
                )
                snap = mgr.get(1)
                self.assertEqual(snap["status"], "running")
                self.assertEqual(snap["heartbeat"]["current_brawler"], "shelly")
            finally:
                im.subprocess.Popen = real_popen


class SaveBrawlerDataPerInstanceTests(unittest.TestCase):
    def setUp(self):
        # Force a fresh utils import so set_config_dir starts at default "cfg".
        for modname in list(sys.modules):
            if modname == "utils":
                del sys.modules[modname]

    def test_default_writes_to_repo_root(self):
        with _TempCwd() as base:
            import utils
            utils.save_brawler_data([{"brawler": "shelly"}])
            self.assertTrue((base / "latest_brawler_data.json").is_file())

    def test_instance_dir_writes_to_per_instance_state(self):
        with _TempCwd() as base:
            import utils
            utils.set_config_dir("instances/3/cfg")
            utils.save_brawler_data([
                {"brawler": "shelly", "push_until": 1000},
                {"brawler": "colt", "push_until": 1000},
            ])
            target = base / "instances" / "3" / "state" / "latest_brawler_data.json"
            self.assertTrue(target.is_file())
            self.assertFalse((base / "latest_brawler_data.json").exists())
            beat = json.loads((base / "instances" / "3" / "state" / "heartbeat.json").read_text())
            self.assertEqual(beat["current_brawler"], "shelly")
            self.assertEqual(beat["brawlers_left"], 1)


class LDPlayerDiscoveryTests(unittest.TestCase):
    """``ldconsole list2`` parsing — uses the real subprocess but with a
    fake binary path so the call is deterministic."""

    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def test_returns_error_when_console_missing(self):
        import backend.instance_manager as im
        im._LDCONSOLE_CANDIDATE_PATHS = [r"C:\does\not\exist\ldconsole.exe"]
        # also stub the cfg-override lookup so it doesn't return a stale path.
        result = im.discover_ldplayer_instances()
        self.assertIsNone(result["console"])
        self.assertEqual(result["instances"], [])
        self.assertIn("not found", result["error"])

    def test_parses_list2_output(self):
        import backend.instance_manager as im

        class _Fake:
            stdout = (
                "0,LDPlayer,12345,67890,1,1234,5678\n"
                "1,LDPlayer-1,0,0,0,0,0\n"
                "2,Дополнительный,0,0,1,9999,0\n"
            )
            stderr = ""
            returncode = 0

        real_run = im.subprocess.run
        real_find = im._find_ldconsole
        im._find_ldconsole = lambda: r"C:\fake\ldconsole.exe"
        im.subprocess.run = lambda *a, **k: _Fake()
        try:
            result = im.discover_ldplayer_instances()
        finally:
            im.subprocess.run = real_run
            im._find_ldconsole = real_find

        self.assertEqual(result["console"], r"C:\fake\ldconsole.exe")
        self.assertEqual(len(result["instances"]), 3)
        self.assertEqual(result["instances"][0],
                         {"index": 0, "name": "LDPlayer", "port": 5555, "running": True})
        self.assertEqual(result["instances"][1]["port"], 5557)
        self.assertEqual(result["instances"][2]["port"], 5559)
        self.assertEqual(result["instances"][2]["name"], "Дополнительный")

    def test_handles_subprocess_timeout(self):
        import backend.instance_manager as im

        def _raises(*a, **k):
            raise im.subprocess.TimeoutExpired(cmd="ldconsole", timeout=4)

        real_run = im.subprocess.run
        real_find = im._find_ldconsole
        im._find_ldconsole = lambda: r"C:\fake\ldconsole.exe"
        im.subprocess.run = _raises
        try:
            result = im.discover_ldplayer_instances()
        finally:
            im.subprocess.run = real_run
            im._find_ldconsole = real_find
        self.assertEqual(result["instances"], [])
        self.assertIn("timed out", result["error"])

    def test_port_for_index_follows_ld_convention(self):
        import backend.instance_manager as im
        self.assertEqual(im._ld_port_for_index(0), 5555)
        self.assertEqual(im._ld_port_for_index(1), 5557)
        self.assertEqual(im._ld_port_for_index(5), 5565)


class StartAllRoutingTests(unittest.TestCase):
    """Verifies the manager's start() is called for every selected instance
    and that 'already running' becomes a 'skipped' rather than a hard error."""

    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_start_loops_over_targets_and_collects_outcomes(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.create(name="B", emulator="LDPlayer", port=5557)
            mgr.create(name="C", emulator="LDPlayer", port=5559)

            import backend.instance_manager as im

            calls: list = []

            class _FakeProc:
                pid = 1
                returncode = None
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0

            def _fake_popen(cmd, **k):
                calls.append(cmd)
                # Find which instance id was requested from the CLI.
                return _FakeProc()

            real_popen = im.subprocess.Popen
            im.subprocess.Popen = _fake_popen
            try:
                snap1 = mgr.start(1, [{"brawler": "shelly"}])
                snap2 = mgr.start(2, [{"brawler": "shelly"}])
                # Trying to start the already-running #1 again must raise.
                with self.assertRaises(RuntimeError):
                    mgr.start(1, [{"brawler": "shelly"}])
                snap3 = mgr.start(3, [{"brawler": "shelly"}])
            finally:
                im.subprocess.Popen = real_popen

            self.assertEqual(snap1["status"], "starting")
            self.assertEqual(snap2["status"], "starting")
            self.assertEqual(snap3["status"], "starting")
            # 3 successful starts (the duplicate raised before incrementing).
            self.assertEqual(len(calls), 3)
            for cmd in calls:
                self.assertIn("--instance", cmd)


class PerInstanceSessionTests(unittest.TestCase):
    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_put_then_get_session_roundtrip(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            saved = mgr.put_session(1, [
                {"brawler": "shelly", "type": "trophies", "push_until": 1500, "trophies": 800},
                {"brawler": "colt", "type": "trophies", "push_until": 1000, "trophies": 0},
            ])
            self.assertEqual(saved["brawlers_data"][0]["brawler"], "shelly")
            got = mgr.get_session(1)
            self.assertIsNotNone(got)
            self.assertEqual(got["brawlers_data"][1]["brawler"], "colt")

    def test_snapshot_includes_session_summary(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.put_session(1, [
                {"brawler": "shelly", "type": "trophies", "push_until": 1500, "trophies": 800},
                {"brawler": "colt", "type": "trophies", "push_until": 1000, "trophies": 0},
            ])
            snap = mgr.get(1)
            self.assertIsNotNone(snap["session"])
            self.assertEqual(snap["session"]["brawler"], "shelly")
            self.assertEqual(snap["session"]["target"], 1500)
            self.assertEqual(snap["session"]["current"], 800)
            self.assertEqual(snap["session"]["queue_length"], 2)

    def test_start_with_none_uses_saved_session(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.put_session(1, [{"brawler": "shelly", "push_until": 1000}])

            import backend.instance_manager as im
            captured: dict = {}

            class _FakeProc:
                pid = 1
                returncode = None
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0

            real_popen = im.subprocess.Popen
            def _fake_popen(cmd, **k):
                captured["cmd"] = cmd
                return _FakeProc()
            im.subprocess.Popen = _fake_popen
            try:
                snap = mgr.start(1, None)  # explicit None — must load saved
            finally:
                im.subprocess.Popen = real_popen

            self.assertEqual(snap["status"], "starting")
            session = json.loads(
                (base / "instances" / "1" / "state" / "session.json").read_text(encoding="utf-8")
            )
            self.assertEqual(session["brawlers_data"][0]["brawler"], "shelly")

    def test_start_with_no_saved_and_none_payload_raises(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            with self.assertRaises(RuntimeError) as ctx:
                mgr.start(1, None)
            self.assertIn("no session", str(ctx.exception))

    def test_clear_session_removes_file(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.put_session(1, [{"brawler": "shelly", "push_until": 1000}])
            self.assertTrue(mgr.clear_session(1))
            self.assertIsNone(mgr.get_session(1))
            # Second clear is a no-op.
            self.assertFalse(mgr.clear_session(1))

    def test_set_auto_restart_persists(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            self.assertFalse(mgr.get(1)["auto_restart"])
            snap = mgr.set_auto_restart(1, True)
            self.assertTrue(snap["auto_restart"])
            # Re-read from disk.
            mgr2 = self._patched_manager(base)
            self.assertTrue(mgr2.get(1)["auto_restart"])

    def test_session_summary_for_wins_mode(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.put_session(1, [{"brawler": "edgar", "type": "wins", "push_until": 50, "wins": 12}])
            snap = mgr.get(1)
            self.assertEqual(snap["session"]["type"], "wins")
            self.assertEqual(snap["session"]["current"], 12)
            self.assertEqual(snap["session"]["target"], 50)


class HeartbeatMetricsTests(unittest.TestCase):
    """The InstanceCard UI renders an IPS sparkline + W/L counters from the
    ``metrics`` block on every snapshot. Verify the manager surfaces them
    when the bot subprocess writes them into heartbeat.json."""

    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_snapshot_exposes_metrics_block(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            heartbeat = base / "instances" / "1" / "state" / "heartbeat.json"
            heartbeat.write_text(json.dumps({
                "ts": time.time(),
                "started_at": time.time() - 60,
                "ips": 11.4,
                "ips_history": [10.1, 10.5, 11.2, 11.4],
                "session_wins": 7,
                "session_losses": 3,
                "session_battles": 10,
                "trophies_delta": 53,
                "win_rate": 0.7,
                "current_brawler": "shelly",
                "brawlers_left": 0,
                "current_state": "match",
            }), encoding="utf-8")
            snap = mgr.get(1)
            self.assertEqual(snap["metrics"]["ips"], 11.4)
            self.assertEqual(snap["metrics"]["wins"], 7)
            self.assertEqual(snap["metrics"]["losses"], 3)
            self.assertEqual(snap["metrics"]["battles"], 10)
            self.assertEqual(snap["metrics"]["trophies_delta"], 53)
            self.assertAlmostEqual(snap["metrics"]["win_rate"], 0.7)
            self.assertEqual(snap["heartbeat"]["ips_history"], [10.1, 10.5, 11.2, 11.4])
            # Aliased so the design mock's ``actions_per_sec`` keeps working.
            self.assertEqual(snap["heartbeat"]["actions_per_sec"], 11.4)
            # Uptime only when alive — instance is "stopped" here so
            # uptime_sec stays None.
            self.assertIsNone(snap["metrics"]["uptime_sec"])

    def test_snapshot_metrics_default_to_none_when_no_heartbeat(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            snap = mgr.get(1)
            self.assertIsNone(snap["metrics"]["ips"])
            self.assertIsNone(snap["metrics"]["wins"])
            self.assertEqual(snap["heartbeat"]["ips_history"], [])


class UserStopVsCrashTests(unittest.TestCase):
    """Regression: a user-issued Stop must not be treated as a crash, and the
    watchdog must not re-spawn the process behind the user's back."""

    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_ctrl_break_exit_is_stopped_not_crashed(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            import backend.instance_manager as im

            class _FakeProc:
                pid = 1
                # 0xC000013A — what CTRL_BREAK leaves on Windows.
                returncode = 3221225786
                def poll(self):
                    return self.returncode
                def wait(self, timeout=None):
                    return self.returncode

            mgr._procs[1] = _FakeProc()
            # User-stopped path: stop() marks it.
            mgr._user_stopped.add(1)
            snap = mgr.get(1)
            self.assertEqual(snap["status"], "stopped",
                             "CTRL_BREAK exit after user-stop must not be 'crashed'")

    def test_user_stopped_blocks_watchdog_restart(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.set_auto_restart(1, True)
            mgr.put_session(1, [{"brawler": "shelly", "push_until": 1000}])
            import backend.instance_manager as im

            class _DeadProc:
                pid = 1
                returncode = 1
                def poll(self):
                    return 1
                def wait(self, timeout=None):
                    return 1

            mgr._procs[1] = _DeadProc()
            mgr._user_stopped.add(1)
            mgr._last_restart_attempt[1] = 0
            mgr._restart_backoff[1] = 0.001

            calls = []
            real_popen = im.subprocess.Popen
            im.subprocess.Popen = lambda *a, **k: calls.append(a) or _DeadProc()
            try:
                # Trip one watchdog tick by hand.
                mgr._stop_watchdog.set()  # stop the live thread first
                # Replay the body of one tick:
                with mgr._lock:
                    for iid, proc in list(mgr._procs.items()):
                        meta = im._read_json(im._state_dir(iid) / "registry.json") or {}
                        if not bool(meta.get("auto_restart")):
                            continue
                        if iid in mgr._user_stopped:
                            continue
                        # If we got past the guard, simulate a respawn.
                        try:
                            mgr.start(iid, mgr._last_session.get(iid))
                        except Exception:
                            pass
            finally:
                im.subprocess.Popen = real_popen
            self.assertEqual(calls, [], "watchdog must NOT respawn a user-stopped instance")

    def test_explicit_start_clears_user_stopped(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="A", emulator="LDPlayer", port=5555)
            mgr.put_session(1, [{"brawler": "shelly", "push_until": 1000}])
            mgr._user_stopped.add(1)
            import backend.instance_manager as im

            class _FakeProc:
                pid = 1
                returncode = None
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0

            real_popen = im.subprocess.Popen
            im.subprocess.Popen = lambda *a, **k: _FakeProc()
            try:
                mgr.start(1, None)
            finally:
                im.subprocess.Popen = real_popen
            self.assertNotIn(1, mgr._user_stopped, "start() must clear the user-stopped guard")


class SerialPortAdbOffsetTests(unittest.TestCase):
    """Regression for the multi-emulator device-selection bug found in live
    test: emulator-XXXX serials report the QEMU console port, but our cfg
    tracks the ADB port (= console + 1). Without the offset both bots latched
    onto the same emulator."""

    def test_emulator_serial_returns_adb_port_not_console(self):
        # Import from adb_serial (the pure module) instead of window_controller
        # so this test runs in any env — including dev machines without the
        # scrcpy/opencv stack the bot runtime needs.
        from adb_serial import _serial_port
        self.assertEqual(_serial_port("emulator-5554"), 5555)
        self.assertEqual(_serial_port("emulator-5556"), 5557)

    def test_tcp_serial_returns_port_directly(self):
        from adb_serial import _serial_port
        self.assertEqual(_serial_port("127.0.0.1:5555"), 5555)
        self.assertEqual(_serial_port("127.0.0.1:16384"), 16384)


class RestartEmulatorTests(unittest.TestCase):
    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_create_infers_ld_index_from_port(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="LD0", emulator="LDPlayer", port=5555)
            mgr.create(name="LD1", emulator="LDPlayer", port=5557)
            mgr.create(name="LD3", emulator="LDPlayer", port=5561)
            metas = [json.loads((base / "instances" / str(i) / "state" / "registry.json").read_text())
                     for i in (1, 2, 3)]
            self.assertEqual(metas[0]["ld_index"], 0)
            self.assertEqual(metas[1]["ld_index"], 1)
            self.assertEqual(metas[2]["ld_index"], 3)

    def test_restart_emulator_calls_ldconsole(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="LD0", emulator="LDPlayer", port=5555)
            import backend.instance_manager as im

            calls: list = []

            def _fake_restart(idx, timeout=8.0):
                calls.append(idx)
                return True, f"LDPlayer instance {idx} restart issued"

            real = im.restart_ldplayer_instance
            im.restart_ldplayer_instance = _fake_restart
            try:
                result = mgr.restart_emulator(1)
            finally:
                im.restart_ldplayer_instance = real
            self.assertTrue(result["ok"])
            self.assertEqual(result["ld_index"], 0)
            self.assertEqual(calls, [0])

    def test_restart_emulator_refuses_non_ldplayer(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="MUMU", emulator="MuMu", port=16384)
            result = mgr.restart_emulator(1)
            self.assertFalse(result["ok"])
            self.assertIn("LDPlayer", result["message"])


class PerInstanceConfigIOTests(unittest.TestCase):
    """The new GET/PUT /api/instances/{id}/config/{section} endpoints write
    into instances/<id>/cfg/<file>.toml. We test the file-level behaviour the
    routes wrap, so the routes themselves stay thin glue."""

    def test_per_instance_general_config_round_trip(self):
        with _TempCwd() as base:
            # Provision via the manager so cfg/general_config.toml gets seeded.
            for modname in list(sys.modules):
                if modname.startswith("backend.instance_manager"):
                    del sys.modules[modname]
            import backend.instance_manager as im
            im.REPO_ROOT = base
            im.INSTANCES_DIR = base / "instances"
            im.GLOBAL_CFG = base / "cfg"
            im.INSTANCES_DIR.mkdir(exist_ok=True)
            mgr = im.InstanceManager()
            mgr.create(name="A", emulator="LDPlayer", port=5557)

            cfg_path = base / "instances" / "1" / "cfg" / "general_config.toml"
            self.assertTrue(cfg_path.is_file())
            import toml
            data = toml.loads(cfg_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(data["emulator_port"], 5557)
            self.assertEqual(data["current_emulator"], "LDPlayer")

            # Write a patch the way put_instance_config would.
            data["super_debug"] = "yes"
            data["max_ips"] = 0
            cfg_path.write_text(toml.dumps(data), encoding="utf-8")
            reread = toml.loads(cfg_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(reread["super_debug"], "yes")
            self.assertEqual(reread["max_ips"], 0)


class RenameTests(unittest.TestCase):
    """Regression for a bug found in real-emulator testing: PUT
    /api/instances/{id}/name on a non-existent id silently created a phantom
    registry.json with no cfg/ dir. The fix raises LookupError so the route
    can return 404 and no ghost instance appears in the listing."""

    def setUp(self):
        for modname in list(sys.modules):
            if modname.startswith("backend.instance_manager"):
                del sys.modules[modname]

    def _patched_manager(self, base):
        import backend.instance_manager as im
        im.REPO_ROOT = base
        im.INSTANCES_DIR = base / "instances"
        im.GLOBAL_CFG = base / "cfg"
        im.INSTANCES_DIR.mkdir(exist_ok=True)
        return im.InstanceManager()

    def test_rename_existing_updates_name_in_snapshot(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="Original", emulator="LDPlayer", port=5555)
            snap = mgr.rename(1, "HOSTI")
            self.assertEqual(snap["name"], "HOSTI")
            # Round-trip through list_instances so we know it's persisted.
            listed = next(i for i in mgr.list_instances() if i["id"] == 1)
            self.assertEqual(listed["name"], "HOSTI")

    def test_rename_truncates_long_names(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="Original", emulator="LDPlayer", port=5555)
            snap = mgr.rename(1, "x" * 500)
            self.assertEqual(len(snap["name"]), 64)

    def test_rename_rejects_empty_name(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            mgr.create(name="Original", emulator="LDPlayer", port=5555)
            with self.assertRaises(ValueError):
                mgr.rename(1, "   ")

    def test_rename_nonexistent_instance_raises_lookup(self):
        with _TempCwd() as base:
            mgr = self._patched_manager(base)
            # Don't create instance 99 first.
            with self.assertRaises(LookupError):
                mgr.rename(99, "Phantom")
            # Critical: the failed rename must NOT leave a ghost dir behind.
            # Before the fix, _state_dir(99) would mkdir instances/99/state and
            # write a registry.json there, so the listing showed a ghost card.
            self.assertFalse((base / "instances" / "99").is_dir(),
                             "rename must not create the instance dir on miss")
            self.assertEqual([i["id"] for i in mgr.list_instances()], [])


if __name__ == "__main__":
    unittest.main()
