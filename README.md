# Listen To Me 🎙️

Push-to-talk voice typing for your desktop — fully local, open source.

> 🇩🇪 **Deutsch:** [Kurzanleitung auf Deutsch →](README.de.md)

Press a hotkey, speak, press it again: your words are transcribed by a **local
Whisper model** and inserted **at the cursor of whatever field is focused** —
in _every_ application, from a small system-tray app. No cloud, no account.

<!-- TODO: screenshot or GIF of a dictation (tray icon + floating icon + inserted text) -->

## Download (Windows)

Grab the latest `ListenToMe-<date>-<hhmm>-win64.exe` from
[**Releases**](https://github.com/fo0/listen-to-me/releases/latest) and run it —
portable single file, no installation. The app appears in the system tray.

> Windows SmartScreen may warn because the binary is not code-signed:
> choose _More info → Run anyway_.

Linux and macOS run [from source](docs/guide/development.md#run-from-source).

## Quickstart

1. Start the app — a short **setup wizard** picks the hotkey, your language,
   the speech engine recommended for this PC and the microphone.
2. Put the cursor where the text should go (editor, browser, chat, form, …).
3. Press `Ctrl+Alt+Space`, speak, press it again — the text lands at the cursor.

Everything else lives in the settings window: click the tray icon, or
right-click it → **Settings…**

## Features

- **100 % local speech recognition** with
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper); models download
  automatically on first use.
- **Global hotkey** as toggle or true push-to-talk (hold).
- **Records what the computer plays** — a call, a meeting, a video — on a
  second hotkey. [More →](docs/guide/system-audio.md)
- **Inserts at the cursor** via paste or simulated typing, with the clipboard
  as a safety net when inserting fails.
- **Fast engines:** NVIDIA CUDA, Intel GPU/NPU via OpenVINO, and Parakeet for
  maximum speed — with automatic CPU fallback.
- **Optional LLM cleanup** through any OpenAI-compatible API, e.g. a local
  Ollama. [More →](docs/guide/assistant.md)
- **Mutes Discord, Zoom, Teams & co.** while you dictate.
  [More →](docs/guide/mute-other-apps.md)
- **Floating status icon**, live preview, transcript history with search and
  export, text replacements, and a filter for phrases Whisper invents on silent
  takes.

[All features in detail →](docs/guide/features.md)

## Documentation

| Guide                                                | What's in it                                                                 |
| ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| [Features](docs/guide/features.md)                   | Every feature in detail, platform notes                                      |
| [Settings](docs/guide/settings.md)                   | Settings pages, `config.json` reference, choosing a model, text replacements |
| [Recording system audio](docs/guide/system-audio.md) | Second hotkey for calls and meetings, loopback devices per platform          |
| [Assistant](docs/guide/assistant.md)                 | Optional LLM post-processing (Ollama, LM Studio, …)                          |
| [Mute other apps](docs/guide/mute-other-apps.md)     | Muting Discord, Zoom, Teams, … while you dictate                             |
| [Troubleshooting](docs/guide/troubleshooting.md)     | CUDA DLLs, OpenVINO, Parakeet, corporate proxies, autostart                  |
| [Development](docs/guide/development.md)             | Run from source, command line, local build, release pipeline                 |

The app also has a built-in help page: right-click the tray icon →
**Help / Troubleshooting**.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set
up a dev environment, the project's conventions, and the checks to run before
opening a pull request. Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
