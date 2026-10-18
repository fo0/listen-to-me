"""Engine auto-configuration: the best engine setup this machine can run.

`autoconfig_hardware.hardware_from_status` reads the dict
`diagnostics.hardware_status` builds on a worker thread into a `Hardware`;
`recommend` turns that, the dictation language and the device class to
optimize for into a `Recommendation` — the config keys to set, plus the sentences
that explain the choice to someone who has never heard of CUDA. `changes`
compares it with a config; `autoconfig_text` words what applying it would
change. The Settings window and the first-run wizard show and apply it; this
module touches neither the UI nor the config.

Quality first, in this order:

1. An NVIDIA GPU CTranslate2 can use → faster-whisper on it with Whisper's
   large turbo model (its German fine-tune for German): the best accuracy
   the app offers, at graphics-card speed.
2. Otherwise Parakeet, when it is installed and understands the language (or
   the language is auto-detected) → on the CPU, int8, the German fine-tune
   for German: about as accurate as the turbo and several times faster on a
   processor.
3. Otherwise an Intel Arc GPU that OpenVINO drives as its "GPU" (GPU.0) →
   OpenVINO with the large turbo on it, int8. The German fine-tune has no
   OpenVINO conversion.
4. Otherwise faster-whisper on the CPU: the large turbo (German: its German
   fine-tune) with 8 or more physical cores and AVX2 not known to be missing,
   else small — a large model on a weaker processor takes longer to
   transcribe than the dictation took to speak.

That is the "auto" target. "Optimize for:" beside the button picks a device
class instead, and the recommendation then stays on it — never one on another
class, and never a model the backend cannot run:

- "cpu" → rules 2 and 4 alone: Parakeet or faster-whisper on the processor,
  whatever graphics card or NPU is there.
- "gpu" → an NVIDIA GPU as in rule 1, else the Intel GPU OpenVINO runs as
  "gpu": an Arc as in rule 3, any other Intel GPU with the small model.
- "npu" → OpenVINO on the NPU at int8 with Whisper's small model, a
  conservative start.

A GPU or NPU is only an option when an installed backend reports it;
`unavailable_reason` says why one is not, and `recommend` raises
`TargetUnavailable` rather than answer for another class.

The recommendation never names `language`: that is the user's choice and the
input here, never an output.

Qt-free and stdlib-only — pure functions over plain data, so the whole rule
table is checked headless (selftest "engine recommendation matrix").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .autoconfig_hardware import Hardware
from .choices import (
    AUTOCONFIG_TARGETS,
    GERMAN_TURBO_CT2,
    LANGUAGES,
    MODEL_CHOICES,
    PARAKEET_QUANTIZATIONS,
)
from .parakeet_models import DEFAULT_MODEL as PARAKEET_V3
from .parakeet_models import V3_LANGUAGES

PARAKEET_GERMAN = "parakeet-primeline-de"
TURBO = "large-v3-turbo"
SMALL = "small"

# Physical cores from which a CPU runs Whisper's large turbo fast enough to
# dictate with; below it, small.
LARGE_MODEL_MIN_CORES = 8

_NO_CUDA = "No usable NVIDIA graphics card found"
# The lead of a CPU recommendation the user asked for: a GPU may well be
# there, so it must not say there is none.
_CPU_CHOSEN = "You chose the CPU"

# The device classes "Optimize for:" offers (choices.AUTOCONFIG_TARGETS).
AUTO, CPU, GPU, NPU = "auto", "cpu", "gpu", "npu"
TARGETS = tuple(value for value, _label in AUTOCONFIG_TARGETS)

# The "~1.6 GB" / "~490 MB" inside a choice note.
_SIZE = re.compile(r"~\s*(\d+(?:\.\d+)?)\s*(MB|GB)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Recommendation:
    """One engine setup, ready to apply and to explain."""

    # Config key → value: `backend` plus exactly the keys that backend reads.
    # Never `language`.
    values: dict
    reason: str  # one or two plain sentences: what was found, why this engine
    summary: str  # one short line: "Parakeet · German model · CPU"
    download: str  # approximate first-use download: "~0.7 GB"


# --------------------------------------------------------------- targets


class TargetUnavailable(ValueError):
    """An explicit target this machine has no usable device for. The message
    is `unavailable_reason`'s sentence, written for the user."""


def normalize_target(target) -> str:
    """`target` as one of TARGETS, lowercased — "auto" for anything else (a
    hand-edited config value, None)."""
    code = str(target or "").strip().lower()
    return code if code in TARGETS else AUTO


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
            return "The NPU is driven by OpenVINO, which is not installed."
        return "OpenVINO reports no NPU — check the Intel NPU driver."
    return ""


# ------------------------------------------------------------- recommend


def _language_code(language) -> str:
    """The dictation language as a lowercased code, "" for auto-detection."""
    code = str(language or "").strip().lower()
    return "" if code == "auto" else code


def _language_name(code: str) -> str:
    """"German" for "de" — the English name from choices.LANGUAGES, "" when
    the code is not listed there."""
    for value, label in LANGUAGES:
        if value == code and value != "auto":
            return label.split(" — ")[0]
    return ""


def _note_size(choices: list[tuple[str, str]], value: str, factor: float = 1.0) -> str:
    """The approximate download of `value`, read out of its choice note (the
    sizes the dropdowns already show) and scaled by `factor`. "size unknown"
    when the note carries none — the selftest fails on that, so a reworded
    note is caught there."""
    for item, note in choices:
        if item != value:
            continue
        match = _SIZE.search(note)
        if not match:
            break
        megabytes = float(match.group(1)) * (1000 if match.group(2).upper() == "GB" else 1)
        megabytes *= factor
        if megabytes >= 500:
            return f"~{megabytes / 1000:.1f} GB"
        return f"~{megabytes:.0f} MB"
    return "size unknown"


def _model_title(model: str) -> str:
    return "German turbo" if model == GERMAN_TURBO_CT2 else model


def _parakeet_speaks(code: str) -> bool:
    return not code or code in V3_LANGUAGES


def _whisper_gpu(code: str) -> Recommendation:
    german = code == "de"
    model = GERMAN_TURBO_CT2 if german else TURBO
    if german:
        reason = (
            "An NVIDIA graphics card was found, so faster-whisper runs on it with Whisper's "
            "large turbo model fine-tuned for German — the most accurate German setup, at "
            "graphics-card speed."
        )
    else:
        reason = (
            "An NVIDIA graphics card was found, so faster-whisper runs on it with Whisper's "
            "large turbo model — close to Whisper's best accuracy, at graphics-card speed."
        )
    return Recommendation(
        values={
            "backend": "faster-whisper",
            "model": model,
            "device": "cuda",
            "compute_type": "auto",
        },
        reason=reason,
        summary=f"faster-whisper · {_model_title(model)} · NVIDIA GPU",
        download=_note_size(MODEL_CHOICES, model),
    )


def _parakeet(code: str, lead: str = _NO_CUDA) -> Recommendation:
    others = len(V3_LANGUAGES) - 1
    start = f"{lead}, so the fast Parakeet engine runs on your processor"
    if code == "de":
        model, detail = PARAKEET_GERMAN, "German model"
        reason = f"{start} — with the model fine-tuned for German."
    elif not code:
        model, detail = PARAKEET_V3, f"{len(V3_LANGUAGES)} languages"
        reason = (
            f"{start}. It understands {len(V3_LANGUAGES)} European languages and detects "
            "which one you speak."
        )
    else:
        model, detail = PARAKEET_V3, f"{len(V3_LANGUAGES)} languages"
        name = _language_name(code) or "your language"
        reason = f"{start} — it understands {name} and {others} other European languages."
    return Recommendation(
        values={
            "backend": "parakeet",
            "parakeet_model": model,
            "parakeet_quantization": "int8",
            "device": "cpu",
        },
        reason=reason,
        summary=f"Parakeet · {detail} · CPU",
        # Both registry models are the same 0.6B network: the size follows
        # the quantization, not the model.
        download=_note_size(PARAKEET_QUANTIZATIONS, "int8"),
    )


def _not_parakeet(hardware: Hardware, code: str) -> str:
    """The clause that says why an installed Parakeet was passed over — only
    ever the language, since a covered language would have picked it."""
    if hardware.parakeet and not _parakeet_speaks(code):
        return f"Parakeet does not understand {_language_name(code) or 'this language'}"
    return ""


def _openvino_arc(hardware: Hardware, code: str, lead: str = "") -> Recommendation:
    """`lead` says why not an engine further up; "" lets the auto rules
    word it (an installed Parakeet passed over, if any)."""
    # Even for German: the German fine-tune exists only as a CTranslate2
    # conversion (choices.openvino_supports_model).
    model = TURBO
    gpu = hardware.gpu_name or "Intel Arc graphics"
    lead = lead or _not_parakeet(hardware, code)
    lead = f"{lead}, so your" if lead else "Your"
    reason = (
        f"{lead} {gpu} runs Whisper's large turbo model through OpenVINO — much faster than "
        "the processor alone."
    )
    if code == "de":
        reason += " It is the multilingual turbo: the German fine-tune has no OpenVINO version."
    return Recommendation(
        values={
            "backend": "openvino",
            "model": model,
            "openvino_device": "gpu",
            "openvino_precision": "int8",
        },
        reason=reason,
        summary=f"OpenVINO · {model} · Intel Arc GPU",
        # MODEL_CHOICES' sizes are the float16 CTranslate2 conversions; int8
        # is about half of fp16 (choices.OPENVINO_PRECISIONS).
        download=_note_size(MODEL_CHOICES, model, factor=0.5),
    )


def _openvino_small(device: str, name: str, lead: str, why: str, code: str) -> Recommendation:
    """OpenVINO with Whisper's small model at int8 on `device` ("gpu" /
    "npu") — the conservative setup for an Intel GPU without Arc and the
    starting profile for an NPU. `name` is that device as the user knows it;
    `lead` and `why` frame the reason."""
    reason = f"{lead}, so your {name} runs Whisper's small model through OpenVINO — {why}"
    if code == "de":
        reason += " The German fine-tune has no OpenVINO version."
    return Recommendation(
        values={
            "backend": "openvino",
            "model": SMALL,
            "openvino_device": device,
            "openvino_precision": "int8",
        },
        reason=reason,
        summary=f"OpenVINO · {SMALL} · Intel {device.upper()}",
        download=_note_size(MODEL_CHOICES, SMALL, factor=0.5),
    )


def _whisper_cpu(hardware: Hardware, code: str, lead: str = _NO_CUDA) -> Recommendation:
    german = code == "de"
    # AVX2 only counts on x86, where CTranslate2's fast kernels need it; an
    # ARM CPU has none and runs its own.
    avx2_missing = hardware.avx2 is False and hardware.x86 is not False
    cores = hardware.physical_cores
    strong = cores >= LARGE_MODEL_MIN_CORES and not avx2_missing
    model = (GERMAN_TURBO_CT2 if german else TURBO) if strong else SMALL

    # Two sentences: what rules out the faster engines, then what the
    # processor can carry.
    passed_over = _not_parakeet(hardware, code)
    found = f"{lead}, and {passed_over}." if passed_over else f"{lead}."
    counted = f"{cores} {'core' if cores == 1 else 'cores'}"
    processor = "Your processor"
    if cores:
        detail = f"{hardware.cpu_name}, {counted}" if hardware.cpu_name else counted
        processor = f"Your processor ({detail})"
    if strong:
        tuned = " fine-tuned for German" if german else ""
        verdict = f"{processor} is strong enough for Whisper's large turbo model{tuned}."
    elif avx2_missing:
        verdict = (
            f"{processor} lacks the AVX2 instructions larger models need to run quickly, so "
            "the small model keeps dictation responsive."
        )
    elif cores:
        verdict = (
            f"With {counted}, the small model keeps dictation responsive — larger models "
            "would be slow on this processor."
        )
    else:
        verdict = "The small model runs on your processor and keeps dictation responsive."
    return Recommendation(
        values={
            "backend": "faster-whisper",
            "model": model,
            "device": "cpu",
            "compute_type": "auto",
        },
        reason=f"{found} {verdict}",
        summary=f"faster-whisper · {_model_title(model)} · CPU",
        download=_note_size(MODEL_CHOICES, model),
    )


def _on_cpu(hardware: Hardware, code: str) -> Recommendation:
    """Target "cpu": the auto rules for the processor, any GPU or NPU left
    out — and a reason that says it was the user's choice, not that no
    graphics card is there."""
    if hardware.parakeet and _parakeet_speaks(code):
        return _parakeet(code, lead=_CPU_CHOSEN)
    return _whisper_cpu(hardware, code, lead=_CPU_CHOSEN)


def _on_gpu(hardware: Hardware, code: str) -> Recommendation:
    """Target "gpu": NVIDIA first, else the Intel GPU OpenVINO runs as
    "gpu" — an Arc with the large turbo, any other with the small model."""
    if hardware.cuda:
        return _whisper_gpu(code)
    if hardware.arc_gpu:
        return _openvino_arc(hardware, code, lead=_NO_CUDA)
    return _openvino_small(
        "gpu",
        hardware.gpu_name or "Intel graphics",
        _NO_CUDA,
        "a conservative choice: larger models need an Intel Arc to run quickly.",
        code,
    )


def _on_npu(hardware: Hardware, code: str) -> Recommendation:
    return _openvino_small(
        "npu",
        hardware.npu_name or "Intel NPU",
        "You chose the NPU",
        "a conservative start that NPUs run reliably; a larger model can be picked by "
        "hand afterwards.",
        code,
    )


def recommend(hardware: Hardware, language, target=AUTO) -> Recommendation:
    """The best engine setup for `hardware` and the dictation `language` (a
    language code; "" or "auto" = auto-detection). Never returns `language`
    among the values.

    `target` is the device class to optimize for (TARGETS): "auto" runs the
    rules in the order of the module docstring; "cpu", "gpu" and "npu" pick
    the best setup on that class and never one on another. An explicit
    target this machine has no device for raises TargetUnavailable — ask
    `unavailable_reason` first; an unknown target counts as "auto"."""
    code = _language_code(language)
    target = normalize_target(target)
    missing = unavailable_reason(hardware, target)
    if missing:
        raise TargetUnavailable(missing)
    if target == CPU:
        return _on_cpu(hardware, code)
    if target == GPU:
        return _on_gpu(hardware, code)
    if target == NPU:
        return _on_npu(hardware, code)
    if hardware.cuda:
        return _whisper_gpu(code)
    if hardware.parakeet and _parakeet_speaks(code):
        return _parakeet(code)
    if hardware.openvino and hardware.arc_gpu:
        return _openvino_arc(hardware, code)
    return _whisper_cpu(hardware, code)


# --------------------------------------------------------------- compare


def changes(recommendation: Recommendation, cfg) -> dict:
    """key → (current, recommended) for every value applying `recommendation`
    would change; {} means the engine is already set up like this.

    `cfg` is a Config or a plain dict (a Settings snapshot) — anything that
    answers ``cfg[key]``. A key it does not have counts as a change.
    """
    result: dict = {}
    for key, value in recommendation.values.items():
        try:
            current = cfg[key]
        except Exception:  # KeyError from a dict without the key
            current = None
        if current != value:
            result[key] = (current, value)
    return result


def differs(recommendation: Recommendation, cfg) -> bool:
    """Whether applying `recommendation` would change anything in `cfg`."""
    return bool(changes(recommendation, cfg))

