# Listen To Me 🎙️

Push-to-talk voice typing for your desktop — fully local, open source.

> 🇩🇪 **Deutsch:** [Kurzanleitung auf Deutsch →](README.de.md)

Press a hotkey, speak, press it again: your words are transcribed by a **local
Whisper model** and inserted **at the cursor position of whatever field is
focused** — like the recording button in Chrome or OpenWebUI, but as a
standalone system-tray app that works in *every* application.

- **100 % local speech recognition** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (CTranslate2), no cloud, no account. Models are downloaded automatically on
  first use.
- **Global hotkey** (default `Ctrl+Alt+Space`) — start/stop recording from any
  app, either as **toggle** (press to start, press to stop) or as true
  **push-to-talk** (record while the keys are held).
- **Inserts at the cursor** — via clipboard paste (default) or simulated typing.
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
  while transcribing. Click it to start/stop, right-click for a menu.
  Optionally shows the transcript in a bubble — after each recording and/or
  as an experimental **live preview while you speak**. A built-in watchdog
  brings the icon back automatically if Windows drops it (display sleep,
  monitor changes, explorer restarts).
- **System tray app** — runs quietly in the background; icon shows
  idle / recording / transcribing state. Only one instance runs at a time:
  starting the app again simply brings the running instance's settings
  window to the front.
- **Transcript history** — the transcribed text of each recording is kept
  locally (never the audio) so you can copy it again from **Settings → History**
  if a paste is lost. Bounded in size, and easy to switch off or clear.
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
  is built in, one click restores it).
- **Mute other apps while dictating** — optionally mute **Discord** (Teams, OBS,
  any app with a global mute keybind) for exactly the duration of a recording,
  so your dictation isn't transmitted into a voice call, then restored when you
  stop. Works via the app's own **push-to-mute / toggle-mute** keybind — no API
  or account needed.
- **First-run setup wizard** — the very first launch walks you through the
  essentials (hotkey, language, model, backend + device, microphone, startup
  behaviour); everything stays changeable in Settings later.
- **Autostart with Windows** (configurable; Linux and macOS equivalents included).
- **Cross-platform code base** — Windows first; Linux and macOS are prepared
  (see [platform notes](#platform-notes)).

## Download (Windows)

Grab the latest `ListenToMe-<date>-<hhmm>-win64.exe` from the
[**Releases**](https://github.com/fo0/listen-to-me/releases) page and run it —
portable single file, no installation. The app appears in the system tray.

> Windows SmartScreen may warn because the binary is not code-signed:
> choose *More info → Run anyway*.

## How it works

1. Put the cursor where the text should go (editor, browser, chat, form, …).
2. Press the hotkey — the tray icon turns **red**, recording starts.
3. Speak.
4. Press the hotkey again — the icon turns **orange** while the local Whisper
   model transcribes (and the assistant cleans up, if enabled).
5. The text is inserted at the cursor. Done.

Double-clicking the tray icon toggles recording too.

## Settings

On the very first launch a short **setup wizard** collects the essentials —
recording hotkey, spoken language, Whisper model, backend + device, microphone
and startup behaviour. Everything it sets (and much more) can be changed later
here:

Right-click the tray icon → **Settings…**

| Tab | Options |
| --- | --- |
| **General** | Hotkey (type it or use the **“Change…” key picker**), **Test hotkey** (confirms the combination actually arrives — recording stays paused), hotkey mode (**toggle** or **hold/push-to-talk**), spoken language, Whisper model (each preset annotated with its advantage), insert mode (paste/type), **live typing** (experimental — type stable parts of the transcript while you speak; append-only, plain text only, pauses while a modifier key is held; skips the assistant; faster-whisper backend only, and with a hold hotkey it needs a modifier-free key such as F9), clipboard restore, notifications, beep, **autostart**, **start minimized to tray** (off by default — normally the settings window opens on launch), **ignore SSL certificate errors** (off by default — only for corporate proxies with self-signed certificates, see Troubleshooting) |
| **Whisper** | **Backend** (faster-whisper = NVIDIA CUDA / CPU, OpenVINO = Intel GPU / NPU / CPU, **Parakeet** = fastest engine, NVIDIA CUDA / CPU), device (auto/CPU/CUDA resp. auto/CPU/GPU/NPU), compute type resp. model/Parakeet precision, **beam size** (faster-whisper: 5 = best accuracy, 1 = greedy ≈ 1.5–2× faster), VAD silence filter (faster-whisper only), **Detected hardware & model status** card (NVIDIA GPU/CUDA found? OpenVINO installed and which Intel devices? Is the selected model already downloaded? — with a **Refresh status** button, updates automatically when you change model/backend), **model download folder** (view, change, open — defaults to the Hugging Face cache), **Download / load model** (fetch the selected model now instead of on the first recording) and **Test transcription** (record 5 s and transcribe them with the current values — result shown inline, nothing inserted), both cancellable with a **Cancel** button, initial prompt (domain vocabulary hint) |
| **Audio** | Microphone selection, **Test microphone** (3-second check with a live level bar, a clear verdict — works / too quiet / no signal — and a **Cancel** button), maximum recording length |
| **Overlay** | Floating always-on-top icon on/off, transcript bubble after each recording, experimental **live transcript preview while recording**, preview display time |
| **Integrations** | **Mute other apps while recording** (Discord, …): master switch (off by default) plus a list of apps, each with an enabled toggle, name, **mute keybind** (with the same key picker) and **mode** (*push-to-mute* / *toggle mute*). Add or remove apps freely. |
| **Assistant** | Enable/disable, API base URL, model, API key, temperature, **system prompt** (editable, with *Reset to default*) |
| **History** | Recent **transcribed text** kept locally (never the audio), each with a **Copy** button so a lost transcript can be recovered; toggle history on/off, how many entries to keep, and **Clear history** |
| **Updates** | Installed version, **check on startup** toggle, include pre-releases, **Check now**, changelog per release and **Download & install** (frozen Windows build) with progress and a **Cancel download** button |
| **Help** | Built-in **troubleshooting** page (GPU/CUDA errors, Intel GPU/NPU setup, hotkey, text insertion, model storage, assistant setup) with clickable links — also on the tray menu |

Every option has a hover tooltip explaining what it does. The sidebar groups
the pages into **Settings** and **More** (History/Updates/Help). **Save**
applies everything immediately and closes, **Apply** applies without closing,
and closing with unsaved changes asks whether to save or discard them.

### Push-to-talk (hold) mode notes

In **hold** mode recording runs only while the hotkey is held. Two things are
worth knowing:

- **Pick a modifier chord** (e.g. `Ctrl+Alt+Space`). The key picker enforces at
  least one modifier for printable keys (bare function keys like `F9` are also
  allowed). It also accepts **modifier-only chords** (e.g. `Ctrl+Alt`) — hold the
  modifiers and click **OK** to confirm, since there is no final key to auto-apply
  them. While the combo is held it is *not* suppressed from the focused
  application on Linux/macOS, so a plain printable key would type into your
  document — a modifier chord avoids that. (Toggle mode only taps the combo, so
  this doesn't apply there.)
- **If a key release is missed** (some window managers/IMEs grab combos such as
  `Cmd+Space`, or focus changes mid-hold), the recording can't see that you let
  go. It still stops when you click the floating icon or the tray *Stop
  recording* entry, or automatically at the *maximum recording length*.

Configuration is a plain JSON file (tray → *Open config folder*):
`%APPDATA%\ListenToMe\config.json` on Windows,
`~/.config/listen-to-me/config.json` on Linux,
`~/Library/Application Support/ListenToMe/config.json` on macOS.

### Choosing a Whisper model

| Model | Size | Notes |
| --- | --- | --- |
| `tiny` / `base` | ~75–140 MB | fastest, okay for short commands |
| `small` *(default)* | ~460 MB | good balance for dictation |
| `medium` | ~1.5 GB | noticeably better, slower on CPU |
| `large-v3` / `large-v3-turbo` | ~3 GB / ~1.6 GB | best quality; turbo is much faster |
| `jimmymeister/whisper-large-v3-turbo-german-ct2` | ~1.6 GB | **German only** — turbo fine-tuned on German speech: noticeably better German accuracy at the same speed |
| `distil-large-v3` | ~1.5 GB | near large quality, faster (English-focused) |
| `distil-large-v3.5` | ~1.5 GB | English only — newer distil, faster than turbo |

`.en` variants are English-only and slightly more accurate for English. The
model dropdown itself is read-only; to use any other CTranslate2 model id from
Hugging Face, pick **Custom model id (Hugging Face)…** at the bottom of the
list and enter the id in the dialog.
Setting your **spoken language** explicitly (instead of auto-detect) improves
both accuracy and speed.

Models are downloaded on first use into the **Hugging Face cache**
(`~/.cache/huggingface/hub`, on Windows `C:\Users\<you>\.cache\huggingface\hub`)
— *not* into the config folder. The settings window (Whisper tab) shows the
effective folder and lets you change it or open it in the file manager
(`model_dir` in `config.json`).

### Assistant (optional LLM cleanup)

Off by default. When enabled, the raw transcript is sent to an
OpenAI-compatible `/chat/completions` endpoint and the *answer* is inserted
instead. The default configuration targets a local [Ollama](https://ollama.com):

```jsonc
"assistant": {
  "enabled": true,
  "base_url": "http://localhost:11434/v1",
  "api_key": "",
  "model": "llama3.2",
  "system_prompt": "…"   // freely editable in the settings window
}
```

The default system prompt fixes punctuation, removes filler words and applies
dictated formatting ("new paragraph", "bullet list") without translating or
rewriting content. Adapt it however you like — e.g. "always answer in formal
German" or "translate everything to English".

### Mute other apps while dictating (Discord, …)

If you dictate while a voice call is open, your speech would normally be picked
up by that call too. The **Integrations** page can mute other apps for exactly
the time you are recording and restore them when you stop.

It uses the target app's own **global mute keybind** — no API, account or
vendor approval is required, so it works with **Discord**, Microsoft Teams, OBS
or anything else that exposes such a keybind. Set the *same* key combination in
both places:

1. In the app, bind a key to mute. In Discord: **User Settings → Keybinds → Add
   a Keybind** and choose either **Push to Mute** or **Toggle Mute**, then press
   your combination (e.g. `F9`).
2. In Listen To Me, open **Settings → Integrations**, enable the app, set the
   **same** combination (use the *Change…* picker) and pick the matching **mode**:
   - **Push-to-mute (hold)** — the key is held down for the whole recording.
     Stateless and self-correcting, so it can never leave you stuck muted.
     Recommended, and the natural match for Discord's *Push to Mute*.
   - **Toggle mute** — the key is tapped once when recording starts and once
     when it stops. Match this to a *Toggle Mute* keybind.

Prefer a modifier chord or a function key so the combination stays inert in the
document you're dictating into, and don't reuse your recording hotkey's keys —
Listen To Me refuses to save a mute keybind identical to it. Add as many apps as
you like; the master switch turns the whole feature off without losing your
entries. Both the `mute_while_recording` master switch and the bundled
**Discord entry ship disabled by default** — turn the switch on, set your
keybind, then enable the entry (as shown):

```jsonc
"integrations": {
  "mute_while_recording": true,
  "targets": [
    { "name": "Discord", "enabled": true, "mode": "hold", "hotkey": "<f9>" }
  ]
}
```

## Troubleshooting

There is a built-in help page: **right-click the tray icon → Help /
Troubleshooting** (also reachable as the **Help** tab in the settings window).
It covers the topics below with clickable download links.

### `Transcription failed: cublas64_12.dll is not found or cannot be loaded`

`cublas64_12.dll` is an NVIDIA **CUDA 12** library (cuBLAS). With the default
`Device = auto`, Listen To Me tries to transcribe on your **GPU**, but the
portable build does not ship the CUDA runtime libraries (cuBLAS + cuDNN 9 for
CUDA 12) — so if they aren't installed, GPU transcription fails.

- **It now recovers on its own:** when those libraries are missing the app
  **falls back to the CPU automatically** for the session and tells you so —
  transcription keeps working.
- **Make it permanent:** set **Settings → Whisper → Device = CPU**. No CUDA
  needed; for the small models the speed difference is minor.
- **Use the GPU instead (NVIDIA only):** install a recent NVIDIA driver plus the
  CUDA 12 runtime libraries — the [CUDA Toolkit
  12.x](https://developer.nvidia.com/cuda-downloads) and
  [cuDNN](https://developer.nvidia.com/cudnn) — or drop the DLLs from the
  [`nvidia-cublas-cu12`](https://pypi.org/project/nvidia-cublas-cu12/) and
  [`nvidia-cudnn-cu12`](https://pypi.org/project/nvidia-cudnn-cu12/) wheels next
  to the `.exe` or on your `PATH`. See the
  [faster-whisper GPU notes](https://github.com/SYSTRAN/faster-whisper#gpu).

### Intel GPU / NPU acceleration (OpenVINO backend)

No NVIDIA card needed: set **Settings → Whisper → Backend = OpenVINO** to run
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
  German turbo model presets and the VAD silence filter.

### Maximum speed (Parakeet backend)

Set **Settings → Whisper → Backend = Parakeet** to swap Whisper for NVIDIA's
**Parakeet TDT 0.6B v3** ([CC-BY-4.0](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3))
— a 25-language model (German included) that transcribes many times faster
than even `large-v3-turbo`, with punctuation and capitalization built in. The
long "processing" pause after a recording all but disappears, even on a CPU.

- The spoken language is **detected automatically** — the Whisper model
  preset, language choice, initial prompt, beam size and VAD options don't
  apply to this engine (live typing needs faster-whisper and stays off too).
- Runs via [ONNX Runtime](https://onnxruntime.ai/): NVIDIA GPUs (CUDA) or any
  CPU; **Device = auto** prefers the GPU. Model precision **int8** (~640 MB
  download, recommended) or fp32 (~2.4 GB, best with a GPU).
- The portable Windows build ships the backend; from source install the extra:
  `pip install -e ".[parakeet]"` (or `pip install "onnx-asr[cpu,hub]"`).

### SSL certificate errors behind a corporate proxy

Corporate proxies often intercept HTTPS with their own (self-signed)
certificate. Python does not trust it, so the model download, the update check
and the assistant fail with errors like `CERTIFICATE_VERIFY_FAILED` or
`SSLError`. If that hits you, enable **Settings → General → Ignore SSL
certificate errors (corporate proxy)** — it disables TLS certificate
verification for all of the app's connections (model downloads from Hugging
Face, the GitHub update check, the assistant API).

**Security note:** with the option enabled, connections are still encrypted
but no longer authenticated — a man-in-the-middle would not be detected. Only
enable it inside a network you trust, and leave it off otherwise.

The in-app Help page also covers the hotkey not firing, text not being inserted,
where models are stored, and assistant/Ollama setup.

## Run from source

Requires Python 3.10+.

```bash
git clone https://github.com/fo0/listen-to-me
cd listen-to-me
pip install -r requirements.txt
python -m listen_to_me   # add src/ to PYTHONPATH or `pip install -e .` first
```

Or properly installed:

```bash
pip install -e .                 # optional backends: pip install -e ".[openvino]" / ".[parakeet]"
listen-to-me
```

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

## Releases (CI)

A manual *Run workflow* (`workflow_dispatch`) on
[`release.yml`](.github/workflows/release.yml) runs the full release pipeline,
which:

1. builds `ListenToMe.exe` with PyInstaller on `windows-latest`,
2. runs a packaging self-test (`ListenToMe.exe --selftest`),
3. creates a GitHub release **named with the current date**
   (e.g. *Listen To Me 2026-07-19 (build 42)*, tag `v2026.07.19.42`),
4. writes the **changelog** (commits since the previous release) into the
   release notes, and
5. attaches the **Windows exe** as a download.

The pipeline only runs when dispatched from `main` — a guard job fails any
run started from another branch.

Pull requests run only the fast **CI** workflow
([`ci.yml`](.github/workflows/ci.yml): syntax compile + offscreen Qt smoke
test) — no Windows build and no release.

## Platform notes

| Platform | Status |
| --- | --- |
| **Windows** | Primary target; exe built by CI. Autostart via registry `Run` key. |
| **Linux** | Runs from source. Needs `xclip`/`xsel` for clipboard paste mode and an X11 session for global hotkeys (Wayland restricts global key grabbing). Autostart via `~/.config/autostart`. |
| **macOS** | Runs from source; grant Accessibility + Microphone permissions. Tray/hotkey main-thread quirks may need polish — contributions welcome. Autostart via LaunchAgent. |

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set
up a dev environment, the project's conventions, and the checks to run before
opening a pull request. Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
