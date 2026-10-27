# Features

Everything Listen To Me does, in detail. The short version is in the
[README](../../README.md).

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
  ([ADR-0010](../adr/0010-the-windows-release-ships-its-own-portaudio.md)),
  so “Stereo Mix” is no longer needed there; Linux needs nothing either, while
  a source install on Windows and any macOS install still need a loopback
  device the system provides — see
  [Recording system audio](system-audio.md).
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
- **A notification takes you where it points** — click one that names a place
  ("Settings → Audio", "it is in Settings → History", "see the log file", "tray
  menu → Help") and that page of the settings window, or the log file, opens.
  A notification that names nowhere stays a plain message.
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
  [Silent takes and invented phrases](settings.md#silent-takes-and-invented-phrases).
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
  as an experimental **live preview while you speak** — and you choose **where
  that text appears**: beside the icon, or **at the mouse pointer**, which the
  bubble then follows while you speak. That is the setting for dictating into a
  window on another screen, where the words otherwise show up in the corner the
  icon happens to live in. The pointer variant needs no icon at all — it works
  with the floating icon **switched off entirely**, which is arguably its most
  useful form: no icon anywhere, the text where you are looking. Either way the
  bubble never takes the click, so you can keep clicking and typing underneath
  it, and it obeys the **always-on-top** switch like the icon does — with that
  off, other windows may cover the bubble too. A **long transcript is shortened
  to its opening** in the bubble, so a recorded fifteen-minute meeting no longer
  covers the whole screen with a column of text for the preview time — the full
  text is what was inserted at the cursor and what **History** keeps. It remembers the
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
  for when the floating icon is switched off — and with the transcript anchored
  to the mouse pointer the previews keep working with the icon off as well, so
  switching it off costs you neither the download progress nor the text.
- **System tray app** — runs quietly in the background; icon shows
  idle / recording / transcribing state and names your configured hotkey
  ("Idle — press Ctrl+Alt+Space to record"), so a forgotten combination is a
  hover away. While you dictate it **counts the take up** ("Recording 1:12… press
  Ctrl+Alt+Space to stop"), so you can see how long you have been speaking
  against the maximum recording length. A transcription that runs longer than
  a few seconds — a long system-audio take on the CPU can need minutes — is
  counted the same way ("Transcribing for 1:12…") here, on the floating icon
  and on the Home page, so a slow one is never mistaken for a hung app; a
  dictation is done before that and keeps the plain "Transcribing…".
  Moved on to another window while it runs? **Don't insert this transcript**
  — the tray's and the floating icon's cancel entry while a take is being
  transcribed — lets the transcription finish but keeps its text away from
  the cursor: it goes to **Settings → History** instead of being pasted into
  whatever you are typing in by then.
  **Record system audio** sits next to
  **Start recording**, so the second source is one click away with or without
  a hotkey of its own, and it names the source it stops
  ("Stop recording system audio (insert text)") — with two start entries in
  one menu, a bare "Stop recording" would not say which take it ends.
  **Pause hotkey** — in this menu and in
  the floating icon's right-click menu, so it stays in reach with the tray icon
  switched off — suspends the global combination for a game or another app that
  wants the same keys; your hotkey is kept, and the pause is forgotten on the
  next start. While it lasts the tray status, the floating icon's tooltip and
  the Home page all say the hotkey is paused — a click on the icon or the Home
  page's **Start recording** still records.
  Only one instance runs at a time:
  starting the app again simply brings the running instance's settings
  window to the front. That window **reopens the way you left it** — the size
  you dragged it to, where you put it, maximized if it was — for as long as
  the app runs; a fresh start opens it at its default size again.
- **Transcript history** — the transcribed text of each recording is kept
  locally so you can copy it again from **Settings → History** if a paste is
  lost. Audio is never stored, with one exception: when the transcription of a
  recording **fails** (a model that will not load, a GPU library error, a
  crashed backend), its audio is kept for **7 days** and the History page lists
  it as a _Transcription failed_ row with the error, the source, its length and
  the date it is kept until. **Retry** transcribes it again with the current
  engine settings (filler filter, assistant profile and replacement rules
  included) and adds the transcript to the history at the time it was recorded
  — nothing is inserted at the cursor; with the history switched off it goes to
  the clipboard instead. A retry that works deletes the audio, as do the row's
  **Delete…** and **Clear history**; one that fails again keeps the row with
  the new error. Nothing is kept while the history is off, and the audio stays on this computer — out of roaming profiles and backups (the folder for each platform is named in [settings.md](settings.md)). Searchable (`Ctrl+F` puts the caret straight into the
  search field, `Esc` clears it again without closing the window) by word
  **or by date** — a term made of digits, `-` and `:`
  such as `2026-09-05` or `14:` also matches the date and time each row shows,
  so a whole day's dictations are one search away. `"release notes"` in
  quotes finds those words as one phrase, and a leading `-` leaves out what
  you do not want (`budget -meeting`, `-2025`) — which keeps long meeting
  recordings, which mention everything, out of a search for a short note.
  Bounded in size, and easy to switch off or
  clear (the confirmation names how many transcripts that deletes) — and a
  single transcript you would rather not keep can be deleted on its own,
  without losing the rest. **Export…** saves the listed transcripts
  (the search filter applies) to a text file, starting in your Documents
  folder and after that wherever the previous export went, and names the file
  it wrote below the buttons; **Copy all**
  puts that same set on the clipboard as one block — so a searched-down
  handful of dictations goes straight into a mail or a note without a detour
  through a file.
  A **long transcript is collapsed** to its opening lines with a **Show more**
  toggle under it, so one recorded fifteen-minute meeting no longer buries
  every dictation below it under screens of scrolling — the collapse is what
  the row _shows_ and nothing else: the search still matches words the row is
  hiding, and Copy, Export and Copy all keep handing over the whole text.
  The newest one is a single click away: **Copy last transcript** in the
  tray menu and in the floating icon's right-click menu puts it straight back
  on the clipboard — and a **Recent transcripts** submenu in both of those
  menus lists the last five, so the one before last is a click away too,
  whichever of the two icons you work from. With nothing to copy it says why —
  no transcript yet, the history switched off (and where to turn it on), or a
  history file that could not be read — instead of promising one is coming.
  If the history file itself ever **cannot be read** — a hand-edit gone wrong,
  a backup tool holding it open — you are told exactly that instead of being
  shown an empty history, and nothing is written over it: your transcripts stay
  in the file, so they can still be rescued with a text editor. **Clear
  history…** starts a fresh one when you no longer need them.
- **Switch the dictation language from the tray** — **Dictation language** in
  the tray menu lists the same languages as Settings → Engine and ticks the one
  in use, so the next recording is transcribed in another language without
  opening the settings window at all. The entry itself names the language that
  is live ("Dictation language: English [en]"), so checking it before a
  dictation takes a glance at the menu, not a search for the tick among
  thirty-five entries. Naming the language instead of leaving it
  on _Auto-detect_ is what makes the recognition more accurate, and it is the
  one engine setting that changes between two dictations — anyone who works in
  two languages was paying for that accuracy with a walk through the sidebar
  several times a day. Both places write the same setting: change it here while
  the settings window happens to be open and its Language box follows, so
  saving there can never put the old language back. With the **Parakeet**
  backend the submenu says so instead of offering a list — that engine detects
  the language itself and ignores the setting, exactly as the Engine page
  already shows (the German Parakeet model names German, the one language it
  knows).
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
  which transcribes many times faster than Whisper in 25 languages — or, with
  primeline's German fine-tune of it, even more accurately in German.
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
  essentials (hotkey, language, a speech engine **recommended for this PC** or
  picked by hand, the microphone with a 3-second level test, startup
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

## Platform notes

| Platform    | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Windows** | Primary target; exe built by CI. Autostart via registry `Run` key. Recording system audio works for **any output device** on the released exe, which bundles its own PortAudio with WASAPI loopback ([ADR-0010](../adr/0010-the-windows-release-ships-its-own-portaudio.md)) — no “Stereo Mix” and no virtual cable. Running **from source** ships no such DLL, so there it still needs “Stereo Mix” enabled (present on most onboard audio, but disabled) or a virtual audio cable. |
| **Linux**   | Runs from source. Wants `xclip`/`xsel` for clipboard paste mode (without them paste falls back to simulated typing) and an X11 session for global hotkeys (Wayland restricts global key grabbing). Autostart via `~/.config/autostart`. Recording system audio works out of the box (PulseAudio/PipeWire monitor sources).                                                                                                                                                           |
| **macOS**   | Runs from source; grant Accessibility + Microphone permissions. Tray/hotkey main-thread quirks may need polish — contributions welcome. Autostart via LaunchAgent. Recording system audio needs a virtual output device (BlackHole).                                                                                                                                                                                                                                                 |
