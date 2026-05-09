import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


TARGET_PYTHON_VERSION = "3.11.9"
PYTHON_MAJOR_MINOR = "3.11"
PYTHON_INSTALLER_URL = (
    "https://www.python.org/ftp/python/"
    f"{TARGET_PYTHON_VERSION}/python-{TARGET_PYTHON_VERSION}-amd64.exe"
)


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def run(command, cwd=None, env=None):
    print("> " + " ".join(str(part) for part in command))
    subprocess.check_call(command, cwd=str(cwd) if cwd else None, env=env)


def python_info(command):
    try:
        output = subprocess.check_output(
            command + [
                "-c",
                "import platform,sys; "
                "print(sys.executable); "
                "print(platform.python_version()); "
                "print(platform.architecture()[0])",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip().splitlines()
    except Exception:
        return None

    if len(output) < 3:
        return None
    executable, version, arch = output[:3]
    if version.startswith(PYTHON_MAJOR_MINOR + ".") and arch == "64bit":
        return executable
    return None


def find_python():
    candidates = [
        ["py", f"-{PYTHON_MAJOR_MINOR}-64"],
        ["py", f"-{PYTHON_MAJOR_MINOR}"],
        ["python"],
    ]
    for command in candidates:
        executable = python_info(command)
        if executable:
            return command, executable

    common_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path(os.environ.get("ProgramFiles", "")),
    ]
    for root in common_roots:
        if not root.exists():
            continue
        for python_exe in root.glob("Python311/python.exe"):
            executable = python_info([str(python_exe)])
            if executable:
                return [str(python_exe)], executable
    return None, None


def download_python_installer():
    destination = Path(tempfile.gettempdir()) / f"pylaai-python-{TARGET_PYTHON_VERSION}-amd64.exe"
    if destination.exists() and destination.stat().st_size > 1_000_000:
        return destination

    print(f"Downloading Python {TARGET_PYTHON_VERSION}...")
    with urllib.request.urlopen(PYTHON_INSTALLER_URL) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def install_python():
    installer = download_python_installer()
    print(f"Installing Python {TARGET_PYTHON_VERSION}...")
    run([
        str(installer),
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_test=0",
        "SimpleInstall=1",
    ])


def create_run_file(project_dir, python_command):
    python_invocation = " ".join(f'"{part}"' if " " in part else part for part in python_command)
    run_bat = project_dir / "Run pylaai-op-xxz.bat"
    run_bat.write_text(
        "@echo off\n"
        "cd /d %~dp0\n"
        f"{python_invocation} main.py\n"
        "pause\n",
        encoding="ascii",
    )
    print(f"Created {run_bat.name}")


def main():
    project_dir = app_dir()
    setup_py = project_dir / "setup.py"
    main_py = project_dir / "main.py"
    if not setup_py.exists() or not main_py.exists():
        print("setup.exe must be placed in the pylaai-op-xxz project folder next to setup.py and main.py.")
        input("Press Enter to close...")
        return 1

    python_command, python_executable = find_python()
    if not python_command:
        install_python()
        python_command, python_executable = find_python()

    if not python_command:
        print("Could not find Python 3.11 after installation.")
        input("Press Enter to close...")
        return 1

    print(f"Using Python: {python_executable}")
    if "--smoke-test" in sys.argv:
        print("Smoke test passed. Python and project files are available.")
        return 0

    run(python_command + ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    env = os.environ.copy()
    env["PYLAAI_SETUP_AUTO"] = "1"
    run(python_command + ["setup.py", "install"], cwd=project_dir, env=env)
    create_run_file(project_dir, python_command)

    print("")
    print("pylaai-op-xxz setup completed.")
    print("Start your emulator, open Brawl Stars, then run Run pylaai-op-xxz.bat or python main.py.")
    input("Press Enter to close...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
