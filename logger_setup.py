import os
import re
import sys
from datetime import datetime

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
LOG_DIR = "logs"
TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


class _TimestampedStream:
    def __init__(self, original, file, prefix=""):
        self._original = original
        self._file = file
        self._prefix = prefix
        self._at_line_start = True

    def write(self, text):
        if not text:
            return 0
        # Prefix the live console too so multiple instances are visually
        # distinguishable when the user runs them in parallel terminals.
        if self._prefix:
            stripped_console = ANSI_ESCAPE_RE.sub("", text)
            console_out = []
            at_start = self._at_line_start
            for ch in stripped_console:
                if at_start and ch != "\n":
                    console_out.append(self._prefix)
                    at_start = False
                console_out.append(ch)
                if ch == "\n":
                    at_start = True
            self._original.write("".join(console_out))
        else:
            self._original.write(text)

        stripped = ANSI_ESCAPE_RE.sub("", text)
        out = []
        for ch in stripped:
            if self._at_line_start and ch != "\n":
                out.append(f"[{datetime.now().strftime(TIMESTAMP_FMT)}] {self._prefix}")
                self._at_line_start = False
            out.append(ch)
            if ch == "\n":
                self._at_line_start = True
        self._file.write("".join(out))
        self._file.flush()
        return len(text)

    def flush(self):
        self._original.flush()
        self._file.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


def setup_logging(instance_id=None):
    """Tee stdout/stderr to a timestamped log file. When ``instance_id`` is
    given the log goes into ``instances/<id>/logs/`` and console/file lines
    are prefixed with ``[Instance-<id>]`` so the backend tail-and-stream code
    (and humans watching multiple terminals) can disambiguate."""
    if instance_id is not None:
        log_dir = os.path.join("instances", str(instance_id), "logs")
        prefix = f"[Instance-{instance_id}] "
    else:
        log_dir = LOG_DIR
        prefix = ""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir, f"pyla_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    )
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = _TimestampedStream(sys.stdout, log_file, prefix=prefix)
    sys.stderr = _TimestampedStream(sys.stderr, log_file, prefix=prefix)
    return log_path


def setup_logging_if_enabled(config_path="./cfg/general_config.toml", instance_id=None):
    import toml
    # When running as an instance, the active CONFIG_DIR has already been
    # swapped — resolve the per-instance copy of general_config.toml so the
    # ``terminal_logging`` flag is read from there rather than the global cfg.
    if instance_id is not None and config_path.replace("\\", "/").lstrip("./").startswith("cfg/"):
        try:
            from utils import resolve_cfg_path
            config_path = resolve_cfg_path(config_path)
        except Exception:
            pass
    if not os.path.exists(config_path):
        # Still install the prefix-aware tee for instances even if the config
        # file is missing — otherwise the parent process can't tell which
        # subprocess emitted a line.
        if instance_id is not None:
            return setup_logging(instance_id=instance_id)
        return None
    with open(config_path, "r") as f:
        enabled = toml.load(f).get("terminal_logging", "no")
    if instance_id is not None or str(enabled).lower() in ("yes", "true"):
        return setup_logging(instance_id=instance_id)
    return None
