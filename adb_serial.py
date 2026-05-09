"""Pure helpers for parsing adb-devices serials.

Lives in its own module (not window_controller.py) so unit tests can import
without dragging the scrcpy / opencv / adb-shell dependency tree along — the
multi-emulator port-offset logic is a small parser, no reason to require the
full bot runtime to verify it.
"""

from __future__ import annotations


def _serial_port(serial):
    """Return the *ADB* port for an adb-devices serial.

    LDPlayer / generic Android emulators report themselves to ``adb devices``
    as ``emulator-<qemu_console_port>``. The actual ADB port is ``+1`` (qemu
    convention: console + 1 = adb). Without this offset, multi-instance setups
    pick the wrong device because ``configured_port=5557`` (the ADB port for
    LD instance #1) never matches ``emulator-5556``'s reported 5556.
    """
    if serial.startswith("emulator-"):
        try:
            return int(serial.rsplit("-", 1)[1]) + 1
        except ValueError:
            return None
    if ":" in serial:
        try:
            return int(serial.rsplit(":", 1)[1])
        except ValueError:
            return None
    return None


def _is_local_adb_serial(serial):
    return (
        str(serial or "").startswith("127.0.0.1:")
        or str(serial or "").startswith("localhost:")
        or str(serial or "").startswith("emulator-")
    )
