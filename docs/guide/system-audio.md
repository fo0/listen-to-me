# Recording system audio (a call, a meeting, a video)

A **second global hotkey** records what the computer _plays_ instead of what
the microphone hears: a call, a meeting, a video, a voice message. The
recording goes through the same local model and the text is inserted at the
cursor just like a dictation — same toggle/hold behaviour, its own device, its
own maximum length (**900 s = 15 minutes** by default, because a recorded
meeting is not a dictation) and its own assistant prompt.

It is **off until you set the hotkey**: Settings → Audio → **System audio**.
Without one, the source is still reachable from **Record system audio** in the
tray menu and in the floating icon's right-click menu — enough for a single
recording without giving up a key combination for it. Once a hotkey is set, the
Home page shows a second row of key caps, and every message about a running
take names which of the two sources it is about.

## The recording device — what it takes per platform

The app records from an ordinary **input** device that carries the computer's
output. On the released Windows exe there is one for every output device and
you do not have to do anything; everywhere else it depends on the platform.

| Platform                          | What to do                                                                                                                                                                                                                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows** (the downloaded exe)  | Nothing. The exe ships its own PortAudio with WASAPI loopback, so **every** output device also shows up as a recordable “… [Loopback]” input — including a USB headset that has no “Stereo Mix”. **Automatic** picks the one for your current output.                                       |
| **Windows** (running from source) | `pip install -e .` ships no such DLL, so this is the old situation: enable “Stereo Mix” in the Windows sound control panel (Recording tab → right-click → **Show Disabled Devices**), or install a virtual audio cable such as [VB-CABLE](https://vb-audio.com/Cable/) and play through it. |
| **Linux**                         | Nothing. Select the “Monitor of …” source that belongs to your output device — PulseAudio and PipeWire provide one for every output. The app picks it automatically.                                                                                                                        |
| **macOS**                         | macOS has no loopback device of its own — install a virtual output device such as [BlackHole](https://existential.audio/blackhole/) and route the playback through it.                                                                                                                      |

**If an update ever breaks audio, `system_audio.bundled_portaudio` is the way
back.** The bundled binary answers for **all** audio in the exe, not just
loopback. So if audio stops working entirely after an update, or recording
fails in a way it did not before, set `system_audio.bundled_portaudio` to
`false` in `config.json` and restart the app: it then loads the PortAudio
inside the `sounddevice` wheel again, the one every earlier build used. That
costs recording what the computer plays on Windows — the wheel's binary
enumerates no loopback device — and nothing else. There is deliberately no
setting for it in the settings window: it is a lever for getting a broken
build working again, not a feature switch.

The **Device** dropdown is grouped, because “System audio” is not a list of
microphones: **Automatic — the best loopback device, or nothing** sits at the
top, then _Loopback devices — these record what the computer plays_, then
_Other input devices — microphones, not what the computer plays_ (in case yours
is named in a way the app does not recognise). A loopback row is labelled with
the **output it records** — “Speakers (Realtek) [Loopback]” shows up as
`12: Speakers (Realtek) — records this output, matched “[loopback]”` — so you pick
the output you are listening to rather than decoding device names. If the first
group is empty it stays visible with a **None found — nothing here can record
the computer's output** row under it, and the hint below the card then names
your outputs, says that none of them can be recorded directly on this build,
and gives you the fix. **Refresh** re-scans and tells you what it found — use
it right after enabling Stereo Mix or installing a cable, no restart needed.

The same hint also names individual outputs that no loopback device covers when
_some_ were found: on a machine with a working monitor source for the speakers
but nothing for the HDMI output, it says so instead of letting you record the
wrong thing.

> **When there is no loopback device, the take is refused** — with a
> notification naming the fix for your platform, exactly as in the table above.
> It deliberately does _not_ fall back to the default input device: that is a
> microphone, so the app would record the room while you asked it for the
> computer's output, and nothing about the resulting text would give that away.
> The Audio page shows the same hint before you ever try. Why the app needs a
> device at all instead of asking Windows for a loopback stream:
> [ADR-0009](../adr/0009-system-audio-is-captured-through-a-loopback-input-device.md);
> why the Windows exe now brings its own PortAudio so that such a device always
> exists:
> [ADR-0010](../adr/0010-the-windows-release-ships-its-own-portaudio.md).

Three more things worth knowing:

- **Where the text ends up.** A system-audio transcript is stored in the local
  history like any other, and with the **System audio** assistant profile
  enabled it is sent to the endpoint configured under Settings → Assistant →
  **Connection** — the same endpoint the dictation profile uses. That profile
  is off by default. A recording of a call or a meeting is a recording of other
  people, so check where that connection points before enabling it for one.
- **Only one recording at a time.** Starting the other source while a take runs
  is refused with a notification naming the one that is running — a system-audio
  recording is not something you want silently replaced by a dictation.
- **Such a device is usually 48 kHz stereo**, and it is recorded in its own
  format and converted to the 16 kHz mono the model wants while it records. You
  do not have to configure anything for that.
