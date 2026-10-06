"""Engine auto-configuration: the best engine setup this machine can run.

`hardware_from_status` reads the dict `diagnostics.hardware_status` builds on
a worker thread into a `Hardware`; `recommend` turns that and the dictation
language into a `Recommendation` — the config keys to set, plus the sentences
that explain the choice to someone who has never heard of CUDA. The Settings
window and the first-run wizard show and apply it; this module touches
neither the UI nor the config.

Quality first, in this order:

1. An NVIDIA GPU CTranslate2 can use → faster-whisper on it with Whisper's
   large turbo model (its German fine-tune for German): the best accuracy
   the app offers, at graphics-card speed.
2. Otherwise Parakeet, when it is installed and understands the language (or
   the language is auto-detected) → on the CPU, int8, the German fine-tune
   for German: about as accurate as the turbo and several times faster on a
   processor.
3. Otherwise an Intel Arc GPU that OpenVINO drives → OpenVINO with the large
   turbo on it, int8. The German fine-tune has no OpenVINO conversion.
4. Otherwise faster-whisper on the CPU: the large turbo (German: its German
   fine-tune) with 8 or more physical cores and AVX2 not known to be missing,
   else small — a large model on a weaker processor takes longer to
   transcribe than the dictation took to speak.

The recommendation never names `language`: that is the user's choice and the
input here, never an output.

Qt-free and stdlib-only — pure functions over plain data, so the whole rule
table is checked headless (selftest "engine recommendation matrix").
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .choices import (
    GERMAN_TURBO_CT2,
    LANGUAGES,
    MODEL_CHOICES,
    PARAKEET_QUANTIZATIONS,
)
from .parakeet_models import DEFAULT_MODEL as PARAKEET_V3
from .parakeet_models import V3_LANGUAGES

log = logging.getLogger(__name__)

PARAKEET_GERMAN = "parakeet-primeline-de"
TURBO = "large-v3-turbo"
SMALL = "small"

# Physical cores from which a CPU runs Whisper's large turbo fast enough to
# dictate with; below it, small.
LARGE_MODEL_MIN_CORES = 8

_NO_CUDA = "No usable NVIDIA graphics card found"

# An OpenVINO GPU whose name says Arc: the discrete A/B-series cards and the
# integrated graphics of Core Ultra ("Intel(R) Arc(TM) Graphics").
_ARC = re.compile(r"\barc\b", re.IGNORECASE)
_TRADEMARKS = re.compile(r"\((?:r|tm|c)\)|[®™]", re.IGNORECASE)
_CLOCK = re.compile(r"\s+(?:cpu\s+)?@\s*[\d.]+\s*[gm]hz\s*$", re.IGNORECASE)
_GPU_TAG = re.compile(r"\s*\([di]gpu\)\s*$", re.IGNORECASE)
_NAME_MAX = 64

# The "~1.6 GB" / "~490 MB" inside a choice note.
_SIZE = re.compile(r"~\s*(\d+(?:\.\d+)?)\s*(MB|GB)\b", re.IGNORECASE)


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
    arc_gpu: bool = False  # OpenVINO sees an Intel Arc GPU
    gpu_name: str = ""  # that GPU, shortened ("Intel Arc A770 Graphics")
    parakeet: bool = False  # the Parakeet backend (onnx-asr + ONNX Runtime) is installed
    physical_cores: int = 0  # 0 = unknown
    performance_cores: int = 0  # 0 = unknown
    avx2: bool | None = None  # None = unknown
    x86: bool | None = None  # None = unknown
    cpu_name: str = ""  # shortened ("Intel Core i7-1265U"), "" = unknown


@dataclass(frozen=True)
class Recommendation:
    """One engine setup, ready to apply and to explain."""

    # Config key → value: `backend` plus exactly the keys that backend reads.
    # Never `language`.
    values: dict
    reason: str  # one or two plain sentences: what was found, why this engine
    summary: str  # one short line: "Parakeet · German model · CPU"
    download: str  # approximate first-use download: "~0.7 GB"


# ---------------------------------------------------------------- hardware


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


def _arc_gpu_name(devices) -> str | None:
    """The shortened name of the first Intel Arc GPU among OpenVINO's devices
    ("GPU", "GPU.0", "GPU.1" …), None when there is none."""
    if not isinstance(devices, list):
        return None
    for device in devices:
        if not isinstance(device, dict):
            continue
        name = device.get("name")
        if (
            str(device.get("device") or "").upper().startswith("GPU")
            and isinstance(name, str)
            and _ARC.search(name)
        ):
            return short_name(name) or "Intel Arc graphics"
    return None


def hardware_from_status(status) -> Hardware:
    """The `Hardware` a `diagnostics.hardware_status()` dict describes.

    Reads the "cuda", "openvino", "parakeet" and "cpu" sections. Never
    raises: a section that is missing, not a dict, or holds a value of the
    wrong type contributes the conservative default for what it would have
    said — so an old or broken probe can only make the recommendation
    lighter, never point it at hardware that is not there.
    """
    if not isinstance(status, dict):
        return Hardware()
    cuda = _section(status, "cuda")
    openvino = _section(status, "openvino")
    cpu = _section(status, "cpu")
    ov_installed = openvino.get("installed") is True
    arc = _arc_gpu_name(openvino.get("devices")) if ov_installed else None
    physical = _count(cpu.get("physical_cores"))
    performance = _count(cpu.get("performance_cores"))
    if physical and performance > physical:
        performance = physical
    hardware = Hardware(
        cuda=cuda.get("available") is True,
        openvino=ov_installed,
        arc_gpu=arc is not None,
        gpu_name=arc or "",
        parakeet=_section(status, "parakeet").get("installed") is True,
        physical_cores=physical,
        performance_cores=performance,
        avx2=_flag(cpu.get("avx2")),
        x86=_flag(cpu.get("x86")),
        cpu_name=short_name(cpu.get("name")),
    )
    log.debug("hardware for the engine recommendation: %s", hardware)
    return hardware


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


def _parakeet(code: str) -> Recommendation:
    others = len(V3_LANGUAGES) - 1
    start = f"{_NO_CUDA}, so the fast Parakeet engine runs on your processor"
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


def _openvino_arc(hardware: Hardware, code: str) -> Recommendation:
    # Even for German: the German fine-tune exists only as a CTranslate2
    # conversion (choices.openvino_supports_model).
    model = TURBO
    gpu = hardware.gpu_name or "Intel Arc graphics"
    lead = _not_parakeet(hardware, code)
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


def _whisper_cpu(hardware: Hardware, code: str) -> Recommendation:
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
    found = f"{_NO_CUDA}, and {passed_over}." if passed_over else f"{_NO_CUDA}."
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


def recommend(hardware: Hardware, language) -> Recommendation:
    """The best engine setup for `hardware` and the dictation `language` (a
    language code; "" or "auto" = auto-detection). The rules and their order
    are the module docstring's. Never returns `language` among the values."""
    code = _language_code(language)
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
