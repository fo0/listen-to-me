"""Which OpenVINO IR model the OpenVINO backend loads, and how: the preset →
Hugging Face repo mapping, the IR format and cache probes, and the compile
cache properties. Split out of `transcriber_openvino`; Qt-free, and
`huggingface_hub` is imported lazily.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .choices import OPENVINO_UNSUPPORTED_MODELS, openvino_alternative

# The backend's logger, as before the split — the log file prints logger names.
log = logging.getLogger("listen_to_me.transcriber_openvino")


def openvino_model_repo(model: str, precision: str) -> str:
    """Map a model preset + precision to its pre-converted Hugging Face repo id,
    e.g. ("small", "int8") → "OpenVINO/whisper-small-int8-ov".

    A value containing "/" is treated as an explicit repo id (or a local path)
    and passed through verbatim, so any OpenVINO IR model can be used. Raises
    ValueError for the presets that have no OpenVINO conversion.
    """
    # Checked before the "/" passthrough below: the German preset is a
    # CTranslate2 repo id, so passing it through verbatim would download a
    # model this backend cannot load. The message leads with the fix that keeps
    # the backend the user chose — swapping the *model* — because the model is
    # the incompatible half; recommending faster-whisper first sent people with
    # an Intel machine and no NVIDIA GPU off the only backend that fits their
    # hardware (#112).
    if model in OPENVINO_UNSUPPORTED_MODELS:
        raise ValueError(
            f"The model '{model}' has no OpenVINO conversion — pick "
            f"'{openvino_alternative(model)}' (or another model) in Settings → "
            "Engine. Only if you need this exact model, switch Backend back to "
            "faster-whisper, which can run it."
        )
    if "/" in model or os.sep in model:
        return model
    base = "distil-whisper-large-v3" if model == "distil-large-v3" else f"whisper-{model}"
    return f"OpenVINO/{base}-{precision}-ov"


def _looks_like_openvino_model(repo: str) -> bool | None:
    """Whether `repo` ships OpenVINO IR files (``openvino_*.xml``).

    Custom model ids are passed through verbatim, so a CTranslate2 id entered
    while this backend is selected downloads a model the pipeline cannot load
    and only fails at load time with a cryptic error. Listing the files first
    turns that into an actionable message before the download starts.

    Returns None when it cannot be determined — offline, a private repo, any
    hub error — so the caller stays permissive rather than blocking a model
    that may well work.
    """
    try:
        if os.path.isdir(repo):
            names = os.listdir(repo)
        else:
            from huggingface_hub import list_repo_files

            names = list_repo_files(repo)
    except Exception:
        log.debug("could not list the files of %r for the format check", repo, exc_info=True)
        return None
    return any(
        name.startswith("openvino_") and name.endswith(".xml")
        for name in (os.path.basename(str(entry)) for entry in names)
    )


def _model_is_cached(repo: str, model_dir) -> bool:
    """Whether the OpenVINO model is already on disk (local dir or a complete
    Hugging Face snapshot), so loading it won't download. Any uncertainty counts
    as "not cached" — same contract as the faster-whisper cache probe."""
    try:
        if os.path.isdir(repo):
            return True
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo,
            local_files_only=True,
            cache_dir=str(model_dir) if model_dir else None,
        )
        return True
    except Exception:
        return False


def _pipeline_properties(device: str, model_dir) -> dict:
    """OpenVINO properties for a pipeline on `device`.

    A GPU or NPU compiles the model on every load — tens of seconds up to
    minutes for large-v3-turbo on an NPU — and OpenVINO can cache the compiled
    blob: with ``CACHE_DIR`` the next start of the same model/device/driver is
    a file read (openvino.genai#1992 measured minutes → seconds on the NPU).
    The CPU plugin compiles fast and its blob would only cost disk, so it gets
    none. The cache sits under the user's own config dir — or next to a custom
    model folder — never under the shared temp dir (see theme._asset_dir for
    what a guessable path there costs). A cache dir that cannot be created is
    a warning and a slower load, never a failed one.
    """
    if device == "CPU":
        return {}
    from .config import config_dir

    root = Path(str(model_dir)) if model_dir else config_dir() / "cache"
    cache = root / "openvino-cache"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning(
            "could not create the OpenVINO compile cache %s — loading without it",
            cache,
            exc_info=True,
        )
        return {}
    return {"CACHE_DIR": str(cache)}
