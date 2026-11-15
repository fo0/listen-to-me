"""What "Optimize for:" and "Focus:" may ask of the engine recommendation.

The device classes (TARGETS) and accuracy/speed weightings (FOCUSES) the
recommendation takes, how a stored config value maps onto them, and why a
target this machine has no usable device for is no option. Split out of
`autoconfig`, which re-exports every name here.

Qt-free and stdlib-only — pure functions over plain data.
"""

from __future__ import annotations

from .autoconfig_hardware import Hardware
from .choices import AUTOCONFIG_FOCUSES, AUTOCONFIG_TARGETS

# The device classes "Optimize for:" offers (choices.AUTOCONFIG_TARGETS).
AUTO, CPU, GPU, NPU = "auto", "cpu", "gpu", "npu"
TARGETS = tuple(value for value, _label in AUTOCONFIG_TARGETS)
# The weightings "Focus:" offers (choices.AUTOCONFIG_FOCUSES).
QUALITY, BALANCED, SPEED = "quality", "balanced", "speed"
FOCUSES = tuple(value for value, _label in AUTOCONFIG_FOCUSES)


class TargetUnavailable(ValueError):
    """An explicit target this machine has no usable device for. The message
    is `unavailable_reason`'s sentence, written for the user."""


def normalize_target(target) -> str:
    """`target` as one of TARGETS, lowercased — "auto" for anything else (a
    hand-edited config value, None)."""
    code = str(target or "").strip().lower()
    return code if code in TARGETS else AUTO


def normalize_focus(focus) -> str:
    """`focus` as one of FOCUSES, lowercased — "balanced" for anything else
    (a hand-edited config value, None)."""
    code = str(focus or "").strip().lower()
    return code if code in FOCUSES else BALANCED


def _gpu_usable(hardware: Hardware) -> bool:
    return hardware.cuda or (hardware.openvino and (hardware.intel_gpu or hardware.arc_gpu))


def unavailable_reason(hardware: Hardware, target) -> str:
    """Why the recommendation cannot optimize for `target` on `hardware`, in
    one sentence for the user; "" when it can. Auto and the CPU always can;
    a GPU needs CTranslate2 to reach an NVIDIA card or OpenVINO to list a
    GPU, an NPU needs OpenVINO to list one — a device no installed backend
    drives is no option."""
    target = normalize_target(target)
    if target == GPU and not _gpu_usable(hardware):
        if not hardware.openvino:
            return (
                "No NVIDIA graphics card usable through CUDA was found, and OpenVINO, the "
                "engine for Intel graphics, is not installed."
            )
        return (
            "No NVIDIA graphics card usable through CUDA was found, and OpenVINO reports no GPU."
        )
    if target == NPU and not (hardware.openvino and hardware.npu):
        if not hardware.openvino:
            return "An NPU can only be used through OpenVINO, which is not installed."
        return "OpenVINO reports no NPU — this PC has none, or its driver is missing."
    return ""
