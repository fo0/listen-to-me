# Listen To Me 🎙️

Push-to-talk voice typing for your desktop — fully local, open source.

> 🇩🇪 **Deutsch:** [Kurzanleitung auf Deutsch →](README.de.md)

Press a hotkey, speak, press it again: your words are transcribed by a **local
Whisper model** and inserted **at the cursor position of whatever field is
focused** — like the recording button in Chrome or OpenWebUI, but as a
standalone system-tray app that works in _every_ application.

- **100 % local speech recognition** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (CTranslate2), no cloud, no account. Models are downloaded automatically on
  first use. The model is loaded **while you are still speaking**, not after
  you stop, so the first dictation of a session no longer waits for it between
  the last word and the inserted text.
- **Global hotkey** (default `Ctrl+Alt+Space`) — start/stop recording from any
  app, either as **toggle** (press to start, press to stop) or as true
  **push-to-talk** (record while the keys are held).
- **A second hotkey records what the computer plays** — a call, a meeting, a
  video: the playback is transcribed by the same local model and inserted at
  the cursor just like a dictation, with its own device, its own maximum
  length (15 minutes by default) and its own assistant prompt. Off until you
  set the hotkey (Settings → Audio → **System audio**), and also reachable
  from the tray menu and the floating icon's menu without one. The released
  Windows **exe records any output device with no setup at all** — it ships
  its own PortAudio with WASAPI loopback
  ([ADR-0010](docs/adr/0010-the-windows-release-ships-its-own-portaudio.md)),
  so “Stereo Mix” is no longer needed there; Linux needs nothing either, while
  a source install on Windows and any macOS install still need a loopback
  device the system provides — see
  [Recording system audio](#recording-system-audio-a-call-a-meeting-a-video).
- **Inserts at the cursor** — via clipboard paste (default) or simulated
  typing; if the clipboard is unavailable, paste mode falls back to typing
  instead of losing the transcript.
- **Clipboard safety net** — when the text cannot be inserted into the focused
  window, it is put on the clipboard so one Ctrl+V recovers it. Optionally
  **always** (every transcript stays on the clipboard) or **never**
  (Settings → General → _Copy the transcript to the clipboard_). Whenever a
  transcript is left on the clipboard, a notification says so and shows the
  first few words — so a recording made with no text field focused (the paste
  lands nowhere and the app cannot tell) still ends with a visible
  "Copied to the clipboard: …" instead of silence.
- **A recording that produced no text says why** — when nothing comes back, the
  app looks at what the microphone actually delivered: no signal at all ("check
  the input device under Settings → Audio and whether the microphone is muted")
  and a signal too quiet to recognize are named as the device problems they are,
  instead of every case reading "No speech detected." and sending you back to
  repeat the dictation into a muted microphone.
- **A silent take no longer inserts a sentence nobody spoke** — press the
  hotkey, say nothing, press it again, and Whisper answers "Vielen Dank.",
  "Thank you." or a subtitle credit. Those phrases come out of the model, not
  out of this app: it was trained on subtitled video, where a stretch without
  speech is usually subtitled with the clip's closing line. So the recording
  decides, not the wording: a transcript is thrown away only when the take's
  own audio was **silent or too quiet** and the text is nothing but such a
  phrase — it is then reported like a take with no speech, which is what it
  was. A take that carried real speech is never filtered, however it reads, so
  a "Vielen Dank." you really did dictate lands at the cursor. The phrase list
  is yours to edit (Settings → Engine → **Silent takes**), see
  [Silent takes and invented phrases](#silent-takes-and-invented-phrases).
- **A microphone that disappeared costs the device, not the dictation** — the
  selected microphone is stored as a device index, and those shift when a USB
  headset is unplugged or anything else is plugged in. When the configured one
  is gone the take is recorded with the **system default** instead of dying
  with a PortAudio error, and a notification says so once, so the swap is never
  silent.
- **Live typing (experimental)** — start typing while you are still speaking:
  parts of the transcript that have become stable are typed at the cursor
  during the recording, the rest follows right after you stop. Strictly
  append-only (never deletes or corrects) and plain text only — no Enter/Tab,
  and typing pauses while Ctrl/Alt/Shift/Win is held so no accidental key
  combination can ever fire (modifier detection is Windows-only; with a hold
  hotkey the feature requires a modifier-free key such as F9 on any platform).
- **Floating status icon** — a small animated always-on-top icon you can drag
  anywhere: a wavy equalizer ring that shimmers gently while idle, pulses with
  your live microphone levels while recording, and shows an orange mic glyph
  while transcribing. Click it to start/stop, right-click for a menu — whose
  entries follow the state like the tray menu's do, so the first one says
  whether it starts or stops the take and **Cancel recording** only appears
  while there is one to cancel. **Record system audio** is in that menu too,
  so the second source can be used once without giving up a global hotkey for
  it. Hovering
  it while you dictate shows **how long the take has been running**
  ("Recording 1:12… click again to stop"), the same clock the tray carries —
  so the maximum recording length is visible on the control that never leaves
  the screen. While the second source is running the label names it
  ("Recording system audio 1:12…"), because an icon that just says
  "Recording…" cannot tell you which of the two takes it is about.
  Optionally shows the transcript in a bubble — after each recording and/or
  as an experimental **live preview while you speak**. It remembers the
  **monitor** you drag it to, not just a screen coordinate, so it comes back
  there after a restart, after a reboot that brings the second screen up late,
  and after a monitor is unplugged and reconnected. A built-in watchdog checks
  every 5 seconds that the icon is actually on screen and brings it back
  automatically if Windows drops it (display sleep, monitor or resolution
  changes, explorer restarts) — including re-applying the **always-on-top**
  state that Windows silently takes away, which is the usual reason the icon
  seems to have vanished when it is really just buried behind another window
  (switchable in Settings → Overlay). **Reset icon position** — in its right-click
  menu, in the tray menu (**Reset floating icon position**) and on the Overlay
  settings page — brings it back from wherever a drag or a rearranged monitor
  left it. The tray entry is the one that still works when the icon itself
  cannot be found or hit any more. While something is downloading — the Whisper
  model on first use, or an app update — the icon turns into a **progress ring
  with the percentage in the middle**, so a multi-minute first download is
  visible at a glance instead of behind a notification that has long since
  disappeared. When the total size cannot be determined it shows a rotating
  sweep instead of a made-up number. The tray tooltip carries the same line,
  for when the floating icon is switched off.
- **System tray app** — runs quietly in the background; icon shows
  idle / recording / transcribing state and names your configured hotkey
  ("Idle — press Ctrl+Alt+Space to record"), so a forgotten combination is a
  hover away. While you dictate it **counts the take up** ("Recording 1:12… press
  Ctrl+Alt+Space to stop"), so you can see how long you have been speaking
  against the maximum recording length. **Record system audio** sits next to
  **Start recording**, so the second source is one click away with or without
  a hotkey of its own, and it names the source it stops
  ("Stop recording system audio (insert text)") — with two start entries in
  one menu, a bare "Stop recording" would not say which take it ends.
  **Pause hotkey** — in this menu and in
  the floating icon's right-click menu, so it stays in reach with the tray icon
  switched off — suspends the global combination for a game or another app that
  wants the same keys; your hotkey is kept, and the pause is forgotten on the
  next start.
  Only one instance runs at a time:
  starting the app again simply brings the running instance's settings
  window to the front.
- **Transcript history** — the transcribed text of each recording is kept
  locally (never the audio) so you can copy it again from **Settings → History**
  if a paste is lost. Searchable (`Ctrl+F` puts the caret straight into the
  search field) by word **or by date** — a term made of digits, `-` and `:`
  such as `2026-09-05` or `14:` also matches the date and time each row shows,
  so a whole day's dictations are one search away. Bounded in size, and easy to switch off or
  clear — and a single transcript you would rather not keep can be deleted on
  its own, without losing the rest. **Export…** saves the listed transcripts
  (the search filter applies) to a text file, and **Copy all** puts that same
  set on the clipboard as one block — so a searched-down handful of dictations
  goes straight into a mail or a note without a detour through a file.
  The newest one is a single click away: **Copy last transcript** in the
  tray menu and in the floating icon's right-click menu puts it straight back
  on the clipboard — and a **Recent transcripts** submenu in both of those
  menus lists the last five, so the one before last is a click away too,
  whichever of the two icons you work from.
- **Home hub** — the main window opens on a **Home page**: the live recording
  state with a big **Start/Stop** button (red while recording), your hotkey
  shown as key caps, at-a-glance cards for the active engine/model, language
  and microphone, quick actions into the right settings page, and your most
  recent transcripts with one-click copy. While you dictate the headline
  **counts the take up** ("Recording 1:12 — speak now"), the same clock the
  tray and the floating icon carry, right above the card naming the maximum
  recording length. Once a **system audio** hotkey is set, a second row of key
  caps appears and both rows are captioned with the source they start, so the
  two combinations are never confused for one another.
- **Settings window** — language, model, hotkey (with a press-the-keys
  **shortcut picker**), microphone, insert mode, notifications, autostart,
  model download folder and more — with explanatory tooltips on every option.
- **Built-in self-tests & status** — test the hotkey, the microphone (with a
  live level bar), download the model ahead of time and run a 5-second
  end-to-end transcription test, all from the settings window before the first
  real dictation. Every running test or download has a **Cancel** button, and
  a **status card** shows what was actually detected: NVIDIA GPU (CUDA) found?
  OpenVINO installed and which Intel devices (GPU/NPU/CPU)? Selected model
  already downloaded?
- **Choose your spoken language** for better accuracy, or let Whisper
  auto-detect it. Swap the model (tiny → large-v3, distil, turbo, a
  **German fine-tuned turbo**, or any CTranslate2 model from Hugging Face).
- **Hardware acceleration** — NVIDIA GPUs via CUDA (default backend), **Intel
  GPUs and NPUs** ("AI Boost" in Core Ultra) via the **OpenVINO** backend —
  with automatic CPU fallback whenever a device is unavailable. For maximum
  speed there is a third engine: **Parakeet** (NVIDIA Parakeet TDT via ONNX),
  which transcribes many times faster than Whisper in 25 languages.
- **Optional assistant post-processing** — pipe the transcript through any
  OpenAI-compatible API (local **Ollama**, LM Studio, llama.cpp, OpenWebUI, or a
  hosted service) with a **freely editable system prompt** (a sensible default
  is built in, one click restores it — and it asks first if you have edited
  the prompt, because nothing else keeps a copy of what you wrote). **Two
  profiles, one connection:** _Microphone dictation_ and _System audio_ each
  have their own switch and their own prompt (the second one also an optional
  model override), because a dictation wants punctuation and filler removal
  while a recorded meeting wants minutes or a summary.
- **Mute other apps while dictating** — optionally mute **Discord, Zoom, Slack,
  Teams, OBS** (or any app with a global mute keybind) for exactly the duration
  of a recording, so your dictation isn't transmitted into a voice call, then
  restored when you stop. Works via the app's own **push-to-mute / toggle-mute**
  keybind — no API or account needed — and ready-made presets bring each app's
  documented keybind along, so there is nothing to look up.
- **First-run setup wizard** — the very first launch walks you through the
  essentials (hotkey, language, model, backend + device, microphone, startup
  behaviour); everything stays changeable in Settings later.
- **Autostart with Windows** (configurable; Linux and macOS equivalents
  included). The entry survives updates: the in-app updater keeps the
  executable's path, and if you replace the exe by hand — a manually downloaded
  build, a rename, a move — the next start repairs the registered path instead
  of silently booting the old version. It also **reports back**: the settings
  page shows the command the system actually has on file, an entry Windows
  switched off in _Task Manager → Startup apps_ is named as such (and switched
  back on when you save), and a registration that fails says so instead of
  looking fine until the next reboot.
- **Cross-platform code base** — Windows first; Linux and macOS are prepared
  (see [platform notes](#platform-notes)).

## Download (Windows)

Grab the latest `ListenToMe-<date>-<hhmm>-win64.exe` from the
[**Releases**](https://github.com/fo0/listen-to-me/releases) page and run it —
portable single file, no installation. The app appears in the system tray.

> Windows SmartScreen may warn because the binary is not code-signed:
> choose _More info → Run anyway_.

## How it works

1. Put the cursor where the text should go (editor, browser, chat, form, …).
2. Press the hotkey — the tray icon turns **red**, recording starts.
3. Speak.
4. Press the hotkey again — the icon turns **orange** while the local Whisper
   model transcribes (and the assistant cleans up, if enabled).
5. The text is inserted at the cursor. Done.

Clicking the tray icon (once or twice) opens the app window — recording is
started by the hotkey, or from the tray menu's **Start recording**.

A **second hotkey** does the same for what the computer _plays_ instead of what
the microphone hears — see
[Recording system audio](#recording-system-audio-a-call-a-meeting-a-video). It
is off until you set it up.

## Settings

On the very first launch a short **setup wizard** collects the essentials —
recording hotkey, spoken language, speech model, backend + device, microphone
and startup behaviour. Everything it sets (and much more) can be changed later
here:

Click the tray icon, or right-click it → **Settings…**

The window footer shows the installed version next to a **GitHub** and a
**Releases** link — the latter goes straight to the download page, which is
what you need when a build can't update itself.

| Tab              | Options                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Home**         | The entry hub: live recording state (counting the running take up, "Recording 1:12 — speak now") with **Start recording / Stop & insert** (and **Cancel**) buttons, the hotkey rendered as key caps, **at-a-glance cards** (engine & model, language, microphone — click one to jump to its settings page), **quick actions** (change hotkey, model & engine, test microphone, overlay, updates, help) and the **most recent transcripts** with a Copy button each                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **General**      | Hotkey (type it or use the **“Change…” key picker**), **Test hotkey** (confirms the combination actually arrives — recording stays paused), hotkey mode (**toggle** or **hold/push-to-talk**) — with a pointer to the second recording hotkey, which lives on the Audio page next to the device and the length cap it belongs to — insert mode (paste/type), **live typing** (experimental — type stable parts of the transcript while you speak; append-only, plain text only, pauses while a modifier key is held; skips the assistant; faster-whisper backend only, and with a hold hotkey it needs a modifier-free key such as F9 — a hint under the option says so, and Save refuses a combination that would leave it off), **copy the transcript to the clipboard** (only when inserting fails / always / never), clipboard restore, notifications, beep (Windows only — greyed out elsewhere), **autostart** (with a status line showing what the system actually has registered), **start minimized to tray** (off by default — normally the settings window opens on launch), **ignore SSL certificate errors** (off by default — only for corporate proxies with self-signed certificates, see Troubleshooting), **Reset to factory settings** (asks first, then puts every setting back to the value it shipped with and reopens the first-run setup wizard — transcript history and downloaded models are kept)                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Engine**       | **Backend** (faster-whisper = NVIDIA CUDA / CPU, OpenVINO = Intel GPU / NPU / CPU, **Parakeet** = fastest engine, NVIDIA CUDA / CPU), **model** (each preset annotated with its advantage; “Custom model id…” takes any CTranslate2 model from Hugging Face) and **spoken language**, device (auto/CPU/CUDA resp. auto/CPU/GPU/NPU), **precision** (per backend: the CTranslate2 compute type, the OpenVINO model precision or the Parakeet ONNX variant), **beam size** (faster-whisper: 5 = best accuracy, 1 = greedy ≈ 1.5–2× faster), VAD silence filter (faster-whisper only), **Detected hardware & model status** card (NVIDIA GPU/CUDA found? OpenVINO installed and which Intel devices? Is the selected model already downloaded? **Running on** — the device and precision the loaded model actually uses, i.e. what `auto` resolved to — with a **Refresh status** button, updates automatically when you change model/backend), **model download folder** (view, change, open — defaults to the Hugging Face cache), **Download / load model** (fetch the selected model now instead of on the first recording — with a byte-accurate progress bar, mirrored onto the floating icon and the tray) and **Test transcription** (record 5 s and transcribe them with the current values — result shown inline, nothing inserted), both cancellable with a **Cancel** button, initial prompt (domain vocabulary hint), **text replacements** (`heard => written` rules applied to every finished transcript, so a word this speaker always gets wrong is corrected before it reaches the cursor) and **Silent takes (invented phrases)** — the on/off switch and the editable list of phrases Whisper invents for a recording with no speech, with a line under the field saying how many are active and which lines were thrown away, plus _Reset to default…_ |
| **Audio**        | **Microphone:** device selection, **Test microphone** (3-second check with a live level bar, a clear verdict — works / too quiet / no signal — and a **Cancel** button), maximum recording length. **System audio:** the hotkey for recording what the computer plays (**empty = this source is off**), its hotkey mode, the **device** list and its own maximum recording length. The list opens with **“Automatic — the best loopback device, or nothing”** and is then split into two labelled groups: _“Loopback devices — these record what the computer plays”_ (each row named after the **output** it records, plus the name fragment that identified it) and _“Other input devices — microphones, not what the computer plays”_; when the first group is empty it keeps its heading and shows a _“None found — nothing here can record the computer's output”_ row. **Refresh** re-scans and reports what it found (“3 loopback ✓” / “None found”), so a device you just enabled shows up without a restart. The hint under the card says what the feature does, **names the outputs that no loopback device covers** (up to three, then “and N more”) with the fix for your platform, and when there is no loopback device at all it leads with a warning that a take would be refused                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Overlay**      | Floating icon on/off, **keep it above all other windows** (on by default — Windows strips that state behind the app's back, which makes the icon look like it vanished when it is only buried), transcript bubble after each recording, experimental **live transcript preview while recording**, preview display time, **Reset position** (moves the icon back to the bottom right — also in the icon's own right-click menu — for when it ended up half off the screen or on a monitor you have since rearranged)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **Integrations** | **Mute other apps while recording** (Discord, …): master switch (off by default) plus a list of apps, each with an enabled toggle, name, **mute keybind** (with the same key picker) and **mode** (_push-to-mute_ / _toggle mute_). Add or remove apps freely — **Remove…** asks first once an entry carries a name or a keybind, so a mis-click doesn't cost a combination you had to look up in the other app's settings.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **Assistant**    | **Connection** (shared by both profiles): API base URL, model, API key, temperature, **request timeout** (how long a dictation is held back waiting for the answer), **Test connection** (sends one sample sentence and shows the reply — verifies the endpoint before a dictation depends on it, with a **Cancel** button so a wrong URL or a stopped endpoint doesn't hold the page for the whole request timeout). Then one card per recording source — **Microphone dictation** and **System audio** — each with its own on/off switch and its own **system prompt** (editable, with _Reset to default…_ — it asks first once you have edited the prompt, since nothing else keeps a copy of what you wrote); the system-audio card also takes an optional **model override** (empty = the model from Connection)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **History**      | Recent **transcribed text** kept locally (never the audio), each with a **Copy** button so a lost transcript can be recovered and a **Delete** button that removes just that one entry; a **search field** (`Ctrl+F`) narrows the list to the transcripts containing your words (any order, case-insensitive) and shows how many of them matched — a term made only of digits, `-` and `:` (e.g. `2026-09-05`, `14:`) also matches the date and time on each row; **Export…** writes the listed transcripts (the search filter applies) to a text file and **Copy all** puts the same set on the clipboard as one block; toggle history on/off, how many entries to keep, and **Clear history**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **Updates**      | Installed version, **check on startup** toggle, include pre-releases, **Check now**, changelog per release and **Download & install** (frozen Windows build) with progress — **download size** next to each release and in the confirmation, and "42.0 MB of 198.0 MB" while it runs — and a **Cancel download** button. The new build is written over the running executable — same folder, same file name — so shortcuts, pinned taskbar entries and the autostart entry keep working; the dated `ListenToMe-…-win64.exe` name is only how the download is published                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Help**         | Built-in **troubleshooting** page (GPU/CUDA errors, Intel GPU/NPU setup, hotkey, text insertion, model storage, assistant setup) with clickable links — also on the tray menu. **Find in help** (`Ctrl+F`) searches the whole page, so an error message you can read on screen is enough to reach the right topic; the search wraps around at the end                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

Every option has a hover tooltip explaining what it does. The sidebar groups
the pages into **Home**, **Settings** and **More** (History/Updates/Help).
**Save**
applies everything immediately and closes, **Apply** applies without closing,
**Close** leaves the window (the app keeps running in the tray), and closing
with unsaved changes asks whether to save or discard them. The window can be
minimized and maximized like any main window.

### Push-to-talk (hold) mode notes

In **hold** mode recording runs only while the hotkey is held. Two things are
worth knowing:

- **Pick a modifier chord** (e.g. `Ctrl+Alt+Space`). The key picker enforces at
  least one modifier for printable keys (bare function keys like `F9` are also
  allowed). It also accepts **modifier-only chords** (e.g. `Ctrl+Alt`) — hold the
  modifiers and click **OK** to confirm, since there is no final key to auto-apply
  them. While the combo is held it is _not_ suppressed from the focused
  application on Linux/macOS, so a plain printable key would type into your
  document — a modifier chord avoids that. (Toggle mode only taps the combo, so
  this doesn't apply there.)
- **If a key release is missed** (some window managers/IMEs grab combos such as
  `Cmd+Space`, or focus changes mid-hold), the recording can't see that you let
  go. It still stops when you click the floating icon or the tray _Stop
  recording_ entry, or automatically at the _maximum recording length_.
- **Before the maximum recording length ends a take**, a notification says how
  many seconds are left, so a long dictation can be wrapped up instead of being
  cut off mid-sentence. (Only when the configured cap is comfortably longer
  than that warning — a deliberately short cap is not a surprise.)

Configuration is a plain JSON file (tray → _Open config folder_):
`%APPDATA%\ListenToMe\config.json` on Windows,
`~/.config/listen-to-me/config.json` on Linux,
`~/Library/Application Support/ListenToMe/config.json` on macOS.

That same folder holds everything else the app keeps on disk, so it is the one
place to look when reporting a bug or cleaning up:

| File                              | What it is                                                                                                                                                                                           |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config.json`                     | Your settings — the only file that may contain a secret (the optional assistant API key). Don't share it unredacted                                                                                  |
| `config.json.bad`                 | Only after a read error: the previous `config.json`, moved aside on the next save so a corrupt or locked file is never overwritten. The app says so on start and runs on the defaults until you save |
| `history.json`                    | The transcript **text** of recent recordings (never audio). Switch it off or clear it in Settings → History                                                                                          |
| `listen-to-me.log` (+ `.1`, `.2`) | Rotating log, 512 KB per file — the first thing to attach to a bug report                                                                                                                            |
| `instance.lock` _(Linux/macOS)_   | The single-instance lock; on Windows a named mutex does the same job without a file                                                                                                                  |

Nothing is written anywhere else — downloaded models live in the Hugging Face
cache (see [Choosing a Whisper model](#choosing-a-whisper-model)), not here.

### config.json reference

Every option above is stored under one of these keys. The file is written with
all defaults on first launch, and unknown/missing keys fall back to the default,
so you only need to keep what you changed. Editing it by hand is optional — the
settings window writes the same keys.

A value of the wrong type falls back to the default (with a line in the log).
The numeric keys additionally carry the range the settings window accepts, noted
below: a hand-edited value outside it keeps working, but opening that settings
page and saving snaps it into range.

| Key                                             | Default                       | What it does                                                                                                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hotkey`                                        | `"<ctrl>+<alt>+<space>"`      | Global recording hotkey, pynput syntax                                                                                                                                                                                                                                                                                                                                                                                      |
| `hotkey_mode`                                   | `"toggle"`                    | `toggle` = press to start/stop, `hold` = push-to-talk                                                                                                                                                                                                                                                                                                                                                                       |
| `language`                                      | `"auto"`                      | Spoken language code, `auto` = detect                                                                                                                                                                                                                                                                                                                                                                                       |
| `model`                                         | `"small"`                     | Whisper preset or any CTranslate2 model id                                                                                                                                                                                                                                                                                                                                                                                  |
| `model_dir`                                     | `null`                        | Model download folder; `null` = Hugging Face cache                                                                                                                                                                                                                                                                                                                                                                          |
| `backend`                                       | `"faster-whisper"`            | Engine: `faster-whisper`, `openvino` or `parakeet`                                                                                                                                                                                                                                                                                                                                                                          |
| `device`                                        | `"auto"`                      | Device for faster-whisper/Parakeet: `auto`/`cpu`/`cuda`                                                                                                                                                                                                                                                                                                                                                                     |
| `compute_type`                                  | `"auto"`                      | CTranslate2 precision: `auto` (= `int8` on the CPU, `float16` on a GPU) / `int8`/`int8_float16`/`float16`/`float32`                                                                                                                                                                                                                                                                                                         |
| `openvino_device`                               | `"auto"`                      | Intel device: `auto`/`cpu`/`gpu`/`npu` (`auto` prefers GPU → NPU → CPU)                                                                                                                                                                                                                                                                                                                                                     |
| `openvino_precision`                            | `"int8"`                      | OpenVINO model precision: `int8`/`fp16`/`int4`                                                                                                                                                                                                                                                                                                                                                                              |
| `parakeet_quantization`                         | `"int8"`                      | Parakeet ONNX variant: `int8`/`fp32`                                                                                                                                                                                                                                                                                                                                                                                        |
| `input_device`                                  | `null`                        | Microphone index; `null` = system default                                                                                                                                                                                                                                                                                                                                                                                   |
| `max_seconds`                                   | `300`                         | Hard cap for a single recording, in seconds (a notification warns 30 s before it ends the take). Settings range: `10`–`3600`                                                                                                                                                                                                                                                                                                |
| `system_audio.hotkey`                           | `""`                          | Second global hotkey, for recording what the computer plays; **empty = this source is off** — see [Recording system audio](#recording-system-audio-a-call-a-meeting-a-video)                                                                                                                                                                                                                                                |
| `system_audio.hotkey_mode`                      | `"toggle"`                    | `toggle` / `hold` for that second hotkey — independent of `hotkey_mode` above                                                                                                                                                                                                                                                                                                                                               |
| `system_audio.device`                           | `null`                        | Index of the loopback/monitor **input** device to record from; `null` = auto-pick the best candidate found                                                                                                                                                                                                                                                                                                                  |
| `system_audio.max_seconds`                      | `900`                         | Hard cap for one system-audio recording, in seconds — higher than `max_seconds` because a recorded meeting is not a dictation. Settings range: `10`–`3600`                                                                                                                                                                                                                                                                  |
| `system_audio.bundled_portaudio`                | `true`                        | Windows exe only: use the PortAudio the exe ships (the one built with WASAPI loopback). `false` falls back to the binary inside the `sounddevice` wheel — the way back if a bundled build turns out worse than that one; it costs system-audio recording on Windows and nothing else. No control for it in the settings window, on purpose — see [Recording system audio](#recording-system-audio-a-call-a-meeting-a-video) |
| `injection_mode`                                | `"paste"`                     | Insert via `paste` (clipboard) or `type` (simulated typing)                                                                                                                                                                                                                                                                                                                                                                 |
| `live_typing`                                   | `false`                       | Experimental live typing while recording (faster-whisper only)                                                                                                                                                                                                                                                                                                                                                              |
| `clipboard_copy`                                | `"on_failure"`                | Also copy the transcript to the clipboard: `on_failure` (only when inserting at the cursor fails), `always` (every transcript — suppresses `restore_clipboard`) or `off`                                                                                                                                                                                                                                                    |
| `restore_clipboard`                             | `true`                        | Restore the previous clipboard content after a paste                                                                                                                                                                                                                                                                                                                                                                        |
| `notifications` / `beep`                        | `true` / `true`               | Desktop notifications and the audible start/stop cue (the beep is Windows only)                                                                                                                                                                                                                                                                                                                                             |
| `autostart`                                     | `false`                       | Start with the OS                                                                                                                                                                                                                                                                                                                                                                                                           |
| `start_in_tray`                                 | `false`                       | Start silently into the tray instead of opening the window                                                                                                                                                                                                                                                                                                                                                                  |
| `initial_prompt`                                | `""`                          | Whisper initial prompt (domain vocabulary hint, not an instruction)                                                                                                                                                                                                                                                                                                                                                         |
| `replacements`                                  | `""`                          | Find/replace rules applied to every finished transcript, one `find => replace` per line — see [Text replacements](#text-replacements)                                                                                                                                                                                                                                                                                       |
| `filler_filter`                                 | `true`                        | Drop a transcript that came out of a **silent or too quiet** recording and is **nothing but** a phrase Whisper invents for a take with no speech. A take that carried real speech is never filtered, however it reads — see [Silent takes and invented phrases](#silent-takes-and-invented-phrases)                                                                                                                         |
| `filler_phrases`                                | _(18 built-in phrases)_       | The list those transcripts are matched against, one phrase per line (`#` comments allowed); consulted only for a take whose own audio was silent or too quiet; editable in Settings → Engine                                                                                                                                                                                                                                |
| `vad_filter`                                    | `true`                        | VAD silence filter (faster-whisper only)                                                                                                                                                                                                                                                                                                                                                                                    |
| `beam_size`                                     | `5`                           | Decoding beam size; `1` = greedy, ≈1.5–2× faster (faster-whisper only). Settings range: `1`–`10`                                                                                                                                                                                                                                                                                                                            |
| `history_enabled` / `history_max`               | `true` / `200`                | Keep a local transcript history (never audio), and how many entries. Settings range for `history_max`: `10`–`5000`                                                                                                                                                                                                                                                                                                          |
| `update_check_on_start` / `include_prereleases` | `true` / `false`              | Check GitHub Releases on launch, and whether pre-releases count                                                                                                                                                                                                                                                                                                                                                             |
| `insecure_ssl`                                  | `false`                       | Skip TLS verification for every connection — model downloads, assistant **and updates**; corporate proxies only                                                                                                                                                                                                                                                                                                             |
| `overlay.enabled`                               | `true`                        | The floating always-on-top status icon                                                                                                                                                                                                                                                                                                                                                                                      |
| `overlay.always_on_top`                         | `true`                        | Keep the icon above all other windows and re-apply that every few seconds (Windows silently strips the always-on-top state). Off = other windows may cover it                                                                                                                                                                                                                                                               |
| `overlay.show_preview`                          | `true`                        | Show the transcript in a bubble after a recording                                                                                                                                                                                                                                                                                                                                                                           |
| `overlay.live_preview`                          | `false`                       | Experimental rolling preview while you speak (costs CPU)                                                                                                                                                                                                                                                                                                                                                                    |
| `overlay.preview_seconds`                       | `6`                           | How long the finished transcript stays visible. Settings range: `2`–`60`                                                                                                                                                                                                                                                                                                                                                    |
| `overlay.x` / `overlay.y`                       | `null`                        | Saved icon position as desktop coordinates; `null` = bottom right                                                                                                                                                                                                                                                                                                                                                           |
| `overlay.screen`                                | `null`                        | The monitor the icon was left on (EDID identity, else the device name)                                                                                                                                                                                                                                                                                                                                                      |
| `overlay.rel_x` / `overlay.rel_y`               | `null`                        | Saved icon position within that monitor — what brings it back to the right screen after a restart                                                                                                                                                                                                                                                                                                                           |
| `assistant.enabled`                             | `false`                       | Optional LLM post-processing of the transcript                                                                                                                                                                                                                                                                                                                                                                              |
| `assistant.base_url`                            | `"http://localhost:11434/v1"` | OpenAI-compatible endpoint                                                                                                                                                                                                                                                                                                                                                                                                  |
| `assistant.api_key`                             | `""`                          | API key — stays in this local file; empty for Ollama                                                                                                                                                                                                                                                                                                                                                                        |
| `assistant.model`                               | `"llama3.2"`                  | Model name sent to that endpoint                                                                                                                                                                                                                                                                                                                                                                                            |
| `assistant.system_prompt`                       | _(built-in default)_          | Cleanup prompt, editable in Settings (one click restores it, asking first once you have edited it)                                                                                                                                                                                                                                                                                                                          |
| `assistant.temperature` / `assistant.timeout`   | `0.2` / `120`                 | Sampling temperature and request timeout in seconds — both editable in Settings → Assistant. Ranges: `0.00`–`2.00` / `5`–`600`                                                                                                                                                                                                                                                                                              |
| `assistant.system_audio.enabled`                | `false`                       | Post-process **system-audio** transcripts too. Independent of `assistant.enabled`, which is the microphone profile; the connection above is shared by both                                                                                                                                                                                                                                                                  |
| `assistant.system_audio.model`                  | `""`                          | Model for that profile only; empty = `assistant.model`                                                                                                                                                                                                                                                                                                                                                                      |
| `assistant.system_audio.system_prompt`          | _(built-in default)_          | Prompt for recorded playback — cleans the transcript up; meant to be replaced with what you want out of a meeting (minutes, a summary, a translation)                                                                                                                                                                                                                                                                       |
| `integrations.mute_while_recording`             | `false`                       | Master switch for muting other apps while recording                                                                                                                                                                                                                                                                                                                                                                         |
| `integrations.targets`                          | 5 presets, all disabled       | Per-app entries: `name`, `enabled`, `mode` (`hold`/`toggle`), `hotkey`                                                                                                                                                                                                                                                                                                                                                      |

### Choosing a Whisper model

| Model                                            | Size            | Notes                                                                                                    |
| ------------------------------------------------ | --------------- | -------------------------------------------------------------------------------------------------------- |
| `tiny` / `base`                                  | ~75–140 MB      | fastest, okay for short commands                                                                         |
| `small` _(default)_                              | ~460 MB         | good balance for dictation                                                                               |
| `medium`                                         | ~1.5 GB         | noticeably better, slower on CPU                                                                         |
| `large-v3` / `large-v3-turbo`                    | ~3 GB / ~1.6 GB | best quality; turbo is much faster                                                                       |
| `jimmymeister/whisper-large-v3-turbo-german-ct2` | ~1.6 GB         | **German only** — turbo fine-tuned on German speech: noticeably better German accuracy at the same speed |
| `distil-large-v3`                                | ~1.5 GB         | near large quality, faster (English-focused)                                                             |
| `distil-large-v3.5`                              | ~1.5 GB         | English only — newer distil, faster than turbo                                                           |

`.en` variants are English-only and slightly more accurate for English. The
model dropdown itself is read-only; to use any other CTranslate2 model id from
Hugging Face, pick **Custom model id (Hugging Face)…** at the bottom of the
list and enter the id in the dialog.
Setting your **spoken language** explicitly (instead of auto-detect) improves
both accuracy and speed.

Models are downloaded on first use into the **Hugging Face cache**
(`~/.cache/huggingface/hub`, on Windows `C:\Users\<you>\.cache\huggingface\hub`)
— _not_ into the config folder. The settings window (Engine tab) shows the
effective folder and lets you change it or open it in the file manager
(`model_dir` in `config.json`).

If you already relocate the Hugging Face cache with the standard environment
variables, the app follows them: `HF_HUB_CACHE` (or `HUGGINGFACE_HUB_CACHE`) is
used as-is, otherwise `HF_HOME` plus `/hub`, otherwise the default path above. A
`model_dir` set in `config.json` (or the settings window) overrides all of them.

### Text replacements

Whisper mis-hears the same words the same way every time — a product name, a
colleague's surname, an acronym. The initial prompt above only _biases_
recognition; text replacements are the deterministic second half: what the
recognizer got wrong anyway is corrected before the text reaches the cursor.

Settings → Engine → **Text replacements**, one rule per line:

```text
# what was heard  =>  what should be written
cuber netes => Kubernetes
posgres => PostgreSQL
tee ess => TypeScript
```

- **Case is ignored and whole words are matched**, so one rule catches the word
  at the start of a sentence as well as inside it, and never eats the middle of
  a longer word (`scala => Scala` leaves `scalable` alone).
- **The replacement is inserted exactly as written**, so the spelling you typed
  is the spelling you get.
- A search term may be several words (`cuber netes => Kubernetes`). An **empty
  right-hand side deletes the word** — useful for a filler you never want
  written out.
- Rules are applied **in the order they are written**, after the assistant, so
  your rules are the final word. Lines starting with `#` are comments; a line
  without `=>` is ignored instead of breaking the rest.
- **The line under the field says what actually took effect** — how many rules
  are active, and which lines were thrown away and why (`2 rules active · 1
line ignored: line 4 has no “=>”.`). An arrow typed as `->`, or a rule with
  nothing on its left-hand side, is otherwise indistinguishable from one that
  works until a dictation comes out uncorrected.
- Not applied while `live_typing` is on: that text is already at the cursor and
  append-only typing cannot take it back.

### Silent takes and invented phrases

Press the hotkey, say nothing, press it again — and a sentence you never spoke
lands at the cursor: "Vielen Dank.", "Thank you.", "Untertitelung des ZDF,
2020".

**That phrase does not come from this app.** It comes from the model. Whisper
was trained on subtitled video, and in subtitles a stretch without speech is
usually captioned with the clip's closing line — a thank-you, a credit, a
`[Musik]` annotation. So when a recording contains no speech, the most likely
continuation the model has ever seen for silence is exactly that phrase, and it
writes it down with full confidence. Which is also why the two guards in front
of it don't help: the VAD silence filter keeps a chunk as soon as there is room
noise or a keyboard click, and Whisper's own no-speech threshold only drops a
segment that the decoder itself was unsure about.

Settings → Engine → **Silent takes (invented phrases)** catches it at the last
possible moment, on the finished transcript:

```text
# one phrase per line, "#" starts a comment
Vielen Dank
Thank you
Untertitelung des ZDF, 2020
[Musik]
```

- **The recording decides, not the wording.** A transcript is only dropped
  when the take's own audio was **silent or too quiet** — the same measurement
  that decides whether an empty transcript is reported as a dead microphone or
  as unrecognized speech. A take that carried real speech is never filtered,
  however it reads: say "Vielen Dank." into a working microphone and it lands
  at the cursor like any other dictation. The phrase list alone cannot tell an
  invented "Vielen Dank." from a dictated one — the audio can, so the audio is
  what gets asked.
- **Only a whole transcript is dropped.** "Vielen Dank" is a sentence people
  really dictate, so a phrase that merely _occurs_ in a longer text is never
  touched — "Vielen Dank für die Datei" is inserted exactly as spoken.
- **Case, punctuation and whitespace are ignored** around the phrase, so the
  base form is enough: `Vielen Dank` also matches `vielen dank!` and
  `„Vielen Dank!“`. No need to list both.
- **Brackets count**, and that is deliberate: `[Musik]` catches the annotation
  the model writes for a passage of music, while somebody dictating the word
  `Musik` keeps their word. Each bracketing style therefore needs its own line
  — the defaults ship `[Musik]` and `(Musik)` separately.
- A transcript with **no letter or digit** in it at all (`...`, `♪♪`, a lone
  dash) needs no entry in the list — it counts as one of these phrases by
  itself. There is nothing there to insert either way.
- A dropped take is reported exactly like a recording with no speech: nothing
  is inserted, and nothing goes into the history — an honest report, because
  the audio check established that much before anything was dropped.
- **18 phrases ship by default**, German and English. The list is yours: add
  what your model invents, remove what you actually dictate, and
  _Reset to default…_ puts the shipped list back. The line under the field says
  how many phrases are active and which lines were thrown away.
- Skipped while `live_typing` is on — that text is already at the cursor, and
  append-only typing cannot take it back.
- Switch the whole thing off with `filler_filter` if you would rather see
  whatever the model produced for a silent take.

### Recording system audio (a call, a meeting, a video)

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

#### The recording device — what it takes per platform

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
> [ADR-0009](docs/adr/0009-system-audio-is-captured-through-a-loopback-input-device.md);
> why the Windows exe now brings its own PortAudio so that such a device always
> exists:
> [ADR-0010](docs/adr/0010-the-windows-release-ships-its-own-portaudio.md).

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

### Assistant (optional LLM cleanup)

Off by default. When enabled, the raw transcript is sent to an
OpenAI-compatible `/chat/completions` endpoint and the _answer_ is inserted
instead. The default configuration targets a local [Ollama](https://ollama.com):

```jsonc
"assistant": {
  "enabled": true,
  "base_url": "http://localhost:11434/v1",
  "api_key": "",
  "model": "llama3.2",
  "system_prompt": "…",   // freely editable in the settings window
  "system_audio": {       // the second profile — see below
    "enabled": false,
    "model": "",          // empty = the shared model above
    "system_prompt": "…"
  }
}
```

The default system prompt fixes punctuation, removes filler words and applies
dictated formatting ("new paragraph", "bullet list") without translating or
rewriting content. Adapt it however you like — e.g. "always answer in formal
German" or "translate everything to English".

**Two profiles, one connection.** A dictation and a recorded meeting want
opposite things from the assistant, so the page has one card per recording
source — **Microphone dictation** and **System audio** — each with its own
switch and its own prompt. What they share is the connection: one endpoint, one
API key, one temperature, one timeout. The system-audio card additionally takes
a **model override** (leave it empty to use the shared model — one endpoint
usually serves one). Its default prompt only tidies the transcript up; it is a
starting point meant to be replaced by whatever you actually want out of a
recorded meeting — minutes, a summary, a translation. The two switches are
independent: turning the assistant on for dictations does not turn it on for
system audio, and a profile whose prompt is empty stays off.

**Test connection** on the Assistant page sends one short sample sentence to the
endpoint with the values currently entered (no _Save_ needed) and shows what
comes back. Use it before you rely on the assistant: it runs after a dictation,
so a wrong URL, an unknown model name or a stopped Ollama would otherwise only
show up once you have already spoken. The reply is shown, not just an "OK" — an
endpoint can answer perfectly while the model or the prompt returns something
you would not want inserted. A running test can be called off with **Cancel** —
the wait is bounded by the request timeout below, which goes up to ten minutes,
and a test against an endpoint that is simply not there should not hold the page
for that long. The request itself cannot be recalled once sent; it is left to run
out on its own and its answer is discarded.

**Request timeout** decides how long a finished dictation is held back waiting
for the answer before the raw transcript is inserted instead. Raise it if your
local model is slow to respond, lower it so an unreachable endpoint fails fast
rather than delaying every recording by two minutes.

### Mute other apps while dictating (Discord, …)

If you dictate while a voice call is open, your speech would normally be picked
up by that call too. The **Integrations** page can mute other apps for exactly
the time you are recording and restore them when you stop.

It uses the target app's own **global mute keybind** — no API, account or
vendor approval is required, so it works with anything that exposes such a
keybind. The **Add app** menu comes with the common ones ready-made, each with
that app's documented mute keybind already filled in:

| Preset              | Keybind                      | Works from another window?                                                                                     |
| ------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Discord**         | `Ctrl+Shift+M` (Toggle Mute) | ✅ Yes, nothing to set up                                                                                      |
| **Zoom**            | `Alt+A`                      | Only after ticking _Settings → Keyboard Shortcuts → Enable Global Shortcut_                                    |
| **Slack**           | `Ctrl+Shift+Space` (huddle)  | Only after enabling _Preferences → Audio & video → allow keyboard shortcut to mute_                            |
| **Microsoft Teams** | `Ctrl+Shift+M`               | ❌ Teams reacts only while focused — no global keybind exists. On Windows 11 try `Win+Alt+K` (`<cmd>+<alt>+k`) |
| **OBS Studio**      | —                            | OBS ships no default; set one under _Settings → Hotkeys_ at your Mic/Aux source, then copy it here             |

Every preset ships **disabled** and repeats its caveat in the app, right under
the row — because a keybind an app only honours while it has focus would do
nothing at all here, silently. Discord is the one that just works.

To set an app up manually, the same combination has to exist in both places:

1. In the app, bind a key to mute. In Discord: **User Settings → Keybinds → Add
   a Keybind** and choose either **Push to Mute** or **Toggle Mute**, then press
   your combination (e.g. `F9`).
2. In Listen To Me, open **Settings → Integrations**, enable the app, set the
   **same** combination (use the _Change…_ picker) and pick the matching **mode**:
   - **Push-to-mute (hold)** — the key is held down for the whole recording.
     Stateless and self-correcting, so it can never leave you stuck muted.
     Recommended, and the natural match for Discord's _Push to Mute_.
   - **Toggle mute** — the key is tapped once when recording starts and once
     when it stops. Match this to a _Toggle Mute_ keybind.

Prefer a modifier chord or a function key so the combination stays inert in the
document you're dictating into. A mute keybind identical to your recording
hotkey is refused; one that merely shares keys with it (Discord's default
`Ctrl+Shift+M` next to the default `Ctrl+Alt+Space`) is fine in **toggle**
mode — the keybind is sent a moment after you let the hotkey go, because the
target app reads the same keyboard you are still holding. In **hold** mode the
start tap has to go out _while_ you hold the hotkey, so a toggle target whose
keybind shares a key with the hotkey or uses a modifier is skipped for that
take and you are told so (pick a plain function key as the hotkey, or switch the
target to hold mode). Add as many apps as you like; the master
switch turns the whole feature off without losing your entries. Two apps that
share a keybind (Discord and Teams both default to `Ctrl+Shift+M`) are sent it
**once** — one press reaches both, and sending it twice would toggle each of
them right back.

Both the `mute_while_recording` master switch and every preset **ship
disabled** — turn the switch on, check the keybind, then enable the entries you
want:

```jsonc
"integrations": {
  "mute_while_recording": true,
  "targets": [
    { "name": "Discord", "enabled": true, "mode": "toggle", "hotkey": "<ctrl>+<shift>+m" }
  ]
}
```

> An existing `config.json` keeps its own target list on upgrade — your entries
> are never overwritten. The presets are then one click away under **Add app**.

## Troubleshooting

There is a built-in help page: **right-click the tray icon → Help /
Troubleshooting** (also reachable as the **Help** tab in the settings window).
It covers the topics below with clickable download links, and the field at the
top of that page (or `Ctrl+F`) searches all of them — paste in a word from the
error you are seeing to jump straight to the matching section.

### `Transcription failed: cublas64_12.dll is not found or cannot be loaded`

`cublas64_12.dll` is an NVIDIA **CUDA 12** library (cuBLAS). With the default
`Device = auto`, Listen To Me tries to transcribe on your **GPU**, but the
portable build does not ship the CUDA runtime libraries — so if they aren't
installed, GPU transcription fails.

- **It now recovers on its own:** when those libraries are missing the app
  **falls back to the CPU automatically** for the session and tells you so —
  transcription keeps working.
- **Make it permanent:** set **Settings → Engine → Device = CPU**. No CUDA
  needed; for the small models the speed difference is minor.
- **Use the GPU instead (NVIDIA only):** install a recent NVIDIA driver plus the
  CUDA 12 runtime library **cuBLAS** — the [CUDA Toolkit
  12.x](https://developer.nvidia.com/cuda-downloads), or drop the DLLs from the
  [`nvidia-cublas-cu12`](https://pypi.org/project/nvidia-cublas-cu12/) wheel next
  to the `.exe` or on your `PATH`. **cuDNN is no longer required** for this
  backend: the CTranslate2 wheels since 4.6.3 (what pip resolves today) are built
  without it; only an older, pinned CTranslate2 in a source install still needs
  [cuDNN 9 for CUDA 12](https://developer.nvidia.com/cudnn) (also available as
  the [`nvidia-cudnn-cu12`](https://pypi.org/project/nvidia-cudnn-cu12/) wheel).
  See the [faster-whisper GPU notes](https://github.com/SYSTRAN/faster-whisper#gpu).

### Intel GPU / NPU acceleration (OpenVINO backend)

No NVIDIA card needed: set **Settings → Engine → Backend = OpenVINO** to run
Whisper on Intel hardware — the integrated GPU of most Intel CPUs, Arc graphics
cards, or the NPU of Core Ultra processors. **Intel device = auto** prefers the
GPU, then the NPU, then the CPU.

- The model is downloaded again for this backend (pre-converted
  [`OpenVINO/whisper-…-ov`](https://huggingface.co/OpenVINO) models from
  Hugging Face) — a one-time setup per model and precision (int8/fp16/int4).
- GPU/NPU use needs a current Intel graphics / [NPU
  driver](https://www.intel.com/content/www/us/en/download/794734/intel-npu-driver-windows.html);
  on failure the app falls back to the CPU for the session and tells you so.
- The portable Windows build ships the backend; from source install the extra:
  `pip install -e ".[openvino]"`.
- Not available on this backend: the `distil-….en` / `distil-large-v3.5` /
  German turbo model presets and the VAD silence filter. The model dropdown
  hides those presets while OpenVINO is selected; if one of them was your
  choice, it is swapped for the closest model that does have an OpenVINO
  version (the note under the dropdown says which) and comes back as soon as
  you pick another backend.

### Maximum speed (Parakeet backend)

Set **Settings → Engine → Backend = Parakeet** to swap Whisper for NVIDIA's
**Parakeet TDT 0.6B v3** ([CC-BY-4.0](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3))
— a 25-language model (German included) that transcribes many times faster
than even `large-v3-turbo`, with punctuation and capitalization built in. The
long "processing" pause after a recording all but disappears, even on a CPU.

- The spoken language is **detected automatically** — the Whisper model
  preset, language choice, initial prompt, beam size and VAD options don't
  apply to this engine (live typing needs faster-whisper and stays off too).
  The settings that don't apply are greyed out while this backend is selected,
  so it stays visible which ones are ignored; your values are kept.
- Runs via [ONNX Runtime](https://onnxruntime.ai/): NVIDIA GPUs (CUDA) or any
  CPU; **Device = auto** prefers the GPU. Model precision **int8** (~640 MB
  download, recommended) or fp32 (~2.4 GB, best with a GPU).
- The portable Windows build ships the backend; from source install the extra:
  `pip install -e ".[parakeet]"` (or `pip install "onnx-asr[cpu,hub]"`).
- **GPU from source:** the `[parakeet]` extra installs the CPU-only
  `onnxruntime`; replace it with `onnxruntime-gpu` — `"onnxruntime-gpu[cuda,cudnn]<1.27"`
  for a **CUDA 12** system (the one CTranslate2 / faster-whisper needs),
  `>=1.27` for **CUDA 13** — and the app preloads the pip-installed CUDA / cuDNN
  DLLs itself before opening the session. Device = CUDA without a CUDA-capable
  onnxruntime is reported, never silently run on the CPU.

### SSL certificate errors behind a corporate proxy

Corporate proxies often intercept HTTPS with their own (self-signed)
certificate. Python does not trust it, so the model download, the update check
and the assistant fail with errors like `CERTIFICATE_VERIFY_FAILED` or
`SSLError`. If that hits you, enable **Settings → General → Ignore SSL
certificate errors (corporate proxy)** — it disables TLS certificate
verification for **every** connection the app makes: the model downloads from
Hugging Face, the assistant API and the updater.

**Security note:** with the option enabled, those connections are still
encrypted but no longer authenticated — a man-in-the-middle would not be
detected. Only enable it inside a network you trust, and leave it off otherwise.

**Updates are included, and that is the part to think about.** An update
replaces the app's own program file, so with the option enabled you are trusting
whatever the connection delivers to run on your machine — the asset's SHA256
digest does not close that gap, because it arrives in the same API response as
the download URL. What still applies either way: the download must come over
HTTPS from a GitHub host (before and after redirects), its size and SHA256 must
match the release, every unverified request is written to the log, and the
install dialog says so before the download starts. If you would rather not take
that trade, leave the option off and fetch the release manually from the
[releases page](https://github.com/fo0/listen-to-me/releases).

### The app doesn't start with Windows

**Start with the system** (_Settings → General → Startup_) registers the app in
your account's autostart. The line right below the checkbox shows what the
system really has on file — `Registered with Windows: …` means the entry is in
place; anything else names the problem and how to fix it.

- **Windows can switch the entry off.** _Task Manager_ (`Ctrl+Shift+Esc`) →
  **Startup apps** shows it as _Disabled_ then, and re-registering alone does
  not change that — the switch lives outside the entry. Set it to _Enabled_
  there, or press **Save** once in the settings with the checkbox ticked: that
  switches it back on. (The same list is in _Windows Settings → Apps → Startup_.)
- **It may be running and just invisible.** Windows 11 hides new tray icons in
  the overflow (**^**) next to the clock — open it and drag the icon onto the
  taskbar to pin it. With **Start minimized to the system tray** ticked, no
  window opens at logon by design. Starting the app again never creates a
  second instance; it brings the running one to the front.
- **Running from a source checkout?** Autostart needs the package installed in
  the environment (`pip install -e .`), because the system starts the command
  without your `PYTHONPATH`. The app probes this and says so instead of
  registering something that would silently do nothing.
- Every launch is logged to `listen-to-me.log` in the config folder (tray menu →
  _Open config folder_) — if the app really didn't start, there is no new line.

The in-app Help page also covers the hotkey not firing, text not being inserted,
where models are stored, and assistant/Ollama setup.

## Run from source

Requires Python 3.10+. A virtual environment is recommended so the
dependencies below don't land in your system Python:

```bash
git clone https://github.com/fo0/listen-to-me
cd listen-to-me
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src python -m listen_to_me   # Windows: set PYTHONPATH=src
```

Or properly installed:

```bash
pip install -e .                 # optional backends: pip install -e ".[openvino]" / ".[parakeet]"
listen-to-me                     # or: listen-to-me-gui (same app, started without a console window)
```

On a minimal Linux install PySide6 also needs the Qt runtime libraries, or the
app aborts with `could not load the Qt platform plugin`. On Debian/Ubuntu that
is the same set CI installs:

```bash
sudo apt-get install libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libfreetype6
```

### Command line

The app is configured in its settings window, not by flags — there are only three:

| Flag           | What it does                                                                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--version`    | Prints the version and exits. Imports no Qt, so it works before the GUI dependencies are installed                                                           |
| `--selftest`   | Runs the packaging self-test and exits with its result (`0` = pass). Needs all runtime dependencies; also used by the release pipeline against the built exe |
| `-h`, `--help` | Prints this list, and the config directory this machine actually uses, then exits — the one place the location is named that does not need the GUI to start  |

Any other argument is refused with exit code `2` instead of quietly starting the
tray app, so a mistyped flag says so.

Everything else — hotkey, model, backend, microphone — lives in `config.json`
(see [config.json reference](#configjson-reference)). Planning to contribute?
[CONTRIBUTING.md](CONTRIBUTING.md) lists the two checks CI runs on every pull request.

## Build the Windows executable locally

```bash
pip install -r requirements.txt pyinstaller
python scripts/make_icon.py build/icon.ico
pyinstaller --noconfirm --onefile --windowed --name ListenToMe --icon build/icon.ico \
  --collect-all faster_whisper --collect-all ctranslate2 \
  --collect-all onnxruntime --collect-all av \
  src/listen_to_me/__main__.py
```

The result is `dist/ListenToMe.exe`.

That build ships the **faster-whisper backend only**. The released exe also
contains the optional OpenVINO and Parakeet backends — selecting one of them in
a build without them fails with a "needs the optional package" message instead.
To match the release, install their packages and collect them too (this is
exactly what [`release.yml`](.github/workflows/release.yml) does):

```bash
pip install "openvino-genai>=2025.2" "huggingface_hub>=0.23" "onnx-asr[cpu,hub]>=0.12"
```

and add these four flags to the `pyinstaller` call above:

```
--collect-all openvino --collect-all openvino_genai \
--collect-all openvino_tokenizers --collect-all onnx_asr
```

## Releases (CI)

A manual _Run workflow_ (`workflow_dispatch`) on
[`release.yml`](.github/workflows/release.yml) runs the full release pipeline,
which:

1. builds `ListenToMe.exe` with PyInstaller on `windows-latest`,
2. runs a packaging self-test (`ListenToMe.exe --selftest`),
3. creates a GitHub release **named with the current UTC timestamp**
   (e.g. _Listen To Me 2026-07-19 08:14 UTC (build 42)_, tag `v2026.07.19.42`),
4. writes the **changelog** (commits since the previous release) into the
   release notes, and
5. attaches the **Windows exe** as a download.

The pipeline only runs when dispatched from `main` — a guard job fails any
run started from another branch.

Pull requests run only the fast **CI** workflow
([`ci.yml`](.github/workflows/ci.yml): syntax compile + offscreen Qt smoke
test) — no Windows build and no release.

## Platform notes

| Platform    | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows** | Primary target; exe built by CI. Autostart via registry `Run` key. Recording system audio works for **any output device** on the released exe, which bundles its own PortAudio with WASAPI loopback ([ADR-0010](docs/adr/0010-the-windows-release-ships-its-own-portaudio.md)) — no “Stereo Mix” and no virtual cable. Running **from source** ships no such DLL, so there it still needs “Stereo Mix” enabled (present on most onboard audio, but disabled) or a virtual audio cable. |
| **Linux**   | Runs from source. Wants `xclip`/`xsel` for clipboard paste mode (without them paste falls back to simulated typing) and an X11 session for global hotkeys (Wayland restricts global key grabbing). Autostart via `~/.config/autostart`. Recording system audio works out of the box (PulseAudio/PipeWire monitor sources).                                                                                                                                                             |
| **macOS**   | Runs from source; grant Accessibility + Microphone permissions. Tray/hotkey main-thread quirks may need polish — contributions welcome. Autostart via LaunchAgent. Recording system audio needs a virtual output device (BlackHole).                                                                                                                                                                                                                                                   |

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set
up a dev environment, the project's conventions, and the checks to run before
opening a pull request. Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
