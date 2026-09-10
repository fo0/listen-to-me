"""Which PortAudio this process talks to — and how a frozen build gets ours.

System audio (#191, ADR-0009) records through a loopback/monitor *input*
device. Linux always has one (PulseAudio/PipeWire give every sink a "Monitor
of ..." source); Windows has none unless the user enables "Stereo Mix" or
installs a virtual cable, because the PortAudio binary inside the
`sounddevice` wheel exports no `PaWasapi_IsLoopback` and enumerates no
loopback device at all. Upstream PortAudio does both, and as a documented
contract, not an internal detail:

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

**The version string is not that proof — it is identical in both binaries.**
At the pinned commit (`PORTAUDIO_COMMIT` in `release.yml`) `paVersionMinor` is
still `7` (`src/common/pa_front.c:94`) and `PA_GIT_REVISION` is still the
checked-in `unknown`, because upstream's `update_gitrevision.sh` is a manual
pre-build script that CMake never runs. So `Pa_GetVersionText()` returns
`"PortAudio V19.7.0-devel, revision unknown"` and `Pa_GetVersion()` returns
`190700` from the DLL we build *and* from the wheel's own (measured on
`libportaudio64bit.dll` in `sounddevice-0.5.6-py3-none-win_amd64.whl`; all six
DLLs in that wheel carry the same string). A release log reading
`V19.7.0-devel` therefore says nothing about which binary answered — the
loaded file path and the `PaWasapi_IsLoopback` export are the only
discriminators, which is why :func:`log_once` leads with the path and labels
the version as no answer, and :func:`describe` reports both.

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

**The escape hatch.** Once our DLL is loaded nothing reverts to the wheel's,
and a DLL that loads but fails `Pa_Initialize` breaks *all* audio in the
frozen build — microphone dictation included — with no recovery until a new
release is dispatched. Nothing in CI captures audio with the new binary (the
release runner has no audio hardware), so `system_audio.bundled_portaudio`
(config, default true) lets a support instruction turn the prepend off:
:func:`prepare_library_path` then leaves `PATH` alone and `sounddevice` loads
its own copy, exactly as a source install does. It is a recovery lever, not a
feature switch — see the key's comment in `config.DEFAULTS`.

**One entry per physical output.** PortAudio enumerates every endpoint once
per host API, so "how many outputs does this machine have?" has no answer
without picking one — :func:`preferred_hostapi` is that pick, and the concrete
false statements it prevents are in its docstring.

Qt-free and stdlib-only at import time (`sounddevice` is imported lazily,
inside :func:`describe`): `audio` imports this module at module scope and
`app.main()` calls it on its first line, and both of those have to stay light
enough for `--version` / `--help`. The config read behind the escape hatch is
stdlib-only for the same reason (`config.bundled_portaudio_enabled`), and it
happens only in the one case that is about to change `PATH`.
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

# The Windows host API that lists each endpoint exactly once and the only one
# that emits the "[Loopback]" twins (:func:`preferred_hostapi`). Matched as a
# casefolded fragment because PortAudio names it "Windows WASAPI".
WINDOWS_HOSTAPI_MARKER = "wasapi"

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
    there is no `sys._MEIPASS`, when the bundle carries no DLL, or when
    `system_audio.bundled_portaudio` is false in `config.json`: a source
    install, a build without the binary and a user following a support
    instruction must all behave exactly as before, which is `sounddevice`
    loading its own copy. Idempotent: a second call cannot grow `PATH`, so
    calling it from more than one entry point is safe.

    The config read is the last check, not the first, for two reasons: it is
    the only one that touches the disk, and the three cases above change
    nothing anyway — a source install must not pay a file read to be told so.
    It is stdlib-only and never raises (`config.bundled_portaudio_enabled`):
    this runs as `main()`'s first statement, before `_setup_logging()`, before
    Qt, and before `--version` / `--help` answer, so an unreadable config must
    cost at most the newer DLL and never the app's start.

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
        # The escape hatch (module docstring): a bundled DLL that loads but
        # fails Pa_Initialize would take microphone dictation down with it, and
        # nothing in CI records audio with the new binary. Read here, where the
        # answer decides the very next statement.
        from .config import bundled_portaudio_enabled

        if not bundled_portaudio_enabled():
            _prepare_note = (
                "system_audio.bundled_portaudio is off — sounddevice keeps its own "
                "PortAudio (no WASAPI loopback; the bundled DLL stays unused)"
            )
            return None
        current = os.environ.get("PATH") or ""
        os.environ["PATH"] = f"{bundle}{os.pathsep}{current}" if current else bundle
        _prepared = bundle
        _prepare_note = f"prepended {bundle} to PATH for {DLL_NAME}"
        return bundle
    except Exception as exc:  # a broken environ costs the DLL, never the start
        _prepare_note = f"could not prepend the bundle directory to PATH: {exc!r}"
        return None


def device_hostapi(device) -> int | None:
    """The host API index a `sd.query_devices()` entry belongs to, or None when
    the entry does not carry a usable one. `bool` is excluded on purpose: it is
    an `int` subclass, so a stand-in device dict carrying `True` would
    otherwise compare equal to host API 1."""
    try:
        api = device.get("hostapi")
    except Exception:
        return None
    if isinstance(api, bool) or not isinstance(api, int):
        return None
    return api


def preferred_hostapi(sd, hostapis: list | None = None) -> tuple[int | None, str]:
    """The PortAudio host API index that lists this machine's audio endpoints
    EXACTLY ONCE, plus its name — WASAPI on Windows, PortAudio's own default
    host API everywhere else. `(None, "")` when neither can be resolved, which
    means "do not count devices", never "there are none".

    Why a filter exists at all: PortAudio enumerates every endpoint once per
    host API. One soundcard on Windows therefore reports the same speaker four
    times (MME, DirectSound, WASAPI, WDM-KS) plus two pseudo-devices that are
    not hardware at all ("Microsoft Sound Mapper - Output",
    "Primary Sound Driver"). Counting or naming that raw list produced two
    measured failures, and both are the reason a later "simplification" back to
    every device must not happen:

    * `settings_ui`'s System audio hint puts the output names into prose. On a
      machine where #194 works perfectly it read “No loopback device was found
      for “Microsoft Sound Mapper - Output”, “Primary Sound Driver” and
      “Speakers (Realtek HD Audio output)” — those outputs cannot be recorded
      directly on this build.” Two of those are not devices the user has; the
      third is the same speaker under WDM-KS. A false sentence about the
      primary platform, in the one sentence #195 exists to add.
    * :func:`describe`'s ratio read "N loopback of ~4×M outputs", and the
      release gate (`selftest._portaudio_supports_wasapi_loopback`: outputs but
      no loopbacks means a DLL built without WASAPI) counted the same way — so
      a runner reporting an MME phantom output while WASAPI enumerates no
      render endpoint would have failed a *correct* build.

    Why WASAPI specifically on Windows, rather than simply the default host
    API: PortAudio's Windows default is MME or DirectSound, and only WASAPI
    emits the "[Loopback]" twins the whole feature rests on (#194). Counting
    the twins on one host API and the outputs on another is exactly how the
    ratio lies.

    This must NOT be extended to the input list. `audio.input_device_profiles`
    deliberately enumerates every host API: the dropdowns store a device
    *index*, and a user may well have picked the WDM-KS entry of their headset.
    The question here is "how many outputs does this machine have", not "which
    devices may be recorded from".

    `sd` is passed in rather than imported so this stays stdlib-only at import
    time, and `hostapis` is injectable so a caller that already listed them
    does not ask twice. Never raises — every lookup is guarded, and the
    unresolved answer is a value the callers report.
    """
    try:
        apis = list(sd.query_hostapis()) if hostapis is None else list(hostapis)
    except Exception:
        log.debug("could not list the PortAudio host APIs", exc_info=True)
        apis = []
    if sys.platform.startswith("win"):
        for index, api in enumerate(apis):
            try:
                name = str(api.get("name", "") or "")
            except Exception:
                continue
            if WINDOWS_HOSTAPI_MARKER in name.casefold():
                return index, name
        # Only reachable on a PortAudio built without the WASAPI host API at
        # all — the wheel's own binary has it (it just enumerates no loopback
        # twins). The default host API is then the best answer available, and
        # `loopback_supported` has already said the interesting half.
        log.debug("no WASAPI host API on this build — falling back to the default one")
    try:
        index = int(sd.default.hostapi)
    except Exception:
        log.debug("could not resolve the default PortAudio host API", exc_info=True)
        return None, ""
    if index < 0:
        return None, ""
    name = ""
    if index < len(apis):
        try:
            name = str(apis[index].get("name", "") or "")
        except Exception:
            name = ""
    return index, name


def describe(devices: list | None = None, hostapis: list | None = None) -> dict:
    """Which PortAudio is loaded and what it can do — the probe behind the log
    line and the release build's self-test.

    Keys: "version" / "version_number" (from `sd.get_portaudio_version()`),
    "library" (the file `sounddevice` resolved), "loopback_supported",
    "hostapi" (the host API the two counts below were taken on),
    "loopback_devices" (input devices carrying the "[Loopback]" marker),
    "output_devices", "bundle_path" / "path_note" (what
    :func:`prepare_library_path` did), and "errors".

    **Both device counts are taken on one host API** — see
    :func:`preferred_hostapi` for the two false statements the unfiltered
    counts produced. "hostapi" is None exactly when that pick failed, and then
    the counts are 0 because nothing was counted: a caller must read that as
    "unknown", not as "this machine has no outputs" (the release gate does,
    and reports the skip rather than failing a correct build).

    `devices` / `hostapis` are injectable so a caller that has just enumerated
    does not pay for a second `sd.query_devices()` — PortAudio can stall for
    hundreds of milliseconds there, which is why `audio.input_device_profiles`
    hands over the lists it already holds.

    "version" / "version_number" are context, never identity: the DLL we
    build and the one in the `sounddevice` wheel both report `PortAudio
    V19.7.0-devel, revision unknown` and `190700` (module docstring). So a
    caller asking "did the DLL we ship get loaded?" reads "library", and one
    asking "can this binary do loopback?" reads "loopback_supported" and
    "loopback_devices" — never a version comparison, which would answer
    "unchanged" for a perfectly good new build.

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
        "hostapi": None,
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
            # Expected on the binary inside the `sounddevice` wheel: the symbol
            # is declared in the CFFI header but not exported by it. This lookup
            # is what separates the two binaries — their version strings do not.
            errors.append(f"PaWasapi_IsLoopback is not reachable: {exc}")
    try:
        apis = list(sd.query_hostapis()) if hostapis is None else list(hostapis)
    except Exception as exc:
        errors.append(f"could not list the host APIs: {exc!r}")
        apis = []
    api_index, api_name = preferred_hostapi(sd, apis)
    if api_index is None:
        errors.append(
            "the host API that lists each endpoint once could not be resolved — "
            "the device counts are not taken"
        )
    else:
        # Never left empty while an index resolved: "hostapi is None" is the
        # only marker for "not counted", so a nameless host API still has to
        # answer with something.
        info["hostapi"] = api_name or f"host API {api_index}"
    try:
        entries = list(sd.query_devices()) if devices is None else list(devices)
    except Exception as exc:
        errors.append(f"could not enumerate the devices: {exc!r}")
        return info
    if api_index is None:
        return info
    for device in entries:
        try:
            if device_hostapi(device) != api_index:
                continue  # the same endpoint under another host API
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


def log_once(devices: list | None = None, hostapis: list | None = None) -> None:
    """Log one INFO line per process naming the *file* the loaded PortAudio
    came from, whether it supports WASAPI loopback, and how many loopback
    inputs it enumerated.

    Those three are the answer to "did the DLL we ship get loaded?". The
    version string is carried along but labelled, in the line itself, as no
    answer at all: a correct new build still logs `PortAudio V19.7.0-devel,
    revision unknown`, byte-identical to what the wheel's binary logs (module
    docstring). The label belongs in the line and not only here, because
    whoever reads this in a release log has no docstring in front of them —
    and reading a "V19.7.0-devel" as "the DLL was not picked up" is the exact
    wrong conclusion. The loaded path leads for the same reason: it is the
    field that actually differs (the bundle's own `portaudio.dll` for ours,
    `_sounddevice_data/portaudio-binaries/libportaudio64bit.dll` for the
    wheel's), and at INFO level a DEBUG line would not be there to carry it.

    The device counts name the host API they were taken on, because without it
    they are not a ratio: the same machine reads "1 of 1" on WASAPI and "1 of
    4" across every host API, and whoever reads a release log cannot tell
    those apart from the numbers (:func:`preferred_hostapi`).

    One line, once, and NOT from the recording path. It costs a device
    enumeration, and `Recorder.start()` runs on the Qt main thread the moment
    the user has pressed the hotkey and is about to speak — a PortAudio stall
    of a few hundred milliseconds is felt there, and the default
    `input_device: null` means nothing else on that path enumerates at all.
    The caller is `audio.input_device_profiles()` instead: the Audio settings
    page, which is where someone hunting a missing loopback device already is,
    and which enumerates anyway — it hands its own lists over through
    `devices` / `hostapis` so this line costs no second enumeration. The price
    is that a session that only dictated and never opened that page carries no
    such line; the stall it saves is at the worst possible moment.

    It is also the only place `prepare_library_path()`'s outcome is ever
    reported — that runs before logging exists (see `app.main`), so it records
    its note and this prints it. That includes the escape hatch being off.

    Never raises: it is a diagnostic, and no diagnostic is worth an exception
    on a settings page.
    """
    global _logged
    if _logged:
        return
    _logged = True
    try:
        info = describe(devices, hostapis)
        # Both segments are built ahead of the call, for one reason each. The
        # caveat has to travel with the string it disclaims — a bare version
        # here reads as a verdict, and the verdict it suggests is wrong. And a
        # missing library must not still read as "loaded from": without
        # sounddevice (the settings page on a bare Linux checkout) nothing was
        # loaded at all. Deliberately not %r on the path: repr() doubles every
        # backslash in a Windows one.
        version = info.get("version")
        library = info.get("library")
        lead = f"PortAudio loaded from {library}" if library else "no PortAudio library identified"
        version_note = (
            f"version {version!r} says nothing: the DLL we ship and the one in the "
            "sounddevice wheel report the same string"
            if version
            else "version unreadable"
        )
        hostapi = info.get("hostapi")
        devices_note = (
            f"{info.get('loopback_devices') or 0} loopback input device(s) of "
            f"{info.get('output_devices') or 0} output(s) on {hostapi}"
            if hostapi
            else "devices not counted: no host API could be resolved"
        )
        log.info(
            "%s — WASAPI loopback %s, %s; %s; %s",
            lead,
            "supported" if info.get("loopback_supported") else "unsupported",
            devices_note,
            version_note,
            info.get("path_note"),
        )
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
