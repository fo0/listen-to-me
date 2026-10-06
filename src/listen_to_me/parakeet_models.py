"""The Parakeet models the parakeet backend can run, and how their files arrive.

A registry (``MODELS``, keyed by ``cfg["parakeet_model"]``) plus the file
helpers both the backend and the Settings status card need: which files a
quantization consists of, whether they are all on disk, and the pinned
download of a model onnx-asr cannot fetch itself. Split out of
``transcriber_parakeet`` so the surfaces that only *name* the selected model
(the Home card, the tray, the diagnostics) reach it without the backend, and
so the backend module stays about loading and decoding.

Qt-free and stdlib-only at import time — huggingface_hub is imported inside
`fetch_pinned`, the one function that downloads.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParakeetModel:
    """One entry of the Parakeet model registry — what ``cfg["parakeet_model"]``
    selects.

    Two ways to get the files. A ``revision`` of None is one of onnx-asr's own
    presets: ``onnx_asr_model`` is the preset name and onnx-asr downloads it
    itself (from the repo's main branch — it cannot pin anything). With a
    revision the app downloads that exact commit through huggingface_hub and
    hands the folder to onnx-asr, ``onnx_asr_model`` then naming the model
    *type*; onnx-asr's ``load_model`` fetches nothing but its presets, and a
    pinned commit keeps a third-party repo from changing under the app.
    """

    id: str  # the config value
    title: str  # what notifications, the log and the Home card call it
    detail: str  # the Home card's second line
    repo: str  # the Hugging Face repo the files come from
    onnx_asr_model: str  # first argument of onnx_asr.load_model
    # Subdirectory below cfg["model_dir"] (when set), so the download never
    # mixes with the CT2/OpenVINO model folders — or the other Parakeet model —
    # in the same directory.
    dirname: str
    revision: str | None = None  # pinned commit, None = an onnx-asr preset
    # The one language the model understands; None = multilingual, detected.
    language: str | None = None


DEFAULT_MODEL = "parakeet-tdt-0.6b-v3"

# The 25 European languages Parakeet TDT 0.6b v3 transcribes, as Whisper
# language codes — the list on NVIDIA's model card
# (https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3). Any other language it
# does not understand at all: the recommendation (autoconfig) offers Parakeet
# only for these, or for auto-detection.
V3_LANGUAGES = frozenset(
    {
        "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "it",
        "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk",
    }
)

# Keyed by config value; the dropdown's notes live in choices.PARAKEET_MODELS.
MODELS = {
    model.id: model
    for model in (
        # The model this backend has always run: download path, cache folder
        # and dirname are exactly what they were before there was a choice, so
        # an existing installation finds its copy and re-downloads nothing.
        ParakeetModel(
            id=DEFAULT_MODEL,
            title="Parakeet TDT 0.6b v3",
            detail="25 languages, auto-detected",
            repo="istupakov/parakeet-tdt-0.6b-v3-onnx",
            onnx_asr_model="nemo-parakeet-tdt-0.6b-v3",
            dirname="parakeet-tdt-0.6b-v3-onnx",
        ),
        # primeline/parakeet-primeline (CC-BY-4.0): a German fine-tune of the
        # model above — average German WER 2.95 against v3's 3.64, same speed —
        # in the ONNX export OpenVoiceOS publishes for onnx-asr. Pinned: the
        # repo is a third party's, and its file layout is part of this code.
        ParakeetModel(
            id="parakeet-primeline-de",
            title="Parakeet primeline (German)",
            detail="German fine-tune, German only",
            repo="OpenVoiceOS/primeline-parakeet-onnx",
            onnx_asr_model="nemo-conformer-tdt",
            dirname="primeline-parakeet-onnx",
            revision="411093fba73540a11c451841a8e7922c13b0fb00",
            language="de",
        ),
    )
}

# The unknown parakeet_model values the log has already named — `loaded` asks
# on every live-preview tick, and one line per value is enough.
_UNKNOWN_MODELS_LOGGED: set[str] = set()


def parakeet_model(value) -> ParakeetModel:
    """The registry entry for a ``cfg["parakeet_model"]`` value.

    config.json is untrusted input: an unknown value — a typo, a model a later
    build added — falls back to the default model with one log line, never to
    an error at the first recording. A missing value (a diagnostics snapshot
    from before the key existed) is the default without a log line.
    """
    if isinstance(value, str) and value in MODELS:
        return MODELS[value]
    if value is not None:
        key = repr(value)
        if key not in _UNKNOWN_MODELS_LOGGED:
            _UNKNOWN_MODELS_LOGGED.add(key)
            log.warning("unknown parakeet_model value %.60s — using %r", key, DEFAULT_MODEL)
    return MODELS[DEFAULT_MODEL]


def model_files(quantization: str | None) -> tuple[str, ...]:
    """The files onnx-asr's NeMo TDT loader reads for `quantization` — every
    registry repo is an export in this one layout (the int8 variant spelled
    into the name, ``encoder-model.int8.onnx``).

    The fp32 encoder of a 0.6B model is ~2.4 GB, past protobuf's 2 GB cap for
    one .onnx file, so its weights sit in an external-data file beside it —
    without which the encoder is a stub that fails at session creation.
    """
    suffix = f".{quantization}" if quantization else ""
    files = [
        "config.json",
        "vocab.txt",
        f"encoder-model{suffix}.onnx",
        f"decoder_joint-model{suffix}.onnx",
    ]
    if not quantization:
        files.append("encoder-model.onnx.data")
    return tuple(files)


def missing_files(folder, quantization: str | None) -> list[str]:
    """The files of `quantization` that are not (completely) in `folder`.

    huggingface_hub only puts a file at its final name once it is complete
    (the bytes in flight live in ``*.incomplete`` elsewhere), so existing is
    the answer."""
    return [
        name
        for name in model_files(quantization)
        if not os.path.isfile(os.path.join(str(folder), name))
    ]


def model_path(model: ParakeetModel, model_dir) -> str | None:
    """The backend's own folder under a custom model_dir; None = the HF cache."""
    return os.path.join(str(model_dir), model.dirname) if model_dir else None


def fetch_pinned(model: ParakeetModel, quantization: str | None, path, *, offline: bool) -> str:
    """Download (or, offline, locate) the pinned commit of `model` — only the
    files of `quantization`, so an int8 choice never fetches the 2.4 GB fp32
    weights — and return the folder holding them.

    Into `path` when a custom model folder is set, else the Hugging Face cache.
    A download that came back without every file — huggingface_hub returns an
    existing local folder as-is when the Hub cannot be reached — is reported
    here, by name, instead of as a cryptic ONNX Runtime error later.
    """
    if offline and path is not None:
        # The backend's own folder, checked file by file below. Asking
        # huggingface_hub would only add a warning to every start that it is
        # "returning the existing local_dir".
        folder = path
    else:
        from huggingface_hub import snapshot_download

        folder = snapshot_download(
            model.repo,
            revision=model.revision,
            allow_patterns=list(model_files(quantization)),
            local_dir=path,
            local_files_only=offline,
        )
    missing = missing_files(folder, quantization)
    if missing:
        raise RuntimeError(
            f"The download of the Parakeet model '{model.title}' is incomplete "
            f"(missing {', '.join(missing)}) — check the internet connection "
            "and try again."
        )
    return str(folder)


def download_filter(quantization: str | None):
    """Which files of a registry repo a download of `quantization` fetches.

    Each repo ships both variants side by side (int8 ≈ 0.7 GB next to fp32 ≈
    2.5 GB), so counting all of it would leave an int8 download stuck at a
    fifth of the bar. The files counted are exactly the ones fetched: the
    pinned download asks for `model_files` by name, and onnx-asr's own preset
    download asks for the same set by pattern.
    """
    wanted = frozenset(model_files(quantization))

    def keep(name: str) -> bool:
        return name in wanted

    return keep
