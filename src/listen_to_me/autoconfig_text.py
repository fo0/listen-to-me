"""How an engine recommendation is put into words for the user.

`autoconfig` decides what to recommend and `changes` lists what applying it
would change; this module words that for the question "Auto-configure for
this PC" asks: one line per changed field in the Engine page's own wording
(`describe_changes`), the sentence about the download (`download_line`,
`model_downloaded`), and the whole question (`confirm_message`). The Settings
window and the first-run wizard show the result; this module touches neither
the UI nor the config.

Qt-free and stdlib-only — pure functions over plain data, so every sentence
is checked headless (selftest "settings engine auto-configures for this PC").
"""

from __future__ import annotations

from .autoconfig import Recommendation
from .choices import (
    OPENVINO_PRECISIONS,
    PARAKEET_MODELS,
    PARAKEET_QUANTIZATIONS,
    backend_label,
    choice_label,
    model_label,
)

# The Engine page's row label for every key a recommendation sets. The three
# precisions share the page's one "Precision" row — only the selected
# backend's is shown, and a recommendation names only that backend's.
FIELD_LABELS = {
    "backend": "Backend",
    "model": "Model",
    "device": "Device",
    "compute_type": "Precision",
    "openvino_device": "Intel device",
    "openvino_precision": "Precision",
    "parakeet_model": "Parakeet model",
    "parakeet_quantization": "Precision",
}

# The keys that decide which model files a setup downloads; the device does not.
_DOWNLOAD_KEYS = (
    "backend",
    "model",
    "openvino_precision",
    "parakeet_model",
    "parakeet_quantization",
)
_NOTED_CHOICES = {
    "openvino_precision": OPENVINO_PRECISIONS,
    "parakeet_model": PARAKEET_MODELS,
    "parakeet_quantization": PARAKEET_QUANTIZATIONS,
}


def shown_value(key: str, value) -> str:
    """`value` as the Engine page's dropdown names it, up to its note:
    "Parakeet" for the backend "parakeet", "int8" for a precision — the words
    the user finds in the field afterwards. "not set" for a missing value."""
    if value is None or value == "":
        return "not set"
    text = str(value)
    if key == "backend":
        label = backend_label(text)
    elif key == "model":
        label = model_label(text)
    elif key in _NOTED_CHOICES:
        label = choice_label(_NOTED_CHOICES[key], text)
    else:
        label = text
    return label.split("  (")[0].split(" — ")[0]


def describe_changes(changed: dict) -> list[str]:
    """One "Backend: faster-whisper → Parakeet" line per entry of a
    `changes()` result, in its order; [] for no change."""
    return [
        f"{FIELD_LABELS.get(key, key)}: {shown_value(key, old)} → {shown_value(key, new)}"
        for key, (old, new) in changed.items()
    ]


def model_downloaded(recommendation: Recommendation, status, model_dir=None) -> bool:
    """Whether the probe `status` found the model `recommendation` would load
    already on disk.

    The probe checks one model: the one entered when it ran, which
    settings_ui records as ``status["snapshot"]``. So this says yes only when
    every download-deciding value of the recommendation and the model folder
    match that snapshot and the probe found it cached. Anything else is "not
    known" (False) — the dialog then names a download that may not happen,
    never hides one that will.
    """
    if not isinstance(status, dict):
        return False
    snapshot, model = status.get("snapshot"), status.get("model")
    if not (isinstance(snapshot, dict) and isinstance(model, dict)):
        return False
    if model.get("cached") is not True or model.get("error"):
        return False
    if snapshot.get("model_dir") != model_dir:
        return False
    return all(
        snapshot.get(key) == value
        for key, value in recommendation.values.items()
        if key in _DOWNLOAD_KEYS
    )


def download_line(recommendation: Recommendation, downloaded: bool = False) -> str:
    """The sentence about the first-use download. It says "the model", never
    "it": the reason before it can end on another model ("the German
    fine-tune has no OpenVINO version")."""
    if downloaded:
        return "The model is already downloaded, so it is ready right away."
    if recommendation.download == "size unknown":
        return "The model is downloaded once, on first use."
    size = recommendation.download.lstrip("~")
    return f"The model (about {size}) is downloaded once, on first use."


def already_set_up_text(recommendation: Recommendation) -> str:
    return f"This PC is already set up for the recommended engine: {recommendation.summary}."


def confirm_message(
    recommendation: Recommendation, changed: dict, downloaded: bool = False
) -> tuple[str, str]:
    """The question before a recommendation is filled in: (headline, body).
    The body is the reason, the download, one line per changed field, and
    that nothing is saved yet."""
    lines = "\n".join(f"• {line}" for line in describe_changes(changed))
    body = (
        f"{recommendation.reason}\n\n{download_line(recommendation, downloaded)}\n\n"
        f"These fields change:\n{lines}\n\n"
        "The spoken language stays as it is, and nothing is saved until you press "
        "Apply or Save."
    )
    return f"Recommended for this PC: {recommendation.summary}", body
