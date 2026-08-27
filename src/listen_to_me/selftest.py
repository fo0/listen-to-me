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
    # The monitor anchor of the floating icon's position — without these the
    # icon can only be remembered by desktop coordinates, which is what put it
    # back on the main screen after every reboot.
    assert set(DEFAULTS["overlay"]) >= {"x", "y", "screen", "rel_x", "rel_y"}
    for key in ("x", "y", "screen", "rel_x", "rel_y"):
        assert DEFAULTS["overlay"][key] is None
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
        # json.load accepts the NaN/Infinity literals; int() of those raises,
        # which once escaped _coerce and reset the WHOLE config to defaults.
        # Each bad value must cost only its own key — the sibling survives.
        path.write_text(
            '{"max_seconds": NaN, "beam_size": Infinity, '
            '"assistant": {"temperature": "nan"}, "language": "de"}',
            encoding="utf-8",
        )
        cfg = Config(path=path)
        assert cfg["max_seconds"] == DEFAULTS["max_seconds"]
        assert cfg["beam_size"] == DEFAULTS["beam_size"]
        assert cfg["assistant"]["temperature"] == DEFAULTS["assistant"]["temperature"]
        assert cfg["language"] == "de"
        assert cfg.load_failed is False


def _config_read_failure_never_costs_the_file():
    """A config that cannot be READ must not be overwritten by the next save:
    the in-memory data is only the defaults then, and the file on disk may be
    intact (a transient AV lock) or recoverable. save() moves it aside once
    (config.json.bad) so the original stays available."""
    import json

    from listen_to_me.config import DEFAULTS, Config

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        broken = '{"language": "de", THIS IS NOT JSON'
        path.write_text(broken, encoding="utf-8")
        cfg = Config(path=path)
        assert cfg.load_failed is True
        assert cfg["language"] == DEFAULTS["language"]  # defaults, not a crash
        assert path.read_text(encoding="utf-8") == broken  # load alone touches nothing
        assert cfg.save() is True
        bad = path.with_name(path.name + ".bad")
        assert bad.read_text(encoding="utf-8") == broken  # original preserved
        assert json.loads(path.read_text(encoding="utf-8"))  # fresh valid config
        assert cfg.load_failed is False
        assert cfg.save() is True  # later saves stay normal
        assert bad.read_text(encoding="utf-8") == broken  # and never touch the backup


def _config_factory_reset():
    """"Reset to factory settings" puts every value back to DEFAULTS, on disk
    as well as in memory — including nested sections, where a shallow reset
    would leave the old overlay/assistant/integration values behind. A config
    that could not be read is preserved as .bad rather than lost, exactly as a
    normal save does."""
    import json

    from listen_to_me.config import DEFAULTS, Config

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = Config(path=path)
        cfg["language"] = "de"
        cfg["backend"] = "openvino"
        cfg["overlay"]["x"] = 1234
        cfg["overlay"]["enabled"] = False
        cfg["assistant"]["enabled"] = True
        assert cfg.save() is True

        assert cfg.reset() is True
        assert cfg.data == DEFAULTS
        assert cfg["overlay"]["x"] is None and cfg["overlay"]["enabled"] is True
        assert cfg["assistant"]["enabled"] is False
        assert json.loads(path.read_text(encoding="utf-8")) == DEFAULTS  # persisted
        assert Config(path=path).data == DEFAULTS  # …and survives a reload
        # DEFAULTS itself must not be aliased by the reset — mutating the live
        # config would otherwise rewrite the defaults for the whole process.
        cfg["overlay"]["x"] = 7
        assert DEFAULTS["overlay"]["x"] is None

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        broken = '{"language": "de", THIS IS NOT JSON'
        path.write_text(broken, encoding="utf-8")
        cfg = Config(path=path)
        assert cfg.load_failed is True
        assert cfg.reset() is True
        assert path.with_name(path.name + ".bad").read_text(encoding="utf-8") == broken
        assert json.loads(path.read_text(encoding="utf-8")) == DEFAULTS


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


def _history_export_format():
    """What Settings → History → "Export…" writes: one block per transcript,
    the local timestamp above the text, blocks separated by a blank line. A
    corrupt timestamp costs the stamp of that one line, never the export."""
    from listen_to_me.history import entry_timestamp, format_entries

    stamp = entry_timestamp({"time": 1_000_000_000.0})
    assert len(stamp) == 16 and stamp[4] == "-" and stamp[10] == " "  # YYYY-MM-DD HH:MM
    for broken in ({"time": "not a number"}, {"time": 10**30}, {"time": None}, {}):
        assert entry_timestamp(broken) == ""

    text = format_entries(
        [
            {"time": 1_000_000_000.0, "text": "second entry\nwith a line break"},
            {"time": "broken", "text": "no stamp"},
            {"time": 999_999_000.0, "text": ""},  # nothing to write
            {"time": 999_999_000.0, "text": "first entry"},
        ]
    )
    blocks = text.rstrip("\n").split("\n\n")
    assert len(blocks) == 3  # the empty transcript is not a block
    assert blocks[0] == f"{stamp}\nsecond entry\nwith a line break"  # order preserved
    assert blocks[1] == "no stamp"  # unusable timestamp keeps the text
    assert text.endswith("first entry\n")  # trailing newline, no trailing blank block
    assert format_entries([]) == ""  # nothing listed → empty file, not a stray newline


def _history_delete_one_entry():
    """Deleting a single transcript removes exactly that one and keeps the
    rest. The row is identified by its own values, never by position: a
    recording appended while the History page sat open must not shift the
    delete onto a neighbouring transcript."""
    from listen_to_me.history import TranscriptHistory

    with tempfile.TemporaryDirectory() as tmp:
        store = TranscriptHistory(Path(tmp) / "history.json")
        store.add("first", timestamp=1.0)
        store.add("secret", timestamp=2.0)
        store.add("third", timestamp=3.0)
        # A newer recording lands between rendering the list and the click.
        store.add("fourth", timestamp=4.0)
        assert store.remove("secret", 2.0) is True
        assert [e["text"] for e in store.entries()] == ["fourth", "third", "first"]
        assert store.latest() == "fourth"  # the newest entry is untouched
        assert store.remove("secret", 2.0) is False  # already gone → no silent success
        # A stored timestamp an older build wrote as a string still matches.
        store.add("stringly", timestamp=5.0)
        assert store.remove("stringly", "5.0") is True
        # Same text at a different second: only the named entry goes.
        store.add("repeat", timestamp=6.0)
        store.add("between", timestamp=7.0)
        store.add("repeat", timestamp=8.0)
        assert store.remove("repeat", 6.0) is True
        assert [e["text"] for e in store.entries()] == [
            "repeat", "between", "fourth", "third", "first",
        ]
        # Without a timestamp the newest match is the one the user clicked.
        assert store.remove("repeat") is True
        assert [e["text"] for e in store.entries()] == ["between", "fourth", "third", "first"]
        # An entry with no usable timestamp is still deletable by text.
        assert store.remove("between", None) is True
        assert [e["text"] for e in store.entries()] == ["fourth", "third", "first"]


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


def _recording_length_warning():
    """The heads-up before the maximum recording length: exactly once, only in
    the closing seconds, never for a cap that is short on purpose, and never an
    exception out of the 100 ms poll for a hand-edited config value."""
    from listen_to_me.app import _LENGTH_WARNING_SECONDS, length_warning_message

    warn = _LENGTH_WARNING_SECONDS
    assert length_warning_message(0.0, 300) is None  # just started
    assert length_warning_message(300 - warn - 1, 300) is None  # still a second early
    message = length_warning_message(300 - warn, 300)  # first tick inside the window
    assert message and str(warn) in message and "300" in message
    assert "seconds left" in message
    message = length_warning_message(295.0, 300)
    assert message and message.startswith("5 seconds left")
    # The cap itself is the auto-stop's business ("Maximum recording length
    # reached"), not a warning about something still to come.
    assert length_warning_message(300.0, 300) is None
    assert length_warning_message(600.0, 300) is None
    # A cap barely longer than the warning window is the user's choice, not a
    # surprise worth interrupting for.
    assert length_warning_message(warn, warn * 2) is None
    assert length_warning_message(warn + 2, warn * 2 + 2) is not None  # cap just past it
    # Untrusted config values must fall through, never raise into the poll.
    for bad in (None, "many", float("nan"), float("inf"), 0, -5):
        assert length_warning_message(10.0, bad) is None
    # A string number is a plausible hand-edit and still works.
    assert length_warning_message(295.0, "300") is not None


def _empty_transcript_names_the_microphone():
    """A take that produced no text says *why*: a microphone that delivered no
    signal (or an unusably quiet one) is a device problem the user can fix,
    and it must not read like a recognition failure. A verdict the classifier
    could not produce falls back to the generic sentence instead of inventing
    a diagnosis."""
    from listen_to_me.diagnostics import _QUIET_PEAK, _SILENT_PEAK, no_speech_message

    generic = no_speech_message("ok")
    assert generic == "No speech detected."
    silent = no_speech_message("silent")
    assert "Settings → Audio" in silent and "muted" in silent
    quiet = no_speech_message("quiet")
    assert "quiet" in quiet.lower() and "Settings → Audio" in quiet
    assert silent != quiet
    for unknown in ("", "unknown", "OK", "Silent"):
        assert no_speech_message(unknown) == generic
    # The thresholds the verdicts rest on: ordered, and both inside full scale.
    assert 0.0 < _SILENT_PEAK < _QUIET_PEAK < 1.0


def _recorder_events_carry_their_take():
    """`auto_stop` / `stream_died` may only stop the take they were posted for:
    both come from PortAudio's callback thread and can wait up to 100 ms in the
    event queue, so one from take A drained after a stop-A/start-B pair inside a
    single poll tick used to stop take B with A's message."""
    from listen_to_me.app import STATE_IDLE, STATE_RECORDING, App

    class _App:
        # Borrowed unbound: a real App needs a tray, a recorder, a transcriber.
        _handle, _owns_take = App._handle, App._owns_take

        def __init__(self, state=STATE_RECORDING):
            self.state, self._recording_id = state, 2
            self.messages: list[str] = []
            self.finished = 0

        def notify(self, message, force=False):
            self.messages.append(message)

        def _finish_recording(self):
            self.finished += 1

    for kind in ("auto_stop", "stream_died"):
        running, stale, idle = _App(), _App(), _App(state=STATE_IDLE)
        running._handle(kind, 2)  # the take that is running
        assert running.finished == 1 and len(running.messages) == 1
        stale._handle(kind, 1)  # a take that already ended
        assert stale.finished == 0 and stale.messages == [], f"{kind} stopped the wrong take"
        idle._handle(kind, 2)
        assert idle.finished == 0, f"{kind} outside a recording must stop nothing"


def _cli_flags():
    """`--help` documents the flags the app really has, and an unrecognized
    argument is answered instead of ignored.

    main() strips its own flags before Qt sees sys.argv, so an unknown one used
    to be swallowed on the way and the tray app came up as if nothing had been
    asked of it — a typo in `--selftest` looked like a hung self-test. Never
    calls main() without arguments: that would start the app."""
    import contextlib
    import io

    from listen_to_me import APP_NAME, __version__
    from listen_to_me.app import main

    def run(args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    for flag in ("--help", "-h"):
        code, out, _err = run([flag])
        assert code == 0, f"{flag} exited {code}"
        # Every flag the app accepts has to appear, or the help lies by omission.
        for documented in ("--version", "--selftest", "--help"):
            assert documented in out, f"{flag} does not mention {documented}"

    code, out, _err = run(["--version"])
    assert code == 0 and __version__ in out and APP_NAME in out

    for bad in (["--verison"], ["-x"], ["--selftest-", "--version"]):
        code, _out, err = run(bad)
        assert code == 2, f"{bad} exited {code} instead of refusing"
        assert bad[0] in err and "--help" in err


def _copy_button_reports_failure():
    """An in-window "Copy" that could not reach the clipboard says so.

    Success and failure used to be indistinguishable: only the success path
    changed the label, so a failed copy looked exactly like a button that was
    never clicked — for the one action whose entire purpose is that the text
    is now somewhere else. The failure state also has to stay up longer than
    the confirmation, because it has to be read rather than just noticed.

    Real Qt is stubbed out: the point is the decision, and the check has to
    hold on a headless runner without an event loop."""
    from listen_to_me import qtutil

    class _Size:
        def __init__(self, width):
            self._width = width

        def width(self):
            return self._width

    class _Button:
        def __init__(self):
            self._text = "Copy"
            self._props: dict = {}
            self.min_width = 0

        def text(self):
            return self._text

        def setText(self, text):
            self._text = text

        def property(self, name):
            return self._props.get(name)

        def setProperty(self, name, value):
            self._props[name] = value

        def sizeHint(self):
            return _Size(len(self._text))

        def setMinimumWidth(self, width):
            self.min_width = width

    class _Timer:
        def __init__(self):
            self.scheduled: list[tuple[int, object]] = []

        def singleShot(self, msec, callback):
            self.scheduled.append((msec, callback))

    original_copy, original_timer = qtutil.copy_to_clipboard, qtutil.QTimer
    try:
        for succeeded in (True, False):
            timer = _Timer()
            qtutil.QTimer = timer
            qtutil.copy_to_clipboard = lambda _text, ok=succeeded: ok
            button = _Button()
            assert qtutil.copy_with_feedback("some transcript", button) is succeeded
            assert button.text() == ("Copied ✓" if succeeded else "Copy failed")
            # Wide enough for the longest label, so the row doesn't reflow.
            assert button.min_width >= len("Copy failed")
            (delay, restore), = timer.scheduled
            restore()
            assert button.text() == "Copy"  # back to the original label
            if succeeded:
                confirmation_ms = delay
            else:
                assert delay > confirmation_ms, "a failure must stay up longer"
        # Nothing to copy stays a no-op — no label flash promising anything.
        timer = _Timer()
        qtutil.QTimer = timer
        qtutil.copy_to_clipboard = lambda _text: True
        button = _Button()
        assert qtutil.copy_with_feedback("", button) is False
        assert button.text() == "Copy" and not timer.scheduled
    finally:
        qtutil.copy_to_clipboard, qtutil.QTimer = original_copy, original_timer


def _assistant_config_is_checked():
    """An enabled assistant with no usable endpoint is refused before a request
    goes out — the settings window asks the same question at Save.

    Without this the misconfiguration only surfaces on the worker thread after
    a dictation, as requests' own "Invalid URL '/chat/completions': No scheme
    supplied" attached to a transcript the user already spoke."""
    from listen_to_me.assistant import AssistantError, config_problem, refine

    good = {"base_url": "http://localhost:11434/v1", "model": "llama3.2"}
    assert config_problem(good) is None
    assert config_problem({**good, "base_url": ""})[0] == "base_url"
    assert config_problem({**good, "base_url": "   "})[0] == "base_url"
    assert config_problem({})[0] == "base_url"  # a truncated config section
    # The scheme is what requests trips over — "localhost:11434" is not a URL.
    assert config_problem({**good, "base_url": "localhost:11434/v1"})[0] == "base_url"
    assert config_problem({**good, "base_url": "HTTPS://host/v1"}) is None  # case
    assert config_problem({**good, "model": " "})[0] == "model"
    # Every reason is a sentence fragment the UI/notification can embed.
    for broken in ({**good, "base_url": ""}, {**good, "model": ""}):
        reason = config_problem(broken)[1]
        assert reason and reason[0].islower() and not reason.endswith(".")
    # refine() must not reach requests with a broken config.
    try:
        refine("hello", {**good, "base_url": ""})
    except AssistantError as exc:
        assert "base URL" in str(exc)
    else:
        raise AssertionError("refine accepted an assistant config without a base URL")


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


def _theme_assets_stay_out_of_shared_temp():
    """The generated chevron SVGs are loaded back through a QSS ``url()``, so
    the directory holding them must belong to this user.

    It used to fall back to ``<system temp>/listen-to-me`` — the same path for
    every account on the box, which anyone can create first and then own. This
    pins that the directory is never under the shared temp root, is ours, and
    (on POSIX) is not group- or world-accessible.
    """
    from listen_to_me.theme import _asset_dir

    d = _asset_dir()
    shared = Path(tempfile.gettempdir()).resolve()
    # Skipped in the odd setup where the home directory itself lives under the
    # temp root — there the two are indistinguishable and the ownership and
    # mode assertions below are the ones that carry the property anyway.
    if shared not in Path.home().resolve().parents:
        assert shared not in d.resolve().parents, f"{d} sits under the shared temp dir"
    if os.name == "posix":
        assert not d.is_symlink(), f"{d} is a symlink"
        st = os.stat(d)
        assert st.st_uid == os.getuid(), f"{d} is owned by uid {st.st_uid}"
        assert st.st_mode & 0o077 == 0, f"{d} is reachable by others: {st.st_mode & 0o777:o}"


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


def _mute_keybind_waits_for_the_hotkey():
    """A mute keybind must not go out while the recording hotkey is still held.

    The target application reads one shared keyboard state, so the hotkey that
    just started the recording lands in the combination it sees: Ctrl+Alt+Space
    turns a Ctrl+Shift+M keybind into Ctrl+Alt+Shift+M, and letting go of the
    shared Ctrl a moment later releases it back out of a held keybind. Both
    halves are why the keys wait for the keyboard to go quiet first.
    """
    import threading
    import time

    from listen_to_me import injector, integrations

    original, held = injector.modifiers_down, [True]
    try:
        # Still held: give up at the timeout and report it, rather than block
        # a recording that is already running for a hotkey held all take long.
        injector.modifiers_down = lambda: True
        started = time.monotonic()
        assert integrations._wait_for_quiet_modifiers(timeout=0.05) is False
        assert time.monotonic() - started >= 0.05, "must not return before the timeout"

        # Released while waiting: proceed as soon as the keyboard is quiet.
        injector.modifiers_down = lambda: held[0]
        threading.Timer(0.02, lambda: held.__setitem__(0, False)).start()
        assert integrations._wait_for_quiet_modifiers(timeout=2.0) is True

        # Nothing held (and every non-Windows run, where the physical state
        # can't be polled): no wait at all, so behaviour is unchanged there.
        injector.modifiers_down = lambda: False
        started = time.monotonic()
        assert integrations._wait_for_quiet_modifiers(timeout=5.0) is True
        assert time.monotonic() - started < 0.05, "a quiet keyboard must not wait"
    finally:
        injector.modifiers_down = original


def _mute_keybind_survives_a_superseded_stop():
    """A stop overtaken by the next recording must not strand held keys.

    The keys go out on a worker now, so a stop's worker can still be waiting
    when the next recording starts and invalidates it. The activation that
    overtook it has to undo the previous one instead of clearing the
    bookkeeping — the alternative leaves the target muted with keys held down
    that nothing will ever release.
    """
    import threading

    from listen_to_me import integrations

    events = []

    class _Controller:
        def press(self, key):
            events.append(("press", key))

        def release(self, key):
            events.append(("release", key))

    mute = integrations.MuteIntegrations.__new__(integrations.MuteIntegrations)
    mute._controller = _Controller()
    mute._held = ["ctrl", "m"]  # left over from the stop that never ran
    mute._toggles = [["shift", "x"]]
    mute._lock = threading.Lock()
    mute._generation = 7

    with mute._lock:
        mute._undo()

    assert events[:2] == [("release", "m"), ("release", "ctrl")], events
    assert ("press", "shift") in events, "a toggle target must be re-tapped"
    assert mute._held == [] and mute._toggles == []

    # A worker whose generation was bumped must not touch a key at all.
    events.clear()
    mute._held = ["ctrl"]
    mute._deactivate(generation=6)  # stale — the current generation is 7
    assert events == [], "a superseded worker must not send keys"
    assert mute._held == ["ctrl"], "...and must leave the bookkeeping alone"
    assert not mute._lock.locked(), "the lock must be released either way"


def _mute_keybind_worker_failure_is_logged():
    """A keybind worker that dies must leave a log line behind.

    The keys go out on a worker, which took them out of the try/except in
    `App._set_state`. An unhandled exception in a thread only reaches
    `threading.excepthook` — it writes to stderr, and a --windowed build has
    none (see app._ensure_std_streams), so the failure would be invisible:
    no log line, no notification, a target simply never muted.
    """
    import logging
    import threading

    from listen_to_me import integrations

    records, done = [], threading.Event()

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
            done.set()

    mute = integrations.MuteIntegrations.__new__(integrations.MuteIntegrations)
    handler = _Capture()
    integrations.log.addHandler(handler)
    try:
        def boom():
            raise RuntimeError("worker blew up")

        mute._spawn(boom)
        assert done.wait(5), "the worker produced no log record at all"
    finally:
        integrations.log.removeHandler(handler)

    assert any(
        r.levelno >= logging.ERROR and r.exc_info for r in records
    ), [r.getMessage() for r in records]


def _mute_presets_are_usable():
    """The shipped mute presets must be sound without pynput on hand.

    They are the whole point of the feature being usable without looking a
    keybind up, so a typo (`<ctlr>`) or a preset that quietly enables itself
    would be worse than shipping none. The real parser check lives in the full
    run (`_hotkey_default_valid`); this pins shape, defaults and the notes.
    """
    from listen_to_me.choices import MUTE_PRESETS, default_mute_targets, mute_preset_note
    from listen_to_me.config import DEFAULTS

    known_names = {
        "ctrl", "alt", "alt_gr", "shift", "cmd", "space", "enter", "tab", "esc",
        "backspace", "delete", "insert", "home", "end", "page_up", "page_down",
        "up", "down", "left", "right", "pause", "print_screen", "scroll_lock",
        "num_lock", "caps_lock", "menu",
    } | {f"f{n}" for n in range(1, 21)}

    seen = set()
    for preset in MUTE_PRESETS:
        assert set(preset) >= {"name", "hotkey", "mode", "note"}, preset
        assert preset["mode"] in ("hold", "toggle"), preset["name"]
        assert preset["name"] not in seen, f"duplicate preset {preset['name']}"
        seen.add(preset["name"])
        # A key combination alone can't say "this app ignores it unless it has
        # focus" — every preset owes the user that sentence.
        assert preset["note"].strip(), preset["name"]
        for token in filter(None, preset["hotkey"].split("+")):
            if token.startswith("<") and token.endswith(">"):
                assert token[1:-1] in known_names, f"{preset['name']}: {token}"
            else:
                assert len(token) == 1, f"{preset['name']}: {token}"

    # Discord is the one preset that needs no setup in the target app, so it
    # leads the list — and its keybind is Discord's Toggle Mute default, which
    # only a toggle-mode target matches.
    assert MUTE_PRESETS[0]["name"] == "Discord"
    assert MUTE_PRESETS[0]["hotkey"] == "<ctrl>+<shift>+m"
    assert MUTE_PRESETS[0]["mode"] == "toggle"

    targets = default_mute_targets()
    assert [t["name"] for t in targets] == [p["name"] for p in MUTE_PRESETS]
    assert all(t["enabled"] is False for t in targets), "presets must ship disabled"
    assert all(set(t) == {"name", "enabled", "mode", "hotkey"} for t in targets), (
        "the note is display-only and must not leak into config.json"
    )
    assert DEFAULTS["integrations"]["targets"] == targets
    # Fresh lists per call, or one Config would mutate the next one's defaults.
    assert default_mute_targets()[0] is not targets[0]

    assert mute_preset_note("discord"), "lookup must ignore case"
    assert mute_preset_note("My Own App") == ""  # a custom row simply shows none


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


def _activation_port_is_exclusive():
    """A live activation listener owns its port alone — nobody can bind it a
    second time and start answering the "show yourself" pings in our place.

    The option that buys this differs per platform (SO_REUSEADDR on POSIX
    relaxes only TIME_WAIT; on Windows it would be the permissive one, so
    SO_EXCLUSIVEADDRUSE goes there instead). This asserts the outcome rather
    than the option, so it holds on both.
    """
    import socket

    from listen_to_me import singleinstance

    holder = singleinstance.SingleInstance(0)
    try:
        port = holder.start_server(lambda: None)
        assert port, "activation server must bind an OS-assigned port"
        rival = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        singleinstance._set_address_reuse(rival)  # a second launch of *this* app
        try:
            rival.bind(("127.0.0.1", port))
            raise AssertionError(f"a second socket bound the live activation port {port}")
        except OSError:
            pass  # refused, as it must be
        finally:
            rival.close()
    finally:
        holder.release()


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
    # Every shipped mute preset must be a combination pynput can actually
    # synthesize — a typo in one of these would ship a target that silently
    # never fires. Checked against the real parser, so it runs in the exe's
    # self-test; the light run only checks their shape.
    from listen_to_me.choices import MUTE_PRESETS

    for preset in MUTE_PRESETS:
        if preset["hotkey"]:
            assert Hotkeys.validate(preset["hotkey"]), preset["name"]
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
    # whole settings page and clips its cards (agent_docs/memory_archive/2026-07.md).
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
    from listen_to_me import RELEASES_URL, updater

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

    # "Open release page" hands its result to webbrowser.open, so a page URL
    # the API response invented must never reach the OS URL handler. The
    # fallback is the releases list — whoever clicked wants a download, not a
    # repository root to navigate out of.
    trusted = "https://github.com/fo0/listen-to-me/releases/tag/v1"
    good, bad = mk("v1"), mk("v1")
    good.html_url = trusted
    assert updater.release_page_url(good) == trusted
    for hostile in ("file:///etc/passwd", "http://evil.example/x", "", "javascript:alert(1)"):
        bad.html_url = hostile
        assert updater.release_page_url(bad) == RELEASES_URL, hostile
    assert updater.download_path_for(Path("/x/ListenToMe.exe")).name == "ListenToMe.update.exe"

    # The relaunch chain must not inherit PyInstaller's bootloader variables,
    # or the updated exe reuses (and misses) the dying process's unpack dir.
    # Restore (not delete) afterwards: inside the packaged exe these variables
    # carry real bootloader values that must survive the check.
    saved = {key: os.environ.get(key) for key in ("_PYI_ARCHIVE_FILE", "_MEIPASS2")}
    os.environ["_PYI_ARCHIVE_FILE"] = "x"
    os.environ["_MEIPASS2"] = "y"
    try:
        env = updater._swap_env()
        assert "_PYI_ARCHIVE_FILE" not in env and "_MEIPASS2" not in env
        assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    finally:
        for key, value in saved.items():
            if value is None:
                del os.environ[key]
            else:
                os.environ[key] = value

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


def _updater_follows_insecure_ssl_switch():
    """The update path honours the insecure-SSL switch like every other
    connection (ADR-0006, superseding ADR-0002): the releases API call and the
    asset download verify by default and stop verifying while the switch is on
    — a hardcoded verify= on either side is the regression this guards against.
    Independent of the switch: the HTTPS/GitHub check on the URL the transfer
    really came from (the only structural guard left once verification is off),
    and a certificate failure surfacing as an explaining UpdateTrustError
    instead of a bare SSLError. requests is faked at the module boundary — it is
    absent in the light CI env."""
    import types

    from listen_to_me import netutil, updater

    asset_url = "https://github.com/fo0/listen-to-me/releases/download/v1/ListenToMe.exe"
    calls: list[dict] = []
    failing: list[bool] = []
    redirect_to: list[str] = []

    class _SSLError(Exception):
        pass

    class _Response:
        headers: dict = {}
        url = ""  # requests: the FINAL URL after redirects

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
        resp = _Response()
        resp.url = redirect_to[0] if redirect_to else url
        return resp

    fake = types.ModuleType("requests")
    fake.get = _get
    fake.exceptions = types.SimpleNamespace(SSLError=_SSLError)
    saved = sys.modules.get("requests")
    sys.modules["requests"] = fake
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for insecure in (False, True):
                netutil.apply_insecure_ssl(insecure)
                assert netutil.verify() is not insecure
                calls.clear()
                updater.fetch_releases()
                updater.download_asset(asset_url, Path(tmp) / "asset.exe")
                assert len(calls) == 2
                # Both requests take the switch's value — neither pins its own.
                assert all(call["verify"] is not insecure for call in calls)

                # requests follows redirects cross-host and cross-scheme; the
                # transfer's final URL must pass the same trust check as the
                # starting one, or a redirect would sidestep the host allowlist.
                redirect_to.append("http://evil.example/ListenToMe.exe")
                try:
                    updater.download_asset(asset_url, Path(tmp) / "asset2.exe")
                    raise AssertionError("a cross-host redirect was followed")
                except ValueError:
                    pass
                redirect_to.clear()

                failing.append(True)
                for attempt in (
                    lambda: updater.fetch_releases(),
                    lambda: updater.download_asset(asset_url, Path(tmp) / "asset.exe"),
                ):
                    try:
                        attempt()
                        raise AssertionError("a certificate failure was not surfaced")
                    except updater.UpdateTrustError as exc:
                        # Explains itself instead of failing silently, and names
                        # the switch only while it is off. With it on there is
                        # no certificate check left to fail, so the message must
                        # not claim one did — that would read as "the option I
                        # enabled did not apply".
                        assert "release page" in str(exc)
                        assert ("Ignore SSL certificate" in str(exc)) is not insecure
                        assert ("could not verify" in str(exc)) is not insecure
                failing.clear()
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
    from listen_to_me.choices import (
        GERMAN_TURBO_CT2,
        MODEL_CHOICES,
        models_for_backend,
        openvino_alternative,
        openvino_supports_model,
    )

    # Every preset the backend refuses names the model that replaces it, and
    # the replacement itself is one the backend accepts — the message used to
    # send the user to faster-whisper instead, which on an Intel machine with
    # no NVIDIA GPU is the wrong half of the pair to change (#112).
    for preset in ("distil-small.en", "distil-medium.en", "distil-large-v3.5", GERMAN_TURBO_CT2):
        assert not openvino_supports_model(preset)
        alternative = openvino_alternative(preset)
        assert openvino_supports_model(alternative)
        assert openvino_model_repo(alternative, "int8").startswith("OpenVINO/")
        try:
            # The German CT2 preset must not fall into the verbatim repo-id branch.
            openvino_model_repo(preset, "int8")
            raise AssertionError(f"expected ValueError for {preset!r} — no OpenVINO conversion")
        except ValueError as exc:
            assert alternative in str(exc), str(exc)

    # What the dropdowns offer per backend: everything for the CT2 backends,
    # only the convertible presets for OpenVINO.
    assert models_for_backend("faster-whisper") == list(MODEL_CHOICES)
    assert all(openvino_supports_model(m) for m, _ in models_for_backend("openvino"))
    assert len(models_for_backend("openvino")) == len(MODEL_CHOICES) - 4
    # A custom id stays allowed: it may well be an OpenVINO IR repo, and the
    # format pre-check below is what decides that.
    assert openvino_supports_model("Someone/custom-ov")

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

    # Download state (#110): a determinate percentage, an indeterminate sweep
    # and the way back. Every one of them has to paint — this replaces the mic
    # glyph with text and an arc, the one path the state animation never takes.
    widget.set_processing(False)
    for fraction in (0.0, 0.07, 0.42, 1.0, None):
        widget.set_progress(fraction)
        assert widget._progress_active is True
        widget._on_tick()
        assert not widget.grab().isNull()
    # Out-of-range input is clamped, never drawn as "-40%" or "250%".
    widget.set_progress(-2.0)
    assert widget._progress == 0.0
    widget.set_progress(9.0)
    assert widget._progress == 1.0
    widget.set_progress(None, active=False)
    assert widget._progress_active is False
    widget._on_tick()
    assert not widget.grab().isNull()
    widget.deleteLater()


def _download_progress_logic():
    """The download progress plumbing (#110): the watcher measures growth from
    a baseline, clamps an overshoot, reports an unknown total as "no
    percentage" rather than inventing one, and always ends with the "download
    over" call. Qt-free and offline — the hub helpers are only checked for not
    raising, since huggingface_hub may or may not be installed here."""
    import time

    from listen_to_me.progress import (
        DownloadWatcher,
        directory_size,
        hub_cache_dir,
        hub_repo_size,
        progress_text,
    )

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        assert directory_size(folder) == 0
        assert directory_size(folder / "does-not-exist") == 0
        (folder / "already-there.bin").write_bytes(b"x" * 400)
        # Partial blobs count: that is what a running download is writing.
        (folder / "model.bin.incomplete").write_bytes(b"y" * 600)
        assert directory_size(folder) == 1000

    # Baseline: what is already on disk when the watch starts is not progress.
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "old.bin").write_bytes(b"x" * (4 * 1024 * 1024))
        reports: list = []
        watcher = DownloadWatcher(
            folder,
            (4 + 8) * 1024 * 1024,  # 4 MB already there, 8 MB still to come
            lambda label, fraction, done, total: reports.append((label, fraction, done, total)),
            label="Downloading test-model",
            poll_seconds=0.1,
        )
        with watcher:
            (folder / "new.bin").write_bytes(b"y" * (2 * 1024 * 1024))
            deadline = time.monotonic() + 5.0
            while not reports and time.monotonic() < deadline:
                time.sleep(0.05)
        assert reports, "the watcher reported nothing"
        label, fraction, done, total = reports[0]
        assert label == "Downloading test-model"
        assert done == 2 * 1024 * 1024  # the pre-existing 4 MB are not progress
        assert total == 8 * 1024 * 1024  # …and neither are they part of the total
        assert 0.24 < fraction < 0.26
        # Leaving the context always reports the end, so no display can stay
        # frozen at some percentage.
        assert reports[-1] == (None, None, 0, 0)

    # An unknown total means no percentage, and an overshoot is clamped.
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        watcher = DownloadWatcher(folder, None, lambda *args: None)
        assert watcher._total is None
        (folder / "big.bin").write_bytes(b"z" * 1024)
        reported: list = []
        watcher = DownloadWatcher(
            folder, 2 * 1024 * 1024, lambda *args: reported.append(args), poll_seconds=0.1
        )
        (folder / "huge.bin").write_bytes(b"z" * (4 * 1024 * 1024))
        watcher._report()
        assert reported and reported[0][1] == 1.0  # clamped, not 2.0

    # A total too small to be a real model is treated as unknown.
    with tempfile.TemporaryDirectory() as tmp:
        assert DownloadWatcher(Path(tmp), 4096, lambda *args: None)._total is None

    assert progress_text("Downloading small", 0.5) == "Downloading small 50%"
    assert "50%" in progress_text("Downloading small", 0.5, 1_000_000, 2_000_000)
    assert "%" not in progress_text("Downloading small", None)
    assert progress_text("", None) == ""

    # Local-only and non-raising whether or not huggingface_hub is installed
    # here. hub_repo_size is deliberately NOT exercised: it is one HTTP request,
    # and the checks stay offline and free.
    hub_cache_dir("OpenVINO/whisper-small-int8-ov")

    # The repo a preset downloads from — an explicit id passes through, and
    # anything unresolvable costs the download its progress display, nothing else.
    from listen_to_me.transcriber import hub_repo_id

    assert hub_repo_id("Someone/faster-whisper-thing") == "Someone/faster-whisper-thing"
    assert hub_repo_id("") is None
    with tempfile.TemporaryDirectory() as tmp:
        assert hub_repo_id(tmp) is None  # a local model directory downloads nothing

    # Parakeet ships both quantizations in one repo, so the size of a download
    # is only the variant it actually fetches.
    from listen_to_me.transcriber_parakeet import _download_filter

    int8, fp32 = _download_filter("int8"), _download_filter(None)
    assert int8("encoder-model.int8.onnx") and not int8("encoder-model.onnx")
    assert fp32("encoder-model.onnx") and fp32("encoder-model.onnx.data")
    assert not fp32("decoder_joint-model.int8.onnx")


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
        self.progress_reports: list = []  # App.progress() calls (download display)
        self.state = "idle"
        # Stands in for an event still sitting in App's queue: _poll() applies
        # it, exactly like the real 100 ms poll timer does.
        self.queued_state: str | None = None

    def post(self, *args, **kwargs):
        self.posts.append(args)

    def progress(self, label, fraction, done=0, total=0):
        self.progress_reports.append((label, fraction, done, total))

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
        self.combo: str | None = None

    def register(self, combo, mode="toggle"):
        self.combo, self.mode = combo, mode
        self.running = True

    def stop(self):
        self.running = False


def _overlay_position_is_anchored_to_its_monitor():
    """The floating icon comes back to the monitor it was dragged onto.

    Desktop coordinates alone cannot express that. They move whenever the
    arrangement, a resolution or the primary screen changes, and at logon the
    app is up before Windows has finished bringing up the secondary displays —
    the saved spot then lands on no screen and the icon falls back to the
    primary. That fallback used to be permanent (nothing ever looked again),
    which is exactly why the icon was back on the main screen after every
    reboot. So: the position is anchored to a monitor identity, and a saved
    position that cannot be honoured yet is retried, not given up on.

    The offscreen platform has a single screen that reports no identity at all,
    so `_screen_key` is stubbed to give it one; the multi-monitor situations are
    then reproduced through the config — a saved identity that matches no
    connected screen is exactly what a monitor that is not up yet looks like.
    """
    _ensure_qapp()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication

    from listen_to_me import overlay as overlay_module
    from listen_to_me.overlay import Overlay

    # The identity itself: EDID fields when the driver reports them, the device
    # name as a fallback, and nothing at all when neither exists — an empty key
    # must stay empty, because a key that every screen shares would "match" the
    # wrong monitor instead of falling back to the coordinates.
    class _FakeScreen:
        def __init__(self, maker="", model="", serial="", name=""):
            self._v = (maker, model, serial, name)

        def manufacturer(self):
            return self._v[0]

        def model(self):
            return self._v[1]

        def serialNumber(self):
            return self._v[2]

        def name(self):
            return self._v[3]

    key = overlay_module._screen_key
    assert key(_FakeScreen("DEL", "U2723QE", "ABC123", r"\\.\DISPLAY2")) == "DEL|U2723QE|ABC123"
    assert key(_FakeScreen(name=r"\\.\DISPLAY2")) == r"\\.\DISPLAY2"
    assert key(_FakeScreen()) == ""

    screen = QGuiApplication.primaryScreen()
    geo = screen.geometry()
    home = (geo.left() + 40, geo.top() + 60)
    overlay_module._screen_key = lambda _s: "TEST-MONITOR"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            stub = _StubApp(Path(tmp))
            overlay = Overlay(stub)
            ocfg = stub.cfg["overlay"]
            try:
                # A drag records the monitor and the offset inside it, not just
                # the desktop coordinates.
                overlay.win.move(*home)
                overlay.save_position()
                assert ocfg["screen"] == "TEST-MONITOR"
                assert (ocfg["rel_x"], ocfg["rel_y"]) == (40, 60)
                assert (ocfg["x"], ocfg["y"]) == home

                # Restart: the icon is where it was left.
                restarted = Overlay(stub)
                assert (restarted.win.x(), restarted.win.y()) == home
                restarted.destroy()

                # That monitor now sits at different desktop coordinates
                # (rearranged / new primary / resolution change): the stale
                # absolute position is off every screen, the anchor still finds
                # the monitor and the icon lands where the user put it.
                ocfg["x"], ocfg["y"] = -4000, -4000
                assert overlay._apply_saved_position()
                assert (overlay.win.x(), overlay.win.y()) == home

                # The monitor is not there (yet) — the logon race. The icon is
                # parked where it can be seen, but the saved position is NOT
                # given up on: the retry picks it up as soon as that monitor
                # answers.
                ocfg["screen"] = "not-connected"
                assert not overlay._apply_saved_position()
                overlay._restore_position()
                assert overlay._on_any_screen(), "the icon was parked off screen"
                assert overlay._place_timer.isActive(), "the saved position was given up on"
                ocfg["screen"] = "TEST-MONITOR"  # …the monitor comes up
                overlay._retry_place()
                assert (overlay.win.x(), overlay.win.y()) == home
                assert not overlay._place_timer.isActive()

                # A monitor that never returns must not leave a timer running:
                # the retry is bounded, and later hot-plug arrives as a screen
                # signal instead.
                ocfg["screen"] = "not-connected"
                overlay._restore_position()
                for _ in range(overlay_module._PLACE_RETRY_LIMIT):
                    overlay._retry_place()
                assert not overlay._place_timer.isActive()

                # Dragging settles it: what the user just chose must not be
                # overwritten by a pending restore of the older position.
                overlay._restore_position()
                assert overlay._place_timer.isActive()
                overlay.win.move(geo.left() + 10, geo.top() + 10)
                overlay.save_position()
                assert not overlay._place_timer.isActive()
                assert ocfg["screen"] == "TEST-MONITOR"

                # A position saved before the anchor existed (upgrade): it is
                # honoured as before AND anchored once, so the very next
                # monitor rearrangement does not misplace the icon again.
                ocfg["screen"] = ocfg["rel_x"] = ocfg["rel_y"] = None
                ocfg["x"], ocfg["y"] = geo.left() + 24, geo.top() + 32
                Overlay(stub).destroy()
                assert ocfg["screen"] == "TEST-MONITOR", "an old position was not anchored"
                assert (ocfg["rel_x"], ocfg["rel_y"]) == (24, 32)
                assert (ocfg["x"], ocfg["y"]) == (geo.left() + 24, geo.top() + 32)

                # Nothing saved at all stays unsaved: the first-run corner is
                # not a position anyone chose, so it must not be recorded as one.
                for k in ("x", "y", "screen", "rel_x", "rel_y"):
                    ocfg[k] = None
                Overlay(stub).destroy()
                assert ocfg["x"] is None and ocfg["screen"] is None

                # A restore must never fight a drag in progress — the drop
                # decides where the icon goes, and saves it.
                ocfg["x"], ocfg["y"] = -4000, -4000
                ocfg["screen"] = "not-connected"
                overlay.win.move(*home)
                overlay.win._drag_start = (QPoint(0, 0), QPoint(*home))
                overlay._restore_position()
                overlay._retry_place()
                assert (overlay.win.x(), overlay.win.y()) == home, "the drag was overruled"
                overlay.win._drag_start = None

                # Hand-edited junk costs the saved position, never the icon
                # (config.json is untrusted input; these keys default to null,
                # so nothing type-checks them on load).
                ocfg["x"], ocfg["y"] = "left", None
                ocfg["screen"], ocfg["rel_x"], ocfg["rel_y"] = 17, float("inf"), 2**40
                overlay._restore_position()
                assert overlay._on_any_screen()

                # A running download takes over the icon and the tooltip, and
                # keeps them across a state change — the model is fetched
                # *during* "processing", so a state update must not wipe it
                # (#110). Reporting the end puts the state wording back.
                overlay.set_state("processing")
                overlay.set_progress(0.35, "Downloading small 35%")
                assert overlay.win.mic._progress_active is True
                assert "35%" in overlay.win.toolTip()
                overlay.set_state("processing")
                assert "35%" in overlay.win.toolTip()
                overlay.set_progress(None, None)
                assert overlay.win.mic._progress_active is False
                assert "Transcribing" in overlay.win.toolTip()
                overlay.set_state("idle")
                assert "35%" not in overlay.win.toolTip()
            finally:
                overlay.destroy()
    finally:
        overlay_module._screen_key = key


def _overlay_counts_the_recording_time():
    """The floating icon counts the running take up, like the tray does.

    The clock rides App's 100 ms poll, so it must only ever apply to a take
    that is actually running: a tick draining just after the recording ended
    would otherwise freeze a counter onto an idle icon. A running download
    still owns the icon, and the tooltip and the accessible description stay
    the same sentence (an icon-only control is unreadable through the tooltip
    alone)."""
    _ensure_qapp()
    from listen_to_me.overlay import Overlay

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        overlay = Overlay(stub)
        try:
            # Entering the state starts from the clock-free wording; the first
            # tick puts the counter in, sharing the tray's formatting.
            overlay.set_state("recording")
            assert "Recording…" in overlay.win.toolTip(), overlay.win.toolTip()
            overlay.set_elapsed(72)
            assert "Recording 1:12…" in overlay.win.toolTip(), overlay.win.toolTip()
            # Tooltip and accessible description are one string, always.
            assert overlay.win.toolTip() == overlay.win.accessibleDescription()

            # A download owns the icon while it runs — a clock tick must not
            # take it away (the model is fetched during a take's processing,
            # and the same rule applies to every progress display).
            overlay.set_progress(0.4, "Downloading small 40%")
            overlay.set_elapsed(73)
            assert "40%" in overlay.win.toolTip(), overlay.win.toolTip()
            overlay.set_progress(None, None)
            assert "Recording 1:13…" in overlay.win.toolTip(), overlay.win.toolTip()

            # Leaving the state clears the counter, and a late tick from the
            # finished take is ignored rather than re-labelling an idle icon.
            overlay.set_state("idle")
            overlay.set_elapsed(74)
            tip = overlay.win.toolTip()
            assert "Recording" not in tip and "Idle" in tip, tip

            # Whatever the clock hands over, the label renders — this runs
            # inside the poll timer and must never raise there.
            overlay.set_state("recording")
            for value in (None, -5, float("nan"), "nonsense"):
                overlay.set_elapsed(value)
                assert "Recording" in overlay.win.toolTip(), value
        finally:
            overlay.destroy()


def _overlay_lists_recent_transcripts():
    """The floating icon's menu offers the last few transcripts, like the tray.

    Same store, same bound, same copy path — someone working from the floating
    icon may have the tray switched off entirely, so the shortcut past
    "Settings → History" has to exist on this menu too. An unreadable or empty
    history is named rather than shown as an empty list."""
    _ensure_qapp()
    from listen_to_me import tray as tray_module
    from listen_to_me.overlay import Overlay

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        overlay = Overlay(stub)
        try:
            overlay._fill_recent_menu()
            labels = [action.text() for action in overlay._recent_menu.actions()]
            # _StubApp seeds two transcripts; newest first, as the store hands
            # them over — the same order the tray renders.
            assert labels == [
                "An entry with a corrupt timestamp.",
                "A stored transcript for the self-test.",
            ], labels

            # One menu line whatever the dictation did: no line breaks, elided,
            # and its "&" doubled so Qt renders it instead of eating it as the
            # mnemonic marker.
            stub.history.add("Fish & chips\nsecond line " + "long " * 30)
            overlay._fill_recent_menu()
            label = overlay._recent_menu.actions()[0].text()
            assert label.startswith("Fish && chips second line long"), label
            assert "\n" not in label and label.endswith("…"), label

            # Clicking one copies that transcript verbatim — line breaks and a
            # single "&", exactly as it was stored.
            stub.posts.clear()
            overlay._recent_menu.actions()[0].trigger()
            assert len(stub.posts) == 1 and stub.posts[0][0] == "copy_text", stub.posts
            assert stub.posts[0][1].startswith("Fish & chips\nsecond line"), stub.posts

            # Bounded, and by the *same* number as the tray: the menu is a
            # shortcut, the History page is the archive.
            for i in range(10):
                stub.history.add(f"Transcript number {i}")
            overlay._fill_recent_menu()
            assert len(overlay._recent_menu.actions()) == tray_module._RECENT_LIMIT
            assert overlay._recent_menu.actions()[0].text() == "Transcript number 9"

            stub.history.clear()
            overlay._fill_recent_menu()
            actions = overlay._recent_menu.actions()
            assert len(actions) == 1 and actions[0].text() == "No transcripts yet"
            assert not actions[0].isEnabled()
        finally:
            overlay.destroy()


def _overlay_menu_follows_the_state():
    """The floating icon's menu says what a click on it will do.

    The toggle entry is labelled after the state — the tray's wording, so the
    two menus can never describe the same app differently — and "Cancel
    recording" is only offered while a take is running, because App drops a
    cancel in any other state and a menu entry that does nothing reads as a
    broken one. The state is re-read when the menu opens, so an entry can
    never advertise a state the app has already left."""
    _ensure_qapp()
    from PySide6.QtCore import QPoint

    from listen_to_me.overlay import Overlay

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        overlay = Overlay(stub)
        try:
            assert overlay._act_toggle.text() == "Start recording"
            assert not overlay._act_cancel.isVisible()

            # App sets its own state before it feeds the overlay — the stub
            # follows the same order.
            stub.state = "recording"
            overlay.set_state("recording")
            assert overlay._act_toggle.text() == "Stop recording (insert text)"
            assert overlay._act_cancel.isVisible()

            stub.state = "processing"
            overlay.set_state("processing")
            assert overlay._act_toggle.text() == "Start recording"
            assert not overlay._act_cancel.isVisible()

            # A state change the overlay never saw (its set_state is fed by
            # App, the menu is opened by the user) still reaches the entries:
            # show_menu re-reads the app right before the popup.
            stub.state = "recording"
            overlay.show_menu(QPoint(0, 0))
            overlay._menu.hide()
            assert overlay._act_toggle.text() == "Stop recording (insert text)"
            assert overlay._act_cancel.isVisible()

            # Both entries still post the events they always did.
            stub.posts.clear()
            overlay._act_toggle.trigger()
            overlay._act_cancel.trigger()
            assert stub.posts == [("toggle",), ("cancel",)], stub.posts
        finally:
            overlay.destroy()


def _tray_counts_the_recording_time():
    """A running take is counted up in the tray status, and the clock survives
    whatever the caller hands it.

    The elapsed time is opt-in per call, so every caller that only knows the
    state — and every state that is not a running recording — must keep the
    exact wording it always had."""
    from listen_to_me.tray import _STATE_LABELS, format_duration, state_label

    assert format_duration(0) == "0:00"
    assert format_duration(9.9) == "0:09"  # truncated, never rounded up
    assert format_duration(75) == "1:15"
    assert format_duration(600) == "10:00"
    assert format_duration(3661) == "1:01:01"
    # A clock read before the take was stamped, and hand-edited/garbage input:
    # this renders inside the 100 ms poll and must never raise there.
    assert format_duration(-5) == "0:00"
    assert format_duration(float("nan")) == "0:00"
    assert format_duration(float("inf")) == "0:00"
    assert format_duration(None) == "0:00"
    assert format_duration("nonsense") == "0:00"

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        assert (
            state_label("recording", stub.cfg, elapsed=72)
            == "Recording 1:12… press Ctrl+Alt+Space to stop"
        )
        stub.cfg["hotkey_mode"] = "hold"
        assert (
            state_label("recording", stub.cfg, elapsed=0)
            == "Recording 0:00… release Ctrl+Alt+Space to stop"
        )
        stub.cfg["hotkey"] = ""  # no combo to name: generic wording, still counting
        assert state_label("recording", stub.cfg, elapsed=72) == "Recording 1:12…"
        # Only a running take has a clock — and no clock means the old wording.
        assert state_label("recording", stub.cfg) == _STATE_LABELS["recording"]
        assert state_label("processing", stub.cfg, elapsed=72) == _STATE_LABELS["processing"]
        assert state_label("idle", stub.cfg, elapsed=72) == _STATE_LABELS["idle"]


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


def _tray_click_opens_the_window():
    """Clicking the tray icon opens the main window — it must never start a
    recording again. Single click and double click both count (Windows sends a
    double click as Trigger + DoubleClick), while the right-click that only
    opens the context menu must post nothing at all: a menu that also opened a
    window behind itself would be its own bug."""
    from listen_to_me import tray as tray_module

    reasons = tray_module.QSystemTrayIcon.ActivationReason
    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        tray = tray_module.Tray(stub)
        for reason in (reasons.Trigger, reasons.DoubleClick):
            stub.posts.clear()
            tray._on_activated(reason)
            assert stub.posts == [("settings",)], f"{reason} posted {stub.posts}"
        for reason in (reasons.Context, reasons.MiddleClick, reasons.Unknown):
            stub.posts.clear()
            tray._on_activated(reason)
            assert not stub.posts, f"{reason} posted {stub.posts}"


def _hotkey_pause_is_visible_and_temporary():
    """Pausing the global hotkey stops the listener, says so in the tray status,
    and survives every path that hands the listener back (a saved setting, a
    finished hotkey test). It is refused while a take is running — a hold-mode
    release would never arrive — and it is never written to the config."""
    from listen_to_me.app import STATE_IDLE, STATE_RECORDING, App
    from listen_to_me.tray import _PAUSED_LABEL, _STATE_LABELS, state_label

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        # Only the idle status changes: "press Ctrl+Alt+Space to record" would
        # be a lie, while a running take is still a running take.
        assert state_label("idle", stub.cfg, paused=True) == _PAUSED_LABEL
        assert state_label("idle", stub.cfg, paused=False) != _PAUSED_LABEL
        assert state_label("recording", stub.cfg, paused=True) == (
            "Recording… press Ctrl+Alt+Space to stop"
        )
        assert state_label("processing", stub.cfg, paused=True) == _STATE_LABELS["processing"]

        class _PauseApp:
            """Just the parts App._toggle_hotkey_pause touches."""

            def __init__(self, cfg):
                self.cfg = cfg
                self.state = STATE_IDLE
                self.hotkey_paused = False
                self.hotkeys = _StubHotkeys()
                self.messages: list = []
                self.tray = self

            def notify(self, message, force=False):
                self.messages.append(message)

            def set_state(self, state):  # the tray's half of the interface
                pass

            _register_hotkey = App._register_hotkey
            _toggle_hotkey_pause = App._toggle_hotkey_pause

        app = _PauseApp(stub.cfg)
        app._toggle_hotkey_pause()
        assert app.hotkey_paused and not app.hotkeys.running
        assert app.messages and "paused" in app.messages[-1].lower()
        # Saving a setting, finishing the hotkey test or closing the key picker
        # all re-register — none of them may quietly undo the pause.
        app.hotkeys.running = True
        app._register_hotkey()
        assert not app.hotkeys.running

        app._toggle_hotkey_pause()
        assert not app.hotkey_paused and app.hotkeys.running

        # A running take owns the listener: pausing it would strand a hold-mode
        # recording until the maximum length cut it off.
        app.state = STATE_RECORDING
        app.messages.clear()
        app._toggle_hotkey_pause()
        assert not app.hotkey_paused and app.hotkeys.running
        assert app.messages and "recording" in app.messages[-1].lower()

        # Session-only: nothing about the pause reaches config.json.
        assert "hotkey_paused" not in stub.cfg.data


def _tray_lists_recent_transcripts():
    """The tray's "Recent transcripts" submenu is built from the history file
    every time it opens — newest first, bounded, one elided line each — and an
    entry copies exactly the transcript it shows. An empty history says so
    instead of offering an empty menu."""
    from listen_to_me import tray as tray_module

    _ensure_qapp()
    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        tray = tray_module.Tray(stub)
        tray.start()
        try:
            tray._fill_recent_menu()
            labels = [action.text() for action in tray._recent_menu.actions()]
            # _StubApp seeds two transcripts; newest first, as the store hands
            # them over.
            assert labels == [
                "An entry with a corrupt timestamp.",
                "A stored transcript for the self-test.",
            ], labels

            # A dictated paragraph is one menu line: no line breaks, elided,
            # and its "&" doubled so Qt renders it instead of eating it as the
            # mnemonic marker.
            stub.history.add("Fish & chips\nsecond line " + "long " * 30)
            tray._fill_recent_menu()
            label = tray._recent_menu.actions()[0].text()
            assert label.startswith("Fish && chips second line long"), label
            assert "\n" not in label and label.endswith("…"), label

            # A running download owns the tooltip and the status line until it
            # reports itself done — the floating icon can be switched off, and
            # the tray is then the only place a model download shows at all
            # (#110). A state change or a clock tick must not wipe it.
            tray.set_progress("Downloading small 40% (200 MB / 500 MB)")
            assert "40%" in tray._icon.toolTip()
            assert "40%" in tray._act_state.text()
            tray.set_state("processing")
            assert "40%" in tray._icon.toolTip()
            stub.state = "recording"
            tray.set_elapsed(12)
            assert "40%" in tray._icon.toolTip()
            stub.state = "idle"
            tray.set_progress(None)
            assert "40%" not in tray._icon.toolTip()
            assert "Idle" in tray._icon.toolTip()

            # Clicking one copies that transcript — with its line breaks and a
            # single "&", exactly as it was stored.
            stub.posts.clear()
            tray._recent_menu.actions()[0].trigger()
            assert len(stub.posts) == 1 and stub.posts[0][0] == "copy_text", stub.posts
            assert stub.posts[0][1].startswith("Fish & chips\nsecond line"), stub.posts

            # Bounded: the menu is a shortcut, the History page is the archive.
            for i in range(10):
                stub.history.add(f"Transcript number {i}")
            tray._fill_recent_menu()
            assert len(tray._recent_menu.actions()) == tray_module._RECENT_LIMIT
            assert tray._recent_menu.actions()[0].text() == "Transcript number 9"

            stub.history.clear()
            tray._fill_recent_menu()
            actions = tray._recent_menu.actions()
            assert len(actions) == 1 and actions[0].text() == "No transcripts yet"
            assert not actions[0].isEnabled()
        finally:
            tray.stop()


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


def _help_page_find():
    """The Help page can be searched, and the search wraps around.

    Every topic sits in one long document whose only navigation is the "Jump
    to" list at the top, so the reader holding an actual error string needs to
    look for it by name. Wrapping is the part that has to hold: a reader who
    started in the middle of the page must not be told "not found" about a word
    that is plainly there — only a term missing from the whole document says
    so."""
    from listen_to_me.settings_ui import SettingsWindow
    from listen_to_me.theme import apply_theme

    app = _ensure_qapp()
    apply_theme(app)

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        window = SettingsWindow(stub)
        try:
            # Nothing to look for yet: the step buttons must not offer an
            # action they cannot perform.
            assert not window.help_find_next.isEnabled()
            assert not window.help_find_prev.isEnabled()

            # Typing searches from the top, so the term resolves to the first
            # match however far the reader had already scrolled.
            window.help_find_edit.setText("proxy")
            assert window.help_find_next.isEnabled()
            assert window.help_find_status.text() == "", window.help_find_status.text()
            selected = window._help_browser.textCursor().selectedText()
            assert selected.casefold() == "proxy", selected

            # Stepping on eventually runs out of matches and starts over —
            # never "Not found" for a term the document contains.
            seen = set()
            for _ in range(20):
                window._find_in_help()
                seen.add(window.help_find_status.text())
            assert "Wrapped around" in seen, seen
            assert "Not found" not in seen, seen

            # Backwards steps too, and wraps the same way.
            window._find_in_help(backwards=True)
            assert window.help_find_status.text() in ("", "Wrapped around")
            selected = window._help_browser.textCursor().selectedText()
            assert selected.casefold() == "proxy", selected

            # A term that is genuinely absent is the one case that says so.
            window.help_find_edit.setText("Zzzz-nope")
            assert window.help_find_status.text() == "Not found"

            # Clearing the field drops the stale verdict and the highlight.
            window.help_find_edit.setText("")
            assert window.help_find_status.text() == ""
            assert not window._help_browser.textCursor().hasSelection()
            assert not window.help_find_next.isEnabled()

            # Ctrl+F's handler selects what is already there, so pressing it
            # twice replaces the old term instead of appending to it.
            window.help_find_edit.setText("OpenVINO")
            window._focus_help_find()
            assert window.help_find_edit.selectedText() == "OpenVINO"

            # A theme switch re-renders the document; the verdict beside an
            # empty selection must not survive it.
            window.help_find_edit.setText("Zzzz-nope")
            assert window.help_find_status.text() == "Not found"
            window._render_help()
            assert window.help_find_status.text() == ""
        finally:
            window.force_close()
            window.deleteLater()


def _gui_construction():
    from listen_to_me import overlay as overlay_module
    from listen_to_me.choices import GERMAN_TURBO_CT2, model_from_label, model_label
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

        # Footer, bottom left: the GitHub and Releases buttons next to the
        # version are real controls that open the project and the download page
        # — before them, the only route to either was the tray menu. Clicked
        # with the browser patched out; a check may never launch anything.
        from listen_to_me import RELEASES_URL, REPO_URL
        from listen_to_me import settings_ui as settings_ui_module

        for button, url in (
            (window.repo_button, REPO_URL),
            (window.releases_button, RELEASES_URL),
        ):
            assert button.isEnabled()
            assert url in button.toolTip()
            assert button.accessibleName(), "a footer link has no accessible name"

        opened: list[str] = []

        class _FakeBrowser:
            @staticmethod
            def open(url):
                opened.append(url)
                return True

        class _DeadBrowser:
            @staticmethod
            def open(url):
                return False  # no handler registered / BROWSER points nowhere

        real_browser = settings_ui_module.webbrowser
        try:
            settings_ui_module.webbrowser = _FakeBrowser
            window.repo_button.click()
            window.releases_button.click()
            # Distinct targets: a Releases link that lands on the project page
            # is the one thing this button must not do.
            assert opened == [REPO_URL, RELEASES_URL], opened
            # A browser that refuses to open must say so — an unreported
            # failure leaves a button that looks alive and does nothing.
            settings_ui_module.webbrowser = _DeadBrowser
            for button in (window.repo_button, window.releases_button):
                window.footer_status.setText("")
                button.click()
                assert window.footer_status.text(), "a failed browser launch reports nothing"
        finally:
            settings_ui_module.webbrowser = real_browser
            window._footer_status_timer.stop()
            window.footer_status.setText("")

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

        # Assistant connection test. It is the only subsystem whose
        # misconfiguration used to surface after the fact — on a worker thread,
        # attached to a dictation already spoken — so the button must (a) not
        # resize mid-click, (b) refuse a statically broken config instantly
        # without touching the network, and (c) report BOTH outcomes and hand
        # the button back either way. Driven through the slots, never through
        # the worker: a check may not make a request or wait on a thread.
        from listen_to_me.settings_ui import _A_TEST_LABEL, _A_TESTING_LABEL

        idle_width = _laid_out_width(window.a_test_button)
        window.a_test_button.setText(_A_TESTING_LABEL)
        assert _laid_out_width(window.a_test_button) == idle_width, (
            "the assistant test button resizes when it switches to the busy label"
        )
        window.a_test_button.setText(_A_TEST_LABEL)

        # The values a test uses are the ones on screen, saved or not — and the
        # enabled checkbox must not gate it: verifying an endpoint BEFORE
        # switching the assistant on is the point of the button.
        window.chk_a_enabled.setChecked(False)
        window.a_url_edit.setText("http://localhost:11434/v1")
        window.a_model_edit.setText("llama3.2")
        values = window._assistant_values()
        assert values["enabled"] and values["model"] == "llama3.2", values
        assert values["base_url"] == "http://localhost:11434/v1", values

        # assistant.timeout was the one DEFAULTS key with no field on any page,
        # so the only way to change it was hand-editing config.json — while it
        # decides how long every dictation is held back by a hung endpoint. It
        # must reach _collect() (Save writes it) and the connection test alike,
        # or the field would silently do nothing.
        window.a_timeout_spin.setValue(45)
        assert window._collect()["assistant"]["timeout"] == 45
        assert window._assistant_values()["timeout"] == 45
        window.a_timeout_spin.setValue(
            SettingsWindow._to_int(stub.cfg["assistant"].get("timeout"), 120)
        )

        # A URL without a scheme is answerable without any request: it must be
        # refused on the spot, not by starting a thread that fails later.
        window.a_url_edit.setText("localhost:11434/v1")
        window._test_assistant()
        assert not window._assistant_busy, "a statically invalid config started a request"
        assert window.a_test_button.isEnabled()
        assert "Cannot test" in window.a_test_status.text(), window.a_test_status.text()

        # Both outcomes: the reply is shown (an endpoint can answer and still
        # return something unusable — that is what would be inserted), the
        # error is shown verbatim, and the button comes back in either case.
        window.a_url_edit.setText("http://localhost:11434/v1")
        for drive, expected in (
            (lambda: window._on_assistant_tested("This is a test of the assistant."), "test of the assistant"),
            (lambda: window._on_assistant_test_failed("Connection refused"), "Connection refused"),
        ):
            window._assistant_busy = True
            window.a_test_button.setEnabled(False)
            window.a_test_button.setText(_A_TESTING_LABEL)
            drive()
            assert not window._assistant_busy
            assert window.a_test_button.isEnabled()
            assert window.a_test_button.text() == _A_TEST_LABEL
            assert expected in window.a_test_status.text(), window.a_test_status.text()

        # "Reset position" for the floating icon. It exists because dragging is
        # unconstrained and a saved position survives as long as its centre is
        # on some screen, so a stranded icon had no way back but config.json.
        # It must post the action (App owns the overlay) and must be greyed out
        # WITH a reason while the icon is off — there is nothing to move then.
        assert window.overlay_reset_button.isEnabled()  # default config: icon on
        posts_before = len(stub.posts)
        window.overlay_reset_button.click()
        assert stub.posts[posts_before:] == [("reset_overlay_position",)], stub.posts
        stub.cfg.data["overlay"]["enabled"] = False
        window._refresh_overlay_reset_button()
        assert not window.overlay_reset_button.isEnabled()
        assert "switched off" in window.overlay_reset_button.toolTip()
        stub.cfg.data["overlay"]["enabled"] = True
        window._refresh_overlay_reset_button()
        assert window.overlay_reset_button.isEnabled()
        assert "bottom right" in window.overlay_reset_button.toolTip()

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
        # "Export…" writes what is listed, so a filtered-to-empty list has
        # nothing to write — an enabled button would produce an empty file.
        assert not window.history_export_button.isEnabled()
        window.history_filter_edit.clear()
        window._refresh_history()
        assert "2 transcripts" in window.history_count_label.text()
        assert "A stored transcript" in _history_text()
        assert window.history_export_button.isEnabled()
        assert len(window._history_export_entries) == 2

        # Ctrl+F reaches the search field from anywhere on this page — the key
        # everyone presses to find something, and the one the Help page's own
        # find field already assumes this page owns. Scoped to the page, so the
        # two searches never compete for it, and it selects what is already in
        # the field so pressing it twice replaces the term instead of appending.
        from PySide6.QtCore import Qt as _QtFind
        from PySide6.QtGui import QKeySequence, QShortcut

        history_page = window.stack.widget(window._history_index)
        find_shortcuts = [
            shortcut
            for shortcut in history_page.findChildren(QShortcut)
            if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Find)
        ]
        assert len(find_shortcuts) == 1, find_shortcuts
        assert (
            find_shortcuts[0].context()
            == _QtFind.ShortcutContext.WidgetWithChildrenShortcut
        )
        window.history_filter_edit.setText("corrupt")
        window._focus_history_filter()
        assert window.history_filter_edit.selectedText() == "corrupt"
        window.history_filter_edit.clear()
        window._refresh_history()

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
            assert not window.history_export_button.isEnabled()
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

        # The OpenVINO backend has no pre-converted model for a few presets.
        # Selecting it must re-list the dropdown and swap an incompatible model
        # for the closest one that works, rather than accept a combination that
        # every screen shows as fine and the first transcription then refuses —
        # after the user has already spoken (#112). Leaving the backend puts the
        # original pick back, and the custom-model row is still recognised by
        # label now that the list length depends on the backend.
        from listen_to_me.choices import GERMAN_TURBO_CT2, model_from_label

        window._fill_model_combo("faster-whisper", GERMAN_TURBO_CT2)
        window._model_index = window.model_combo.currentIndex()
        window.backend_combo.setCurrentIndex(1)  # OpenVINO
        assert window._selected_model() == "large-v3-turbo"
        assert window.model_combo.findText(model_label(GERMAN_TURBO_CT2)) < 0
        assert GERMAN_TURBO_CT2 in window._speech_hint.text()
        last = window.model_combo.count() - 1
        assert window.model_combo.itemText(last) == CUSTOM_MODEL_LABEL
        assert not window._is_custom_entry(window.model_combo.itemText(last - 1))
        assert window._is_custom_entry("Someone/private-ct2-model")

        # …and the "Custom model id…" dialog must not smuggle a filtered-out
        # preset back in through the side door: typing one while OpenVINO is
        # selected is refused with a message, and the previous model stays.
        from listen_to_me import settings_ui as _settings_module

        warned: list = []

        class _FakeInput:
            @staticmethod
            def getText(*_args, **_kwargs):
                return ("distil-small.en", True)

        class _FakeBox:
            @staticmethod
            def warning(*args, **_kwargs):
                warned.append(args[-1])

        real_input = _settings_module.QInputDialog
        real_box = _settings_module.QMessageBox
        _settings_module.QInputDialog, _settings_module.QMessageBox = _FakeInput, _FakeBox
        try:
            before = window._selected_model()
            sentinel_row = window.model_combo.count() - 1
            window.model_combo.setCurrentIndex(sentinel_row)
            window._on_model_activated(sentinel_row)
        finally:
            _settings_module.QInputDialog = real_input
            _settings_module.QMessageBox = real_box
        assert warned and "distil-small.en" in warned[0]
        assert window._selected_model() == before
        assert window.model_combo.currentIndex() == window._model_index

        window.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        assert model_from_label(window.model_combo.currentText()) == GERMAN_TURBO_CT2
        window._fill_model_combo("faster-whisper", saved_model)
        window._model_index = window.model_combo.currentIndex()
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
        assert overlay._watchdog.interval() == 5_000, "the probe cadence regressed"

        def _healthy_tick():
            """One tick with the probes reporting a healthy icon.

            The win32 probes read real OS state (expose, WS_VISIBLE, DWM
            cloaking) that no CI runner guarantees — the frozen Windows build
            failed exactly here, on an icon Qt had shown but not yet painted.
            What these assertions are about is the ladder, so the verdict is
            stubbed; the probe itself gets its own guard further down.
            """
            overlay._dropped_reason = lambda: None
            try:
                overlay._watchdog_tick()
            finally:
                del overlay._dropped_reason
        overlay.win.hide()
        overlay._reassert()
        assert overlay.win.isVisible()
        overlay.win.hide()
        overlay._reassert(hard=True)
        assert overlay.win.isVisible()

        # The tick repairs what its probes report — a Qt-hidden window is
        # re-shown, and a healthy tick afterwards ends the drop episode.
        overlay.win.hide()
        overlay._watchdog_tick()
        assert overlay.win.isVisible(), "the tick did not repair a hidden icon"
        assert overlay._drop_streak == 1
        _healthy_tick()
        assert overlay._drop_streak == 0

        # A position stranded outside every screen (a pure resolution change
        # fires no screenAdded/Removed signal) is brought back by the tick.
        overlay.win.move(-4000, -4000)
        overlay._watchdog_tick()
        assert overlay._on_any_screen(), "the tick did not rescue a stranded icon"
        _healthy_tick()  # healthy again → the episode ends

        # A drag in progress is proof the icon is on screen — and a repair
        # mid-drag would abort the drag, so the tick must stand down.
        overlay.win.hide()
        overlay.win._drag_start = (QPoint(0, 0), QPoint(0, 0))
        overlay._watchdog_tick()
        assert not overlay.win.isVisible(), "the tick fought a drag in progress"
        overlay.win._drag_start = None
        overlay._watchdog_tick()
        assert overlay.win.isVisible()
        _healthy_tick()  # healthy again → the episode ends

        # A tick arriving far too late means the machine was suspended —
        # the window is hard-reshown without waiting for a probe.
        overlay.win.hide()
        overlay._last_tick -= 100.0
        overlay._watchdog_tick()
        assert overlay.win.isVisible(), "no hard re-show after a resume"
        assert overlay._drop_streak == 0

        # The ladder throttles: a drop that survives its repair (a probe that
        # cannot be satisfied on this setup) is retried every 6th tick — once
        # by rebuilding the native window — never on every 5 s tick.
        repairs = []
        overlay._dropped_reason = lambda: "stubbed drop"  # instance shadows method
        overlay._reassert = lambda hard=False: repairs.append("hard" if hard else "soft")
        overlay._recreate_window = lambda: repairs.append("recreate")
        for _ in range(13):
            overlay._watchdog_tick()
        assert repairs == ["hard", "recreate", "hard"], repairs
        del overlay._dropped_reason, overlay._reassert, overlay._recreate_window
        _healthy_tick()
        assert overlay._drop_streak == 0 and overlay.win.isVisible()

        # The last rung actually works on this platform: destroying the
        # native window and re-asserting brings a visible icon back.
        overlay._recreate_window()
        assert overlay.win.isVisible(), "the native rebuild lost the icon"

        # Always-on-top is a setting, applied without a restart: the flag
        # follows the config on both windows, a visible icon stays visible
        # across the native rebuild Qt does for a flag change, and turning it
        # off stops the watchdog forcing the icon back over everything.
        from PySide6.QtCore import Qt as _QtNs

        on_top = _QtNs.WindowType.WindowStaysOnTopHint
        assert overlay.win.windowFlags() & on_top, "the icon should start on top"
        stub.cfg["overlay"]["always_on_top"] = False
        overlay.apply_always_on_top()
        assert not overlay.win.windowFlags() & on_top, "the setting did not reach the icon"
        assert not overlay.bubble.windowFlags() & on_top, "the bubble ignored the setting"
        assert overlay.win.isVisible(), "the flag change lost the icon"
        assert not overlay._always_on_top
        # …and with it off, a healthy tick leaves the z-order alone: raising
        # the icon every 5 s would fight whatever the user just focused.
        raises = []
        overlay.win.raise_ = lambda: raises.append(1)
        _healthy_tick()
        assert not raises, "a healthy tick raised the icon although it may be covered"
        overlay.win.hide()  # …but a real repair still shows and raises it
        overlay._watchdog_tick()
        assert raises and overlay.win.isVisible()
        del overlay.win.raise_
        _healthy_tick()
        stub.cfg["overlay"]["always_on_top"] = True
        overlay.apply_always_on_top()
        assert overlay.win.windowFlags() & on_top and overlay.win.isVisible()

        # A stripped z-order is repaired in place: the tick must not treat it
        # as a drop (no hide()/show() flicker for a window that is only
        # buried) and must not escalate the ladder.
        overlay._dropped_reason = lambda: overlay_module._TOPMOST_LOST
        overlay._watchdog_tick()
        assert overlay._drop_streak == 0, "a lost z-order escalated like a real drop"
        assert overlay.win.isVisible() and overlay._topmost_lost
        del overlay._dropped_reason
        _healthy_tick()
        assert not overlay._topmost_lost, "the z-order episode never ended"

        # The win32 probe path itself, which no Linux run reaches on its own
        # (it sits behind a sys.platform check) — and which is where the
        # frozen Windows build failed: Qt clears the expose state until the
        # platform has painted the window, so a just-repaired icon reports
        # isExposed() == False and counting that on the spot made every
        # repair look like it had failed.
        class _Handle:
            def __init__(self, exposed):
                self._exposed = exposed

            def isExposed(self):
                return self._exposed

        real_platform, real_handle = overlay_module.sys.platform, overlay.win.windowHandle
        try:
            overlay_module.sys.platform = "win32"
            overlay.win.windowHandle = lambda: _Handle(False)
            overlay._unexposed = False
            assert overlay._dropped_reason() is None, "a just-shown window counted as dropped"
            assert overlay._dropped_reason() == overlay_module._UNEXPOSED, (
                "an icon that stays unexposed must be reported"
            )
            overlay.win.windowHandle = lambda: _Handle(True)
            overlay._dropped_reason()  # an exposed tick clears it again…
            overlay.win.windowHandle = lambda: _Handle(False)
            assert overlay._dropped_reason() is None, "an exposed tick must clear the debounce"
        finally:
            overlay_module.sys.platform = real_platform
            overlay.win.windowHandle = real_handle

        # Screen-change bursts (one geometryChanged per screen) coalesce into
        # one settle pass instead of re-placing once per signal.
        overlay._on_screens_changed()
        overlay._on_screens_changed()
        assert overlay._settle_timer.isActive()
        overlay._settle_timer.stop()
        overlay._on_screens_settled()
        assert overlay.win.isVisible()

        overlay.set_visible(False)
        assert not overlay._watchdog.isActive()
        overlay._reassert()  # disabled → must stay hidden
        assert not overlay.win.isVisible()

        # Reset position: an icon dragged almost off screen (drag is
        # unconstrained by design) must be recoverable without editing
        # config.json. It has to move AND persist — a reset that is not written
        # back would be undone by the next launch, which is exactly when the
        # stranded position hurts.
        stranded = (-4000, -4000)
        overlay.win.move(*stranded)
        overlay.reset_position()
        assert (overlay.win.x(), overlay.win.y()) != stranded, "the icon was not moved"
        assert (stub.cfg["overlay"]["x"], stub.cfg["overlay"]["y"]) == (
            overlay.win.x(),
            overlay.win.y(),
        ), "the reset position was not persisted"
        # …and it lands where a first run would have put it, so "reset" and
        # "never moved" cannot drift apart.
        from PySide6.QtGui import QGuiApplication as _QGuiApp

        assert (overlay.win.x(), overlay.win.y()) == overlay._default_corner(
            _QGuiApp.primaryScreen().availableGeometry()
        )

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
        assert "OpenVINO" in wizard._engine_note.text()
        # Parakeet ignores the model and language chosen on the previous wizard
        # page — the page must say so instead of dropping them silently.
        wizard.backend_combo.setCurrentIndex(2)  # Parakeet
        assert "Parakeet" in wizard._engine_note.text()
        wizard.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        assert not wizard._engine_note.text()

        # The OpenVINO backend has no conversion for a few presets. Picking one
        # of those must not survive the switch — the wizard swaps in the closest
        # model that works, says so, and restores the original when the backend
        # moves on (#112).
        wizard._fill_model_combo("faster-whisper", GERMAN_TURBO_CT2)
        wizard.backend_combo.setCurrentIndex(1)  # OpenVINO
        assert model_from_label(wizard.model_combo.currentText()) == "large-v3-turbo"
        assert GERMAN_TURBO_CT2 in wizard._engine_note.text()
        assert wizard.model_combo.findText(model_label(GERMAN_TURBO_CT2)) < 0  # filtered out
        wizard.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        assert model_from_label(wizard.model_combo.currentText()) == GERMAN_TURBO_CT2
        wizard._fill_model_combo("faster-whisper", "small")
        wizard._apply()
        assert stub.cfg["backend"] == "faster-whisper"
        assert stub.cfg["model"] == "small"  # preset label round-trips to the id

        app.processEvents()

        # A model download's byte progress reaches this page's bar *and* the
        # floating icon, and every way a diagnostic ends clears the icon again
        # — a display left at 62% forever is wrong whatever happened (#110).
        window._model_download_label = "small"
        gen = window._diag_gen
        window._on_model_progress(gen, 50 * 1024 * 1024, 200 * 1024 * 1024)
        assert window.diag_progress.value() == 25
        assert stub.progress_reports[-1][1] == 0.25
        # An unknown total means an indeterminate bar and no percentage.
        window._on_model_progress(gen, 50 * 1024 * 1024, 0)
        assert window.diag_progress.maximum() == 0
        assert stub.progress_reports[-1][1] is None
        window._set_diag_busy(False)
        assert stub.progress_reports[-1][0] is None
        # A report from a detached (cancelled/superseded) worker is ignored.
        window.diag_progress.setRange(0, 100)
        window.diag_progress.setValue(7)
        window._on_model_progress(gen + 1, 1, 2)
        assert window.diag_progress.value() == 7

        # "Reset to factory settings" is the one destructive button in this
        # window. It must ask first, and a confirmed reset hands the work to
        # App — which owns the hotkey, the OS autostart entry and the wizard —
        # instead of rewriting values behind the user's back. Declining leaves
        # everything alone; confirming closes the window without the
        # unsaved-changes prompt, since those edits are being discarded anyway.
        from PySide6.QtWidgets import QMessageBox as _RealBox

        class _FakeBox:
            StandardButton = _RealBox.StandardButton
            answer = _RealBox.StandardButton.Cancel
            informed: list = []

            @classmethod
            def question(cls, *_args, **_kwargs):
                return cls.answer

            @classmethod
            def information(cls, *args, **_kwargs):
                cls.informed.append(args[-1])

        real_box = _settings_module.QMessageBox
        _settings_module.QMessageBox = _FakeBox
        try:
            # Not while a take is running: the reset re-registers the hotkey and
            # hands the key picker to the wizard, which would lose the dictation.
            before = len(stub.posts)
            stub.state = "recording"
            window._factory_reset()
            stub.state = "idle"
            assert len(stub.posts) == before
            assert _FakeBox.informed and "recording" in _FakeBox.informed[0]
            assert window._force_close is False

            window._factory_reset()  # declined
            assert len(stub.posts) == before
            assert window._force_close is False
            _FakeBox.answer = _RealBox.StandardButton.Reset
            window._factory_reset()  # confirmed
            assert ("factory_reset",) in stub.posts
            assert window._force_close is True
        finally:
            _settings_module.QMessageBox = real_box

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
    ("config read failure never costs the file", _config_read_failure_never_costs_the_file),
    ("config factory reset", _config_factory_reset),
    ("history normalizes entries", _history_normalizes_entries),
    ("history latest transcript", _history_latest_transcript),
    ("history search matching", _history_search_matching),
    ("history deletes one entry", _history_delete_one_entry),
    ("history export format", _history_export_format),
    ("CLI flags", _cli_flags),
    ("recording length warning", _recording_length_warning),
    ("empty transcript names the microphone", _empty_transcript_names_the_microphone),
    ("recorder events carry their take", _recorder_events_carry_their_take),
    ("assistant config is checked", _assistant_config_is_checked),
    ("recorder start failure resets", _recorder_start_failure_resets),
    ("injector paste fallback", _injector_paste_falls_back_to_typing),
    ("injector clipboard policy", _injector_clipboard_policy),
    ("clipboard copy is announced", _clipboard_copy_is_announced),
    ("copy button reports a failure", _copy_button_reports_failure),
    ("theme scrollbar contrast", _theme_scrollbar_contrast),
    ("theme assets stay out of shared temp", _theme_assets_stay_out_of_shared_temp),
    ("mute integrations no-op", _integrations_noop),
    ("mute keybind uses virtual keys", _mute_keybind_uses_virtual_keys),
    ("mute keybind waits for the hotkey", _mute_keybind_waits_for_the_hotkey),
    ("mute keybind survives a superseded stop", _mute_keybind_survives_a_superseded_stop),
    ("mute keybind worker failure is logged", _mute_keybind_worker_failure_is_logged),
    ("mute presets are usable", _mute_presets_are_usable),
    ("single-instance guard", _single_instance_guard),
    ("activation port is exclusive", _activation_port_is_exclusive),
    ("live typing logic", _live_typing_logic),
    ("icon render", _icon_render),
    ("key picker key mapping", _key_mapping),
    ("autostart entry refresh", _autostart_refresh),
    ("autostart reports a failed registration", _autostart_reporting),
    ("updater version logic", _updater_logic),
    ("updater follows the insecure-SSL switch", _updater_follows_insecure_ssl_switch),
    ("insecure SSL switch", _insecure_ssl_switch),
    ("insecure SSL huggingface httpx API", _insecure_ssl_hub_httpx),
    ("std stream stub (windowed build)", _std_stream_stub),
    ("download progress logic", _download_progress_logic),
    ("transcriber cache probe", _transcriber_cache_probe),
    ("CUDA error detection", _cuda_error_detection),
    ("transcriber CPU fallback", _transcriber_cpu_fallback),
    ("openvino backend logic", _openvino_backend_logic),
    ("parakeet backend logic", _parakeet_backend_logic),
    ("diagnostics engine", _diagnostics_engine),
    ("hardware/status probes", _hardware_probes),
    ("help content renders", _help_content_renders),
    ("help page find", _help_page_find),
    ("Qt icon conversion", _qt_icons),
    ("clipboard copy falls back to Qt", _clipboard_copy_falls_back_to_qt),
    ("glyph icons render", _glyph_icons),
    ("keyboard focus stays visible", _theme_focus_visible),
    ("disabled buttons look disabled", _theme_disabled_visible),
    ("voice mic widget", _voice_mic_widget),
    ("overlay position is anchored to its monitor", _overlay_position_is_anchored_to_its_monitor),
    ("overlay counts the recording time", _overlay_counts_the_recording_time),
    ("overlay lists recent transcripts", _overlay_lists_recent_transcripts),
    ("overlay menu follows the state", _overlay_menu_follows_the_state),
    ("tray names the hotkey", _tray_names_the_hotkey),
    ("tray counts the recording time", _tray_counts_the_recording_time),
    ("tray lists recent transcripts", _tray_lists_recent_transcripts),
    ("hotkey pause is visible and temporary", _hotkey_pause_is_visible_and_temporary),
    ("tray click opens the window", _tray_click_opens_the_window),
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
