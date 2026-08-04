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
    assert DEFAULTS["clipboard_copy"] in ("off", "on_failure", "always")
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


def _config_guards_scalar_types():
    """The section guard's little brother: a scalar of the wrong type must not
    reach the code that uses it. `"history_max": "many"` used to raise inside
    App.__init__ — before tray, overlay or any window existed — so the app just
    never appeared. Plausible hand-edits (a quoted number) are repaired, the
    rest falls back to that one option's default."""
    import json

    from listen_to_me.config import DEFAULTS, Config

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "history_max": "many",  # unusable → default
                    "max_seconds": "120",  # quoted number → repaired
                    "beam_size": 1.0,  # float for an int → repaired
                    "notifications": 0,  # 0/1 for a bool → repaired
                    "beep": "yes",  # unusable → default
                    "hotkey": None,  # null where a value belongs → default
                    "model": 3,  # number for a string → default
                    "hotkey_mode": "hold",  # a valid sibling must still apply
                    "overlay": {"preview_seconds": "9", "enabled": []},
                    "input_device": 2,  # default is null → no type to check
                    "model_dir": "/models",  # default is null → passed through
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cfg = Config(path=path)
        assert cfg["history_max"] == DEFAULTS["history_max"]
        assert cfg["max_seconds"] == 120 and isinstance(cfg["max_seconds"], int)
        assert cfg["beam_size"] == 1 and isinstance(cfg["beam_size"], int)
        assert cfg["notifications"] is False
        assert cfg["beep"] == DEFAULTS["beep"]
        assert cfg["hotkey"] == DEFAULTS["hotkey"]
        assert cfg["model"] == DEFAULTS["model"]
        assert cfg["hotkey_mode"] == "hold"
        assert cfg["overlay"]["preview_seconds"] == 9
        assert cfg["overlay"]["enabled"] == DEFAULTS["overlay"]["enabled"]
        assert cfg["input_device"] == 2
        assert cfg["model_dir"] == "/models"
        # A bool where a number belongs is a mistake, not a 1 (bool subclasses
        # int) — and the repaired config must survive a save/reload cycle.
        path.write_text(json.dumps({"beam_size": True}), encoding="utf-8")
        cfg = Config(path=path)
        assert cfg["beam_size"] == DEFAULTS["beam_size"]
        cfg.save()
        assert Config(path=path)["beam_size"] == DEFAULTS["beam_size"]


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


def _history_latest_transcript():
    """What the tray/overlay "Copy last transcript" hands to the clipboard: the
    newest entry, "" when there is none (or the file is unreadable) — never an
    exception into an event handler and never a stale value after an append."""
    import json

    from listen_to_me.history import TranscriptHistory

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "history.json"
        store = TranscriptHistory(path)
        assert store.latest() == ""  # nothing recorded yet
        store.add("first")
        store.add("second")
        assert store.latest() == "second"
        assert store.latest() == store.entries()[0]["text"]  # entries() is newest-first
        # Same normalization as entries(): a corrupt tail entry is not "the
        # last transcript", the newest usable one is.
        path.write_text(
            json.dumps([{"time": 1.0, "text": "kept"}, {"time": 2.0, "text": 42}]),
            encoding="utf-8",
        )
        assert store.latest() == "kept"
        path.write_text("{ truncated", encoding="utf-8")
        assert store.latest() == ""


def _clipboard_copy_falls_back_to_qt():
    """pyperclip raises without xclip/xsel on Linux — the Qt clipboard then has
    to take over, or every "Copy" button in the app silently does nothing on a
    bare desktop. Only a failure of both paths may report False."""
    from listen_to_me import qtutil

    _ensure_qapp()
    assert qtutil.copy_to_clipboard("") is False  # nothing to copy
    assert qtutil.copy_to_clipboard("plain text") is True

    class _Broken:
        @staticmethod
        def copy(_text):
            raise RuntimeError("no clipboard mechanism available")

    original = sys.modules.get("pyperclip")
    sys.modules["pyperclip"] = _Broken
    try:
        assert qtutil.copy_to_clipboard("via Qt") is True
        from PySide6.QtWidgets import QApplication

        assert QApplication.clipboard().text() == "via Qt"
    finally:
        if original is None:
            sys.modules.pop("pyperclip", None)
        else:
            sys.modules["pyperclip"] = original


def _history_search_matching():
    """The History page's search rule: every term must appear, in any order and
    any case. An empty query must never hide anything."""
    from listen_to_me.history import filter_entries

    entries = [
        {"time": 1.0, "text": "Meeting notes for the Kubernetes migration"},
        {"time": 2.0, "text": "Grocery list: Äpfel, Milch"},
        {"time": 3.0, "text": "kubernetes cluster upgrade plan"},
    ]

    def texts(query):
        return [e["text"] for e in filter_entries(entries, query)]

    assert len(texts("")) == 3 and len(texts("   ")) == 3  # no query hides nothing
    assert len(texts("KUBERNETES")) == 2  # case-insensitive
    assert texts("kubernetes migration") == [entries[0]["text"]]  # AND over terms
    assert texts("migration kubernetes") == [entries[0]["text"]]  # order-independent
    assert texts("ÄPFEL") == [entries[1]["text"]]  # casefold, not ASCII lower
    assert texts("nothing here") == []
    # A non-string text must not raise: the store normalizes, the file is not.
    assert filter_entries([{"text": None}], "x") == []


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
        def _paste(self, text, keep=False):
            raise RuntimeError("clipboard is unavailable")

        def _type(self, text):
            typed.append(text)

    injector = _Injector(
        {"injection_mode": "paste", "restore_clipboard": True, "clipboard_copy": "off"}
    )
    injector.insert("recovered text")
    assert typed == ["recovered text"]
    injector.insert("")  # empty stays a no-op
    assert typed == ["recovered text"]


def _injector_clipboard_policy():
    """The clipboard option holds for every insertion path — and never fights
    the "restore previous clipboard" setting.

    "always" is what a user picks to be safe, so it must also work in typing
    mode (which never touches the clipboard on its own) and must suppress the
    restore in paste mode — putting the old content back would wipe the very
    transcript that mode promises to keep. "off" must stay off: an unwanted
    copy leaks dictated text into the clipboard of a shared machine. An
    unknown value from a hand-edited config falls back to the default safety
    net, not to "off".
    """
    from listen_to_me.injector import Injector

    copied: list[str] = []
    pastes: list[bool] = []

    class _Injector(Injector):
        def _type(self, text):
            pass

        def _paste(self, text, keep=False):
            pastes.append(keep)
            return keep  # a kept paste leaves the transcript on the clipboard

        def copy_to_clipboard(self, text):
            copied.append(text)
            return True

    def _cfg(clipboard_copy, injection_mode="type"):
        return {
            "injection_mode": injection_mode,
            "restore_clipboard": True,
            "clipboard_copy": clipboard_copy,
        }

    assert _Injector(_cfg("always")).insert("hello") is True
    assert copied == ["hello"], "typing mode must still put the transcript on the clipboard"
    copied.clear()
    for mode in ("on_failure", "off", "hand-edited nonsense"):
        assert _Injector(_cfg(mode)).insert("hello") is False
        assert copied == [], f"{mode} must not copy after a successful insertion"

    # Paste mode: only "always" suppresses the restore, and it does not copy a
    # second time on top of the paste that already left the text there.
    assert _Injector(_cfg("always", "paste")).insert("hello") is True
    assert pastes == [True] and copied == []
    pastes.clear()
    assert _Injector(_cfg("on_failure", "paste")).insert("hello") is False
    assert pastes == [False] and copied == []

    assert _Injector(_cfg("hand-edited nonsense")).clipboard_mode() == "on_failure"
    assert _Injector(_cfg("off")).clipboard_mode() == "off"

    # The write is read back, because "could not insert it — press Ctrl+V" must
    # not point at a clipboard that took nothing: the user would paste whatever
    # was there before and never notice the transcript is gone. Windows hands
    # the text back with \r\n line endings, which is the same text.
    class _FakeClipboard:
        def __init__(self):
            self.stored = "something else"
            self.accepts = True

        def copy(self, text):
            if self.accepts:
                self.stored = text.replace("\n", "\r\n")

        def paste(self):
            return self.stored

    fake = _FakeClipboard()
    injector = Injector(_cfg("always"))
    previous = sys.modules.get("pyperclip")
    sys.modules["pyperclip"] = fake
    try:
        assert injector.copy_to_clipboard("line one\nline two") is True
        fake.accepts = False  # the write silently did nothing
        assert injector.copy_to_clipboard("lost text") is False
        assert injector.copy_to_clipboard("") is False
    finally:
        if previous is None:
            del sys.modules["pyperclip"]
        else:
            sys.modules["pyperclip"] = previous


def _clipboard_copy_is_announced():
    """A transcript that ends up on the clipboard says so — and a recording
    never produces two notifications about it.

    The app cannot see whether the focused window took the paste: with no text
    field under the cursor the insertion "succeeds" into nothing, so without
    this message the clipboard option looks like it did nothing at all. The
    failure path must keep replacing that message instead of adding to it, and
    must still never promise a clipboard that took nothing.
    """
    from listen_to_me.app import App

    class _Injector:
        def __init__(self, on_clipboard, mode="always", exc=None):
            self._on_clipboard = on_clipboard
            self._mode = mode
            self._exc = exc
            self.recovered: list[str] = []

        def clipboard_mode(self):
            return self._mode

        def insert(self, text):
            if self._exc is not None:
                raise self._exc
            return self._on_clipboard

        def copy_to_clipboard(self, text):
            self.recovered.append(text)
            return self._on_clipboard

    class _App:
        # Borrowed unbound: the notification wording is App's, but building a
        # real App would need the tray, the recorder and a transcriber.
        _insert_transcript = App._insert_transcript
        _notify_copied = App._notify_copied
        _copy_for_recovery = App._copy_for_recovery

        def __init__(self, injector):
            self.injector = injector
            self.messages: list[tuple[str, bool]] = []

        def notify(self, message, force=False):
            self.messages.append((message, force))

    app = _App(_Injector(True))
    app._insert_transcript("kept text")
    assert app.messages == [("Copied to the clipboard: kept text", False)]

    app = _App(_Injector(False))
    app._insert_transcript("inserted at the cursor")
    assert app.messages == [], "an insertion that kept nothing stays silent"

    # A notification is a one-line toast: long transcripts are previewed.
    app = _App(_Injector(True))
    app._insert_transcript("word " * 40)
    assert app.messages[0][0].endswith("…") and len(app.messages[0][0]) < 100

    # A failed insertion reports the failure — that message replaces the copy
    # confirmation rather than arriving next to it.
    injector = _Injector(True, exc=RuntimeError("blocked"))
    app = _App(injector)
    app._insert_transcript("recovered")
    assert len(app.messages) == 1 and app.messages[0][1] is True
    assert "press Ctrl+V" in app.messages[0][0] and injector.recovered == ["recovered"]

    injector = _Injector(False, exc=RuntimeError("blocked"))
    app = _App(injector)
    app._insert_transcript("lost")
    assert len(app.messages) == 1 and "Settings → History" in app.messages[0][0]

    # "off" still means off: the recovery copy is skipped and the message says
    # where the text really is.
    injector = _Injector(True, mode="off", exc=RuntimeError("blocked"))
    app = _App(injector)
    app._insert_transcript("private")
    assert injector.recovered == [] and "Settings → History" in app.messages[0][0]


def _contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two "#rrggbb" palette tokens."""

    def _relative_luminance(hex_color: str) -> float:
        raw = hex_color.lstrip("#")
        channels = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    la, lb = _relative_luminance(a), _relative_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _theme_scrollbar_contrast():
    """The scroll-bar handle must be visible against the page it sits on.

    Several settings pages scroll and the horizontal bar is switched off, so the
    vertical handle is the *only* hint that a page continues below the fold — at
    the border colour it used to have (~1.3:1) it was effectively invisible.
    Pure arithmetic on the palette tokens, no rendering: 3:1 is the WCAG minimum
    for non-text UI components.
    """
    from listen_to_me.theme import _DARK, _LIGHT

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


def _mute_keybind_uses_virtual_keys():
    """A synthesized mute keybind must go out as real key events, never as a
    character — otherwise the target's global keybind hook doesn't see it.

    pynput parses the character part of a combination to a char-only KeyCode,
    and a Controller that already holds Shift (Discord's default mute keybind
    is Ctrl+Shift+M) uppercases it — which the Windows backend can only deliver
    as a Unicode packet: invisible to the target's hook, and typed as literal
    text into the focused field. `_synth_keys` substitutes the virtual-key code
    so neither can happen; this pins the substitution. Stubs stand in for
    pynput, which the headless CI runner has no X display to import.
    """
    from listen_to_me import integrations

    class _KeyCode:
        def __init__(self, vk=None, char=None):
            self.vk, self.char = vk, char

        @classmethod
        def from_vk(cls, vk):
            return cls(vk=vk)

    ctrl, shift = object(), object()  # Key members carry no .char
    m = _KeyCode(char="m")  # what HotKey.parse yields for "m"
    f9 = _KeyCode(vk=120)  # ...and for "<f9>", already a virtual key

    original = integrations._char_vk
    try:
        integrations._char_vk = lambda char: {"m": 0x4D}.get(char)
        keys = integrations._synth_keys([ctrl, shift, m, f9], _KeyCode)
        assert keys[0] is ctrl and keys[1] is shift, "modifiers must pass through"
        assert keys[2].vk == 0x4D, "'m' must be pressed as VK_M"
        assert keys[2].char is None, "a char would let pynput uppercase it again"
        assert keys[3] is f9, "a key that already has a vk must be left alone"

        # No layout mapping (not Windows, or an unmappable character): the
        # parsed key survives unchanged — never dropped from the combination,
        # which would silently send an incomplete chord.
        integrations._char_vk = lambda char: None
        assert integrations._synth_keys([ctrl, m], _KeyCode) == [ctrl, m]
    finally:
        integrations._char_vk = original


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

    # Hand-over: app._process takes the untyped remainder and its typed_any
    # bookkeeping; a worker resuming after the join timeout must not type that
    # text a second time (duplicate words).
    lt.pending = "again"
    assert lt.hand_over() == ("again", True)
    lt._flush_pending()
    assert lt.app.injector.typed == ["hello", " world"] and lt.pending == "again"


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


def _autostart_reporting():
    """A registration that doesn't take must be reported, not assumed: the
    Windows startup block is decoded, enable() reads its own write back, and
    sync()/describe() turn all of that into something the user can act on."""
    from listen_to_me import autostart

    # Windows StartupApproved record: even first byte = enabled, odd = disabled.
    assert autostart._is_blocked(None) is False
    assert autostart._is_blocked(b"") is False
    assert autostart._is_blocked(bytes([0x02]) + bytes(11)) is False
    assert autostart._is_blocked(bytes([0x06]) + bytes(11)) is False
    assert autostart._is_blocked(bytes([0x03]) + bytes(11)) is True
    assert autostart._is_blocked(bytes([0x09]) + bytes(11)) is True
    # The import probe answers with a reason or with nothing at all — never an
    # exception, and never a second subprocess (it caches its verdict).
    verdict = autostart.launch_problem()
    assert verdict is None or (isinstance(verdict, str) and verdict)
    assert autostart.launch_problem() is verdict
    # A status line must never carry a raw program path: a Windows path has no
    # space to wrap at, so the label would set a minimum width that widens the
    # whole settings page and clips its cards (see MEMORY.md).
    # Native separators: _split_command only keeps backslashes on Windows, so a
    # hard-coded Windows path would test nothing on the CI runner.
    deep = os.path.join(os.sep + "programs", "listen to me", "ListenToMe.exe")
    assert autostart.short_command(f'"{deep}"') == "ListenToMe.exe"  # quoted, with spaces
    assert autostart.short_command(
        os.path.join(os.sep + "usr", "bin", "python3") + " -m listen_to_me"
    ) == "python3 -m listen_to_me"
    assert autostart.short_command("") == ""

    if sys.platform in ("win32", "darwin"):
        return  # the entry lives in the registry / the real home — don't touch it
    original = os.environ.get("XDG_CONFIG_HOME")
    probe = autostart.launch_problem
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_CONFIG_HOME"] = tmp
        # The real probe would flag this very checkout when it runs from
        # PYTHONPATH (as CI does) — pin it so both outcomes are exercised.
        autostart.launch_problem = lambda: None
        try:
            assert autostart.stored_command() is None
            assert autostart.describe(False) == (True, "")  # nothing to say
            assert autostart.sync(True) is None
            stored = autostart.stored_command()
            assert stored and autostart._launch_command() in stored
            healthy, text = autostart.describe(True)
            # The file name identifies the build; the full path stays out of
            # the label (it lands in its tooltip instead).
            assert healthy and autostart.short_command(stored) in text
            assert stored not in text and len(text) < 80
            # Unticked but still registered: say that saving removes it.
            healthy, text = autostart.describe(False)
            assert healthy and "remove" in text
            # A launch that would start nothing is reported, never green.
            autostart.launch_problem = lambda: "the command would start nothing"
            healthy, text = autostart.describe(True)
            assert not healthy and "⚠" in text
            assert autostart.sync(True) == "the command would start nothing"
            autostart.launch_problem = lambda: None
            assert autostart.sync(False) is None
            assert autostart.stored_command() is None
            # A write that silently produced nothing must raise, not pass.
            readable = autostart.stored_command
            autostart.stored_command = lambda: None
            try:
                enable_failed = False
                try:
                    autostart.enable()
                except autostart.AutostartError:
                    enable_failed = True
                assert enable_failed
                # ... and sync() turns that into a message instead of silence.
                assert autostart.sync(True)
            finally:
                autostart.stored_command = readable
        finally:
            autostart.launch_problem = probe
            if original is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = original


def _updater_logic():
    from listen_to_me import updater

    assert updater.parse_version("v2026.07.19.11") == (2026, 7, 19, 11)
    assert updater.parse_version("0.0.0.dev0") == (0, 0, 0, 0)
    assert updater.parse_version("v2026.07.19.11") > updater.parse_version("v2026.07.19.5")

    # Asset sizes shown in the release list, the confirmation and the download
    # progress line. An unknown size must format to "" so callers can skip it.
    assert updater.format_size(None) == "" and updater.format_size(0) == ""
    assert updater.format_size(-1) == ""
    assert updater.format_size(512) == "512 bytes"
    assert updater.format_size(2048) == "2 KB"
    assert updater.format_size(198 * 1024 * 1024) == "198.0 MB"
    assert updater.format_size(3 * 1024**3) == "3.0 GB"

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

    # Format pre-check for custom ids: an OpenVINO IR directory passes, a
    # CTranslate2 one is recognized as the wrong format, and anything that
    # can't be listed (no network, private repo) stays permissive (None).
    from listen_to_me.transcriber_openvino import _looks_like_openvino_model

    with tempfile.TemporaryDirectory() as tmp:
        ir_dir = Path(tmp) / "ir-model"
        ir_dir.mkdir()
        (ir_dir / "openvino_encoder_model.xml").write_text("<net/>", encoding="utf-8")
        assert _looks_like_openvino_model(str(ir_dir)) is True
        ct2_dir = Path(tmp) / "ct2-model"
        ct2_dir.mkdir()
        (ct2_dir / "model.bin").write_bytes(b"")
        assert _looks_like_openvino_model(str(ct2_dir)) is False

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


def _styled_button(text: str, prop: str | None = None, name: str | None = None):
    """A QPushButton in one of the stylesheet's variants (theme.py) — the
    property/object name is what selects the variant rule."""
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(text)
    if prop:
        button.setProperty(prop, True)
    if name:
        button.setObjectName(name)
    return button


def _theme_focus_visible():
    """Keyboard focus must be visible on every control the user can tab to.

    The stylesheet gives buttons a custom border, which switches Qt to
    stylesheet rendering and drops the native focus rect — before the :focus
    rules in theme.py, tabbing through the window changed not a single pixel.
    Rendered, not read off the style sheet, because only the render proves the
    rule actually applies. The size hint must stay put as well: a ring that
    widens the border would make the layout jump as focus moves.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QLineEdit,
        QRadioButton,
        QVBoxLayout,
        QWidget,
    )

    app = _ensure_qapp()
    from listen_to_me.theme import apply_theme

    apply_theme(app)

    def _focus_changes(widget, name: str) -> None:
        host = QWidget()
        # Set as real Tab navigation does — some styles only paint the focus
        # ring after a keyboard-driven focus change.
        host.setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, True)
        layout = QVBoxLayout(host)
        elsewhere = QLineEdit()
        layout.addWidget(widget)
        layout.addWidget(elsewhere)
        host.show()
        elsewhere.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        hint, before = widget.sizeHint(), widget.grab().toImage()
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        after = widget.grab().toImage()
        assert before != after, f"{name} looks identical focused and unfocused"
        assert widget.sizeHint() == hint, f"{name} changes size when focused"
        host.deleteLater()

    _focus_changes(_styled_button("Apply"), "QPushButton")
    _focus_changes(_styled_button("Save", prop="accent"), "accent QPushButton")
    _focus_changes(
        _styled_button("Clear history", prop="destructive"), "destructive QPushButton"
    )
    _focus_changes(_styled_button("  Change hotkey", prop="quick"), "quick QPushButton")
    _focus_changes(_styled_button("Start recording", name="recordBtn"), "hero record button")
    _focus_changes(_styled_button("Cancel", name="heroCancel"), "hero cancel button")
    _focus_changes(QCheckBox("Beep on start/stop"), "QCheckBox")
    _focus_changes(QRadioButton("Toggle"), "QRadioButton")
    _focus_changes(QLineEdit("text"), "QLineEdit")


def _theme_disabled_visible():
    """A disabled button must LOOK disabled — in every stylesheet variant.

    `QPushButton:disabled` and `QPushButton[accent="true"]` carry the same CSS
    specificity, so while the plain `:disabled` rule sat above the variant
    rules, the variant simply won: an accent or destructive button rendered
    pixel-identically enabled and disabled. Settings → Updates disables
    "Download & install" for the length of a GitHub round trip (and the hotkey
    picker's OK, and Clear history on an empty list, start out disabled too), so
    users clicked a button that still looked live, got nothing, and reported
    having to press it twice. Rendered, not read off the style sheet — only the
    render proves the rule applies. The size hint has to stay put as well, or
    every enable/disable would nudge the layout.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    app = _ensure_qapp()
    from listen_to_me.theme import apply_theme

    apply_theme(app)

    def _surface(image):
        """The button's fill, sampled above the label and inside the border —
        the part the variant rules paint."""
        return image.pixelColor(image.width() // 2, 4)

    def _disabled_changes(widget, name: str, *, surface: bool = True) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.addWidget(widget)
        # Park the focus somewhere else first. A focus ring appearing or
        # vanishing between the two renders differs all by itself and would
        # pass this check for a disabled state that changes nothing else.
        elsewhere = QLineEdit()
        layout.addWidget(elsewhere)
        host.show()
        elsewhere.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        hint, enabled = widget.sizeHint(), widget.grab().toImage()
        widget.setEnabled(False)
        app.processEvents()
        disabled = widget.grab().toImage()
        assert enabled != disabled, f"{name} looks identical enabled and disabled"
        # Dimming only the label is what let the accent button read as live:
        # the surface has to drop its colour cue too. Widgets that paint no
        # surface of their own (check boxes) pass surface=False.
        if surface:
            assert _surface(enabled) != _surface(disabled), (
                f"{name} keeps its surface colour when disabled"
            )
        assert widget.sizeHint() == hint, f"{name} changes size when disabled"
        host.deleteLater()

    _disabled_changes(_styled_button("Check now"), "QPushButton")
    _disabled_changes(
        _styled_button("Download && install", prop="accent"), "accent QPushButton"
    )
    _disabled_changes(
        _styled_button("Clear history", prop="destructive"), "destructive QPushButton"
    )
    _disabled_changes(_styled_button("  Change hotkey", prop="quick"), "quick QPushButton")
    _disabled_changes(_styled_button("Start recording", name="recordBtn"), "hero record button")
    # Check boxes fall into the same trap: the QSS rule that reserves their
    # focus ring switches them to stylesheet rendering, where the palette's
    # Disabled group stops applying. General greys out "restore the previous
    # clipboard" while clipboard_copy = "always" overrules it — an option that
    # no longer applies has to look that way. Only the label can dim (a check
    # box paints no surface), so this one checks the render alone.
    from PySide6.QtWidgets import QCheckBox

    _disabled_changes(QCheckBox("Restore previous clipboard content"), "QCheckBox", surface=False)

    # The renders above only exercise whatever scheme the test host runs in (CI
    # is light), so a dark-palette edit could bring the bug back for half the
    # users unseen. Check the tokens themselves for both, like the scroll-bar
    # contrast check does: a disabled button must shed the accent fill and the
    # danger red, and dim its label.
    from listen_to_me.theme import ACCENT, _DARK, _LIGHT

    for name, palette in (("light", _LIGHT), ("dark", _DARK)):
        ratio = _contrast(palette["disabled_bg"], ACCENT)
        assert ratio >= 2.0, f"{name} disabled surface vs the accent fill: {ratio:.2f}:1"
        for live in ("text", "danger"):
            ratio = _contrast(palette["disabled"], palette[live])
            assert ratio >= 1.5, f"{name} disabled label vs {live}: {ratio:.2f}:1"


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
        self.state = "idle"
        # Stands in for an event still sitting in App's queue: _poll() applies
        # it, exactly like the real 100 ms poll timer does.
        self.queued_state: str | None = None

    def post(self, *args, **kwargs):
        self.posts.append(args)

    def _poll(self):
        if self.queued_state is not None:
            self.state, self.queued_state = self.queued_state, None

    def _register_hotkey(self):
        self.hotkeys.running = True

    def apply_settings(self):
        pass


class _StubHotkeys:
    def __init__(self):
        self.running = True

    def stop(self):
        self.running = False


def _tray_names_the_hotkey():
    """The tray status spells the configured combination out instead of saying
    "the hotkey" — including after it was changed in the settings, and with the
    right verb for hold mode. An unusable combo falls back to the generic
    wording, never to a raw pynput token in a sentence."""
    from listen_to_me.tray import _STATE_LABELS, state_label

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        assert state_label("idle", stub.cfg) == "Idle — press Ctrl+Alt+Space to record"
        assert state_label("recording", stub.cfg) == "Recording… press Ctrl+Alt+Space to stop"
        assert state_label("processing", stub.cfg) == _STATE_LABELS["processing"]

        stub.cfg["hotkey"] = "<f9>"
        stub.cfg["hotkey_mode"] = "hold"
        # Hold mode stops on release — "press it again" would be wrong.
        assert state_label("recording", stub.cfg) == "Recording… release F9 to stop"
        assert state_label("idle", stub.cfg) == "Idle — press F9 to record"

        stub.cfg["hotkey"] = ""  # nothing to name → generic wording
        assert state_label("idle", stub.cfg) == _STATE_LABELS["idle"]
        assert state_label("recording", stub.cfg) == _STATE_LABELS["recording"]
        assert state_label("nonsense", stub.cfg) == "nonsense"


def _tray_survives_a_missing_notification_area():
    """Started by the OS autostart, the app can be up before the shell is: the
    tray icon is dropped and Qt still reports it visible. Tray.start() must keep
    re-adding it and, when there is no floating icon either, fall back to a
    window instead of leaving the app running with nothing to see.

    The offscreen platform reproduces the situation exactly (no tray available,
    isVisible() == True anyway); on a machine with a real notification area
    there is no retry to exercise, so the check passes trivially."""
    from listen_to_me import tray as tray_module

    _ensure_qapp()
    if tray_module.QSystemTrayIcon.isSystemTrayAvailable():
        return
    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        stub.cfg["overlay"]["enabled"] = False
        tray = tray_module.Tray(stub)
        tray.start()
        assert tray._retry_timer is not None and tray._retry_timer.isActive()
        for _ in range(tray_module._RETRY_LIMIT - 1):
            tray._retry_show()  # keep trying, quietly
        assert tray._retry_timer is not None and not stub.posts
        tray._retry_show()  # ... and give up on the last attempt
        assert tray._retry_timer is None
        assert ("settings",) in stub.posts
        tray.stop()

        # With the floating icon on there is something to see, so no window is
        # forced on the user.
        stub.posts.clear()
        stub.cfg["overlay"]["enabled"] = True
        tray = tray_module.Tray(stub)
        tray.start()
        for _ in range(tray_module._RETRY_LIMIT):
            tray._retry_show()
        assert tray._retry_timer is None and not stub.posts
        tray.stop()  # a stopped tray must not leave a timer running
        assert tray._retry_timer is None


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

        from listen_to_me.keymap import pretty_keys

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

        # The at-a-glance cards are controls, not decoration: they must take
        # keyboard focus and open their settings page on Space/Enter. Enter
        # especially — an unaccepted Return would fall through to the dialog's
        # default button (Save) and close the window instead.
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            window._show_page("Home")
            card = window.home.card_mic
            assert card.focusPolicy() != Qt.FocusPolicy.NoFocus, "stat card is not focusable"
            assert card.accessibleName(), "stat card has no accessible name"
            card.setFocus(Qt.FocusReason.TabFocusReason)
            card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
            assert window.nav.currentRow() == window._nav_row["Audio"], key

        # The language card must not show the (ignored) Whisper language for
        # the Parakeet backend — Parakeet always auto-detects.
        stub.cfg.data["backend"] = "parakeet"
        window.home.refresh()
        assert window.home.card_language.value.text() == "Auto-detect"
        stub.cfg.data["backend"] = "faster-whisper"
        window.home.refresh()

        # The Updates check button swaps its label while the check runs. A
        # control that resizes under the cursor can drop the click that is
        # pressing it, so the button is pinned to the wider label — character
        # counts are no proof of that in a proportional font.
        # Deliberately WITHOUT opening the page: _on_page_changed would fire the
        # automatic check, and the checks must never touch the network.
        from listen_to_me.settings_ui import _CHECK_LABEL, _CHECKING_LABEL

        def _laid_out_width(button) -> int:
            # What the user actually sees: a layout gives the button its size
            # hint but never goes below the pinned minimum, and sizeHint() on
            # its own is blind to that pin.
            return max(button.sizeHint().width(), button.minimumWidth())

        idle_width = _laid_out_width(window.update_check_button)
        window.update_check_button.setText(_CHECKING_LABEL)
        assert _laid_out_width(window.update_check_button) == idle_width, (
            "the update check button resizes when it switches to the busy label"
        )
        window.update_check_button.setText(_CHECK_LABEL)

        # Every download outcome that does NOT restart the app has to leave the
        # page idle. The failed-swap path used to reset it by hand and had
        # drifted: it left the progress bar at 100 %, so the failure message sat
        # under a full bar that reads as success.
        window.update_progress.setValue(100)
        window.update_progress.setVisible(True)
        window.update_cancel_button.setVisible(True)
        window._update_busy = True
        window._end_update_download("Could not apply update: boom")
        assert window.update_progress.isHidden(), "progress bar survives a failed update"
        assert window.update_cancel_button.isHidden(), "cancel button survives a failed update"
        assert window.update_check_button.isEnabled() and window.update_button.isEnabled()
        assert not window._update_busy
        assert "Could not apply update" in window.update_status.text()

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

        # History search: it must narrow the list, report how much of the
        # history matched, and a no-match search must not read like an empty
        # history (the transcripts are still there, just hidden).
        def _history_text() -> str:
            return " ".join(
                label.text() for label in window._history_inner.findChildren(QLabel)
            )

        window.history_filter_edit.setText("corrupt")
        window._refresh_history()  # the debounce timer would need the event loop
        assert "corrupt timestamp" in _history_text()
        assert "A stored transcript" not in _history_text()
        assert "1 of 2" in window.history_count_label.text()
        window.history_filter_edit.setText("nothing-matches-this")
        window._refresh_history()
        assert "No transcript contains" in _history_text()
        assert window.history_clear_button.isEnabled()  # entries exist, only hidden
        window.history_filter_edit.clear()
        window._refresh_history()
        assert "2 transcripts" in window.history_count_label.text()
        assert "A stored transcript" in _history_text()

        # "Clear history" on an empty history did nothing at all when clicked —
        # a greyed-out button says so instead.
        class _NoHistory:
            @staticmethod
            def entries():
                return []

        stored_history = stub.history
        stub.history = _NoHistory()
        try:
            window._refresh_history()
            assert not window.history_clear_button.isEnabled()
            assert "No transcripts yet" in _history_text()
        finally:
            stub.history = stored_history
            window._refresh_history()
        assert window.history_clear_button.isEnabled()

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

        # "Always keep it on the clipboard" and "restore the previous clipboard
        # content" contradict each other, and the injector resolves it in favour
        # of the first. A checkbox nothing acts on must not stay tickable: it
        # greys out and the hint says why.
        from listen_to_me.choices import clipboard_copy_label

        saved_clipboard = window._selected_clipboard_mode()
        window.clipboard_combo.setCurrentText(clipboard_copy_label("always"))
        assert not window.chk_restore.isEnabled()
        assert "Always" in window._clipboard_hint.text()
        window.clipboard_combo.setCurrentText(clipboard_copy_label("on_failure"))
        assert window.chk_restore.isEnabled() and not window._clipboard_hint.text()
        assert window._collect()["clipboard_copy"] == "on_failure"
        window.clipboard_combo.setCurrentText(clipboard_copy_label(saved_clipboard))

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

        # The clipping guard above only ever renders short strings, which is
        # why this trap survived it: a wrapping QLabel reports its longest
        # *word* as its minimum width, and a Windows path, a URL or a repo id
        # has nothing to wrap at. One such status line used to push the whole
        # page past its viewport. Every label whose text is composed from a
        # probe, a path or an exception must therefore stay elastic — what the
        # layout really asks for is the widget item's minimum, so measure that.
        from PySide6.QtWidgets import QWidgetItem

        long_path = (
            r"C:\Users\a.verylongusername\AppData\Local\Programs\ListenToMe"
            r"\models\huggingface\hub\models--openai--whisper-large-v3"
        )
        for name, label in {
            "CUDA status": window.hw_cuda_label,
            "OpenVINO status": window.hw_ov_label,
            "model status": window.hw_model_label,
            "transcription test": window.diag_status,
            "microphone test": window.mic_status,
            "hotkey test": window.hotkey_test_status,
            "update check": window.update_status,
            "autostart": window.autostart_status,
        }.items():
            label.setText(f"failed: {long_path}")
            label.setVisible(True)  # the autostart line hides itself when empty
            demanded = QWidgetItem(label).minimumSize().width()
            assert 0 < demanded <= label.minimumWidth(), (
                f"{name} label demands {demanded}px for its longest word "
                f"(elastic floor {label.minimumWidth()}px) — that widens the page"
            )

        # Update download feedback: a bare percentage says nothing about a
        # few-hundred-MB transfer, so the status line carries the sizes — and
        # keeps reporting progress when the server sends no Content-Length.
        window._update_download_label = "v2026.07.30.1"
        window._on_update_progress(50 * 1024 * 1024, 200 * 1024 * 1024)
        assert window.update_progress.value() == 25
        assert "50.0 MB of 200.0 MB" in window.update_status.text()
        window._on_update_progress(1024 * 1024, 0)  # unknown total → indeterminate
        assert window.update_progress.maximum() == 0
        assert "1.0 MB so far" in window.update_status.text()

        # Idle guard: a hotkey press still queued in App is applied before the
        # state is read, so a test can't take the microphone/listener while a
        # recording is starting behind it.
        stub.queued_state = "recording"
        assert window._app_busy()
        stub.state = "idle"
        assert not window._app_busy()

        # Cancel plumbing: Cancel stops the diagnostic, re-enables the buttons
        # and makes everything the detached worker still emits stale.
        gen, cancel = window._begin_diag("mic")
        assert window._diag_busy and window.mic_cancel_button.isEnabled()
        assert not window.mic_test_button.isEnabled()
        # A recording test owns the microphone: the global hotkey is paused so
        # a press can't open a second input stream on the same device.
        assert not stub.hotkeys.running
        window._cancel_diagnostic()
        assert cancel.is_set() and not window._diag_busy
        assert stub.hotkeys.running
        assert not window.mic_cancel_button.isEnabled()
        # Cool-down: the start buttons come back only after the timer, so a
        # restart can't race the worker that was just detached.
        assert window._diag_cooldown_timer.isActive()
        assert not window.mic_test_button.isEnabled()
        window._end_diag_cooldown()
        assert window.mic_test_button.isEnabled()
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
        assert not wizard._engine_note.text()
        # Parakeet ignores the model and language chosen on the previous wizard
        # page — the page must say so instead of dropping them silently.
        wizard.backend_combo.setCurrentIndex(2)  # Parakeet
        assert "Parakeet" in wizard._engine_note.text()
        wizard.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        assert not wizard._engine_note.text()
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
    ("config guards scalar types", _config_guards_scalar_types),
    ("history normalizes entries", _history_normalizes_entries),
    ("history latest transcript", _history_latest_transcript),
    ("history search matching", _history_search_matching),
    ("recorder start failure resets", _recorder_start_failure_resets),
    ("injector paste fallback", _injector_paste_falls_back_to_typing),
    ("injector clipboard policy", _injector_clipboard_policy),
    ("clipboard copy is announced", _clipboard_copy_is_announced),
    ("theme scrollbar contrast", _theme_scrollbar_contrast),
    ("mute integrations no-op", _integrations_noop),
    ("mute keybind uses virtual keys", _mute_keybind_uses_virtual_keys),
    ("single-instance guard", _single_instance_guard),
    ("live typing logic", _live_typing_logic),
    ("icon render", _icon_render),
    ("key picker key mapping", _key_mapping),
    ("autostart entry refresh", _autostart_refresh),
    ("autostart reports a failed registration", _autostart_reporting),
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
    ("clipboard copy falls back to Qt", _clipboard_copy_falls_back_to_qt),
    ("glyph icons render", _glyph_icons),
    ("keyboard focus stays visible", _theme_focus_visible),
    ("disabled buttons look disabled", _theme_disabled_visible),
    ("voice mic widget", _voice_mic_widget),
    ("tray names the hotkey", _tray_names_the_hotkey),
    ("tray survives a missing notification area", _tray_survives_a_missing_notification_area),
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
