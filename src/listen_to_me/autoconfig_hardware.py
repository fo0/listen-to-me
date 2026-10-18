"""What the engine recommendation knows about this machine.

`hardware_from_status` reads the dict `diagnostics.hardware_status` builds on
a worker thread into a `Hardware`: an NVIDIA GPU CTranslate2 can use, the
optional OpenVINO and Parakeet backends, the Intel GPU and NPU OpenVINO
lists, and the processor. `autoconfig` recommends from it; this module only
reads, and never probes anything itself.

Qt-free and stdlib-only — pure functions over plain data, so every reading
is checked headless (selftest "engine recommendation reads the probe").
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# An OpenVINO GPU whose name says Arc: the discrete A/B-series cards and the
# integrated graphics of Core Ultra ("Intel(R) Arc(TM) Graphics").
_ARC = re.compile(r"\barc\b", re.IGNORECASE)
_TRADEMARKS = re.compile(r"\((?:r|tm|c)\)|[®™]", re.IGNORECASE)
_CLOCK = re.compile(r"\s+(?:cpu\s+)?@\s*[\d.]+\s*[gm]hz\s*$", re.IGNORECASE)
_GPU_TAG = re.compile(r"\s*\([di]gpu\)\s*$", re.IGNORECASE)
_NAME_MAX = 64


@dataclass(frozen=True)
class Hardware:
    """What the recommendation weighs.

    The defaults are the conservative answers — no GPU, no optional backend,
    core count unknown (0) — which a missing or broken probe falls back to:
    they recommend faster-whisper's small model on the CPU, the setup that
    runs wherever the app runs.
    """

    cuda: bool = False  # an NVIDIA GPU CTranslate2 can use
    openvino: bool = False  # the OpenVINO backend is installed
    intel_gpu: bool = False  # OpenVINO lists a "GPU" (GPU.0), Arc or not
    arc_gpu: bool = False  # that GPU is an Intel Arc
    gpu_name: str = ""  # that GPU, shortened ("Intel Arc A770 Graphics")
    npu: bool = False  # OpenVINO lists an NPU
    npu_name: str = ""  # that NPU, shortened ("Intel AI Boost")
    parakeet: bool = False  # the Parakeet backend (onnx-asr + ONNX Runtime) is installed
    physical_cores: int = 0  # 0 = unknown
    performance_cores: int = 0  # 0 = unknown
    avx2: bool | None = None  # None = unknown
    x86: bool | None = None  # None = unknown
    cpu_name: str = ""  # shortened ("Intel Core i7-1265U"), "" = unknown


def _section(status: dict, key: str) -> dict:
    value = status.get(key)
    return value if isinstance(value, dict) else {}


def _count(value) -> int:
    """A core count from the probe, 0 (unknown) for anything that is not a
    positive whole number — a bool is no count."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


def _flag(value) -> bool | None:
    return value if isinstance(value, bool) else None


def short_name(name) -> str:
    """A hardware name without trademark marks, clock speed and the
    (dGPU)/(iGPU) tag — "Intel(R) Core(TM) i7-8650U CPU @ 1.90GHz" reads
    "Intel Core i7-8650U". "" for anything that is not a string."""
    if not isinstance(name, str):
        return ""
    text = _GPU_TAG.sub("", _CLOCK.sub("", _TRADEMARKS.sub("", name)))
    return " ".join(text.split())[:_NAME_MAX].strip()


def _device_entries(devices) -> list[dict]:
    """The dict entries of probe_openvino's device list; [] for anything
    that is not a list."""
    if not isinstance(devices, list):
        return []
    return [device for device in devices if isinstance(device, dict)]


def _default_gpu(devices) -> tuple[str, bool] | None:
    """(shortened name, is an Intel Arc) of the GPU ``openvino_device =
    "gpu"`` runs on; None when OpenVINO lists no GPU.

    "gpu" becomes OpenVINO's "GPU", an alias for GPU.0 — listed as "GPU"
    when it is the only one, else "GPU.0", and always the integrated GPU
    when there is one. An Arc card enumerated behind a UHD/Iris iGPU (GPU.1)
    is out of the config's reach, and recommending "gpu" for it would run
    the iGPU while the reason names the card — so that machine's GPU is the
    iGPU, by its own name.
    """
    for device in _device_entries(devices):
        if str(device.get("device") or "").upper() not in ("GPU", "GPU.0"):
            continue
        name = device.get("name")
        arc = isinstance(name, str) and bool(_ARC.search(name))
        return short_name(name) or ("Intel Arc graphics" if arc else "Intel graphics"), arc
    return None


def _npu_name(devices) -> str | None:
    """The shortened name of the NPU ``openvino_device = "npu"`` runs on
    (OpenVINO's "NPU"); None when OpenVINO lists none."""
    for device in _device_entries(devices):
        if str(device.get("device") or "").upper().split(".")[0] != "NPU":
            continue
        return short_name(device.get("name")) or "Intel NPU"
    return None


def hardware_from_status(status) -> Hardware:
    """The `Hardware` a `diagnostics.hardware_status()` dict describes.

    Reads the "cuda", "openvino", "parakeet" and "cpu" sections. Never
    raises: a section that is missing, not a dict, or holds a value of the
    wrong type contributes the conservative default for what it would have
    said — so an old or broken probe can only make the recommendation
    lighter, never point it at hardware that is not there. An Intel GPU or
    NPU counts only with OpenVINO installed: no other backend drives one.
    """
    if not isinstance(status, dict):
        return Hardware()
    cuda = _section(status, "cuda")
    openvino = _section(status, "openvino")
    cpu = _section(status, "cpu")
    ov_installed = openvino.get("installed") is True
    devices = openvino.get("devices") if ov_installed else None
    gpu = _default_gpu(devices)
    npu = _npu_name(devices)
    physical = _count(cpu.get("physical_cores"))
    performance = _count(cpu.get("performance_cores"))
    if physical and performance > physical:
        performance = physical
    hardware = Hardware(
        cuda=cuda.get("available") is True,
        openvino=ov_installed,
        intel_gpu=gpu is not None,
        arc_gpu=gpu is not None and gpu[1],
        gpu_name=gpu[0] if gpu else "",
        npu=npu is not None,
        npu_name=npu or "",
        parakeet=_section(status, "parakeet").get("installed") is True,
        physical_cores=physical,
        performance_cores=performance,
        avx2=_flag(cpu.get("avx2")),
        x86=_flag(cpu.get("x86")),
        cpu_name=short_name(cpu.get("name")),
    )
    log.debug("hardware for the engine recommendation: %s", hardware)
    return hardware
