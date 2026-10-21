# Troubleshooting

There is a built-in help page: **right-click the tray icon → Help /
Troubleshooting** (also reachable as the **Help** tab in the settings window).
It covers the topics below with clickable download links, and the field at the
top of that page (or `Ctrl+F`) searches all of them — paste in a word from the
error you are seeing to jump straight to the matching section, and step through
the other matches with `F3` / `Shift+F3` without leaving the text.

## `Transcription failed: cublas64_12.dll is not found or cannot be loaded`

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

## Intel GPU / NPU acceleration (OpenVINO backend)

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

## Maximum speed (Parakeet backend)

Set **Settings → Engine → Backend = Parakeet** to swap Whisper for NVIDIA's
**Parakeet TDT 0.6B v3** ([CC-BY-4.0](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3))
— a 25-language model (German included) that transcribes many times faster
than even `large-v3-turbo`, with punctuation and capitalization built in. The
long "processing" pause after a recording all but disappears, even on a CPU.

| Parakeet model (`parakeet_model`)  | Languages                  | Download (int8 / fp32) | Notes                                                                                |
| ---------------------------------- | -------------------------- | ---------------------- | ------------------------------------------------------------------------------------ |
| `parakeet-tdt-0.6b-v3` _(default)_ | 25 European, auto-detected | ~640 MB / ~2.4 GB      | NVIDIA's original                                                                    |
| `parakeet-primeline-de`            | **German only**            | ~640 MB / ~2.4 GB      | primeline's German fine-tune: lower German error rates at the same speed (CC-BY-4.0) |

- The spoken language is **detected automatically** (the German model only
  knows German) — the Whisper model preset, language choice, initial prompt,
  beam size and VAD options don't apply to this engine (live typing needs faster-whisper and stays off too).
  The settings that don't apply are greyed out while this backend is selected,
  so it stays visible which ones are ignored; your values are kept.
- **German fine-tune:** **Settings → Engine → Parakeet model =
  parakeet-primeline-de** runs primeline's German fine-tune of the same model —
  same size and speed, clearly lower German error rates (average WER 2.95 %
  against 3.64 % for v3 on its model card's German benchmarks), but it understands
  **German only**. It downloads once, into its own folder, from a pinned
  revision of the ONNX export.
- Runs via [ONNX Runtime](https://onnxruntime.ai/): NVIDIA GPUs (CUDA) or any
  CPU; **Device = auto** prefers the GPU. Model precision **int8** (~640 MB
  download, recommended) or fp32 (~2.4 GB, best with a GPU) — for either model.
- The portable Windows build ships the backend; from source install the extra:
  `pip install -e ".[parakeet]"` (or `pip install "onnx-asr[cpu,hub]"`).
- **GPU from source:** the `[parakeet]` extra installs the CPU-only
  `onnxruntime`; replace it with `onnxruntime-gpu` — `"onnxruntime-gpu[cuda,cudnn]<1.27"`
  for a **CUDA 12** system (the one CTranslate2 / faster-whisper needs),
  `>=1.27` for **CUDA 13** — and the app preloads the pip-installed CUDA / cuDNN
  DLLs itself before opening the session. Device = CUDA without a CUDA-capable
  onnxruntime is reported, never silently run on the CPU.

**Attribution (CC-BY-4.0):** the German model is
[primeline/parakeet-primeline](https://huggingface.co/primeline/parakeet-primeline)
by primeline (Florian Zimmermeister), a fine-tune of NVIDIA's
[Parakeet-TDT-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3); the
app downloads the ONNX export
[OpenVoiceOS/primeline-parakeet-onnx](https://huggingface.co/OpenVoiceOS/primeline-parakeet-onnx)
by OpenVoiceOS. Both are licensed
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

## SSL certificate errors behind a corporate proxy

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

## The app doesn't start with Windows

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
- Every launch is logged to `listen-to-me.log` in the config folder — **tray
  menu → _Open log file_** opens it directly, which is also the file every
  "see the log file" message in the app means. If the app really didn't start,
  there is no new line. (_Open config folder_ right above it shows the folder
  the file sits in, for when your system has no handler for `.log`.)

The in-app Help page also covers the hotkey not firing, text not being inserted,
where models are stored, and assistant/Ollama setup.
