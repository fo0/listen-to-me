"""In-app Help / Troubleshooting content.

Kept deliberately Qt-free and as plain structured data so it stays easy to
extend, can be rendered anywhere (the Settings → Help ``QTextBrowser``, an
exported HTML file, tests) and imports without pulling in PySide6.

Add a topic by appending a dict to :data:`HELP_TOPICS`; ``help_html()`` builds
the "jump to" table of contents and the anchors for it automatically.
"""

from __future__ import annotations

from . import APP_NAME, REPO_URL

# Each topic: a short anchor ``id``, a ``title`` and an HTML ``body`` (a subset
# of HTML that Qt's rich-text engine renders: headings, paragraphs, lists,
# <b>/<code>, links). The CUDA entry comes first — it is the most common cause
# of a failed transcription on the portable Windows build.
HELP_TOPICS: list[dict] = [
    {
        "id": "cuda",
        "title": "Transcription failed: cublas64_12.dll not found (GPU / CUDA errors)",
        "body": f"""
<p><b>What it means.</b> <code>cublas64_12.dll</code> is an NVIDIA <b>CUDA&nbsp;12</b>
library (cuBLAS). {APP_NAME} tried to transcribe on your <b>GPU</b>, but the CUDA
runtime libraries needed for that are not installed on your system. The portable
build does not ship them, so loading or running the model on the GPU fails.</p>

<p>{APP_NAME} now <b>falls back to the CPU automatically</b> when these libraries
are missing, so transcription keeps working — you will see a one-time notice that
it switched to CPU for the session. The steps below are only needed if you want
to make CPU the permanent choice, or to run on the GPU on purpose.</p>

<p><b>Quick fix — works on any PC.</b> Open <b>Settings → Whisper → Device</b> and
set it to <b>CPU</b>. No CUDA required. It is a bit slower but reliable; for the
small models the difference is minor.</p>

<p><b>Use the GPU (NVIDIA graphics cards only).</b> You need a recent NVIDIA
driver plus the CUDA&nbsp;12 runtime libraries (<b>cuBLAS</b> and
<b>cuDNN&nbsp;9 for CUDA&nbsp;12</b>). Either install the CUDA Toolkit, or place
the required DLLs next to <code>ListenToMe-*.exe</code> or in a folder on your
<code>PATH</code>.</p>

<p><b>Download links</b></p>
<ul>
<li>NVIDIA drivers &mdash; <a href="https://www.nvidia.com/Download/index.aspx">nvidia.com/Download</a></li>
<li>CUDA Toolkit 12.x &mdash; <a href="https://developer.nvidia.com/cuda-downloads">developer.nvidia.com/cuda-downloads</a></li>
<li>cuDNN (for CUDA&nbsp;12) &mdash; <a href="https://developer.nvidia.com/cudnn">developer.nvidia.com/cudnn</a></li>
<li>Advanced &mdash; the DLLs also ship in the PyPI wheels
<a href="https://pypi.org/project/nvidia-cublas-cu12/">nvidia-cublas-cu12</a> and
<a href="https://pypi.org/project/nvidia-cudnn-cu12/">nvidia-cudnn-cu12</a></li>
<li>faster-whisper GPU requirements &mdash;
<a href="https://github.com/SYSTRAN/faster-whisper#gpu">github.com/SYSTRAN/faster-whisper</a></li>
</ul>

<p><b>No NVIDIA GPU?</b> Then CUDA cannot work &mdash; use <b>Device = CPU</b>
(see the quick fix above), or switch to the <b>OpenVINO backend</b> for Intel
GPUs/NPUs (see the next topic). AMD graphics are not supported for acceleration
yet.</p>
""",
    },
    {
        "id": "intel",
        "title": "Use an Intel GPU or NPU (OpenVINO backend)",
        "body": f"""
<p>{APP_NAME} can transcribe on Intel hardware &mdash; the integrated GPU of
most Intel CPUs, Arc graphics cards and the NPU (&ldquo;AI&nbsp;Boost&rdquo; in
Core&nbsp;Ultra processors) &mdash; through the <b>OpenVINO</b> backend.</p>
<ul>
<li>Open <b>Settings → Whisper → Backend</b> and select
<b>OpenVINO — Intel GPU / NPU / CPU</b>. <b>Intel device = auto</b> prefers the
GPU, then the NPU, then the CPU.</li>
<li>The model is downloaded again for this backend (pre-converted
<code>OpenVINO/whisper-&hellip;-ov</code> models from Hugging Face) &mdash; a
one-time setup per model and precision.</li>
<li>GPU/NPU acceleration needs a current Intel graphics / NPU driver. If the
device cannot run the model, {APP_NAME} falls back to the CPU for the session
and shows a one-time notice.</li>
<li>Running from source, install the extra first:
<code>pip install -e ".[openvino]"</code> (or just
<code>pip install openvino-genai</code>). The portable Windows build ships it
already.</li>
<li>Not available on this backend: the <code>distil-&hellip;.en</code> model
presets and the VAD silence filter.</li>
</ul>
""",
    },
    {
        "id": "hotkey",
        "title": "The hotkey doesn't start recording",
        "body": f"""
<p>Another application may already use the same combination, or the global
listener could not grab it.</p>
<ul>
<li><b>Change it.</b> <b>Settings → General → Global hotkey</b>, click
<b>Change…</b> and press a new combination (a modifier chord such as
<code>Ctrl+Alt+Space</code> works best).</li>
<li><b>Hold (push-to-talk) mode:</b> if a key release is missed, recording can
seem stuck &mdash; stop it with the floating icon, the tray <b>Stop recording</b>
entry, or wait for the maximum recording length.</li>
<li><b>Linux:</b> global hotkeys need an X11 session (Wayland restricts global
key grabbing). <b>macOS:</b> grant {APP_NAME} the <b>Accessibility</b> permission.</li>
<li>Confirm the app is running &mdash; its icon sits in the system tray.</li>
</ul>
""",
    },
    {
        "id": "insert",
        "title": "The transcribed text isn't inserted",
        "body": """
<p>The text is inserted into whatever field currently has focus, using the
method set in <b>Settings → General → Insert text by</b>.</p>
<ul>
<li>Click into the target field first so it has the cursor, then record.</li>
<li>Some apps block programmatic paste. Switch <b>Insert text by</b> from
<b>Paste via clipboard</b> to <b>Simulate typing</b>.</li>
<li><b>Linux:</b> clipboard paste needs <code>xclip</code> or <code>xsel</code>
installed.</li>
<li>Nothing is lost: every transcript is also kept under
<b>Settings → History</b>, each with a <b>Copy</b> button.</li>
</ul>
""",
    },
    {
        "id": "models",
        "title": "First recording is slow / where are the models stored",
        "body": """
<p>Whisper models are downloaded from Hugging Face <b>on first use</b> (a
one-time setup that can take a few minutes for the larger models) and then
loaded from a local cache on every later run &mdash; there is no second
download.</p>
<ul>
<li>See or change the folder in <b>Settings → Whisper → Model download folder</b>
(empty = the default Hugging Face cache, shown there).</li>
<li>Smaller models (<code>tiny</code>, <code>base</code>, <code>small</code>) are
fast on the CPU; <code>medium</code> and <code>large-v3</code> are much happier
with a GPU.</li>
<li>Setting your spoken language explicitly (instead of auto-detect) improves
both accuracy and speed.</li>
</ul>
""",
    },
    {
        "id": "ssl",
        "title": "SSL certificate errors behind a corporate proxy",
        "body": f"""
<p>Corporate proxies often intercept HTTPS traffic with their own
(self-signed) certificate. {APP_NAME} does not trust it, so the model
download, the update check and the assistant fail with errors like
<code>CERTIFICATE_VERIFY_FAILED</code> or <code>SSLError</code>.</p>
<ul>
<li>Enable <b>Settings → General → Ignore SSL certificate errors (corporate
proxy)</b>. It disables TLS certificate verification for all of
{APP_NAME}&rsquo;s connections (model downloads from Hugging Face, the GitHub
update check, the assistant API) and takes effect immediately &mdash; no
restart needed.</li>
<li><b>Security note:</b> connections stay encrypted but are no longer
authenticated &mdash; a man-in-the-middle would not be detected. Only enable
this inside a network you trust, and leave it off otherwise.</li>
</ul>
""",
    },
    {
        "id": "assistant",
        "title": "Assistant (LLM) cleanup won't connect",
        "body": """
<p>The optional assistant sends the raw transcript to an OpenAI-compatible
<code>/chat/completions</code> endpoint and inserts the cleaned-up answer
instead. It is off by default.</p>
<ul>
<li>Enable it and set the endpoint under <b>Settings → Assistant</b>. The default
targets a local <a href="https://ollama.com">Ollama</a> at
<code>http://localhost:11434/v1</code>.</li>
<li>For Ollama: install it, then pull the model you configured, e.g.
<code>ollama pull llama3.2</code>, and make sure it is running.</li>
<li>Hosted services need an <b>API key</b>; most local servers do not.</li>
<li>If the assistant call fails, {app} inserts the raw transcript and shows a
notification &mdash; your dictation is never lost.</li>
</ul>
""".replace("{app}", APP_NAME),
    },
]


def help_html() -> str:
    """Assemble the full Help document as a single HTML string.

    Starts with a short lead paragraph and an automatically generated
    "jump to" list, followed by every topic under its own anchor. Suitable for
    ``QTextBrowser.setHtml`` (with ``setOpenExternalLinks(True)`` the external
    links open in the default browser and the in-page anchors scroll)."""
    parts: list[str] = [
        f"<p>Common questions and fixes for {APP_NAME}. External links open in "
        "your web browser.</p>",
        "<p><b>Jump to</b></p>",
        "<ul>",
    ]
    for topic in HELP_TOPICS:
        parts.append(f'<li><a href="#{topic["id"]}">{topic["title"]}</a></li>')
    parts.append("</ul>")
    for topic in HELP_TOPICS:
        parts.append("<hr>")
        parts.append(f'<h3><a name="{topic["id"]}"></a>{topic["title"]}</h3>')
        parts.append(topic["body"].strip())
    parts.append("<hr>")
    parts.append(
        f'<p>Still stuck? Visit the <a href="{REPO_URL}">project page</a> or '
        f'<a href="{REPO_URL}/issues">open an issue</a>.</p>'
    )
    return "\n".join(parts)
