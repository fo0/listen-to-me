"""Packaging self-test: verifies that all runtime dependencies are bundled and
that the Qt UI constructs without error.

Run with `ListenToMe.exe --selftest` (used by CI after the PyInstaller build).
Writes results to <tempdir>/listen-to-me-selftest.log and exits non-zero on
failure — the executable is windowed, so the log file is the reliable output.

gui_smoke() runs only the light, dependency-free checks (config/icon/keymap/UI
construction) and is what the Linux CI check job calls from source.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


# --------------------------------------------------------------- checks


def _config_roundtrip():
    from listen_to_me.config import Config

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(path=Path(tmp) / "config.json")
        assert cfg.first_run is True  # no config file existed → onboarding
        cfg["language"] = "de"
        cfg.save()
        reloaded = Config(path=cfg.path)
        assert reloaded["language"] == "de"
        assert reloaded.first_run is False  # file exists → no onboarding


def _config_defaults():
    from listen_to_me.config import DEFAULTS

    assert DEFAULTS["hotkey_mode"] in ("toggle", "hold")
    assert DEFAULTS["start_in_tray"] is False
    assert DEFAULTS["injection_mode"] in ("paste", "type")
    assert DEFAULTS["live_typing"] is False  # experimental, opt-in
    assert DEFAULTS["backend"] in ("faster-whisper", "openvino", "parakeet")
    assert DEFAULTS["openvino_device"] in ("auto", "cpu", "gpu", "npu")
    assert DEFAULTS["openvino_precision"] in ("int8", "fp16", "int4")
    assert DEFAULTS["parakeet_quantization"] in ("int8", "fp32")
    assert isinstance(DEFAULTS["beam_size"], int) and DEFAULTS["beam_size"] >= 1
    assert set(DEFAULTS["overlay"]) >= {"enabled", "show_preview", "live_preview", "preview_seconds"}
    assert {"update_check_on_start", "include_prereleases"} <= set(DEFAULTS)
    integrations = DEFAULTS["integrations"]
    assert set(integrations) >= {"mute_while_recording", "targets"}
    assert integrations["mute_while_recording"] is False  # opt-in feature
    assert isinstance(integrations["targets"], list)
    for target in integrations["targets"]:
        assert set(target) >= {"name", "enabled", "mode", "hotkey"}
        assert target["mode"] in ("hold", "toggle")


def _config_survives_corrupt_sections():
    """A stored value where the defaults have a nested section must not replace
    that section. `"overlay": null` used to survive the merge, and the very
    first access (Tray.start → cfg["overlay"]["enabled"]) then raised before any
    UI existed to report it — the app just didn't start."""
    import json

    from listen_to_me.config import DEFAULTS, Config

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "overlay": None,  # whole section nulled
                    "assistant": "nonsense",  # wrong type
                    "integrations": [1, 2],  # wrong type
                    "language": "de",  # a valid sibling must still apply
                }
            ),
            encoding="utf-8",
        )
        cfg = Config(path=path)
        assert cfg["language"] == "de"
        for section in ("overlay", "assistant", "integrations"):
            assert isinstance(cfg[section], dict), section
        assert cfg["overlay"]["enabled"] == DEFAULTS["overlay"]["enabled"]
        assert cfg["assistant"]["base_url"] == DEFAULTS["assistant"]["base_url"]
        # A nested dict that IS a dict still merges key by key.
        path.write_text(json.dumps({"overlay": {"preview_seconds": 9}}), encoding="utf-8")
        cfg = Config(path=path)
        assert cfg["overlay"]["preview_seconds"] == 9
        assert cfg["overlay"]["enabled"] == DEFAULTS["overlay"]["enabled"]


def _history_normalizes_entries():
    """The history file is untrusted input and its text goes straight into a
    QLabel. Entries whose "text" is not a non-empty string are dropped, so no
    renderer can be handed an int/list/None."""
    import json

    from listen_to_me.history import TranscriptHistory

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "history.json"
        path.write_text(
            json.dumps(
                [
                    {"time": 1.0, "text": "kept"},
                    {"time": 2.0, "text": 42},  # non-string
                    {"time": 3.0, "text": ["a"]},  # non-string
                    {"time": 4.0, "text": ""},  # empty
                    {"time": 5.0},  # missing
                    "not an entry",
                ]
            ),
            encoding="utf-8",
        )
        store = TranscriptHistory(path)
        entries = store.entries()
        assert [e["text"] for e in entries] == ["kept"]
        # Appending still works on top of a filtered file.
        store.add("second")
        assert [e["text"] for e in store.entries()] == ["second", "kept"]
        store.add("second")  # exact consecutive duplicate → ignored
        assert len(store.entries()) == 2


def _recorder_start_failure_resets():
    """A stream that opens but fails to start must leave the recorder idle.
    self._stream used to be assigned before start(), so `active` stayed True
    forever and every later recording raised "recording already active" — the
    hotkey was dead until the app restarted."""
    import sys as _sys
    import types

    from listen_to_me.audio import Recorder

    class _Stream:
        def __init__(self, **_kwargs):
            self.closed = False

        def start(self):
            raise OSError("device disappeared")

        def close(self):
            self.closed = True

    opened: list = []

    def _input_stream(**kwargs):
        stream = _Stream(**kwargs)
        opened.append(stream)
        return stream

    fake = types.ModuleType("sounddevice")
    fake.InputStream = _input_stream
    fake.CallbackStop = RuntimeError
    previous = _sys.modules.get("sounddevice")
    _sys.modules["sounddevice"] = fake
    try:
        recorder = Recorder()
        for _ in range(2):
            try:
                recorder.start()
            except OSError:
                pass
            else:
                raise AssertionError("expected the failing start() to raise")
            assert not recorder.active, "a failed start must not leave the recorder active"
        assert len(opened) == 2 and all(s.closed for s in opened)
    finally:
        if previous is None:
            del _sys.modules["sounddevice"]
        else:
            _sys.modules["sounddevice"] = previous


def _injector_paste_falls_back_to_typing():
    """A clipboard failure must not lose an already-transcribed text: paste mode
    falls back to simulated typing instead of propagating (which surfaced as a
    misleading "Transcription failed" notification)."""
    from listen_to_me.injector import Injector

    typed: list[str] = []

    class _Injector(Injector):
        def _paste(self, text):
            raise RuntimeError("clipboard is unavailable")

        def _type(self, text):
            typed.append(text)

    injector = _Injector({"injection_mode": "paste", "restore_clipboard": True})
    injector.insert("recovered text")
    assert typed == ["recovered text"]
    injector.insert("")  # empty stays a no-op
    assert typed == ["recovered text"]


def _theme_scrollbar_contrast():
    """The scroll-bar handle must be visible against the page it sits on.

    Several settings pages scroll and the horizontal bar is switched off, so the
    vertical handle is the *only* hint that a page continues below the fold — at
    the border colour it used to have (~1.3:1) it was effectively invisible.
    Pure arithmetic on the palette tokens, no rendering: 3:1 is the WCAG minimum
    for non-text UI components.
    """
    from listen_to_me.theme import _DARK, _LIGHT

    def _relative_luminance(hex_color: str) -> float:
        raw = hex_color.lstrip("#")
        channels = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def _contrast(a: str, b: str) -> float:
        la, lb = _relative_luminance(a), _relative_luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    for name, palette in (("light", _LIGHT), ("dark", _DARK)):
        for surface in ("window", "base"):
            ratio = _contrast(palette["scroll"], palette[surface])
            assert ratio >= 3.0, f"{name} scroll handle on {surface}: {ratio:.2f}:1"
        # The hover state must be a visible change, not a same-tone swap.
        assert _contrast(palette["scroll"], palette["muted"]) >= 1.3, name


def _integrations_noop():
    """With no enabled mute target (the default), the recording hooks must be a
    complete no-op and must not import pynput — so they stay safe on the
    headless CI runner that has no X display for pynput to attach to."""
    from listen_to_me.config import Config
    from listen_to_me.integrations import MuteIntegrations

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(path=Path(tmp) / "config.json")
        mute = MuteIntegrations(cfg)
        assert mute._active_targets() == []  # default Discord preset is disabled
        mute.on_recording_start()
        mute.on_recording_stop()
        mute.reset()


def _single_instance_guard():
    """The OS-level guard (mutex on Windows, flock elsewhere) admits exactly
    one holder; a refused second acquire pings the winner's activation
    callback, while foreign garbage on the activation port never does. Lock
    dir, mutex name and port are scoped to this test so a really-running app
    is never disturbed (port=0 → OS-assigned)."""
    import socket
    import threading

    from listen_to_me import singleinstance

    with tempfile.TemporaryDirectory() as tmp:
        name = f"ListenToMe.SelfTest.{os.getpid()}"
        first = singleinstance.acquire(port=0, lock_dir=Path(tmp), mutex_name=name)
        assert first is not None
        try:
            hits: list = []
            fired = threading.Event()

            def on_activate():
                hits.append(1)
                fired.set()

            port = first.start_server(on_activate)
            assert port, "activation server must bind an OS-assigned port"

            # Garbage first: the server handles connections sequentially, so
            # this is fully processed before the real ping below is accepted.
            with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
                conn.sendall(b"GET / HTTP/1.0\r\n\r\n")

            second = singleinstance.acquire(port=port, lock_dir=Path(tmp), mutex_name=name)
            assert second is None  # guard held → refused
            assert fired.wait(5.0), "activation ping never reached the holder"
            assert hits == [1]  # the garbage connection must not have fired it
        finally:
            first.release()  # unlock so the temp dir can be removed on Windows


def _icon_render():
    from listen_to_me.icons import mic_image

    assert mic_image("recording", 64).size == (64, 64)
    assert mic_image("app", 256).size == (256, 256)


def _band_levels():
    """Needs numpy, so this runs only in the full (packaged) self-test."""
    import numpy as np

    from listen_to_me.audio import SAMPLE_RATE, band_levels

    t = np.arange(SAMPLE_RATE // 10, dtype="float32") / SAMPLE_RATE
    low, mid, high = band_levels(0.2 * np.sin(2 * np.pi * 220.0 * t))
    assert low > 0.5 and low > mid and low > high  # 220 Hz lands in the low band
    assert band_levels(np.zeros(SAMPLE_RATE // 10, dtype="float32")) == (0.0, 0.0, 0.0)


def _hotkey_default_valid():
    from listen_to_me.config import DEFAULTS
    from listen_to_me.hotkeys import Hotkeys

    assert Hotkeys.validate(DEFAULTS["hotkey"])
    # combo_flags drives the live-typing hold-mode gate: the default chord has
    # modifiers AND a typable key (Space), a bare F-key has neither.
    assert Hotkeys.combo_flags(DEFAULTS["hotkey"]) == (True, True)
    assert Hotkeys.combo_flags("<f9>") == (False, False)
    assert Hotkeys.combo_flags("<ctrl>+<f9>") == (True, False)
    assert Hotkeys.combo_flags("<ctrl>+m") == (True, True)
    assert Hotkeys.combo_flags("not a combo") == (True, True)  # unparseable → unsafe


def _live_typing_logic():
    """The live-typing agreement policy commits only segments that two
    consecutive passes agree on (and that end before the tail guard), text is
    sanitized so no control character can ever reach the keyboard, and the
    pending/typed bookkeeping survives a modifier-deferred flush — all without
    pynput (the keyboard is stubbed)."""
    from listen_to_me.injector import sanitize_typed_text
    from listen_to_me.livetype import LiveTyper, stable_prefix

    # Sanitize: whitespace runs (incl. Enter/Tab) collapse to single spaces,
    # control characters vanish — only printable text can be typed.
    assert sanitize_typed_text("hello\nworld\tfoo") == "hello world foo"
    assert sanitize_typed_text("  a \r\n b \x07 c ") == "a b c"
    assert sanitize_typed_text("\n\t\x00") == ""

    prev = [(2.0, "Hello world."), (4.0, "How are")]
    cur = [(2.1, "Hello world."), (4.5, "How are you")]
    assert stable_prefix(prev, cur, max_end=10.0) == (["Hello world."], 2.1)
    # Tail guard: a segment ending too close to the snapshot end never commits.
    assert stable_prefix(prev, cur, max_end=1.0) == ([], 0.0)
    # Flicker between passes commits nothing.
    assert stable_prefix([(2.0, "Hallo")], [(2.0, "Hello")], max_end=10.0) == ([], 0.0)
    assert stable_prefix([], cur, max_end=10.0) == ([], 0.0)

    class _StubInjector:
        def __init__(self):
            self.typed: list = []
            self.defer = False

        def type_plain(self, text):
            if self.defer:
                return text
            self.typed.append(text)
            return ""

    class _StubTypeApp:
        def __init__(self):
            self.injector = _StubInjector()

        def _take_active(self, recording_id):
            return False

    lt = LiveTyper(_StubTypeApp(), 1, post_preview=False)
    lt.pending = "hello"
    lt.app.injector.defer = True  # modifier held: nothing may go out
    lt._flush_pending()
    assert lt.pending == "hello" and lt.typed_any is False
    lt.app.injector.defer = False
    lt._flush_pending()
    assert lt.app.injector.typed == ["hello"] and lt.typed_any and lt.pending == ""
    lt.pending = "world"
    lt._flush_pending()  # later chunks get a separating space
    assert lt.app.injector.typed == ["hello", " world"] and lt.pending == ""


def _key_mapping():
    from PySide6.QtCore import Qt

    from listen_to_me.keymap import allowed_standalone, key_token

    assert key_token(Qt.Key.Key_Space) == "<space>"
    assert key_token(Qt.Key.Key_F9) == "<f9>"
    assert key_token(Qt.Key.Key_F21) is None  # pynput only defines f1..f20
    assert key_token(Qt.Key.Key_A) == "a"
    assert key_token(Qt.Key.Key_5) == "5"
    assert key_token(Qt.Key.Key_Comma) == ","
    assert allowed_standalone("<f9>") and not allowed_standalone("a")


def _autostart_refresh():
    """An autostart entry that outlived a program-file move is detected (and
    rewritten by sync()), while a still-valid one — including the in-app
    updater's same-path swap and a source checkout next to an installed build —
    is left alone."""
    from listen_to_me import autostart

    original = autostart._launch_args
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "ListenToMe old.exe"  # the space exercises the quoting
        new = Path(tmp) / "ListenToMe-2026-07-27-1200-win64.exe"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        try:
            autostart._launch_args = lambda: [str(new)]
            # Same path as the running build: the self-update case, nothing to do.
            assert autostart._refresh_reason(autostart._launch_command()) is None
            # A manually downloaded build placed next to the old one.
            assert autostart._refresh_reason(f'"{old}"') is not None
            # ... and the old exe renamed/moved away entirely.
            old.unlink()
            assert autostart._refresh_reason(f'"{old}"') is not None
            assert autostart._refresh_reason("") is not None
            # Running from source must not hijack an installed build's entry.
            autostart._launch_args = lambda: [sys.executable, "-m", "listen_to_me"]
            assert autostart._refresh_reason(f'"{new}"') is None
            assert autostart._refresh_reason(autostart._launch_command()) is None
        finally:
            autostart._launch_args = original


def _updater_logic():
    from listen_to_me import updater

    assert updater.parse_version("v2026.07.19.11") == (2026, 7, 19, 11)
    assert updater.parse_version("0.0.0.dev0") == (0, 0, 0, 0)
    assert updater.parse_version("v2026.07.19.11") > updater.parse_version("v2026.07.19.5")

    def mk(tag):
        return updater.Release(
            tag=tag, name=tag, body="", published_at="2026-01-02T00:00:00Z",
            html_url="", prerelease=False, asset_url="x", asset_name="a.exe",
        )

    rels = [mk("v2026.07.19.11"), mk("v2026.07.19.7"), mk("v2026.07.19.3")]
    newer = updater.newer_releases(rels, current=(2026, 7, 19, 5))
    assert [r.tag for r in newer] == ["v2026.07.19.11", "v2026.07.19.7"]
    assert updater.download_path_for(Path("/x/ListenToMe.exe")).name == "ListenToMe.update.exe"

    # The relaunch chain must not inherit PyInstaller's bootloader variables,
    # or the updated exe reuses (and misses) the dying process's unpack dir.
    os.environ["_PYI_ARCHIVE_FILE"] = "x"
    os.environ["_MEIPASS2"] = "y"
    try:
        env = updater._swap_env()
        assert "_PYI_ARCHIVE_FILE" not in env and "_MEIPASS2" not in env
        assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    finally:
        del os.environ["_PYI_ARCHIVE_FILE"], os.environ["_MEIPASS2"]

    # Startup cleanup: stale downloads and old swap scripts go, fresh ones stay.
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "ListenToMe.exe"
        stale_exe = updater.download_path_for(target)
        stale_exe.write_bytes(b"x")
        old_bat = Path(tmp) / "listen-to-me-update-11111.bat"
        old_bat.write_bytes(b"@echo off")
        os.utime(old_bat, times=(0, 0))
        fresh_bat = Path(tmp) / "listen-to-me-update-22222.bat"
        fresh_bat.write_bytes(b"@echo off")
        updater.cleanup_stale_update(target, temp_dir=Path(tmp))
        assert not stale_exe.exists() and not old_bat.exists()
        assert fresh_bat.exists()
        updater.cleanup_stale_update(target, temp_dir=Path(tmp))  # idempotent, no error

    # A truncated or corrupted download must be rejected before the swap.
    import hashlib

    with tempfile.TemporaryDirectory() as tmp:
        blob = Path(tmp) / "asset.bin"
        blob.write_bytes(b"listen-to-me")
        good = "sha256:" + hashlib.sha256(b"listen-to-me").hexdigest()
        updater.verify_download(blob, expected_size=len(b"listen-to-me"), expected_digest=good)
        updater.verify_download(blob)  # metadata absent -> best effort, no error
        for bad in ({"expected_size": 11}, {"expected_digest": "sha256:" + "0" * 64}):
            try:
                updater.verify_download(blob, **bad)
                raise AssertionError(f"verify_download accepted {bad}")
            except ValueError:
                pass


def _updater_forces_tls_verification():
    """The update path never honours the insecure-SSL switch: the releases API
    call and the asset download must both pass verify=True even while it is on,
    and a certificate failure must surface as an explaining UpdateTrustError
    instead of a bare SSLError. requests is faked at the module boundary — it is
    absent in the light CI env, and silently inheriting netutil.verify() here is
    exactly the regression this guards against."""
    import types

    from listen_to_me import netutil, updater

    asset_url = "https://github.com/fo0/listen-to-me/releases/download/v1/ListenToMe.exe"
    calls: list[dict] = []
    failing: list[bool] = []

    class _SSLError(Exception):
        pass

    class _Response:
        headers: dict = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def raise_for_status(self):
            pass

        def json(self):
            return []

        def iter_content(self, chunk_size=0):
            return iter((b"payload",))

    def _get(url, **kwargs):
        calls.append(dict(kwargs, url=url))
        if failing:
            raise _SSLError("certificate verify failed")
        return _Response()

    fake = types.ModuleType("requests")
    fake.get = _get
    fake.exceptions = types.SimpleNamespace(SSLError=_SSLError)
    saved = sys.modules.get("requests")
    sys.modules["requests"] = fake
    try:
        netutil.apply_insecure_ssl(True)
        assert netutil.verify() is False  # the switch really is on for everyone else
        with tempfile.TemporaryDirectory() as tmp:
            updater.fetch_releases()
            updater.download_asset(asset_url, Path(tmp) / "asset.exe")
            assert len(calls) == 2
            assert all(call["verify"] is True for call in calls)

            failing.append(True)
            for attempt in (
                lambda: updater.fetch_releases(),
                lambda: updater.download_asset(asset_url, Path(tmp) / "asset.exe"),
            ):
                try:
                    attempt()
                    raise AssertionError("a certificate failure was not surfaced")
                except updater.UpdateTrustError as exc:
                    # Explains itself instead of failing silently, and says so
                    # while the switch that would "have covered this" is on.
                    assert "does not cover updates" in str(exc)
                    assert "release page" in str(exc)
    finally:
        netutil.apply_insecure_ssl(False)
        if saved is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = saved


def _insecure_ssl_switch():
    """The insecure-SSL switch flips the requests verify flag both ways and
    never raises — even when urllib3/huggingface_hub are unavailable (their
    reconfiguration is best-effort at this layer)."""
    from listen_to_me import netutil

    assert netutil.verify() is True
    netutil.apply_insecure_ssl(True)
    try:
        assert netutil.verify() is False
    finally:
        netutil.apply_insecure_ssl(False)
    assert netutil.verify() is True


def _insecure_ssl_hub_httpx():
    """netutil drives huggingface_hub >= 1.0 (httpx-based) through
    set_client_factory: enabling installs the insecure client factory,
    disabling restores the hub's own default factory. The hub is faked at the
    module boundary — the real package is absent in the light CI env, and the
    v0.x code path silently doing nothing on v1.x is exactly the bug this
    guards against."""
    import types

    from listen_to_me import netutil

    calls: list = []
    hub = types.ModuleType("huggingface_hub")
    hub.set_client_factory = calls.append
    hub_utils = types.ModuleType("huggingface_hub.utils")
    hub_http = types.ModuleType("huggingface_hub.utils._http")

    def default_client_factory():
        raise AssertionError("factory is only installed, never called here")

    hub_http.default_client_factory = default_client_factory
    hub.utils = hub_utils
    hub_utils._http = hub_http
    names = ("huggingface_hub", "huggingface_hub.utils", "huggingface_hub.utils._http")
    saved = {name: sys.modules.get(name) for name in names}
    sys.modules.update({names[0]: hub, names[1]: hub_utils, names[2]: hub_http})
    try:
        netutil.apply_insecure_ssl(True)
        netutil.apply_insecure_ssl(False)
    finally:
        netutil.apply_insecure_ssl(False)
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    assert calls == [netutil._insecure_hub_client, default_client_factory]


def _std_stream_stub():
    """A --windowed PyInstaller build has sys.stdout/sys.stderr = None; the
    stub replaces them with devnull streams so library writes (e.g.
    huggingface_hub's tqdm progress bar during a model download) are no-ops
    instead of crashing the transcription."""
    from listen_to_me.app import _ensure_std_streams

    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stdout = None
        sys.stderr = None
        _ensure_std_streams()
        assert sys.stdout is not None and sys.stderr is not None
        sys.stdout.write("must not raise\n")
        sys.stderr.write("must not raise\n")
    finally:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and stream is not saved_out and stream is not saved_err:
                try:
                    stream.close()
                except Exception:
                    pass
        sys.stdout, sys.stderr = saved_out, saved_err


def _transcriber_cache_probe():
    """`_model_is_cached` recognises a local model directory as ready and treats
    an unknown model id as "needs download", so ensure_loaded's notification says
    "Loading…" vs "Downloading…" correctly. Runs without faster-whisper: the
    id-branch import failure is swallowed and reported as not-cached, and the
    offline probe never touches the network."""
    from listen_to_me.transcriber import _model_is_cached

    with tempfile.TemporaryDirectory() as tmp:
        assert _model_is_cached(tmp, None) is True  # a real directory is a model
        assert _model_is_cached("no-such-whisper-model-xyz", tmp) is False


def _cuda_error_detection():
    """The GPU-unavailable errors are recognised (so they trigger the CPU
    fallback / actionable message); unrelated errors and transient GPU
    out-of-memory are not."""
    from listen_to_me.transcriber import is_cuda_library_error

    assert is_cuda_library_error(
        RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
    )
    assert is_cuda_library_error(Exception("Unable to load cudnn_ops64_9.dll"))
    assert is_cuda_library_error("CUDA driver version is insufficient for CUDA runtime")
    assert not is_cuda_library_error(RuntimeError("No speech detected"))
    assert not is_cuda_library_error(ValueError("some unrelated failure"))
    # Transient OOM must NOT be treated as "GPU unavailable" — it would wrongly
    # force the CPU for the whole session with a "libraries missing" message.
    assert not is_cuda_library_error(RuntimeError("CUDA failed with error out of memory"))


def _transcriber_cpu_fallback():
    """A CUDA library failure forces the transcriber onto the CPU for the
    session (relaxing a GPU-only compute type); changing the configured device
    auto-expires the fallback; a non-CUDA error never triggers it — all without
    importing faster-whisper."""
    from listen_to_me.config import Config
    from listen_to_me.transcriber import Transcriber

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(path=Path(tmp) / "config.json")
        cfg["device"] = "auto"
        cfg["compute_type"] = "float16"  # GPU-only
        t = Transcriber(cfg)
        assert t._current_key()[1] == "auto"

        forced = t._maybe_force_cpu("auto", RuntimeError("cublas64_12.dll cannot be loaded"), None)
        assert forced is True
        assert t._current_key()[1] == "cpu"
        assert t._current_key()[2] == "auto"  # GPU-only precision relaxed

        # Changing the configured device auto-expires the fallback (no explicit
        # reset needed); the same key is always internally consistent.
        cfg["device"] = "cuda"
        assert t._current_key()[1] == "cuda"
        assert t._current_key()[2] == "float16"
        cfg["device"] = "auto"  # re-selecting the failed config re-applies it
        assert t._current_key()[1] == "cpu"

        # A non-CUDA error must not force a CPU fallback, and a load already on
        # the CPU is never "recovered" onto the CPU again.
        t2 = Transcriber(cfg)
        assert t2._maybe_force_cpu("auto", RuntimeError("disk full"), None) is False
        assert t2._maybe_force_cpu("cpu", RuntimeError("cublas missing"), None) is False


def _openvino_backend_logic():
    """The OpenVINO backend maps model presets to the pre-converted Hugging
    Face repos, refuses the presets that have no OpenVINO conversion, is picked
    by the backend factory, and mirrors the session CPU fallback — all without
    importing openvino/openvino_genai (they stay lazy)."""
    from listen_to_me.config import Config
    from listen_to_me.transcriber import Transcriber, create_transcriber
    from listen_to_me.transcriber_openvino import OpenVinoTranscriber, openvino_model_repo

    assert openvino_model_repo("small", "int8") == "OpenVINO/whisper-small-int8-ov"
    assert (
        openvino_model_repo("large-v3-turbo", "fp16") == "OpenVINO/whisper-large-v3-turbo-fp16-ov"
    )
    assert openvino_model_repo("distil-large-v3", "int8") == "OpenVINO/distil-whisper-large-v3-int8-ov"
    assert openvino_model_repo("base.en", "int4") == "OpenVINO/whisper-base.en-int4-ov"
    assert openvino_model_repo("Someone/custom-ov", "int8") == "Someone/custom-ov"  # verbatim
    try:
        openvino_model_repo("distil-small.en", "int8")
        raise AssertionError("expected ValueError for a preset without an OpenVINO conversion")
    except ValueError:
        pass
    try:
        openvino_model_repo("distil-large-v3.5", "int8")
        raise AssertionError("expected ValueError for a preset without an OpenVINO conversion")
    except ValueError:
        pass
    from listen_to_me.choices import GERMAN_TURBO_CT2

    try:
        # The German CT2 preset must not fall into the verbatim repo-id branch.
        openvino_model_repo(GERMAN_TURBO_CT2, "int8")
        raise AssertionError("expected ValueError for the CT2-only German preset")
    except ValueError:
        pass

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(path=Path(tmp) / "config.json")
        assert isinstance(create_transcriber(cfg), Transcriber)  # default backend
        cfg["backend"] = "openvino"
        t = create_transcriber(cfg)
        assert isinstance(t, OpenVinoTranscriber) and t.backend == "openvino"

        # A GPU/NPU failure forces the CPU for the session; changing the
        # configured device OR precision auto-expires the fallback (mirrors
        # the CUDA path, where compute_type is part of the fallback key).
        assert t._current_key()[2] == "auto"
        assert t._maybe_force_cpu("GPU", RuntimeError("compile failed"), None) is True
        assert t._current_key()[2] == "cpu"
        cfg["openvino_device"] = "npu"
        assert t._current_key()[2] == "npu"
        cfg["openvino_device"] = "auto"  # re-selecting the failed config re-applies it
        assert t._current_key()[2] == "cpu"
        cfg["openvino_precision"] = "fp16"  # a different precision may work on the device
        assert t._current_key()[2] == "auto"
        cfg["openvino_precision"] = "int8"
        assert t._current_key()[2] == "cpu"

        # Already on the CPU there is nothing to fall back to.
        t2 = create_transcriber(cfg)
        assert t2._maybe_force_cpu("CPU", RuntimeError("anything"), None) is False


def _parakeet_backend_logic():
    """The Parakeet backend is picked by the factory, resolves ONNX Runtime
    execution providers with a guaranteed CPU fallback, maps the quantization
    config value and re-keys on quantization/device/model_dir changes — all
    without importing onnx_asr (it stays lazy)."""
    from listen_to_me.config import Config
    from listen_to_me.transcriber import create_transcriber
    from listen_to_me.transcriber_parakeet import (
        ParakeetTranscriber,
        _quantization,
        _resolve_providers,
    )

    assert _quantization("int8") == "int8"
    assert _quantization("fp32") is None  # onnx-asr spelling for "unquantized"
    assert _quantization("") == "int8"

    assert _resolve_providers("cpu") == ["CPUExecutionProvider"]
    for device in ("auto", "cuda", "cpu"):
        # Whatever the device and installed onnxruntime build, the CPU provider
        # is always the last resort — a missing GPU degrades, never errors.
        assert _resolve_providers(device)[-1] == "CPUExecutionProvider"

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(path=Path(tmp) / "config.json")
        cfg["backend"] = "parakeet"
        t = create_transcriber(cfg)
        assert isinstance(t, ParakeetTranscriber) and t.backend == "parakeet"
        assert t.loaded is False
        # No segment previews → live typing stays gated off for this backend.
        assert not hasattr(t, "preview_segments")
        key = t._current_key()
        cfg["parakeet_quantization"] = "fp32"
        assert t._current_key() != key  # quantization change → reload


def _diagnostics_engine():
    """The Settings diagnostics engine builds a transcriber from a plain
    UI-snapshot dict, caches it while the snapshot is unchanged and rebuilds
    it when a value (or the backend) changes — without importing any heavy
    runtime dependency (faster-whisper/openvino stay lazy)."""
    from listen_to_me.diagnostics import DiagnosticsEngine
    from listen_to_me.transcriber import Transcriber
    from listen_to_me.transcriber_openvino import OpenVinoTranscriber

    snapshot = {
        "backend": "faster-whisper",
        "model": "small",
        "device": "cpu",
        "compute_type": "auto",
        "model_dir": None,
        "language": "auto",
        "initial_prompt": "",
        "vad_filter": True,
        "openvino_device": "auto",
        "openvino_precision": "int8",
    }
    engine = DiagnosticsEngine()
    first = engine._transcriber_for(snapshot)
    assert isinstance(first, Transcriber)
    assert engine._transcriber_for(dict(snapshot)) is first  # unchanged → cached
    second = engine._transcriber_for(dict(snapshot, model="base"))
    assert second is not first
    ov = engine._transcriber_for(dict(snapshot, backend="openvino"))
    assert isinstance(ov, OpenVinoTranscriber)


def _hardware_probes():
    """The status-card probes never raise and degrade to honest "not found"
    answers on a machine without ctranslate2/openvino (like the light CI
    runner); the model cache probe recognises a local directory as downloaded
    and reports the presets without an OpenVINO conversion as an error."""
    from listen_to_me.diagnostics import (
        hardware_status,
        model_cache_status,
        probe_cuda,
        probe_openvino,
    )

    cuda = probe_cuda()
    assert set(cuda) == {"available", "count", "error"}
    assert isinstance(cuda["available"], bool) and cuda["count"] >= 0

    ov = probe_openvino()
    assert set(ov) == {"installed", "devices", "error"}
    assert isinstance(ov["installed"], bool) and isinstance(ov["devices"], list)

    with tempfile.TemporaryDirectory() as tmp:
        snap = {
            "backend": "faster-whisper",
            "model": tmp,  # a local directory counts as a downloaded model
            "model_dir": None,
            "openvino_precision": "int8",
        }
        assert model_cache_status(snap) == {"target": tmp, "cached": True, "error": None}
        missing = model_cache_status(
            dict(snap, model="no-such-whisper-model-xyz", model_dir=tmp)
        )
        assert missing["cached"] is False and missing["error"] is None
        ov_local = model_cache_status(dict(snap, backend="openvino"))
        assert ov_local == {"target": tmp, "cached": True, "error": None}
        no_conversion = model_cache_status(
            dict(snap, backend="openvino", model="distil-small.en")
        )
        assert no_conversion["cached"] is False and no_conversion["error"]
        from listen_to_me.transcriber_parakeet import MODEL_REPO

        # A custom model dir without the Parakeet subfolder is decisively
        # "not downloaded" (the HF-cache probe depends on the machine).
        pk = model_cache_status(
            dict(snap, backend="parakeet", parakeet_quantization="int8", model_dir=tmp)
        )
        assert pk == {"target": MODEL_REPO, "cached": False, "error": None}

        assert set(hardware_status(snap)) == {"cuda", "openvino", "model"}


def _clip_stats_verdicts():
    """clip_stats classifies a recorded clip: silence, a too-quiet signal and
    normal speech levels get distinct verdicts (drives the microphone test's
    result message). Needs numpy, so this runs only in the full self-test."""
    import numpy as np

    from listen_to_me.audio import SAMPLE_RATE
    from listen_to_me.diagnostics import clip_stats

    silent = clip_stats(np.zeros(SAMPLE_RATE, dtype="float32"))
    assert silent["verdict"] == "silent" and silent["peak"] == 0.0
    t = np.arange(SAMPLE_RATE, dtype="float32") / SAMPLE_RATE
    quiet = clip_stats((0.02 * np.sin(2 * np.pi * 220.0 * t)).astype("float32"))
    assert quiet["verdict"] == "quiet"
    ok = clip_stats((0.3 * np.sin(2 * np.pi * 220.0 * t)).astype("float32"))
    assert ok["verdict"] == "ok" and 0.0 < ok["rms"] < ok["peak"] <= 1.0
    assert clip_stats(np.zeros(0, dtype="float32"))["verdict"] == "silent"


def _help_content_renders():
    """The Help page renders to HTML with the CUDA content, working download
    links, and a table-of-contents entry plus anchor for every topic."""
    from listen_to_me import help_content

    html = help_content.help_html()
    assert "cublas" in html.lower()
    assert "developer.nvidia.com/cuda-downloads" in html
    assert help_content.HELP_TOPICS, "expected at least one help topic"
    for topic in help_content.HELP_TOPICS:
        assert topic["id"] and topic["title"] and topic["body"].strip()
        assert f'href="#{topic["id"]}"' in html  # table-of-contents link
        assert f'name="{topic["id"]}"' in html  # scroll target


def _ensure_qapp():
    """A QApplication must exist before any QPixmap/QWidget is created. Create
    one on a display-less platform (offscreen off Windows; Windows works headless
    with its native plugin) and reuse it for the rest of the process."""
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _qt_icons():
    _ensure_qapp()  # QPixmap requires a QGuiApplication to exist first
    from listen_to_me.qtutil import tray_icon

    for state in ("idle", "recording", "processing"):
        assert not tray_icon(state).isNull()


def _glyph_icons():
    """Every painted sidebar/Home glyph renders to a non-empty pixmap."""
    _ensure_qapp()
    from listen_to_me.glyphs import GLYPH_NAMES, glyph_icon, glyph_pixmap

    for name in GLYPH_NAMES:
        assert not glyph_pixmap(name, "#888888").isNull(), name
    assert not glyph_icon("home", "#888888", "#4f6ef7").isNull()


def _voice_mic_widget():
    """Render the animated overlay icon through a few ticks in every state."""
    _ensure_qapp()
    from listen_to_me.voice_mic_widget import VoiceMicWidget

    widget = VoiceMicWidget()
    widget.setFixedSize(64, 64)
    widget.set_recording(True)
    widget.set_levels(0.8, 0.5, 0.2)
    for _ in range(5):
        widget._on_tick()
    assert not widget.grab().isNull()
    widget.set_recording(False)
    widget.set_processing(True)
    widget._on_tick()
    assert not widget.grab().isNull()
    widget.deleteLater()


class _StubApp:
    """Minimal stand-in for App, exposing just what the widgets read on
    construction. Backed by a real Config/TranscriptHistory in a temp dir."""

    def __init__(self, tmp: Path):
        from listen_to_me.config import Config
        from listen_to_me.history import TranscriptHistory

        self.cfg = Config(path=tmp / "config.json")
        self.history = TranscriptHistory(tmp / "history.json")
        self.history.add("A stored transcript for the self-test.")
        # Out-of-range timestamp (OverflowError in time.localtime): rendering
        # it must lose only the stamp — the Home page builds the recent list
        # during SettingsWindow construction, so a corrupt history.json must
        # never make the main window unconstructable.
        self.history.add("An entry with a corrupt timestamp.", timestamp=1e300)
        self.hotkeys = _StubHotkeys()
        self.posts: list = []  # events the UI posted (asserted by the tests)

    def post(self, *args, **kwargs):
        self.posts.append(args)

    def _register_hotkey(self):
        pass

    def apply_settings(self):
        pass


class _StubHotkeys:
    def stop(self):
        pass


def _gui_construction():
    from listen_to_me.onboarding import OnboardingWizard
    from listen_to_me.overlay import Overlay
    from listen_to_me.settings_ui import SettingsWindow
    from listen_to_me.theme import apply_theme
    from listen_to_me.widgets import HotkeyCaptureDialog

    app = _ensure_qapp()
    apply_theme(app)

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))

        window = SettingsWindow(stub)
        # Sidebar has non-selectable section headers, so nav rows and stack
        # indexes differ; the Home hub is preselected and _show_page maps by title.
        assert window.nav.currentRow() == window._nav_row["Home"]
        assert window.stack.currentIndex() == window._home_index

        # Home hub: the hotkey renders as key caps, the stored transcript is
        # listed, and the hero mirrors every app state (posted by App via
        # set_app_state). isHidden() not isVisible(): the window isn't shown.
        from PySide6.QtWidgets import QLabel

        from listen_to_me.home_page import pretty_keys

        assert pretty_keys("<ctrl>+<alt>+<space>") == ["Ctrl", "Alt", "Space"]
        assert pretty_keys("<f9>") == ["F9"]
        assert pretty_keys("<ctrl>++") == ["Ctrl", "+"]  # literal plus key kept
        assert pretty_keys("") == []
        assert window.home._chips_row.count() >= 1
        recent_text = " ".join(
            label.text() for label in window.home._recent_frame.findChildren(QLabel)
        )
        assert "A stored transcript" in recent_text
        window.set_app_state("recording")
        assert "Stop" in window.home.record_button.text()
        assert not window.home.cancel_button.isHidden()
        window.set_app_state("processing")
        assert not window.home.record_button.isEnabled()
        window.set_app_state("idle")
        assert window.home.record_button.isEnabled()
        assert window.home.cancel_button.isHidden()

        # Record-button debounce: a double-click emits two clicked signals
        # before the event poll runs — only ONE toggle may be posted, or the
        # recording would start and instantly stop ("too short").
        posts_before = len(stub.posts)
        window.home._toggle()
        window.home._toggle()  # the double-click's second click
        assert stub.posts[posts_before:] == [("toggle",)]

        # The language card must not show the (ignored) Whisper language for
        # the Parakeet backend — Parakeet always auto-detects.
        stub.cfg.data["backend"] = "parakeet"
        window.home.refresh()
        assert window.home.card_language.value.text() == "Auto-detect"
        stub.cfg.data["backend"] = "faster-whisper"
        window.home.refresh()

        window._show_page("History")  # force History render (lazy on first view)
        assert window.stack.currentIndex() == window._history_index
        window._refresh_history()

        # Replaced transcript rows must be DETACHED, not just taken out of the
        # layout: deleteLater only frees them once the event loop runs, and a
        # still-parented row keeps painting as a ghost behind the rebuilt list
        # (a finished dictation re-renders this page live).
        rows = [
            window._history_layout.itemAt(i).widget()
            for i in range(window._history_layout.count())
            if window._history_layout.itemAt(i).widget() is not None
        ]
        assert rows, "expected at least one rendered transcript row"
        window._refresh_history()

        def _detached(widget) -> bool:
            try:
                return widget.parent() is None
            except RuntimeError:
                return True  # already deleted — it cannot paint either

        assert all(_detached(row) for row in rows)

        # The Parakeet backend ignores the Whisper preset, the spoken language
        # and the initial prompt — those inputs must read as inactive instead of
        # silently doing nothing. (Values are kept, so the dialog stays clean.)
        window.backend_combo.setCurrentIndex(2)  # Parakeet
        assert not window.model_combo.isEnabled()
        assert not window.language_combo.isEnabled()
        assert not window.initial_prompt_edit.isEnabled()
        assert not window.chk_live_typing.isEnabled()
        # …and the card says WHY, or the greyed-out fields just look broken.
        assert "Parakeet" in window._speech_hint.text()
        window.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        assert window.language_combo.isEnabled() and window.initial_prompt_edit.isEnabled()
        assert window.model_combo.isEnabled() and window.chk_live_typing.isEnabled()
        assert "Parakeet" not in window._speech_hint.text()

        # A live OS light/dark switch repaints the code-drawn icons (the palette
        # and QSS are theme.py's job): they used to keep the colours they were
        # built with until the window was reopened.
        quick_button, _quick_glyph = window.home._glyph_buttons[0]
        themed = quick_button.icon().pixmap(20, 20).toImage()
        window.home.restyle_icons("#ff0000", "#00ff00")
        assert quick_button.icon().pixmap(20, 20).toImage() != themed
        window._on_color_scheme_changed()
        assert not quick_button.icon().isNull()
        assert not window.nav.item(window._nav_row["Whisper"]).icon().isNull()
        assert window._help_browser.toPlainText().strip()

        # This is the app's main window, not a preferences dialog: a plain
        # QDialog offers only a close button, so it could neither be minimized
        # to the taskbar nor maximized.
        from PySide6.QtCore import Qt as _Qt

        assert window.windowFlags() & _Qt.WindowType.WindowMinimizeButtonHint
        assert window.windowFlags() & _Qt.WindowType.WindowMaximizeButtonHint

        # Unsaved-changes tracking: untouched dialog is clean, a toggled
        # checkbox makes it dirty, toggling back makes it clean again.
        assert window._collect() == window._saved_snapshot
        window.chk_beep.setChecked(not window.chk_beep.isChecked())
        assert window._collect() != window._saved_snapshot
        window.chk_beep.setChecked(not window.chk_beep.isChecked())
        assert window._collect() == window._saved_snapshot

        # Read-only dropdowns: free text typed into the (formerly editable)
        # model combo was saved verbatim as the model id and failed only at
        # model load. Custom ids go through the "Custom model id…" sentinel,
        # whose dialog opens on user activation only — selected
        # programmatically it must resolve to the saved model, never to the
        # sentinel text.
        from listen_to_me.choices import CUSTOM_MODEL_LABEL, model_label

        assert not window.model_combo.isEditable()
        sentinel = window.model_combo.count() - 1
        assert window.model_combo.itemText(sentinel) == CUSTOM_MODEL_LABEL
        saved_model = window._selected_model()
        window.model_combo.setCurrentIndex(sentinel)
        assert window._selected_model() == saved_model
        window.model_combo.setCurrentText(model_label(saved_model))
        assert window._collect() == window._saved_snapshot

        # Wheel guard: a wheel tick over an unfocused combo/spin box must not
        # change its value (it would scroll the page instead), and the wheel
        # alone can never give the widget focus (StrongFocus, not WheelFocus).
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent

        assert window.language_combo.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert window.model_combo.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert window.max_seconds_spin.focusPolicy() == Qt.FocusPolicy.StrongFocus
        # Mute-target rows are created after the window's guard sweep, so they
        # must guard their own combo on construction.
        window._add_target_row({"name": "", "enabled": False, "mode": "hold", "hotkey": ""})
        row = window._target_rows[-1]
        assert row.mode_combo.focusPolicy() == Qt.FocusPolicy.StrongFocus
        window._remove_target_row(row)

        def wheel_tick(widget):
            event = QWheelEvent(
                QPointF(5, 5),
                QPointF(widget.mapToGlobal(QPoint(5, 5))),
                QPoint(0, -120),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            app.sendEvent(widget, event)

        window.language_combo.setCurrentIndex(1)
        wheel_tick(window.language_combo)
        assert window.language_combo.currentIndex() == 1  # unfocused → unchanged
        seconds_before = window.max_seconds_spin.value()
        wheel_tick(window.max_seconds_spin)
        assert window.max_seconds_spin.value() == seconds_before

        # Layout regression guard: the horizontal scroll bar is always off, so
        # a page whose minimum width exceeds the viewport is silently clipped
        # at the right edge (one over-long combo item once did this to
        # General). Visit every page at the default window size and check the
        # scroll content ends up no wider than its viewport. First-visit side
        # effects stay suppressed: the Whisper hardware probe would race the
        # stale-generation asserts below, the Updates check would hit the
        # network.
        from PySide6.QtWidgets import QScrollArea

        window._status_probed = True
        window._updates_auto_checked = True
        window.show()
        app.processEvents()
        for title in window._page_index:
            window._show_page(title)
            app.processEvents()
            page = window.stack.widget(window._page_index[title])
            for scroll in page.findChildren(QScrollArea):
                inner_w = scroll.widget().width()
                viewport_w = scroll.viewport().width()
                assert inner_w <= viewport_w, (
                    f"{title} page clipped: content {inner_w}px > viewport {viewport_w}px"
                )
        # Stat-card click routing, with the window still shown: a click lands
        # on the card's child QLabel in practice — the label ignores the press
        # and Qt must propagate it to the card's mouseReleaseEvent handler.
        from PySide6.QtCore import QPoint as _QPoint
        from PySide6.QtTest import QTest

        window._show_page("Home")
        app.processEvents()
        QTest.mouseClick(
            window.home.card_model.value, Qt.MouseButton.LeftButton, pos=_QPoint(2, 2)
        )
        app.processEvents()
        assert window.stack.currentIndex() == window._whisper_index

        window._show_page("General")
        window.hide()

        # Status-card formatters: every probe shape renders a clear verdict.
        fmt_cuda = window._format_cuda_status
        assert fmt_cuda({"available": True, "count": 1, "error": None}).startswith("✓")
        assert fmt_cuda({"available": False, "count": 0, "error": None}).startswith("✗")
        assert fmt_cuda({"available": False, "count": 0, "error": "no ctranslate2"}).startswith("✗")
        fmt_ov = window._format_openvino_status
        assert fmt_ov({"installed": False, "devices": [], "error": None}).startswith("✗")
        ov_ok = fmt_ov(
            {"installed": True, "devices": [{"device": "GPU", "name": "Intel Arc"}], "error": None}
        )
        assert ov_ok.startswith("✓") and "Intel Arc" in ov_ok
        assert fmt_ov({"installed": True, "devices": [], "error": "boom"}).startswith("⚠")
        fmt_model = window._format_model_status
        assert fmt_model({"target": "small", "cached": True, "error": None}).startswith("✓")
        assert "not downloaded" in fmt_model({"target": "small", "cached": False, "error": None})
        assert fmt_model({"target": "x", "cached": False, "error": "no conversion"}).startswith("⚠")

        # Applying a probe result fills the card; a stale generation is ignored.
        window._hw_gen = 2
        window._hw_busy = True
        probe = {
            "cuda": {"available": False, "count": 0, "error": None},
            "openvino": {"installed": False, "devices": [], "error": None},
            "model": {"target": "small", "cached": False, "error": None},
        }
        window._on_hw_done(1, probe)  # stale → dropped
        assert window.hw_cuda_label.text() == "Not checked yet."
        window._on_hw_done(2, probe)
        assert window.hw_cuda_label.text().startswith("✗") and not window._hw_busy

        # Cancel plumbing: Cancel stops the diagnostic, re-enables the buttons
        # and makes everything the detached worker still emits stale.
        gen, cancel = window._begin_diag("mic")
        assert window._diag_busy and window.mic_cancel_button.isEnabled()
        assert not window.mic_test_button.isEnabled()
        window._cancel_diagnostic()
        assert cancel.is_set() and not window._diag_busy
        assert window.mic_test_button.isEnabled() and not window.mic_cancel_button.isEnabled()
        assert "cancelled" in window.mic_status.text()
        window._on_mic_done(gen, {"peak": 0.5, "rms": 0.1, "seconds": 3.0, "verdict": "ok"})
        assert "cancelled" in window.mic_status.text()  # stale result ignored

        overlay = Overlay(stub)
        for state in ("recording", "processing", "idle"):
            overlay.set_state(state)
        overlay.reposition_bubble()

        # Overlay watchdog: enabling arms it; a re-assert after the OS dropped
        # the window (simulated by hiding it natively) shows it again — the
        # hard path (post-resume / monitor change) too; disabling stops it.
        overlay.set_visible(True)
        assert overlay._watchdog.isActive()
        overlay.win.hide()
        overlay._reassert()
        assert overlay.win.isVisible()
        overlay.win.hide()
        overlay._reassert(hard=True)
        assert overlay.win.isVisible()
        overlay.set_visible(False)
        assert not overlay._watchdog.isActive()
        overlay._reassert()  # disabled → must stay hidden
        assert not overlay.win.isVisible()

        dialog = HotkeyCaptureDialog(None)

        # The first-run wizard: build, exercise the backend-dependent device
        # rows, then apply — the chosen values must land in the config dict.
        # _apply() instead of accept(): accept re-validates the current page,
        # and the hotkey validation imports pynput (absent on the CI runner).
        wizard = OnboardingWizard(stub.cfg)
        wizard.restart()
        assert wizard.language_combo.focusPolicy() == Qt.FocusPolicy.StrongFocus  # wheel guard
        assert not wizard.model_combo.isEditable()  # read-only — presets only
        wizard.backend_combo.setCurrentIndex(1)  # OpenVINO → Intel device row
        wizard.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        wizard._apply()
        assert stub.cfg["backend"] == "faster-whisper"
        assert stub.cfg["model"] == "small"  # preset label round-trips to the id

        app.processEvents()

        # force_close bypasses the unsaved-changes prompt even when dirty —
        # App._quit relies on that; a modal box here would hang this run.
        window.chk_beep.setChecked(not window.chk_beep.isChecked())
        window._force_close = True
        window.reject()

        dialog.deleteLater()
        wizard.deleteLater()
        overlay.destroy()
        window.deleteLater()
        app.processEvents()


# --------------------------------------------------------------- runners


def _report(lines: list[str], ok: bool) -> int:
    report = "\n".join(lines) + f"\n\nRESULT: {'PASS' if ok else 'FAIL'}\n"
    log_path = Path(tempfile.gettempdir()) / "listen-to-me-selftest.log"
    try:
        log_path.write_text(report, encoding="utf-8")
    except Exception:
        pass
    try:
        print(report)
    except Exception:
        pass
    return 0 if ok else 1


def _run_checks(checks, imports=()) -> int:
    lines: list[str] = []
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            fn()
            lines.append(f"OK   {name}")
        except Exception:
            ok = False
            lines.append(f"FAIL {name}\n{traceback.format_exc()}")

    for name, fn in checks:
        check(name, fn)
    for module in imports:
        check(f"import {module}", lambda m=module: __import__(m))
    return _report(lines, ok)


# Light checks need only PySide6 + Pillow — safe on a headless Linux CI runner.
# pynput is deliberately excluded: importing it needs an X display, which the
# offscreen CI job doesn't have. It's covered by the full run() on Windows.
_LIGHT_CHECKS = [
    ("config roundtrip", _config_roundtrip),
    ("config defaults", _config_defaults),
    ("config survives corrupt sections", _config_survives_corrupt_sections),
    ("history normalizes entries", _history_normalizes_entries),
    ("recorder start failure resets", _recorder_start_failure_resets),
    ("injector paste fallback", _injector_paste_falls_back_to_typing),
    ("theme scrollbar contrast", _theme_scrollbar_contrast),
    ("mute integrations no-op", _integrations_noop),
    ("single-instance guard", _single_instance_guard),
    ("live typing logic", _live_typing_logic),
    ("icon render", _icon_render),
    ("key picker key mapping", _key_mapping),
    ("autostart entry refresh", _autostart_refresh),
    ("updater version logic", _updater_logic),
    ("updater forces TLS verification", _updater_forces_tls_verification),
    ("insecure SSL switch", _insecure_ssl_switch),
    ("insecure SSL huggingface httpx API", _insecure_ssl_hub_httpx),
    ("std stream stub (windowed build)", _std_stream_stub),
    ("transcriber cache probe", _transcriber_cache_probe),
    ("CUDA error detection", _cuda_error_detection),
    ("transcriber CPU fallback", _transcriber_cpu_fallback),
    ("openvino backend logic", _openvino_backend_logic),
    ("parakeet backend logic", _parakeet_backend_logic),
    ("diagnostics engine", _diagnostics_engine),
    ("hardware/status probes", _hardware_probes),
    ("help content renders", _help_content_renders),
    ("Qt icon conversion", _qt_icons),
    ("glyph icons render", _glyph_icons),
    ("voice mic widget", _voice_mic_widget),
    ("Qt UI construction", _gui_construction),
]

def _insecure_hub_client_builds():
    """The insecure/default httpx clients for huggingface_hub >= 1.0 actually
    construct against the bundled httpx (catches kwargs drift at release
    time). Silently skipped when httpx isn't installed (hub < 1.0 setups)."""
    try:
        import httpx  # noqa: F401
    except ImportError:
        return
    from listen_to_me import netutil

    netutil._build_hub_client(verify=False).close()
    netutil._build_hub_client(verify=True).close()


_FULL_EXTRA = [
    ("default hotkey parses", _hotkey_default_valid),
    ("audio band levels", _band_levels),
    ("clip stats verdicts", _clip_stats_verdicts),
    ("insecure hub client builds", _insecure_hub_client_builds),
]

_BUNDLED_IMPORTS = [
    "numpy",
    "sounddevice",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "openvino_genai",  # optional [openvino] extra, but bundled in the Windows exe
    "onnx_asr",  # optional [parakeet] extra, but bundled in the Windows exe
    "huggingface_hub",  # model downloads for all backends (transitive via faster-whisper)
    "pynput.keyboard",
    "PIL.Image",
    "pyperclip",
    "requests",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]


def gui_smoke() -> int:
    """Light checks only (no heavy runtime deps) — used by the Linux CI job."""
    return _run_checks(_LIGHT_CHECKS)


def run() -> int:
    """Full self-test for the packaged executable: UI checks + every bundled
    runtime dependency importable."""
    return _run_checks(_LIGHT_CHECKS + _FULL_EXTRA, _BUNDLED_IMPORTS)
