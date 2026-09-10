# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Released Windows builds are published on the
[GitHub Releases](https://github.com/fo0/listen-to-me/releases) page — each
release lists the commits it contains (auto-generated) and attaches the portable
`.exe`. Release tags follow the `vYYYY.MM.DD.<build>` scheme, so the Releases
page is the authoritative, always-current history; this file highlights notable
changes at a glance.

## [Unreleased]

### Added

- **A second hotkey records what the computer plays.** A call, a meeting, a
  video, a voice message — transcribed by the same local model and inserted at
  the cursor like a dictation, and controlled exactly like one (press once to
  start, again to stop; hold mode works too). The app could only ever hear the
  microphone, so getting a call into text meant playing it into the room and
  recording that back, with everything the speakers and the room added to it.
  The second source brings its own device, its own maximum length (900 s by
  default, because a recorded meeting is not a dictation) and its own assistant
  profile: the Assistant page is now one shared connection with two profiles,
  **Microphone dictation** and **System audio**, each with its own switch and
  its own prompt, the second one with a model override as well. It is reachable
  by hotkey, from the tray menu and from the floating icon's menu; the Home hub
  shows a second row of key caps once a hotkey is set, and every control that
  used to say "Stop recording" now names and stops the source that is actually
  running. What it records from is an ordinary loopback/monitor **input** device
  the operating system provides — Linux (PulseAudio/PipeWire) has a
  "Monitor of …" source for every output and needs no setup, Windows has
  "Stereo Mix" on most onboard audio but ships it disabled (Sound Control Panel
  → Recording tab → right-click → **Show Disabled Devices**) and otherwise takes
  a virtual cable such as VB-CABLE, macOS needs a virtual output device such as
  BlackHole — because the shipped audio stack cannot ask Windows for a loopback
  stream directly
  ([ADR-0009](docs/adr/0009-system-audio-is-captured-through-a-loopback-input-device.md)).
  Without such a device the take is **refused**, with that instruction in the
  notification: falling back to the default input is deliberately not done,
  because that one is a microphone — recording the room while you asked for what
  the computer plays is a wrong result, not a degraded one, and nothing about
  the resulting text would give it away.
- **Recording what the computer plays now needs no setup on Windows — and the
  device list finally names your outputs.** The released `.exe` brings its own
  PortAudio, built with WASAPI loopback and pinned by commit SHA like every
  action in the release workflow, so Windows offers a recordable
  “… [Loopback]” input for **every** output device: no “Stereo Mix” to un-hide
  and switch on, no virtual audio cable, and a laptop with nothing but a USB
  headset can record a call at all — until now it could not, because the
  PortAudio inside the audio library's own wheel enumerates no loopback device
  whatsoever. The picker was the other half of the same failure: it can only
  ever list _input_ devices, so a machine without “Stereo Mix” showed a list of
  microphones under a card headed “System audio” and nothing that answered
  “where are my speakers?”. It is now two labelled groups — the devices that
  record what the computer plays first, each named after the **output** it
  records, then the microphones — the first heading stays visible with a “None
  found” row under it when nothing was found, and the hint below names the
  outputs that no loopback device covers (three by name, then a count) followed
  by the fix for your platform. Two consequences worth knowing: the swap is not
  scoped to this feature — the bundled binary answers for **all** audio in the
  exe, microphone dictation included, which is why the release refuses to
  publish a DLL that does not export `PaWasapi_IsLoopback` and why the exe's
  self-test has to pass; and the version string cannot tell the two binaries
  apart, because a correct new build reports `PortAudio V19.7.0-devel, revision
unknown` — byte for byte what the old bundled one reports — so the log line
  names the **file** that was loaded and whether loopback is supported instead
  of a version. Running from source is deliberately unchanged: `pip install -e .`
  ships no DLL, so there “Stereo Mix” or a virtual cable is still required
  ([ADR-0010](docs/adr/0010-the-windows-release-ships-its-own-portaudio.md)).
- **A silent take no longer inserts a phrase nobody spoke — and the recording
  decides that, not the wording.** A transcript is dropped only when the take's
  own audio carried no usable signal: the clip statistics that already decide
  whether an empty result is reported as a dead microphone or as unrecognized
  speech have to come back **silent or too quiet** first, and a verdict that
  could not be computed at all keeps the text. Only then is the transcript
  matched against the phrase list, and only as a whole — a listed phrase inside
  a longer dictation is never touched. A take that carried real speech is never
  filtered, however it reads, so a "Vielen Dank." you really did dictate lands
  at the cursor like any other dictation. What the filter is for is the take
  you meant to be empty: press the hotkey, say nothing, press it again, and
  what landed at the cursor was "Vielen Dank.", "Thank you." or a subtitle
  credit. Not one of those strings exists anywhere in this app — a repo-wide
  grep finds none of them; they come out of the model. Whisper's training data
  is subtitle-heavy, and a stretch of video without speech is usually subtitled
  with the clip's closing phrase, so near-silence decodes to the most likely
  "silence continuation" the model ever saw. Neither guard already in place
  catches that: the VAD silence filter (`vad_filter`, Silero) keeps a chunk as
  soon as there is room noise or a keyboard click, and faster-whisper's
  `no_speech_threshold` only drops a segment when `no_speech_prob` is high
  _and_ `avg_logprob` is low — while these hallucinations are decoded with high
  confidence and pass every quality gate the decoder has. The audio is what
  tells the two cases apart, because the wording cannot: "Vielen Dank" and
  "Thank you" are complete messages people dictate, and going by the list alone
  would answer a spoken one with nothing at the cursor, nothing in the history
  and no way to get it back. A take the recording does condemn is dropped and
  reported exactly like one with no speech: nothing is inserted, and nothing
  goes into the history. The single drop neither the list nor the recording has
  a say in is a transcript with **no letter and no digit** left in it (`...`,
  `♪♪`) — there is nothing there to insert either way. The list is editable on
  the Engine settings page (18 phrases ship by default, German and English) and
  the whole filter switches off. Matching ignores case and the punctuation
  around the phrase but keeps brackets — so the annotation `[Musik]` is caught
  while a dictated `Musik` is inserted as spoken — and a take that has already
  live-typed text is never filtered, because that text cannot be taken back.
- **The assistant's "Test connection" can be cancelled.** It was the one test
  in the settings window with no way out: the microphone test, the model
  download, the transcription test and the update download all have a
  **Cancel** button, while this one held the page for the full request timeout
  — configurable up to 600 s, and deliberately set high for slow local models.
  Testing a wrong URL or a stopped Ollama could therefore sit on "Testing…"
  for ten minutes. Cancel detaches the waiting worker rather than aborting the
  request, which cannot be recalled once sent: the answer still arrives and is
  discarded, so it can no longer overwrite the status line minutes later.
  Closing the settings window detaches a running test the same way.
- **The Text replacements field says which of its rules took effect.** A rule
  with a typo — an arrow written as `->`, a line with nothing on its left-hand
  side — was skipped with a warning that only ever reached the log file, so
  the field looked exactly like one whose rules all work and the next
  uncorrected dictation was the first hint. A line under the field now counts
  the active rules and names the ignored ones while they are being typed
  (`2 rules active · 1 line ignored: line 4 has no “=>”.`), capped at three
  named lines plus a count so a pasted-in list of junk stays one line.

- **Copy all** on the History page — puts every transcript the list currently
  shows on the clipboard in one block, newest first and each with its date,
  which is exactly what **Export…** would have written to a file. The search
  filter applies to both, so a handful of dictations found by a word or a date
  goes straight into a mail or a note; before this, getting more than one
  transcript out meant exporting to a file and opening it, or pressing the
  per-row **Copy** button once per transcript.

- **The History search finds a date, not just a word.** Every row on
  Settings → History carries a `YYYY-MM-DD HH:MM` stamp, but the search field
  only ever looked at the transcript text — and a dictation does not repeat its
  own date, so "what did I dictate last Friday" was the one obvious question
  the field could not answer. A term made only of digits, `-` and `:`
  (`2026-09-05`, `2026-09`, `14:`) is now matched against that stamp as well.
  Ordinary words are still matched against the text alone, a single digit
  stays a word, and nothing a query found before stops being found.

- **Text replacements** (Settings → Whisper) — `heard => written` rules applied
  to every finished transcript, one per line. Whisper mis-hears the same domain
  word the same way every time, and the initial prompt only _biases_
  recognition; these rules fix what it got wrong anyway before the text reaches
  the cursor. Case is ignored and whole words are matched, so one rule catches
  the word at the start of a sentence as well as inside it, and the replacement
  is inserted exactly as written.

- **A recording survives a microphone that disappeared.** The selected
  microphone is stored as a PortAudio device index, and those are positional:
  unplugging a USB headset (or plugging anything else in) made the stored index
  point at nothing, and the dictation was lost to a raw PortAudio error naming
  no fix. The take is now recorded with the system default instead, and a
  notification says so once per device — never a silent swap of the recording
  device.

- **Pause hotkey** in the tray menu — suspends the global hotkey while a game,
  a remote session or another app needs the same keys, without changing (and
  having to remember) the configured combination. The tray status says it out
  loud while it is off, and the pause is deliberately not remembered across a
  restart.
- **A “Recent transcripts” submenu in the tray menu** — the last five
  transcripts, newest first, each one click away from the clipboard. "Copy last
  transcript" only ever reached the newest one; anything older meant opening
  Settings → History.
- **A running clock for the recording** in the tray status line and the tray
  icon's tooltip ("Recording 1:12… press Ctrl+Alt+Space to stop") — how long
  you have been dictating was invisible until the heads-up 30 seconds before
  the maximum length. The **floating icon carries the same clock** in its
  tooltip, so the take length is on the control that never leaves the screen
  and not only on the one that can be switched off. The **Home hero counts the
  take up as well** ("Recording 1:12 — speak now"): the biggest and most
  explicit recording control the app has showed a frozen "Recording" for the
  whole take, so anyone dictating from the open window was the one user without
  the clock.
- **The “Recent transcripts” submenu on the floating icon's menu too** — the
  shortcut past Settings → History existed only in the tray, which is exactly
  the icon someone working from the floating control may have turned off.
- **Find in help** on the Help / Troubleshooting page (`Ctrl+F`, or the field
  above the text): all topics live in one long page whose only navigation was
  the "Jump to" list at the very top, so an error message you can read on your
  own screen was not something you could search for. The search wraps around
  and only says "Not found" for a word the page really does not contain.
- **`Ctrl+F` on the History page** puts the caret straight into the transcript
  search field, the same key the Help page's find field uses. The field was
  reachable by mouse only, and it sits above a list a long history has already
  scrolled past; pressing the shortcut twice replaces the old search term
  instead of appending to it.

- **The floating icon remembers the monitor** it was left on, not just a screen
  coordinate — so it comes back to the right screen after a restart, after a
  reboot that brings the second monitor up late, and after a monitor is
  unplugged and reconnected.
- **Reset icon position** — in the floating icon's right-click menu and on the
  Overlay settings page — brings the icon back from wherever a drag or a
  rearranged desktop left it, without editing `config.json`.
- **A request timeout for the assistant**, editable in Settings → Assistant
  (`assistant.timeout`, 120 s by default): how long a finished dictation is held
  back waiting for the LLM before the raw transcript is inserted instead.
- **Test connection** on the Assistant settings page — sends one sample sentence
  and shows the reply, so the endpoint is verified before a dictation depends on
  it.
- **A Releases link in the window footer**, next to the version and the
  existing GitHub link — straight to the download page, which is where you end
  up whenever the in-app updater can't serve you.
- **Heads-up before the maximum recording length** — a notification 30 seconds
  before the cap ends a running take, instead of only "Maximum recording length
  reached." once everything said after it was already lost.
- **Export transcripts** in Settings → History: an **Export…** button writes the
  listed transcripts — the search field filters them — to a plain text file,
  each with its timestamp.
- **Delete a single transcript** in Settings → History: every entry now has its
  own **Delete** button next to **Copy**, so one dictation that should not stay
  on disk no longer costs the whole history.
- **Copy last transcript** in the tray menu and the floating icon's right-click
  menu — puts the text of the most recent recording back on the clipboard
  without opening Settings → History.
- The tray status line and the floating icon's tooltip now name the configured
  hotkey ("Idle — press Ctrl+Alt+Space to record") instead of saying "the
  hotkey", and follow it when it is changed in the settings.

### Fixed

- **A failing assistant now says what to do.** The Assistant page's "Test
  connection" has translated transport failures into one actionable sentence
  for a while, but the notification after a real dictation still printed the
  raw `requests` transport chain ("HTTPSConnectionPool(host='localhost',
  port=11434): Max retries exceeded … NewConnectionError(…)") — a stack-trace
  fragment in the one place the user is not sitting in the settings window
  looking for it. Both paths now use the same wording, and the message still
  says the raw transcript was inserted.
- A `config.json` with a wrong-typed value (a quoted number, a string where a
  number belongs, `null` where a value belongs) no longer reaches the code that
  uses it: plausible hand-edits are repaired, anything else falls back to that
  one option's default instead of failing during startup.

### Changed

- **"Reset to default" for the assistant system prompt asks before discarding
  an edited one.** The button sits directly above the box it overwrites, and
  the prompt is free text with no second copy anywhere — replacing it also
  drops the edit history, so Ctrl+Z did not bring it back either. It is now
  **Reset to default…** and asks whenever the prompt differs from the built-in
  one; a prompt that already is the default has nothing to lose and still
  resets on the first click.
- **Removing an app from "Mute other apps while recording" asks first.** The
  button is now **Remove…** and names the app and its keybind before the row
  goes — every other destructive button in the settings window (Clear history…,
  Delete…, Reset to factory settings…) already confirmed, and this one dropped
  a fully configured entry on a single click with no undo. The keybind is
  normally looked up in the other app's own settings, so re-adding a row
  removed by accident was not free. A row still blank from "Other app…" has
  nothing to lose and is removed at once.
- **The floating icon's right-click menu now follows the app state**, the way
  the tray menu always has: the first entry says whether it will start or stop
  the recording instead of the ambiguous "Start / stop recording", and "Cancel
  recording" is only offered while a take is actually running — clicking it
  while idle did nothing at all, which reads as a broken entry.
- **Clicking the tray icon opens the app window** instead of starting a
  recording. A single click does it as well as a double click. Recording is
  what the hotkey is for — it fires from the field the text should land in,
  while reaching for the tray has already moved the focus away — and a stray
  click that silently started a take was the worse of the two failure modes.
  The tray menu's **Start recording** is unchanged.
- **"Ignore SSL certificate errors" now covers updates too.** The option
  previously applied to the model downloads and the assistant only, so behind
  the very corporate proxy it exists for, the update check kept failing. It now
  covers every connection the app makes. Updates are the risky part of that —
  they replace the program file — so the download still has to come over HTTPS
  from a GitHub host and match the release's size and SHA256, every unverified
  request is logged, and the install dialog says the download is not
  authenticated before it starts. The option remains off by default.
- Documentation and repository housekeeping in preparation for the public
  release (English-only main README with a separate German quick-start,
  contributor guide, hardened `.gitignore`).
