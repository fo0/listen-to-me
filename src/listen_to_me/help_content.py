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

<p><b>Quick fix — works on any PC.</b> Open <b>Settings → Engine → Device</b> and
set it to <b>CPU</b>. No CUDA required. It is a bit slower but reliable; for the
small models the difference is minor.</p>

<p><b>Use the GPU (NVIDIA graphics cards only).</b> You need a recent NVIDIA
driver plus the CUDA&nbsp;12 runtime library <b>cuBLAS</b>. Either install the
CUDA Toolkit, or place the required DLLs next to <code>ListenToMe-*.exe</code>
or in a folder on your <code>PATH</code>. cuDNN is <b>no longer required</b> for
this backend &mdash; the CTranslate2 wheels since 4.6.3 (what this build uses)
are built without it; only an older CTranslate2 from a source install still
needs cuDNN&nbsp;9 for CUDA&nbsp;12.</p>

<p><b>Download links</b></p>
<ul>
<li>NVIDIA drivers &mdash; <a href="https://www.nvidia.com/Download/index.aspx">nvidia.com/Download</a></li>
<li>CUDA Toolkit 12.x &mdash; <a href="https://developer.nvidia.com/cuda-downloads">developer.nvidia.com/cuda-downloads</a></li>
<li>Advanced &mdash; the DLL also ships in the PyPI wheel
<a href="https://pypi.org/project/nvidia-cublas-cu12/">nvidia-cublas-cu12</a>
(cuDNN, only for CTranslate2 &lt; 4.6.3:
<a href="https://developer.nvidia.com/cudnn">developer.nvidia.com/cudnn</a> or
<a href="https://pypi.org/project/nvidia-cudnn-cu12/">nvidia-cudnn-cu12</a>)</li>
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
<li>Open <b>Settings → Engine → Backend</b> and select
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
        "id": "autostart",
        "title": "The app doesn't start with Windows (or you just can't see it)",
        "body": f"""
<p><b>Start with the system</b> (<b>Settings → General → Startup</b>) registers
{APP_NAME} with your user account&rsquo;s autostart. The line right below the
checkbox shows what the system really has on file &mdash; if it says
<b>Registered with Windows: &hellip;</b>, the entry is in place.</p>

<p><b>Windows can switch the entry off.</b> Task Manager
(<code>Ctrl+Shift+Esc</code>) &rarr; <b>Startup apps</b> lists it as
<b>Disabled</b> then, and no amount of re-registering changes that on its own
&mdash; the switch lives outside the entry. Set it to <b>Enabled</b> there, or
simply press <b>Save</b> in {APP_NAME}&rsquo;s settings once: with the checkbox
ticked, saving switches it back on. The same happens in
<b>Windows Settings → Apps → Startup</b>.</p>

<p><b>It may be running and just invisible.</b> Windows&nbsp;11 hides new tray
icons in the overflow (<b>^</b>) next to the clock: open it and drag the
{APP_NAME} icon onto the taskbar to pin it. With
<b>Start minimized to the system tray</b> ticked, no window opens at logon by
design &mdash; the floating icon (<b>Settings → Overlay</b>) or the tray icon is
then the only sign of life. Clicking the tray icon brings the window back.
Starting the app a second time never opens a second copy; it brings the running
one to the front.</p>

<p><b>Running from a source checkout?</b> Autostart needs the package to be
installed in the environment (<code>pip install -e .</code>), because the system
starts the command without your <code>PYTHONPATH</code>. {APP_NAME} probes this
and says so below the checkbox instead of registering something that would
silently do nothing.</p>

<p><b>Moved or replaced the program file?</b> A manually downloaded build under
a new name leaves the old path registered. {APP_NAME} detects that at startup
and rewrites the entry by itself &mdash; start it once from the new location.</p>

<p>If it still doesn&rsquo;t come up, check <code>listen-to-me.log</code> in the
config folder (tray menu &rarr; <b>Open config folder</b>): the startup line is
written there on every launch.</p>
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
<li>Nothing is lost: a transcript that could not be inserted is put on the
clipboard &mdash; just press <b>Ctrl+V</b> where you want it. Set when that
happens under <b>Settings → General → Copy the transcript to the clipboard</b>
(only on failure, always, or never).</li>
<li>If no field had the focus, the paste goes nowhere and the app cannot see
it. Set the option above to <b>Always</b>: every transcript then stays on the
clipboard and a notification (&ldquo;Copied to the clipboard: …&rdquo;)
confirms it, so <b>Ctrl+V</b> gets the text once you click into a field.</li>
<li>Every transcript is also kept under <b>Settings → History</b>, each with a
<b>Copy</b> button.</li>
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
<li>See or change the folder in <b>Settings → Engine → Model download folder</b>
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
<li><b>This includes updates</b>, which replace {APP_NAME}&rsquo;s own program
file: with the option on, the downloaded exe is no longer proven to come from
GitHub. It must still arrive over HTTPS from a GitHub host and match the
release&rsquo;s size and SHA256 &mdash; but those come from the same response as
the download link, so they prove the file arrived intact, not that it is
genuine. The install dialog says so before the download starts; if you would
rather not take that trade, leave the option off and download releases
manually.</li>
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
    {
        "id": "factory-reset",
        "title": "Start over: reset to factory settings",
        "body": f"""
<p>When a setting has been changed past the point of remembering what it was,
<b>Settings &rarr; General &rarr; Reset</b> puts all of them back to the values
{APP_NAME} shipped with and reopens the guided setup from the first launch.</p>
<ul>
<li>You are asked to confirm first &mdash; nothing happens until you do.</li>
<li>Hotkey, model, backend, microphone, floating icon, assistant and the app
integrations all go back to their defaults, and <b>autostart is switched
off</b>.</li>
<li><b>Kept:</b> your transcript history and every speech model already
downloaded &mdash; the setup does not download anything again.</li>
<li>Cancelling the wizard still leaves the defaults in place; the reset itself
cannot be undone.</li>
</ul>
""",
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
