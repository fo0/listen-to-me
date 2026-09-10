# ADR-0010: The Windows release builds and ships its own PortAudio

- **Status:** Accepted — supersedes ADR-0009 in part: only its rejected alternative "Ship a newer PortAudio DLL in the one-file build". ADR-0009's decision — capture through a loopback **input** device — stays in force and is reinforced by this one.
- **Date:** 2026-09-10
- **Decider(s):** user (approved the #192 option) + agent
- **Tags:** audio, packaging, build, deploy, platform

> This ADR does not replace [ADR-0009](0009-system-audio-is-captured-through-a-loopback-input-device.md). Nothing about the capture path changes: system audio is still recorded from an ordinary loopback/monitor **input** device, `system_audio.py` still ranks it by name, and a missing candidate still **refuses** the take. What changes is that on the released Windows exe such a device now always exists, because we ship the PortAudio that enumerates one for every output. ADR-0009 recorded this as an alternative "rejected for now … tracked in issue #192"; that one line is what this ADR overrides.

## Context

ADR-0009's most visible cost is Windows, the platform this app targets first: the PortAudio inside the `sounddevice` wheel exports no `PaWasapi_IsLoopback` and enumerates no loopback device at all, so a user had to enable "Stereo Mix" or install a virtual cable, and a machine with a USB headset has nothing capturable whatsoever. Issue #192 put the three ways out to the maintainer; the maintainer approved building and shipping our own DLL (#194).

The premise was then **verified against upstream source** rather than inferred from the version number:

- `include/pa_win_wasapi.h:527` declares `int PaWasapi_IsLoopback(PaDeviceIndex)`.
- `src/hostapi/wasapi/pa_win_wasapi.c:2050` (`FillLooopbackDeviceInfo`) enumerates **every** WASAPI render endpoint a second time as an input device and appends the marker `"[Loopback]"` to its name, under the comment _"Some projects depend on loopback device detection by device name, do not change!"_. That makes the marker a **documented, name-based contract** — and it is exactly the fragment `system_audio.LOOPBACK_HINTS` already scores highest, so the sanctioned way to find these devices is the ranking the app already had. **No device code changed for this.**
- The lever that makes a bundled DLL win is `sounddevice`'s own load order (0.5.6, lines 63-91): `ctypes.util.find_library("portaudio")` first — on Windows that walks the directories on `PATH` looking for `portaudio.dll` — then two conda/anaconda paths, and only then its own `_sounddevice_data/portaudio-binaries/libportaudio64bit.dll`.

The last PortAudio release, 19.7.0 (2021), predates loopback support, so there is no released version to take this from: it has to be a master commit, and the commit SHA is the only version identity that exists.

## Decision

We will **build `portaudio.dll` from a pinned PortAudio master commit inside the `build-windows` job and ship it in the one-file exe**, and we will make it the binary that actually answers by exploiting `sounddevice`'s load order rather than by patching `sounddevice`. Three parts, none of them touching the capture path: `release.yml` fetches the pinned commit (`PORTAUDIO_COMMIT`), configures CMake with `PA_USE_WASAPI=ON` plus a static MSVC runtime, and **refuses to continue** unless the fresh DLL loads and exports `PaWasapi_IsLoopback` — a build without WASAPI must stop the release, not surface months later as "no loopback device" on a user's machine; PyInstaller then places it at the bundle root with `--add-binary`; and `portaudio.prepare_library_path()` — `app.main()`'s **first statement**, deliberately ahead of the flag block because `--version`/`--help`/`--selftest` return before logging exists and `--selftest` is the one run that can verify the DLL — prepends `sys._MEIPASS` to `PATH` so step 1 of that load order finds ours. Everything degrades to today's behaviour when the DLL is absent or unloadable: no `sys.frozen`, no `sys._MEIPASS`, no DLL in the bundle, or an `OSError` on load, and `sounddevice` keeps its own copy.

## Consequences

### Positive

- **Windows needs no setup any more — on the release exe.** Every output device gets a `… [Loopback]` input twin, so any output can be recorded, `Stereo Mix` is not required and a USB-headset-only machine works (#194).
- **The picker can finally name outputs** (#195): the marker carries the output's own name, so a row reads as the output it records and the hint can name the outputs that no loopback device covers. `audio.list_output_devices()` is back as that hint's data source.
- **Nothing is monkeypatched and nothing is forked.** The integration is a file name and a `PATH` entry; the wheel's DLL stays in place as the fallback.
- **The rollback is deleting two workflow steps.** If a future `sounddevice` wheel carries a loopback-capable binary, the build steps and the `--add-binary` go away and `prepare_library_path()` becomes a no-op that costs nothing.
- **ADR-0009's forward-compatibility claim was collected, not replaced.** It predicted that a newer PortAudio would name loopback devices `<name> [Loopback]` and that the existing ranking would then simply get better. That is what happened.

### Negative / Trade-offs

- **The swap is not scoped to loopback.** Our binary answers for **all** audio in the frozen build — WMME, DirectSound, WDM-KS and WASAPI alike — so a master-only regression in any host API reaches plain microphone dictation too, not just the new source. The exe's `--selftest` in the **Smoke test executable** step is the only automated gate, and it runs on a GitHub runner with no real audio devices.
- **The version string cannot identify the binary.** The pinned commit still defines `paVersionMinor 7` (`src/common/pa_front.c`) and still ships the checked-in `#define PA_GIT_REVISION unknown` (upstream's `update_gitrevision.sh` is a manual pre-build script CMake never runs), so it reports `PortAudio V19.7.0-devel, revision unknown` — byte-identical, revision suffix included, to all six DLLs in the `sounddevice` wheel (measured on both sides). What identifies the loaded binary is the **file path** and whether **`PaWasapi_IsLoopback` is reachable**; that is why `portaudio.log_once()` leads its INFO line with the path and labels the version, in the line itself, as no answer at all.
- **A source install ships no DLL.** `pip install -e .` on Windows leaves `sounddevice` on its own bundled copy, so those users still need `Stereo Mix` or a virtual cable. The release exe and a source checkout now behave **differently** for the same feature on the same machine — a new asymmetry, and the reason the README says which is which.
- **A non-release commit means no release notes.** Every bump is a judgment call over a raw commit range, against four upstream things the build leans on (declaration, name marker, CMake option names, artifact name) — the checklist is in `agent_docs/deployment.md`.
- **Not verifiable in a pull request.** `release.yml` is `workflow_dispatch`-only and guarded to `main`, so both gates first run on the first dispatch after the merge; earlier verification means running the `cmake` commands by hand on a Windows machine.
- **The release job carries a native toolchain step** (fetch, CMake configure, MSVC build) and its wall clock, on every dispatch — and the DLL is as unsigned as the exe, so nothing changes about SmartScreen.

### Neutral

- **Pinned by commit SHA, like every action in the workflow** (#22) — for a stronger reason here, since this is native code inside a binary the in-app updater hands to end users.
- The gate is an **export check, not a version comparison**: a version comparison would answer "unchanged" for a perfectly good new build (see the trade-off above).
- `portaudio.py` is Qt-free and stdlib-only at import time (`sounddevice` is imported lazily inside `describe()`), because `audio` imports it at module scope and `main()` calls it on its first line — both have to stay light enough for `--version`.

## Alternatives Considered

- **Keep ADR-0009's status quo and only document the workaround** — this is what #192 asked about, and the maintainer decided against it: "enable a hidden device or install a virtual cable" is a setup step on the primary platform, and on a headset-only machine it is not even available.
- **Wait for `sounddevice` to bundle a PortAudio that exports `PaWasapi_IsLoopback`** — still not rejected, just still not a plan (ADR-0009 said the same). The CFFI declaration is already in the package, so the day the wheel catches up this ADR's build steps become removable. Until then, waiting means shipping the gap.
- **Add a `soundcard` dependency behind an optional extra** — stays rejected: a second audio stack next to `sounddevice` for one platform's convenience, a new runtime dependency needing the maintainer's approval, and more weight in the one-file build.
- **Fall back to the default input device when no loopback device is found** — stays rejected outright, unchanged from ADR-0009: the default input is a microphone, so this would record the room while the user asked for the computer's output.

## References

- Issue #192 — the decision this ADR records (the three ways out of the Windows gap). Issue #194 — build and ship the DLL. Issue #195 — the system-audio device picker that names outputs. Issue #191 — the second recording source. Issue #22 — why everything in a release workflow is pinned by SHA.
- [ADR-0009](0009-system-audio-is-captured-through-a-loopback-input-device.md) — the capture path, unchanged.
- **Bump procedure, the four upstream contracts to re-check, the verification gates and the costs stated plainly:** `agent_docs/deployment.md` → _PortAudio is pinned by commit SHA too_ (the artifact, the commands and the checklist live there, not here).
- Load order, the `PATH` prepend and the probe that says which binary won: `src/listen_to_me/portaudio.py` (`prepare_library_path`, `describe`, `log_once`); call site `app.main()`.
- Build, gate and bundling: `.github/workflows/release.yml` → **Build PortAudio with WASAPI loopback**, **Verify the PortAudio DLL exports WASAPI loopback**, `--add-binary`.
- What the picker does with the result: `audio.list_output_devices`, `settings_ui._load_system_devices`, `settings_ui._refresh_system_audio_hint`.
