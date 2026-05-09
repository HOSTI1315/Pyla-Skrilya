import platform
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import load_toml_as_dict


def main():
    cfg = load_toml_as_dict(str(ROOT / "cfg" / "general_config.toml"))
    print("pylaai-op-xxz performance check")
    print(f"Python: {platform.python_version()} {platform.architecture()[0]} ({sys.executable})")
    print(f"ONNX Runtime: {ort.__version__}")
    print(f"Available providers: {', '.join(ort.get_available_providers())}")
    print(f"Configured cpu_or_gpu: {cfg.get('cpu_or_gpu', 'auto')}")
    print(f"Configured directml_device_id: {cfg.get('directml_device_id', 'auto')}")
    print(f"Configured onnx_cpu_threads: {cfg.get('onnx_cpu_threads', 'auto')}")
    print(f"Configured max_ips: {cfg.get('max_ips', 'auto')}")

    model_path = ROOT / "models" / "mainInGameModel.onnx"
    if not model_path.exists():
        print(f"Missing model: {model_path}")
        return 1

    from detect import Detect

    detector = Detect(str(model_path), classes=["enemy", "teammate", "player"])
    print(f"Selected provider: {detector.device}")

    sample = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for _ in range(3):
        detector.detect_objects(sample, conf_tresh=0.75)

    runs = 20
    started = time.perf_counter()
    for _ in range(runs):
        detector.detect_objects(sample, conf_tresh=0.75)
    elapsed = time.perf_counter() - started
    ips = runs / elapsed if elapsed > 0 else 0
    print(f"Detector-only speed: {ips:.2f} IPS")

    if platform.architecture()[0] != "64bit":
        print("WARNING: Python is not 64-bit. Re-run setup.exe to install Python 3.11 64-bit.")
    if detector.device == "CPUExecutionProvider":
        print("WARNING: ONNX is running on CPU. Re-run setup.exe and use DirectML, or set cfg/general_config.toml cpu_or_gpu = \"directml\".")
    if detector.device == "DmlExecutionProvider" and ips < 10:
        print("WARNING: DirectML is active but slow. On dual-GPU laptops, try directml_device_id = \"1\" and restart the bot.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
