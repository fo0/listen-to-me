"""Shared UI choice lists (languages, models, backends) and label mapping.

Single source of truth for the dropdowns that appear both in the settings
window and in the first-run onboarding wizard. Qt-free (sounddevice is
imported lazily inside input_device_choices) so the lists stay testable
headless.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# German fine-tune of large-v3-turbo (CTranslate2 conversion of
# primeline/whisper-large-v3-turbo-german, Apache-2.0): same architecture and
# speed as the large-v3-turbo preset, ~28% lower German WER — but German only.
# Referenced by name in transcriber_openvino (no OpenVINO conversion exists).
GERMAN_TURBO_CT2 = "jimmymeister/whisper-large-v3-turbo-german-ct2"

# (model id, short benefit shown in parentheses in the dropdown)
MODEL_CHOICES = [
    ("tiny", "fastest, lowest accuracy, ~75 MB"),
    ("base", "very fast, basic accuracy, ~140 MB"),
    ("small", "recommended — good balance of speed and accuracy, ~460 MB"),
    ("medium", "high accuracy, noticeably slower, ~1.5 GB"),
    ("large-v3", "best accuracy, slow without a GPU, ~3 GB"),
    ("large-v3-turbo", "near large-v3 accuracy at much higher speed, ~1.6 GB"),
    (GERMAN_TURBO_CT2, "German fine-tuned turbo — best German accuracy at turbo speed, ~1.6 GB"),
    ("distil-large-v3", "distilled large — fast, English only, ~1.5 GB"),
    ("distil-large-v3.5", "distilled large v3.5 — English only, faster than turbo, ~1.5 GB"),
    ("tiny.en", "English only — more accurate than tiny for English"),
    ("base.en", "English only — more accurate than base for English"),
    ("small.en", "English only — more accurate than small for English"),
    ("medium.en", "English only — more accurate than medium for English"),
    ("distil-small.en", "distilled English only — very fast"),
    ("distil-medium.en", "distilled English only — fast with good accuracy"),
]

# Model presets that exist only as a CTranslate2 conversion — the OpenVINO
# organisation publishes no pre-converted IR model for them, so pairing one
# with the OpenVINO backend can only fail. Each maps to the closest preset that
# *does* have an OpenVINO conversion, so the UI can offer a working replacement
# instead of pushing the user off the backend they deliberately chose (#112).
# Lives here rather than in transcriber_openvino so the settings window and the
# onboarding wizard can filter their dropdown without importing the backend.
OPENVINO_UNSUPPORTED_MODELS = {
    GERMAN_TURBO_CT2: "large-v3-turbo",
    "distil-large-v3.5": "distil-large-v3",
    "distil-small.en": "small.en",
    "distil-medium.en": "medium.en",
}


def openvino_supports_model(model: str) -> bool:
    """Whether `model` can run on the OpenVINO backend.

    Only the known CT2-only presets are refused. Any other id — a custom
    Hugging Face id in particular — stays allowed: it may well be an OpenVINO
    IR repo, and the backend checks the actual file format before downloading.
    """
    return model not in OPENVINO_UNSUPPORTED_MODELS


def openvino_alternative(model: str) -> str:
    """The preset to offer instead of `model` on the OpenVINO backend — the
    closest conversion that exists. `model` itself when it needs no swap."""
    return OPENVINO_UNSUPPORTED_MODELS.get(model, model)


def models_for_backend(backend: str) -> list[tuple[str, str]]:
    """MODEL_CHOICES narrowed to the presets `backend` can actually run."""
    if backend != "openvino":
        return list(MODEL_CHOICES)
    return [(model, benefit) for model, benefit in MODEL_CHOICES if openvino_supports_model(model)]


# Sentinel entry at the bottom of the read-only model dropdown: activating it
# opens an explicit input dialog for an arbitrary CTranslate2 model id (the
# combo itself takes no free text — accidental typing was once saved verbatim
# as the model id). Never a config value: settings_ui resolves it before
# collecting and falls back to the saved model if it is ever left selected.
CUSTOM_MODEL_LABEL = "Custom model id (Hugging Face)…"

LANGUAGES = [
    ("auto", "Auto-detect"),
    ("de", "German — Deutsch"),
    ("en", "English"),
    ("fr", "French — Français"),
    ("es", "Spanish — Español"),
    ("it", "Italian — Italiano"),
    ("pt", "Portuguese — Português"),
    ("nl", "Dutch — Nederlands"),
    ("pl", "Polish — Polski"),
    ("cs", "Czech — Čeština"),
    ("sk", "Slovak — Slovenčina"),
    ("hu", "Hungarian — Magyar"),
    ("ro", "Romanian — Română"),
    ("bg", "Bulgarian"),
    ("el", "Greek"),
    ("sv", "Swedish — Svenska"),
    ("da", "Danish — Dansk"),
    ("no", "Norwegian — Norsk"),
    ("fi", "Finnish — Suomi"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("tr", "Turkish — Türkçe"),
    ("ar", "Arabic"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("id", "Indonesian"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ca", "Catalan"),
    ("hr", "Croatian"),
    ("sl", "Slovenian"),
    ("sr", "Serbian"),
]

DEVICES = ["auto", "cpu", "cuda"]
COMPUTE_TYPES = ["auto", "int8", "int8_float16", "float16", "float32"]

# (backend id, label shown in the dropdown)
BACKENDS = [
    ("faster-whisper", "faster-whisper — NVIDIA GPU (CUDA) / CPU"),
    ("openvino", "OpenVINO — Intel GPU / NPU / CPU"),
    ("parakeet", "Parakeet — fastest engine, NVIDIA GPU (CUDA) / CPU"),
]
OPENVINO_DEVICES = ["auto", "cpu", "gpu", "npu"]
OPENVINO_PRECISIONS = ["int8", "fp16", "int4"]
PARAKEET_QUANTIZATIONS = ["int8", "fp32"]

# What happens to a finished transcript *besides* being inserted at the cursor.
# (config value, label shown in the dropdown)
CLIPBOARD_COPY_MODES = [
    ("on_failure", "Only when inserting at the cursor fails (recommended)"),
    ("always", "Always — every transcript also stays on the clipboard"),
    ("off", "Never — only insert at the cursor"),
]

SYSTEM_DEFAULT_DEVICE = "System default"


# ------------------------------------------------------- value -> label


def language_label(code: str) -> str:
    for lang_code, name in LANGUAGES:
        if lang_code == code:
            return f"{name} [{lang_code}]" if lang_code != "auto" else name
    return code


def model_label(name: str) -> str:
    for model, benefit in MODEL_CHOICES:
        if model == name:
            return f"{model}  ({benefit})"
    return name


def backend_label(backend: str) -> str:
    for backend_id, label in BACKENDS:
        if backend_id == backend:
            return label
    return backend


def clipboard_copy_mode(value: str) -> str:
    """`value` narrowed to a clipboard mode this code knows.

    config.json is untrusted input, and the modes differ in what they promise:
    an unrecognised string must fall back to the default safety net, never to
    "off" — that would leave a failed insertion with nowhere to recover from
    while the settings dropdown still shows something else.
    """
    for mode, _ in CLIPBOARD_COPY_MODES:
        if value == mode:
            return mode
    log.warning("unknown clipboard_copy value %r — using %r", value, CLIPBOARD_COPY_MODES[0][0])
    return CLIPBOARD_COPY_MODES[0][0]


def clipboard_copy_label(mode: str) -> str:
    for value, label in CLIPBOARD_COPY_MODES:
        if value == mode:
            return label
    return CLIPBOARD_COPY_MODES[0][1]


# ------------------------------------------------------- label -> value


def language_from_label(label: str) -> str:
    for code, _ in LANGUAGES:
        if label == language_label(code):
            return code
    return label.strip() or "auto"


def model_from_label(label: str) -> str:
    label = label.strip()
    for model, _ in MODEL_CHOICES:
        if label == model_label(model):
            return model
    # Custom Hugging Face model id typed by the user — keep it verbatim.
    return label or "small"


def backend_from_label(label: str) -> str:
    for backend, full_label in BACKENDS:
        if label == full_label:
            return backend
    return "faster-whisper"


def clipboard_copy_from_label(label: str) -> str:
    for mode, full_label in CLIPBOARD_COPY_MODES:
        if label == full_label:
            return mode
    return CLIPBOARD_COPY_MODES[0][0]


def resolve_input_device(
    index: int | None, devices: list[tuple[int, str]] | None = None
) -> tuple[int | None, str | None]:
    """The device to actually record from, plus the sentence to show when that
    is not the one the user configured (None = nothing to report).

    ``input_device`` is stored as a PortAudio index, and those are positional:
    unplug the USB headset the app was pointed at — or plug in a webcam — and
    the index either points at nothing (PortAudio raises, and the dictation is
    lost with a message naming no fix) or at a device that is simply no longer
    the same microphone. Falling back to the system default keeps the take,
    and saying so is what stops it from being a silent swap.

    `devices` is injectable so the rule is testable headlessly; left out, the
    live list is enumerated. An enumeration that fails or comes back empty
    passes the configured index through untouched: it cannot tell "this
    microphone is gone" from "PortAudio could not be asked", and guessing here
    would move a recording off a device that works.
    """
    if index is None:
        return None, None
    if devices is None:
        try:
            from .audio import list_input_devices

            devices = list_input_devices()
        except Exception:
            log.exception("could not check whether the selected microphone still exists")
            return index, None
    if not devices:
        return index, None
    if any(idx == index for idx, _name in devices):
        return index, None
    return None, (
        "The microphone selected in the settings is no longer available — "
        "recording with the system default instead. Pick it again under "
        "Settings → Audio."
    )


def input_device_from_label(label: str) -> int | None:
    """Parse the "<index>: <name>" dropdown entry; None = system default
    (also for the inline error entry, which has no numeric prefix)."""
    if not label or label == SYSTEM_DEFAULT_DEVICE or ":" not in label:
        return None
    try:
        return int(label.split(":", 1)[0])
    except ValueError:
        return None


# Ready-made mute targets for the apps people actually dictate next to, so the
# keybind doesn't have to be looked up. Ships as the default target list (all
# disabled) and backs the "Add app" menu on the Integrations page.
#
# `note` is the part that a bare key combination can't carry: this feature
# synthesizes an app's *global* mute keybind, and most of these apps only listen
# for theirs while their own window has focus. An app-local shortcut would make
# the target a silent no-op — so each preset says what it still needs. Discord
# is the only one that works untouched, which is why it comes first.
#
# Display-only, and deliberately not stored in config.json: `mute_preset_note`
# looks it up by name, so the config schema stays name/enabled/mode/hotkey.
MUTE_PRESETS = [
    {
        "name": "Discord",
        "hotkey": "<ctrl>+<shift>+m",
        "mode": "toggle",
        "note": "Discord's built-in Toggle Mute keybind — global already, nothing "
                "to set up. For push-to-mute instead, bind a “Push to Mute” key "
                "under User Settings → Keybinds and switch the mode above.",
    },
    {
        "name": "Zoom",
        "hotkey": "<alt>+a",
        "mode": "toggle",
        "note": "Zoom's mute shortcut. Tick Settings → Keyboard Shortcuts → "
                "“Enable Global Shortcut” next to it, or Zoom only reacts while "
                "its own window has focus.",
    },
    {
        "name": "Slack",
        "hotkey": "<ctrl>+<shift>+<space>",
        "mode": "toggle",
        "note": "Mutes a Slack huddle. Turn on Preferences → Audio & video → "
                "“When Slack is in the background: allow keyboard shortcut to "
                "mute”, or it only works while Slack has focus.",
    },
    {
        "name": "Microsoft Teams",
        "hotkey": "<ctrl>+<shift>+m",
        "mode": "toggle",
        "note": "Teams' mute shortcut — but Teams only reacts while its own "
                "window has focus, and offers no global keybind at all. On "
                "Windows 11, Win+Alt+K mutes the call system-wide instead: enter "
                "it here as <cmd>+<alt>+k and test it before relying on it.",
    },
    {
        "name": "OBS Studio",
        "hotkey": "",
        "mode": "hold",
        "note": "OBS ships no mute hotkey — set one under Settings → Hotkeys at "
                "your Mic/Aux source (“Push-to-mute” for this mode, or the same "
                "key on both “Mute” and “Unmute” for Toggle) and copy it here. "
                "OBS hotkeys are global, so it works once a key is set.",
    },
]


def mute_preset_note(name: str) -> str:
    """The setup note for a preset target, matched by name — "" for a custom or
    renamed entry, which simply shows no note."""
    wanted = (name or "").strip().casefold()
    for preset in MUTE_PRESETS:
        if preset["name"].casefold() == wanted:
            return preset["note"]
    return ""


def default_mute_targets() -> list[dict]:
    """The presets as fresh config entries, all disabled: every one of them
    needs the matching keybind to exist in the target app, and half of them need
    a setting turned on there first. Enabling any by default would mute — or
    silently fail to mute — without the user ever choosing it."""
    return [
        {
            "name": preset["name"],
            "enabled": False,
            "mode": preset["mode"],
            "hotkey": preset["hotkey"],
        }
        for preset in MUTE_PRESETS
    ]


def input_device_choices(current_index: int | None = None) -> tuple[list[str], str]:
    """Labels for the input-device dropdown and the entry to preselect for
    `current_index`. An enumeration failure yields an inline error entry
    instead of raising, so the dropdown always renders."""
    values = [SYSTEM_DEFAULT_DEVICE]
    current = SYSTEM_DEFAULT_DEVICE
    try:
        from .audio import list_input_devices

        for idx, name in list_input_devices():
            entry = f"{idx}: {name}"
            values.append(entry)
            if current_index == idx:
                current = entry
    except Exception:
        # The exception text belongs in the log, not in a dropdown: a user
        # picking a microphone gets no use out of "PortAudioError: ..." or a
        # missing-module traceback line, and it is already logged in full.
        log.exception("could not list audio devices")
        values.append("(could not read the microphone list — see the log file)")
    return values, current
