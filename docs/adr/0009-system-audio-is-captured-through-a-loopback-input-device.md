# ADR-0009: System audio is captured through a loopback input device

- **Status:** Accepted
- **Date:** 2026-09-10
- **Decider(s):** agent
- **Tags:** audio, dependencies, packaging, platform

## Context

The second recording source (#191) records what the computer **plays** — a call, a meeting, a video — instead of what the microphone hears. On Windows, the obvious way to do that is WASAPI loopback: the OS can hand out the render endpoint's stream as a capture stream, with no device to install and nothing for the user to enable.

The shipped stack cannot ask for it. Three measurements taken while building the feature, each of which will date this decision:

- **`sounddevice>=0.5.6` exposes no loopback option.** Its only WASAPI hook is `WasapiSettings(exclusive, auto_convert, explicit_sample_format)` — those three keywords and nothing else — and the word "loopback" does not appear anywhere in `sounddevice.py`.
- **The PortAudio binary bundled in its Windows wheel is too old.** It reports itself as `PortAudio V19.7.0-devel` and exports 13 `PaWasapi_*` symbols, none of which is `PaWasapi_IsLoopback`; the DLL also carries no `[Loopback]` device-name string, in neither ASCII nor UTF-16. The `-asio` and `arm64` builds in the same wheel measure identically.
- **The API does exist upstream, and that is the trap.** sounddevice's own CFFI declarations _do_ declare `PaWasapi_IsLoopback` — so a reader who greps the Python package concludes the feature is one `_lib` call away, and only the bundled binary says otherwise. The declaration is a promise about a PortAudio newer than the one in the wheel.

Ordering a newer PortAudio is not a small change either: the one-file Windows build ships whatever DLL the wheel carries, so replacing it means carrying and updating a binary of our own in `release.yml`.

## Decision

We will capture system audio from an ordinary PortAudio **input** device that the operating system already provides — a loopback or monitor source — and not from a WASAPI loopback stream. `system_audio.py` ranks the visible input devices by name (`LOOPBACK_HINTS`), auto-picks the best candidate when `system_audio.device` is `null`, and `audio.Recorder` falls back to the device's native format (48 kHz stereo as a rule) with `resample.py` converting to 16 kHz mono inside the capture callback.

When no candidate exists, the take is **refused** with the platform's own fix named in the notification (`system_audio.system_audio_help()`). It is deliberately not degraded to the default input device: the default input _is_ a microphone, so falling back would record the room while the user asked for the computer's output — a wrong result rather than a degraded one, and nothing about the resulting transcript would give it away. This is the one place the contract differs from `choices.resolve_input_device`, where a `None` index does mean "use the system default".

## Consequences

### Positive

- **Linux works out of the box.** PulseAudio and PipeWire give every sink a `Monitor of …` source, so there is always a candidate and the auto-pick finds it.
- **No new dependency, no bundled binary.** The feature rides on the `sounddevice` the app already ships, and the one-file Windows build is unchanged.
- **One capture path, one engine.** A loopback source is a normal input device, so recording, the length cap, the transcriber, the history and the assistant are the same code as for a dictation — only the device, the cap and the assistant profile differ.
- **Forward-compatible by construction.** A newer PortAudio enumerates every output device a second time as `<name> [Loopback]`; `LOOPBACK_HINTS` already scores that suffix highest, so the day the wheel carries such a binary the auto-pick simply gets better with no code change.

### Negative / Trade-offs

- **Windows needs a one-time setup step.** "Stereo Mix" / "What U Hear" exists on most onboard audio but is **disabled by default** (Sound Control Panel → Recording → right-click → Show Disabled Devices); a chipset without it needs a virtual cable (VB-CABLE, VoiceMeeter). This is the platform the app targets first, which makes it the most visible cost of this decision.
- **macOS needs a virtual device** (BlackHole, Soundflower, Rogue Amoeba Loopback) — it ships no loopback source at all.
- **The device is matched by name.** A loopback device named in a language or by a vendor that `LOOPBACK_HINTS` does not list is not auto-picked; the user selects it by hand from the full input list on the Audio page. Extending the ranking is one line of data, but it is a list that can never be complete.
- **A resampler in the capture callback.** A loopback device rarely offers 16 kHz mono and PortAudio does not resample, so the callback runs a windowed-sinc low-pass plus a phase-continuous linear interpolator per block — work a WASAPI loopback stream with `auto_convert` would not have needed.

### Neutral

- On Windows the WASAPI `auto_convert` flag is still used where it helps: `os_convert` is opt-in per take, on for system audio and off for the microphone, which already opens at 16 kHz mono.
- The ranking is data (`LOOPBACK_HINTS`), not branching logic, so a newly seen device name is one line rather than a new code path.

## Alternatives Considered

- **Ship a newer PortAudio DLL in the one-file build** — rejected for now: it puts a hand-maintained native binary into `release.yml` and into the update path, for a platform-specific convenience. Tracked in issue #192.
- **Wait for sounddevice to bundle a PortAudio that exports `PaWasapi_IsLoopback`** — not rejected, just not a plan: the CFFI declaration is already there, so the day the wheel catches up this becomes a small additive change. Tracked in issue #192.
- **Add a `soundcard` dependency behind an optional extra** — it implements WASAPI loopback directly, but it is a second audio stack next to `sounddevice` for one platform's convenience, and a new runtime dependency needs the maintainer's approval (it also bloats the one-file build). Tracked in issue #192.
- **Fall back to the default input device when no loopback device is found** — rejected outright, and it is the reason `resolve_loopback_device` returns `None` instead: recording the microphone under the label "system audio" produces a transcript the user has every reason to believe came from the meeting.

## References

- Issue #191 — the second recording source. Issue #192 — the Windows loopback gap and the three alternatives above; it needs the maintainer's decision.
- Device ranking, the auto-pick and the refusal contract: `src/listen_to_me/system_audio.py`.
- Native-format fallback and the WASAPI `auto_convert` opt-in: `src/listen_to_me/audio.py` (`Recorder.start`, `_wasapi_auto_convert`).
- The 16 kHz mono conversion and its accuracy contract: `src/listen_to_me/resample.py`.
- Per-source assistant profiles: `assistant.profile`, `config.DEFAULTS → assistant.system_audio`.
