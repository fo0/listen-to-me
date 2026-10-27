# Settings

On the very first launch a short **setup wizard** collects the essentials, one
page each:

1. **Recording hotkey.**
2. **Spoken language.**
3. **Transcription engine** — **Recommended for this PC** is preselected: the
   wizard checks the hardware in the background while you are on the first two
   pages and shows the setup it picks for this computer and the language you
   chose, with the reason and the approximate first-use download (the same
   recommendation as [Auto-configure](#auto-configure-for-this-pc) with
   _Optimize for: Auto_). **Choose
   manually** reveals backend, device, Intel device, Whisper model and — for
   Parakeet — the Parakeet model, prefilled with the recommendation. If the
   check fails, or is still running when you press Next, the page switches to
   the manual fields and says so; nothing ever waits on it.
4. **Microphone** — the input device, with the same **Test microphone (3 s)**
   level check as Settings → Audio.
5. **Startup behaviour.**

Everything it sets (and much more) can be changed later here:

Click the tray icon, or right-click it → **Settings…**

The window footer shows the installed version (selectable, so it can be copied
into a bug report) next to a **GitHub** and a
**Releases** link — the latter goes straight to the download page, which is
what you need when a build can't update itself. **Apply** saves and applies
every change and keeps the window open — `Ctrl+S` does the same from any field
on any page — while **Save** also closes it.

| Tab              | Options                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Home**         | The entry hub: live recording state (counting the running take up, "Recording 1:12 — speak now") with **Start recording / Stop & insert** (and **Cancel**) buttons, the hotkey rendered as key caps, **at-a-glance cards** (engine & model, language, microphone — click one to jump to its settings page), **quick actions** (change hotkey, model & engine, test microphone, overlay, updates, help) and the **most recent transcripts** with a Copy button each (hover one that is cut off to read the rest)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **General**      | Hotkey (type it or use the **“Change…” key picker**), **Test hotkey** (confirms the combination actually arrives — recording stays paused), hotkey mode (**toggle** or **hold/push-to-talk**) — with a pointer to the second recording hotkey, which lives on the Audio page next to the device and the length cap it belongs to — insert mode (paste/type), **live typing** (experimental — type stable parts of the transcript while you speak; append-only, plain text only, pauses while a modifier key is held; skips the assistant; faster-whisper backend only, and with a hold hotkey it needs a modifier-free key such as F9 — a hint under the option says so, and Save refuses a combination that would leave it off), **copy the transcript to the clipboard** (only when inserting fails / always / never), clipboard restore, notifications, beep (Windows only — greyed out elsewhere), **autostart** (with a status line showing what the system actually has registered), **start minimized to tray** (off by default — normally the settings window opens on launch), **ignore SSL certificate errors** (off by default — only for corporate proxies with self-signed certificates, see Troubleshooting), **Reset to factory settings** (asks first, then puts every setting back to the value it shipped with and reopens the first-run setup wizard — transcript history and downloaded models are kept)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **Engine**       | **Backend** (faster-whisper = NVIDIA CUDA / CPU, OpenVINO = Intel GPU / NPU / CPU, **Parakeet** = fastest engine, NVIDIA CUDA / CPU), **model** (each preset annotated with its advantage; “Custom model id…” takes any CTranslate2 model from Hugging Face) and **spoken language**, device (auto/CPU/CUDA resp. auto/CPU/GPU/NPU), **precision** (per backend: the CTranslate2 compute type, the OpenVINO model precision or the Parakeet ONNX variant), **beam size** (faster-whisper: 5 = best accuracy, 1 = greedy ≈ 1.5–2× faster), **CPU threads** (faster-whisper on the CPU: 0 = automatic, the performance cores), VAD silence filter (faster-whisper only), **Parakeet model** (NVIDIA's multilingual original or primeline's German fine-tune), **Detected hardware & model status** card (NVIDIA GPU/CUDA found? OpenVINO installed and which Intel devices? Is the selected model already downloaded? **Running on** — the device and precision the loaded model actually uses, i.e. what `auto` resolved to — updates when you change model/backend; **Refresh status**, **Optimize for** (Auto / CPU / GPU / NPU) and **Auto-configure for this PC**, see [below](#auto-configure-for-this-pc)), **model download folder** (view, change, open — defaults to the Hugging Face cache), **Download / load model** (fetch the selected model now instead of on the first recording — with a byte-accurate progress bar, mirrored onto the floating icon and the tray) and **Test transcription** (record 5 s and transcribe them with the current values — result shown inline, nothing inserted), both cancellable with a **Cancel** button, initial prompt (domain vocabulary hint), **text replacements** (`heard => written` rules applied to every finished transcript, so a word this speaker always gets wrong is corrected before it reaches the cursor) and **Silent takes (invented phrases)** — the on/off switch and the editable list of phrases Whisper invents for a recording with no speech, with a line under the field saying how many are active and which lines were thrown away, plus _Reset to default…_ |
| **Audio**        | **Microphone:** device selection, **Test microphone** (3-second check with a live level bar, a clear verdict — works / too quiet / no signal — and a **Cancel** button), maximum recording length. **System audio:** the hotkey for recording what the computer plays (**empty = this source is off**), its hotkey mode, the **device** list and its own maximum recording length. The list opens with **“Automatic — the best loopback device, or nothing”** and is then split into two labelled groups: _“Loopback devices — these record what the computer plays”_ (each row named after the **output** it records, plus the name fragment that identified it) and _“Other input devices — microphones, not what the computer plays”_; when the first group is empty it keeps its heading and shows a _“None found — nothing here can record the computer's output”_ row. **Refresh** re-scans and reports what it found (“3 loopback ✓” / “None found”), so a device you just enabled shows up without a restart. The hint under the card says what the feature does, **names the outputs that no loopback device covers** (up to three, then “and N more”) with the fix for your platform, and when there is no loopback device at all it leads with a warning that a take would be refused                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Overlay**      | Floating icon on/off, **keep it above all other windows** (on by default — Windows strips that state behind the app's back, which makes the icon look like it vanished when it is only buried), transcript bubble after each recording, experimental **live transcript preview while recording**, **where the transcript appears** (beside the floating icon, or at the mouse pointer, which the bubble then follows while you speak — that one also works with the icon switched off), preview display time, **Reset position** (moves the icon back to the bottom right — also in the icon's own right-click menu — for when it ended up half off the screen or on a monitor you have since rearranged)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Integrations** | **Mute other apps while recording** (Discord, …): master switch (off by default) plus a list of apps, each with an enabled toggle, name, **mute keybind** (with the same key picker) and **mode** (_push-to-mute_ / _toggle mute_). Add or remove apps freely — **Remove…** asks first once an entry carries a name or a keybind, so a mis-click doesn't cost a combination you had to look up in the other app's settings.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Assistant**    | **Connection** (shared by both profiles): API base URL, model, API key (**Show** reveals it to check what was pasted, masked again when you leave the page), temperature, **request timeout** (how long a dictation is held back waiting for the answer), **Test connection** (sends one sample sentence through the profile picked in the dropdown beside it and shows the reply — verifies the endpoint, that profile's model override and its prompt before a recording depends on them, with a **Cancel** button so a wrong URL or a stopped endpoint doesn't hold the page for the whole request timeout). Then one card per recording source — **Microphone dictation** and **System audio** — each with its own on/off switch and its own **system prompt** (editable, with _Reset to default…_ — it asks first once you have edited the prompt, since nothing else keeps a copy of what you wrote); the system-audio card also takes an optional **model override** (empty = the model from Connection)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **History**      | Recent **transcribed text** kept locally, each with a **Copy** button so a lost transcript can be recovered and a **Delete** button that removes just that one entry; a recording whose **transcription failed** is listed among them for 7 days (its audio is the one thing ever kept — only while the history is on) with the error and a **Retry** button that transcribes it again into the history at its original time, plus **Delete…**; a **search field** (`Ctrl+F`; `Esc` clears it) narrows the list to the transcripts containing your words (any order, case-insensitive) and shows how many of them matched — a term made only of digits, `-` and `:` (e.g. `2026-09-05`, `14:`) also matches the date and time on each row, `"quoted words"` match as one phrase and a leading `-` excludes a word or phrase (`-meeting`); **Export…** writes the listed transcripts (the search filter applies) to a text file and **Copy all** puts the same set on the clipboard as one block; toggle history on/off, how many entries to keep, and **Clear history**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **Updates**      | Installed version, **check on startup** toggle, include pre-releases, **Check now**, a **release history** of the recent releases with their changelogs — the newer ones first, then the one you are running (marked _(installed)_ and preselected when you are up to date) and older ones, ten at a time with **Show more** — and **Download & install** (frozen Windows build; newer releases only, no downgrades) with progress — **download size** next to each newer release and in the confirmation, and "42.0 MB of 198.0 MB" while it runs — and a **Cancel download** button. The new build is written over the running executable — same folder, same file name — so shortcuts, pinned taskbar entries and the autostart entry keep working; the dated `ListenToMe-…-win64.exe` name is only how the download is published                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Help**         | Built-in **troubleshooting** page (GPU/CUDA errors, Intel GPU/NPU setup, picking the engine with Auto-configure, hotkey, text insertion, model storage, assistant setup) with clickable links — also on the tray menu. **Find in help** (`Ctrl+F`) searches the whole page, so an error message you can read on screen is enough to reach the right topic; `F3` / `Shift+F3` step to the next and previous match from anywhere on the page, including while you are reading the text itself; the search wraps around at the end, a count beside the field says which match is selected ("Match 2 of 5"), and `Esc` clears the term                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

Every option has a hover tooltip explaining what it does. The sidebar groups
the pages into **Home**, **Settings** and **More** (History/Updates/Help).
**Save**
applies everything immediately and closes, **Apply** applies without closing,
**Close** leaves the window (the app keeps running in the tray), and closing
with unsaved changes asks whether to save or discard them. The window can be
minimized and maximized like any main window.

## Push-to-talk (hold) mode notes

In **hold** mode recording runs only while the hotkey is held. A few things
are worth knowing:

- **Pick a modifier chord** (e.g. `Ctrl+Alt+Space`). The key picker enforces at
  least one modifier for printable keys (bare function keys like `F9` are also
  allowed). It also accepts **modifier-only chords** (e.g. `Ctrl+Alt`) — hold the
  modifiers and click **OK** (or release them and press **Enter**) to confirm,
  since there is no final key to auto-apply them. While the combo is held it is
  _not_ suppressed from the focused application on Linux/macOS, so a plain
  printable key would type into your document — a modifier chord avoids that.
  (Toggle mode only taps the combo, so this doesn't apply there.)
- **If a key release is missed** (some window managers/IMEs grab combos such as
  `Cmd+Space`, or focus changes mid-hold), the recording can't see that you let
  go. It still stops when you click the floating icon or the tray _Stop
  recording_ entry, or automatically at the _maximum recording length_.
- **Before the maximum recording length ends a take**, a notification says how
  many seconds are left, so a long dictation can be wrapped up instead of being
  cut off mid-sentence. (Only when the configured cap is comfortably longer
  than that warning — a deliberately short cap is not a surprise.)
- **A quick tap records nothing.** A take shorter than 0.3 s is dropped, and in
  hold mode the notification says why: "Recording too short — nothing
  inserted. In hold mode, keep “Ctrl+Alt+Space” held down while you speak." —
  pressing and releasing the key the way toggle mode works is the usual cause.

Configuration is a plain JSON file (tray → _Open config folder_):
`%APPDATA%\ListenToMe\config.json` on Windows,
`~/.config/listen-to-me/config.json` on Linux,
`~/Library/Application Support/ListenToMe/config.json` on macOS.

That same folder holds everything else the app keeps on disk, so it is the one
place to look when reporting a bug or cleaning up:

| File                              | What it is                                                                                                                                                                                                                                                                                               |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config.json`                     | Your settings — the only file that may contain a secret (the optional assistant API key). Don't share it unredacted                                                                                                                                                                                      |
| `config.json.bad`                 | Only after a read error: the previous `config.json`, moved aside on the next save so a corrupt or locked file is never overwritten. The app says so on start and runs on the defaults until you save                                                                                                     |
| `history.json`                    | The transcript **text** of recent recordings (never audio). Switch it off or clear it in Settings → History                                                                                                                                                                                              |
| `failed-takes/`                   | Only after a transcription failed while the history is on: that recording's audio (`.wav`) and its error (`.json`), kept 7 days for **Retry** in Settings → History (at most 50 recordings and 1 GB — the oldest goes first). Deleted by a retry that works, the row's **Delete…** and **Clear history** |
| `listen-to-me.log` (+ `.1`, `.2`) | Rotating log, 512 KB per file — the first thing to attach to a bug report                                                                                                                                                                                                                                |
| `instance.lock` _(Linux/macOS)_   | The single-instance lock; on Windows a named mutex does the same job without a file                                                                                                                                                                                                                      |
| `cache/openvino-cache/`           | OpenVINO on a GPU or NPU only: the compiled model, so a restart on the same model, device and driver skips a recompile of up to minutes. A custom `model_dir` holds it instead. Safe to delete                                                                                                           |

Nothing is written anywhere else — downloaded models live in the Hugging Face
cache (see [Choosing a Whisper model](#choosing-a-whisper-model)), not here.

## config.json reference

Every option above is stored under one of these keys. The file is written with
all defaults on first launch, and unknown/missing keys fall back to the default,
so you only need to keep what you changed. Editing it by hand is optional — the
settings window writes the same keys.

A value of the wrong type falls back to the default (with a line in the log).
The numeric keys additionally carry the range the settings window accepts, noted
below: a hand-edited value outside it keeps working, but opening that settings
page and saving snaps it into range.

Five of them are also held to that range when they take effect — the recording
cap, the history trim and the assistant request: `max_seconds`,
`system_audio.max_seconds`, `history_max`, `assistant.temperature` and
`assistant.timeout`. For those an out-of-range value works only as the nearest
bound, with one line in the log naming the key. The other two have looser
guards of their own:
`overlay.preview_seconds` is kept between `2` and `600` seconds, `beam_size` at
`1` or more.

| Key                                             | Default                       | What it does                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `hotkey`                                        | `"<ctrl>+<alt>+<space>"`      | Global recording hotkey, pynput syntax                                                                                                                                                                                                                                                                                                                                                     |
| `hotkey_mode`                                   | `"toggle"`                    | `toggle` = press to start/stop (a modifier-only combo such as `Ctrl+Alt` fires on release, and only if no other key went down), `hold` = push-to-talk                                                                                                                                                                                                                                      |
| `language`                                      | `"auto"`                      | Spoken language code, `auto` = detect                                                                                                                                                                                                                                                                                                                                                      |
| `model`                                         | `"small"`                     | Whisper preset or any CTranslate2 model id                                                                                                                                                                                                                                                                                                                                                 |
| `model_dir`                                     | `null`                        | Model download folder; `null` = Hugging Face cache                                                                                                                                                                                                                                                                                                                                         |
| `backend`                                       | `"faster-whisper"`            | Engine: `faster-whisper`, `openvino` or `parakeet`                                                                                                                                                                                                                                                                                                                                         |
| `device`                                        | `"auto"`                      | Device for faster-whisper/Parakeet: `auto`/`cpu`/`cuda`                                                                                                                                                                                                                                                                                                                                    |
| `compute_type`                                  | `"auto"`                      | CTranslate2 precision: `auto` (= `int8` on the CPU, `float16` on a GPU) / `int8`/`int8_float16`/`float16`/`float32`                                                                                                                                                                                                                                                                        |
| `openvino_device`                               | `"auto"`                      | Intel device: `auto`/`cpu`/`gpu`/`npu` (`auto` prefers GPU → NPU → CPU)                                                                                                                                                                                                                                                                                                                    |
| `openvino_precision`                            | `"int8"`                      | OpenVINO model precision: `int8`/`fp16`/`int4`                                                                                                                                                                                                                                                                                                                                             |
| `parakeet_quantization`                         | `"int8"`                      | Parakeet ONNX variant: `int8`/`fp32`                                                                                                                                                                                                                                                                                                                                                       |
| `parakeet_model`                                | `"parakeet-tdt-0.6b-v3"`      | Parakeet model: `parakeet-tdt-0.6b-v3` (NVIDIA's multilingual original, 25 languages) or `parakeet-primeline-de` (primeline's German fine-tune — more accurate for German, German only); an unknown value runs the default, with a line in the log                                                                                                                                         |
| `autoconfig_target`                             | `"auto"`                      | Device class _Auto-configure for this PC_ optimizes for (_Optimize for_): `auto` (its full recommendation order) / `cpu` / `gpu` / `npu`; only steers the next recommendation, an unknown value counts as `auto`. The setup wizard always uses `auto`                                                                                                                                      |
| `input_device`                                  | `null`                        | Microphone index; `null` = system default                                                                                                                                                                                                                                                                                                                                                  |
| `max_seconds`                                   | `300`                         | Hard cap for a single recording, in seconds (a notification warns 30 s before it ends the take). Settings range: `10`–`3600`                                                                                                                                                                                                                                                               |
| `system_audio.hotkey`                           | `""`                          | Second global hotkey, for recording what the computer plays; **empty = this source is off** — see [Recording system audio](system-audio.md)                                                                                                                                                                                                                                                |
| `system_audio.hotkey_mode`                      | `"toggle"`                    | `toggle` / `hold` for that second hotkey — independent of `hotkey_mode` above                                                                                                                                                                                                                                                                                                              |
| `system_audio.device`                           | `null`                        | Index of the loopback/monitor **input** device to record from; `null` = auto-pick the best candidate found                                                                                                                                                                                                                                                                                 |
| `system_audio.max_seconds`                      | `900`                         | Hard cap for one system-audio recording, in seconds — higher than `max_seconds` because a recorded meeting is not a dictation. Settings range: `10`–`3600`                                                                                                                                                                                                                                 |
| `system_audio.bundled_portaudio`                | `true`                        | Windows exe only: use the PortAudio the exe ships (the one built with WASAPI loopback). `false` falls back to the binary inside the `sounddevice` wheel — the way back if a bundled build turns out worse than that one; it costs system-audio recording on Windows and nothing else. No control for it in the settings window, on purpose — see [Recording system audio](system-audio.md) |
| `injection_mode`                                | `"paste"`                     | Insert via `paste` (clipboard) or `type` (simulated typing)                                                                                                                                                                                                                                                                                                                                |
| `live_typing`                                   | `false`                       | Experimental live typing while recording (faster-whisper only)                                                                                                                                                                                                                                                                                                                             |
| `clipboard_copy`                                | `"on_failure"`                | Also copy the transcript to the clipboard: `on_failure` (only when inserting at the cursor fails), `always` (every transcript — suppresses `restore_clipboard`) or `off`                                                                                                                                                                                                                   |
| `restore_clipboard`                             | `true`                        | Restore the previous clipboard content after a paste                                                                                                                                                                                                                                                                                                                                       |
| `notifications` / `beep`                        | `true` / `true`               | Desktop notifications and the audible start/stop cue (the beep is Windows only)                                                                                                                                                                                                                                                                                                            |
| `autostart`                                     | `false`                       | Start with the OS                                                                                                                                                                                                                                                                                                                                                                          |
| `start_in_tray`                                 | `false`                       | Start silently into the tray instead of opening the window                                                                                                                                                                                                                                                                                                                                 |
| `initial_prompt`                                | `""`                          | Whisper initial prompt (domain vocabulary hint, not an instruction). Whisper reads only its last ~223 tokens (about 560 characters), and only for the first 30 s of a take, so a short list works best, the most important terms last — Settings says when a prompt is longer. Not used by Parakeet                                                                                        |
| `replacements`                                  | `""`                          | Find/replace rules applied to every finished transcript, one `find => replace` per line — see [Text replacements](#text-replacements)                                                                                                                                                                                                                                                      |
| `filler_filter`                                 | `true`                        | Drop a transcript that came out of a **silent or too quiet** recording and is **nothing but** a phrase Whisper invents for a take with no speech. A take that carried real speech is never filtered, however it reads — see [Silent takes and invented phrases](#silent-takes-and-invented-phrases)                                                                                        |
| `filler_phrases`                                | _(18 built-in phrases)_       | The list those transcripts are matched against, one phrase per line (`#` comments allowed); consulted only for a take whose own audio was silent or too quiet; editable in Settings → Engine                                                                                                                                                                                               |
| `vad_filter`                                    | `true`                        | VAD silence filter (faster-whisper only)                                                                                                                                                                                                                                                                                                                                                   |
| `beam_size`                                     | `5`                           | Decoding beam size; `1` = greedy, ≈1.5–2× faster (faster-whisper only). Settings range: `1`–`10`                                                                                                                                                                                                                                                                                           |
| `cpu_threads`                                   | `0`                           | CPU threads faster-whisper transcribes with on the CPU (ignored on CUDA); `0` = automatic: the performance cores, at least `4` (or the physical cores, if fewer) and at most `8`. Held to the processor count and to `64`. Settings range: `0`–`64`                                                                                                                                        |
| `history_enabled` / `history_max`               | `true` / `200`                | Keep a local transcript history, and how many entries. Audio only for a recording whose transcription failed — kept 7 days in `failed-takes/` for a retry, never while this is off. Settings range for `history_max`: `10`–`5000`                                                                                                                                                          |
| `update_check_on_start` / `include_prereleases` | `true` / `false`              | Check GitHub Releases on launch, and whether pre-releases count                                                                                                                                                                                                                                                                                                                            |
| `insecure_ssl`                                  | `false`                       | Skip TLS verification for every connection — model downloads, assistant **and updates**; corporate proxies only                                                                                                                                                                                                                                                                            |
| `overlay.enabled`                               | `true`                        | The floating always-on-top status icon                                                                                                                                                                                                                                                                                                                                                     |
| `overlay.always_on_top`                         | `true`                        | Keep the icon above all other windows and re-apply that every few seconds (Windows silently strips the always-on-top state). Off = other windows may cover it                                                                                                                                                                                                                              |
| `overlay.show_preview`                          | `true`                        | Show the transcript in a bubble after a recording                                                                                                                                                                                                                                                                                                                                          |
| `overlay.live_preview`                          | `false`                       | Experimental rolling preview while you speak (costs CPU)                                                                                                                                                                                                                                                                                                                                   |
| `overlay.preview_seconds`                       | `6`                           | How long the finished transcript stays visible. Settings range: `2`–`60`                                                                                                                                                                                                                                                                                                                   |
| `overlay.preview_anchor`                        | `"icon"`                      | Where **both** previews above are drawn. `"icon"` = beside the floating icon, wherever you dragged it; `"cursor"` = below-right of the mouse pointer, on whichever monitor it is on, following it while you speak — and it works with the icon switched off. Any other value degrades to `"icon"`                                                                                          |
| `overlay.x` / `overlay.y`                       | `null`                        | Saved icon position as desktop coordinates; `null` = bottom right                                                                                                                                                                                                                                                                                                                          |
| `overlay.screen`                                | `null`                        | The monitor the icon was left on (EDID identity, else the device name)                                                                                                                                                                                                                                                                                                                     |
| `overlay.rel_x` / `overlay.rel_y`               | `null`                        | Saved icon position within that monitor — what brings it back to the right screen after a restart                                                                                                                                                                                                                                                                                          |
| `assistant.enabled`                             | `false`                       | Optional LLM post-processing of the transcript                                                                                                                                                                                                                                                                                                                                             |
| `assistant.base_url`                            | `"http://localhost:11434/v1"` | OpenAI-compatible endpoint                                                                                                                                                                                                                                                                                                                                                                 |
| `assistant.api_key`                             | `""`                          | API key — stays in this local file; empty for Ollama                                                                                                                                                                                                                                                                                                                                       |
| `assistant.model`                               | `"llama3.2"`                  | Model name sent to that endpoint                                                                                                                                                                                                                                                                                                                                                           |
| `assistant.system_prompt`                       | _(built-in default)_          | Cleanup prompt, editable in Settings (one click restores it, asking first once you have edited it)                                                                                                                                                                                                                                                                                         |
| `assistant.temperature` / `assistant.timeout`   | `0.2` / `120`                 | Sampling temperature and request timeout in seconds — both editable in Settings → Assistant. Ranges: `0.00`–`2.00` / `5`–`600`                                                                                                                                                                                                                                                             |
| `assistant.system_audio.enabled`                | `false`                       | Post-process **system-audio** transcripts too. Independent of `assistant.enabled`, which is the microphone profile; the connection above is shared by both                                                                                                                                                                                                                                 |
| `assistant.system_audio.model`                  | `""`                          | Model for that profile only; empty = `assistant.model`                                                                                                                                                                                                                                                                                                                                     |
| `assistant.system_audio.system_prompt`          | _(built-in default)_          | Prompt for recorded playback — cleans the transcript up; meant to be replaced with what you want out of a meeting (minutes, a summary, a translation)                                                                                                                                                                                                                                      |
| `integrations.mute_while_recording`             | `false`                       | Master switch for muting other apps while recording                                                                                                                                                                                                                                                                                                                                        |
| `integrations.targets`                          | 5 presets, all disabled       | Per-app entries: `name`, `enabled`, `mode` (`hold`/`toggle`), `hotkey`                                                                                                                                                                                                                                                                                                                     |

## Auto-configure for this PC

**Settings → Engine → Auto-configure for this PC** (in the _Detected hardware &
model status_ card) picks the most accurate engine setup that still runs well on
this computer. It uses what the status card detects — an NVIDIA GPU usable
through CUDA, the Intel GPU (Arc or not) and NPU OpenVINO lists, whether the
optional Parakeet engine is installed, the processor's cores and AVX2 support — and the **spoken
language** selected on the page, which it never changes. Quality comes first,
in this order:

1. **An NVIDIA GPU** → faster-whisper on it with `large-v3-turbo`, for German
   its German fine-tune.
2. **Parakeet installed and it understands the language** (or the language is
   auto-detected) → Parakeet on the CPU at int8, for German primeline's German
   model.
3. **OpenVINO installed and an Intel Arc as its default GPU** → OpenVINO
   with `large-v3-turbo` on that GPU at int8.
4. **Otherwise** → faster-whisper on the CPU with `large-v3-turbo` (German: the
   German fine-tune) on 8 or more physical cores, unless the processor reports
   no AVX2; else `small`.

**Optimize for** beside the button picks the device class instead —
**Auto (recommended)** is the order above, the default. The choice only steers
the next recommendation; it changes no engine field by itself, and is saved
with **Apply** / **Save** like any other field (`autoconfig_target`).

- **CPU** → rules 2 and 4 alone: Parakeet or faster-whisper on the processor,
  with the same language and core rules, even when a graphics card or NPU is
  there.
- **GPU** → an NVIDIA GPU through CUDA as in rule 1, otherwise the Intel GPU
  OpenVINO runs as its default GPU: an Arc with `large-v3-turbo`, any other
  Intel GPU (UHD, Iris Xe) with the conservative `small`, both at int8.
- **NPU** → OpenVINO on the Intel NPU (`openvino_device` = `npu`) at int8 with
  `small`, a conservative starting profile — pick a larger model by hand once
  it runs well.

CPU is always offered. GPU and NPU can only be chosen when an installed backend
reports them; otherwise they are shown greyed out, with the reason below the
dropdown, and a recommendation for them says why it cannot be made instead of
switching to another device. OpenVINO never gets the German fine-tune: it has
no OpenVINO version. If the chosen device fails at runtime, the engine still
falls back to the CPU for the session, and **Running on** shows the device
actually in use.

Before anything changes it shows the recommendation, why it was chosen, the
approximate first-use download and every field it would change, and asks.
**Use these settings** only fills the fields in: nothing is saved until you
press **Apply** or **Save**, and closing the window without saving discards it
like any other edit. When the page already matches, it says so instead.

The first-run setup wizard offers the same recommendation (_Optimize for: Auto_)
as its preselected **Recommended for this PC** engine choice, for the language
picked on the page before it; there, Finish saves it together with the other
choices.

## Choosing a Whisper model

| Model                                            | Size            | Notes                                                                                                    |
| ------------------------------------------------ | --------------- | -------------------------------------------------------------------------------------------------------- |
| `tiny` / `base`                                  | ~75–140 MB      | fastest, okay for short commands                                                                         |
| `small` _(default)_                              | ~490 MB         | good balance for dictation                                                                               |
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

## Text replacements

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
- **Try the rules before you rely on them** — type a sentence into the field
  under the rules and the line below it shows what they make of it
  (`Result: we moved the cluster to Kubernetes`), updated as you type in
  either field and before you save. It runs exactly what a finished dictation
  goes through, minus the assistant, so whether a rule also catches the word
  at the start of a sentence, or leaves a longer word alone, is visible
  without dictating.
- Not applied while `live_typing` is on: that text is already at the cursor and
  append-only typing cannot take it back.

## Silent takes and invented phrases

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

**Invented text in a take that did carry speech** is a different failure, and
other guards catch it (#293). A hard stretch of audio is re-decoded at ever
higher sampling temperatures, and high up that ladder Whisper writes random
multilingual tokens — `結, 那个, 这 果` at the end of a German dictation. The
app now stops the ladder at 0.4, and while decoding, a segment that is mostly
foreign script for a Latin-script language is dropped, and so is one still
looping after every fallback temperature; a stray foreign run inside a real
sentence is only cut out, and a sentence that was merely hard to hear is never
dropped for its low confidence alone. The OpenVINO backend also trims the
silence around a take, holds its output to what the take's length can carry
(never beyond what the model's own window allows), and gives a take under 3 s
no initial prompt — that is where it read its own prompt back for 1547
characters. Both Whisper backends hand the model only the end of a long
prompt, measured with the model's own tokenizer. Last, a finished transcript
that cannot have come from the audio — the same words over and over, the
initial prompt read back, far more text than a microphone take's length allows
— is **not inserted**: it is kept in Settings → History (when the history is
on, with your text replacements applied) and one notification says why. The
length rule does not apply to system audio, which may be played faster than
anyone speaks, and a take the OpenVINO backend decoded without a prompt is
never refused as an echo of one. That last check is skipped while
`live_typing` is on, for the same reason as the phrase list.
