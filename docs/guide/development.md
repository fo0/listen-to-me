# Development

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
tray app, so a mistyped flag says so — and, when one is close, names the flag
it most likely meant (`--verison` → `Did you mean --version?`).

Everything else — hotkey, model, backend, microphone — lives in `config.json`
(see [config.json reference](settings.md#configjson-reference)). Planning to contribute?
[CONTRIBUTING.md](../../CONTRIBUTING.md) lists the two checks CI runs on every pull request.

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
To get those backends too, install their packages (the same versions
[`desktop-release.yml`](../../.github/workflows/desktop-release.yml) installs):

```bash
pip install "openvino-genai>=2025.2" "huggingface_hub>=0.23" "onnx-asr[cpu,hub]>=0.12"
```

and add these four flags to the `pyinstaller` call above:

```
--collect-all openvino --collect-all openvino_genai \
--collect-all openvino_tokenizers --collect-all onnx_asr
```

**One difference stays either way.** `desktop-release.yml` also builds
PortAudio from a commit-pinned checkout and bundles the result with
`--add-binary "<built portaudio.dll>;."`, which is what gives the released exe a
`… [Loopback]` input for every output device
([ADR-0010](../adr/0010-the-windows-release-ships-its-own-portaudio.md)). A
locally built exe carries no such DLL, so recording system audio there still
needs "Stereo Mix" or a virtual cable — exactly as
[running from source](#run-from-source) does.

## Releases (CI)

A manual _Run workflow_ (`workflow_dispatch`) on
[`desktop-release.yml`](../../.github/workflows/desktop-release.yml) runs the full
release pipeline, which:

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
([`ci.yml`](../../.github/workflows/ci.yml): syntax compile + offscreen Qt smoke
test) — no Windows build and no release.
