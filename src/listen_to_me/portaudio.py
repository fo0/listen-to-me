"""Which PortAudio this process talks to — and how a frozen build gets ours.

System audio (#191, ADR-0009) records through a loopback/monitor *input*
device. Linux always has one (PulseAudio/PipeWire give every sink a "Monitor
of ..." source); Windows has none unless the user enables "Stereo Mix" or
installs a virtual cable, because the PortAudio binary inside the
`sounddevice` wheel reports `PortAudio V19.7.0-devel` and carries no WASAPI
loopback support. Upstream PortAudio does, and as a documented contract, not
an internal detail:

* `include/pa_win_wasapi.h:527` declares `int PaWasapi_IsLoopback(PaDeviceIndex)`;
* `src/hostapi/wasapi/pa_win_wasapi.c:2050` (`FillLooopbackDeviceInfo`)
  enumerates **every** WASAPI render endpoint a second time as an input
  device and appends the marker "[Loopback]" to its name, under the comment
  "Some projects depend on loopback device detection by device name, do not
  change!".

That marker is exactly what `system_audio.LOOPBACK_HINTS` already scores
highest, so a newer DLL needs no device code whatsoever (#194) — it only needs
to be the binary that actually gets loaded. This module is that half, plus the
proof of which one won.

**The lever is `sounddevice`'s own load order** (0.5.6, lines 63-91): it asks
`ctypes.util.find_library("portaudio")` first — on Windows that walks the
directories on `PATH` looking for `portaudio.dll` — then tries two
conda/anaconda paths, and only then falls back to the
`_sounddevice_data/portaudio-binaries/libportaudio64bit.dll` shipped inside
its own package. So the release build puts a newer `portaudio.dll` in the
one-file bundle and :func:`prepare_library_path` puts that directory on
`PATH`: step 1 wins, nothing is monkeypatched and nothing is forked. A build
that ships no DLL — every `pip install -e .`, every non-Windows build —
reaches step 3 exactly as it does today.

Qt-free and stdlib-only at import time (`sounddevice` is imported lazily,
inside :func:`describe`): `audio` imports this module at module scope and
`app.main()` calls it on its first line, and both of those have to stay light
enough for `--version` / `--help`.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

# The file name the release build bundles (release.yml `--add-binary`) and the
# name `find_library("portaudio")` looks for on Windows. Public so the caller
# that fakes a bundle (selftest) and the pipeline that fills one cannot drift
# apart on a rename.
DLL_NAME = "portaudio.dll"

# Upstream's PA_WASAPI_LOOPBACK_NAME_IDENTIFICATOR, casefolded for comparison.
# Same string as the strongest entry of `system_audio.LOOPBACK_HINTS`, which
# ranks devices; this module only ever counts them, and the count is what
# proves a DLL was built with WASAPI at all.
LOOPBACK_MARKER = "[loopback]"

# What prepare_library_path() did, for describe() and log_once() to report.
# It runs before `_setup_logging()` (see the call site in app.main), so it
# cannot log its own outcome — it leaves it here and log_once() says it later,
# once there is somewhere for a log record to go.
_prepared: str | None = None
_prepare_note = "prepare_library_path() has not run"
_prepare_done = False
_logged = False


def prepare_library_path() -> str | None:
    """Put the frozen bundle's directory at the front of `PATH` so that
    `sounddevice` loads the `portaudio.dll` we ship. Returns that directory,
    or None when nothing was changed.

    Why prepend at all: PyInstaller's one-file bundle unpacks to
    `sys._MEIPASS`, and that directory is not reliably on `PATH` — the
    bootloader puts it on the DLL search path for the *interpreter*, not into
    the environment `ctypes.util.find_library()` reads. Without this the newer
    DLL sits in the bundle unused and `sounddevice` silently falls back to its
    own.

    Why prepend rather than append: a `portaudio.dll` that happens to sit
    earlier on the user's `PATH` (another audio app, a conda environment)
    would otherwise be found first, and the whole point is to be certain which
    binary answers. Ours is the one we built with WASAPI on.

    Does nothing at all — by design — when this is not a frozen build, when
    there is no `sys._MEIPASS`, or when the bundle carries no DLL: a source
    install and a build without the binary must behave exactly as before,
    which is `sounddevice` loading its own copy. Idempotent: a second call
    cannot grow `PATH`, so calling it from more than one entry point is safe.
    Never raises — an unwritable `os.environ` costs the newer DLL, never the
    app's start.
    """
    global _prepared, _prepare_note, _prepare_done
    if _prepare_done:
        return _prepared
    _prepare_done = True
    try:
        if not getattr(sys, "frozen", False):
            _prepare_note = "not a frozen build — sounddevice keeps its own PortAudio"
            return None
        bundle = getattr(sys, "_MEIPASS", None)
        if not bundle:
            _prepare_note = "frozen build without sys._MEIPASS — PATH left alone"
            return None
        bundle = str(bundle)
        if not os.path.isfile(os.path.join(bundle, DLL_NAME)):
            _prepare_note = f"no {DLL_NAME} in the bundle — sounddevice keeps its own PortAudio"
            return None
        current = os.environ.get("PATH") or ""
        os.environ["PATH"] = f"{bundle}{os.pathsep}{current}" if current else bundle
        _prepared = bundle
        _prepare_note = f"prepended {bundle} to PATH for {DLL_NAME}"
        return bundle
    except Exception as exc:  # a broken environ costs the DLL, never the start
        _prepare_note = f"could not prepend the bundle directory to PATH: {exc!r}"
        return None


def describe() -> dict:
    """Which PortAudio is loaded and what it can do — the probe behind the log
    line and the release build's self-test.

    Keys: "version" / "version_number" (from `sd.get_portaudio_version()`),
    "library" (the file `sounddevice` resolved), "loopback_supported",
    "loopback_devices" (input devices carrying the "[Loopback]" marker),
    "output_devices", "bundle_path" / "path_note" (what
    :func:`prepare_library_path` did), and "errors".

    `loopback_supported` is tested by *accessing* `PaWasapi_IsLoopback` on the
    loaded library, not by calling it: sounddevice's CFFI declaration exists
    either way, so the symbol lookup against the binary is the test, and it
    raises for the old binary that does not export it. Calling it would need
    an initialized stream and a device index, and the "[Loopback]" device
    count already proves the functional half — a DLL built without WASAPI
    enumerates none.

    Never raises. This is a diagnostic, and a diagnostic that throws is worse
    than none: every field degrades to None/False/0 with the reason appended
    to "errors", so the caller always gets the same shape to report.
    """
    errors: list[str] = []
    info: dict = {
        "version": None,
        "version_number": None,
        "library": None,
        "loopback_supported": False,
        "loopback_devices": 0,
        "output_devices": 0,
        "bundle_path": _prepared,
        "path_note": _prepare_note,
        "errors": errors,
    }
    try:
        import sounddevice as sd
    except Exception as exc:  # ImportError, or a PortAudio that fails to load
        errors.append(f"sounddevice is unavailable: {exc!r}")
        return info
    try:
        version = sd.get_portaudio_version()
        # Documented as (number, text); unpacked defensively because the whole
        # point of this function is to survive a stack that differs from the
        # one it was written against.
        if isinstance(version, (tuple, list)) and len(version) >= 2:
            info["version_number"] = version[0]
            info["version"] = str(version[1])
        else:
            info["version"] = str(version)
    except Exception as exc:
        errors.append(f"could not read the PortAudio version: {exc!r}")
    library = getattr(sd, "_libname", None)
    if library:
        info["library"] = str(library)
    lib = getattr(sd, "_lib", None)
    if lib is None:
        errors.append("sounddevice exposes no loaded library (_lib)")
    else:
        try:
            info["loopback_supported"] = getattr(lib, "PaWasapi_IsLoopback") is not None
        except Exception as exc:
            # Expected on the wheel's V19.7.0-devel: the symbol is declared in
            # the CFFI header but not exported by that binary.
            errors.append(f"PaWasapi_IsLoopback is not reachable: {exc}")
    try:
        devices = list(sd.query_devices())
    except Exception as exc:
        errors.append(f"could not enumerate the devices: {exc!r}")
        return info
    for device in devices:
        try:
            name = str(device.get("name", "") or "")
            if int(device.get("max_output_channels", 0) or 0) > 0:
                info["output_devices"] += 1
            if int(device.get("max_input_channels", 0) or 0) <= 0:
                continue
            if LOOPBACK_MARKER in name.casefold():
                info["loopback_devices"] += 1
        except Exception as exc:
            errors.append(f"unreadable device entry: {exc!r}")
    return info


def log_once() -> None:
    """Log one INFO line per process naming the PortAudio in use, whether it
    supports WASAPI loopback, and how many loopback inputs it enumerated.

    One line, once: the callers sit on paths that run repeatedly (every take,
    every visit to the Audio settings page) and this costs a device
    enumeration. It is also the only place `prepare_library_path()`'s outcome
    is ever reported — that runs before logging exists (see `app.main`), so it
    records its note and this prints it.

    Never raises: it is called from the recording path, and no diagnostic is
    worth a refused take.
    """
    global _logged
    if _logged:
        return
    _logged = True
    try:
        info = describe()
        # The version string already starts with "PortAudio", so it is the
        # whole subject of the line rather than a value appended to it.
        log.info(
            "%s — WASAPI loopback %s, %d loopback input device(s) of %d output(s); %s",
            info.get("version") or "PortAudio version unknown",
            "supported" if info.get("loopback_supported") else "unsupported",
            info.get("loopback_devices") or 0,
            info.get("output_devices") or 0,
            info.get("path_note"),
        )
        library = info.get("library")
        if library:
            log.debug("PortAudio loaded from %s", library)
        for reason in info.get("errors") or []:
            log.debug("PortAudio probe: %s", reason)
    except Exception:
        log.debug("could not describe the loaded PortAudio", exc_info=True)


def _reset_state() -> None:
    """Forget what :func:`prepare_library_path` and :func:`log_once` already
    did.

    The seam the self-test needs: both are deliberately one-shot per process,
    so the only way to exercise their four cases in one run is to reset the
    flags between them. Nothing in the app calls this — a second real prepend
    is exactly what the flag exists to prevent.
    """
    global _prepared, _prepare_note, _prepare_done, _logged
    _prepared = None
    _prepare_note = "prepare_library_path() has not run"
    _prepare_done = False
    _logged = False
