# ADR-0009: System audio is captured through a loopback input device

- **Status:** Accepted; partly superseded — the workflow file name `release.yml` by ADR-0011
- **Date:** 2026-09-10
- **Decider(s):** agent
- **Tags:** audio, dependencies, packaging, platform
- **Details:** [details/0009-system-audio-is-captured-through-a-loopback-input-device.md](details/0009-system-audio-is-captured-through-a-loopback-input-device.md)

## Decision

We will capture system audio from an ordinary PortAudio **input** device that the operating system already provides — a loopback or monitor source — and not from a WASAPI loopback stream. `system_audio.py` ranks the visible input devices by name (`LOOPBACK_HINTS`), auto-picks the best candidate when `system_audio.device` is `null`, and `audio.Recorder` falls back to the device's native format (48 kHz stereo as a rule) with `resample.py` converting to 16 kHz mono inside the capture callback.

When no candidate exists, the take is **refused** with the platform's own fix named in the notification (`system_audio.system_audio_help()`). It is deliberately not degraded to the default input device: the default input _is_ a microphone, so falling back would record the room while the user asked for the computer's output — a wrong result rather than a degraded one, and nothing about the resulting transcript would give it away. This is the one place the contract differs from `choices.resolve_input_device`, where a `None` index does mean "use the system default".
