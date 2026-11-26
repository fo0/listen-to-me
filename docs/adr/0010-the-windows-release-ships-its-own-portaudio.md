# ADR-0010: The Windows release builds and ships its own PortAudio

- **Status:** Accepted — supersedes ADR-0009 in part: only its rejected alternative "Ship a newer PortAudio DLL in the one-file build". ADR-0009's decision — capture through a loopback **input** device — stays in force and is reinforced by this one. Partly superseded — the workflow file name `release.yml` by ADR-0011.
- **Date:** 2026-09-10
- **Decider(s):** user (approved the #192 option) + agent
- **Tags:** audio, packaging, build, deploy, platform
- **Details:** [details/0010-the-windows-release-ships-its-own-portaudio.md](details/0010-the-windows-release-ships-its-own-portaudio.md)

> This ADR does not replace [ADR-0009](0009-system-audio-is-captured-through-a-loopback-input-device.md). Nothing about the capture path changes: system audio is still recorded from an ordinary loopback/monitor **input** device, `system_audio.py` still ranks it by name, and a missing candidate still **refuses** the take. What changes is that on the released Windows exe such a device now always exists, because we ship the PortAudio that enumerates one for every output. ADR-0009 recorded this as an alternative "rejected for now … tracked in issue #192"; that one line is what this ADR overrides.

## Decision

We will **build `portaudio.dll` from a pinned PortAudio master commit inside the `build-windows` job and ship it in the one-file exe**, and we will make it the binary that actually answers by exploiting `sounddevice`'s load order rather than by patching `sounddevice`. Three parts, none of them touching the capture path: `release.yml` _(superseded by ADR-0011)_ fetches the pinned commit (`PORTAUDIO_COMMIT`), configures CMake with `PA_USE_WASAPI=ON` plus a static MSVC runtime, and **refuses to continue** unless the fresh DLL loads and exports `PaWasapi_IsLoopback` — a build without WASAPI must stop the release, not surface months later as "no loopback device" on a user's machine; PyInstaller then places it at the bundle root with `--add-binary`; and `portaudio.prepare_library_path()` — `app.main()`'s **first statement**, deliberately ahead of the flag block because `--version`/`--help`/`--selftest` return before logging exists and `--selftest` is the one run that can verify the DLL — prepends `sys._MEIPASS` to `PATH` so step 1 of that load order finds ours. Everything degrades to today's behaviour when the DLL is absent or unloadable: no `sys.frozen`, no `sys._MEIPASS`, no DLL in the bundle, or an `OSError` on load, and `sounddevice` keeps its own copy.
