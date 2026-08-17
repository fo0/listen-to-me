"""Progress reporting for the long downloads — models and app updates.

A first-use model download moves up to ~3 GB and takes minutes, and until now
the only sign of it was one notification that disappeared after a few seconds.
This module produces the numbers the floating icon and the tray show while it
runs (issue #10's icon, issue #110's percentage).

Two shapes of source feed it:

- The updater streams its asset itself and counts bytes as they arrive, so it
  reports exact progress with no help from here (``updater.download_asset``).
- The model downloads are performed *inside* faster-whisper, onnx-asr and
  huggingface_hub, none of which offers a progress callback reachable without
  reaching into its internals. What all of them do share is where the bytes
  land: a directory on disk. :class:`DownloadWatcher` polls that directory's
  size from a background thread and reports it against the repo's total size
  from the Hugging Face metadata.

Everything here is best-effort by construction: an unknown total is reported
as an unknown total (the icon then shows an indeterminate ring, never an
invented percentage), and any failure degrades to "no progress reported"
rather than disturbing the download it is watching.

Qt-free and thread-safe on purpose — the callbacks run on the watcher thread,
so callers must route them through ``App.post``/``App.progress``, never touch
Qt from them.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# How often the watched directory is measured. Fast enough that the percentage
# moves visibly, slow enough that walking a cache folder costs nothing next to
# a download saturating the connection.
_POLL_SECONDS = 0.7

# Below this the percentage is meaningless — a "total" that small means the
# metadata lookup returned something unusable rather than a real model.
_MIN_TOTAL_BYTES = 1024 * 1024


def format_size(num_bytes: int | None) -> str:
    """A byte count for the UI ("198.4 MB", "512 KB").

    A model or a portable build is a few hundred MB, so a bare percentage says
    nothing about how long it will take — the UI shows the sizes next to it.
    Binary units (what the OS reports), one decimal from MB up, empty string
    when the size is unknown so callers can just skip it."""
    if not num_bytes or num_bytes < 0:
        return ""
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            if unit == "KB":
                return f"{size:.0f} KB"
            return f"{size:.1f} {unit}"
        size /= 1024
    return ""  # unreachable: the loop returns on "GB"


def progress_text(label: str, fraction: float | None, done: int = 0, total: int = 0) -> str:
    """One line describing a running download, for the tray tooltip.

    The percentage alone says nothing about how long is left on a 3 GB model,
    so the sizes come along whenever they are known.
    """
    parts = [label] if label else []
    if fraction is not None:
        parts.append(f"{int(fraction * 100)}%")
    sizes = " / ".join(part for part in (format_size(done), format_size(total)) if part)
    if sizes:
        parts.append(f"({sizes})")
    return " ".join(parts)


def hub_cache_dir(repo: str, cache_dir=None) -> Path | None:
    """The Hugging Face cache folder a repo's files land in, or None when it
    cannot be determined (no huggingface_hub, unexpected layout).

    The folder name (``models--org--name``) is part of the cache format, and
    ``repo_folder_name`` is the library's own way of building it — asking it
    keeps this working if the scheme ever changes.
    """
    try:
        from huggingface_hub import constants
        from huggingface_hub.file_download import repo_folder_name

        base = Path(str(cache_dir)) if cache_dir else Path(constants.HF_HUB_CACHE)
        return base / repo_folder_name(repo_id=repo, repo_type="model")
    except Exception:
        log.debug("could not resolve the hub cache folder of %r", repo, exc_info=True)
        return None


def hub_repo_size(repo: str, keep: Callable[[str], bool] | None = None) -> int | None:
    """Total size in bytes of the files a download of `repo` will fetch, from
    the Hugging Face metadata — None when it cannot be determined.

    `keep` filters the repo's files down to the ones the caller actually
    downloads; without it every file counts. A repo that ships several variants
    of the same model (Parakeet: int8 next to fp32) must pass one, or the
    percentage would stall at a fraction of the way through.

    One extra HTTP request, and only on a download that is about to move
    hundreds of megabytes anyway. Never raises: no metadata simply means no
    percentage.
    """
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, files_metadata=True)
        total = 0
        for sibling in info.siblings or ():
            name = str(getattr(sibling, "rfilename", ""))
            if keep is not None and not keep(name):
                continue
            total += int(getattr(sibling, "size", 0) or 0)
    except Exception:
        log.debug("could not read the size of %r from the hub", repo, exc_info=True)
        return None
    return total if total >= _MIN_TOTAL_BYTES else None


def directory_size(path) -> int:
    """Bytes currently on disk under `path`, partial ``*.incomplete`` blobs
    included — that is what a running download is writing into. Files that
    vanish mid-walk (a blob being renamed into place) are skipped rather than
    raised; a missing directory is simply 0."""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    stat = os.stat(os.path.join(root, name), follow_symlinks=False)
                except OSError:
                    continue  # renamed/removed while we walked — skip it
                total += stat.st_size
    except OSError:
        return total
    return total


class DownloadWatcher:
    """Reports the progress of a download that writes into `directory`.

    Used as a context manager around the library call that performs the
    download::

        with DownloadWatcher(folder, total, on_progress, label="Whisper model"):
            WhisperModel(...)

    `on_progress(label, fraction, done, total)` is called from the watcher
    thread roughly every 0.7 s, with `fraction` None while the total is
    unknown. Leaving the context sends one final call with `label=None`, which
    means "nothing is downloading any more" — success and failure alike, since
    a display left showing 62% forever is wrong either way.

    What is already in `directory` when the watch starts is the baseline, so a
    resumed or partly cached download counts from where it actually is instead
    of jumping to a percentage it never earned.
    """

    def __init__(
        self,
        directory,
        total_bytes: int | None,
        on_progress: Callable[[str, float | None, int, int], None] | None,
        *,
        label: str = "",
        poll_seconds: float = _POLL_SECONDS,
    ):
        self._directory = directory
        self._on_progress = on_progress
        self._label = label
        self._poll = max(0.1, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline = directory_size(directory) if directory is not None else 0
        # The bytes still to come, not the repo's full size: with a partial
        # download already on disk the remainder is what the percentage is of.
        remaining = None if total_bytes is None else total_bytes - self._baseline
        self._total = remaining if remaining and remaining >= _MIN_TOTAL_BYTES else None

    def __enter__(self) -> "DownloadWatcher":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()
        if self._on_progress is not None:
            # After the join, so a tick still in flight cannot overwrite this
            # and leave the icon frozen at some percentage forever.
            self._on_progress(None, None, 0, 0)

    def start(self) -> None:
        if self._on_progress is None or self._directory is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="download-progress", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            # Bounded: the loop only sleeps on the stop event, so this returns
            # immediately unless a directory walk is mid-flight.
            thread.join(timeout=2.0)

    def _run(self) -> None:
        # A download that is watched must never be brought down by the watching
        # — hence one broad guard around the whole loop (the app's boundary
        # rule) instead of trusting each os.stat.
        try:
            while not self._stop.wait(self._poll):
                self._report()
        except Exception:
            log.exception("download progress watcher stopped early")

    def _report(self) -> None:
        if self._stop.is_set():
            return  # stopped while this tick was being scheduled
        done = max(0, directory_size(self._directory) - self._baseline)
        fraction = None
        if self._total:
            # Clamped: the total is an estimate from the repo metadata, and a
            # download that overshoots it must show 99%, never 137%.
            fraction = min(1.0, done / self._total)
        self._on_progress(self._label, fraction, done, self._total or 0)
