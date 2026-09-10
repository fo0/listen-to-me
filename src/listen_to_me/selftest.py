"""Packaging self-test: verifies that all runtime dependencies are bundled and
that the Qt UI constructs without error.

Run with `ListenToMe.exe --selftest` (used by CI after the PyInstaller build).
Writes results to <tempdir>/listen-to-me-selftest.log and exits non-zero on
failure — the executable is windowed, so the log file is the reliable output.

gui_smoke() runs only the light, dependency-free checks (config/icon/keymap/UI
construction) and is what the Linux CI check job calls from source.
"""

from __future__ import annotations

import contextlib
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
    from listen_to_me.config import DEFAULT_FILLER_PHRASES, DEFAULTS

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
    # The filler filter (#190) ships ON: a take with no speech comes back as a
    # sentence nobody spoke, and inserting that at the cursor is the bug — an
    # opt-in guard would leave every fresh install with it.
    assert DEFAULTS["filler_filter"] is True
    assert DEFAULTS["filler_phrases"] == DEFAULT_FILLER_PHRASES
    assert isinstance(DEFAULTS["filler_phrases"], str) and DEFAULTS["filler_phrases"].strip()
    # The second recording source (#191). An empty hotkey is what switches it
    # off, so that — not a flag — is the default; a null device means "auto-pick
    # the best loopback candidate", never "the system default input", which is
    # a microphone (system_audio.resolve_loopback_device).
    system_audio = DEFAULTS["system_audio"]
    assert set(system_audio) == {
        "hotkey", "hotkey_mode", "device", "max_seconds", "bundled_portaudio",
    }
    assert system_audio["hotkey"] == ""
    assert system_audio["hotkey_mode"] in ("toggle", "hold")
    assert system_audio["device"] is None
    # A recorded meeting is not a dictation, so its cap is the longer one.
    assert system_audio["max_seconds"] == 900
    assert system_audio["max_seconds"] > DEFAULTS["max_seconds"]
    # The second assistant profile: only what differs per source lives in it.
    # A base_url/api_key of its own would be one server to configure twice
    # (assistant.profile keeps the connection shared).
    assistant_system = DEFAULTS["assistant"]["system_audio"]
    assert set(assistant_system) == {"enabled", "model", "system_prompt"}
    assert assistant_system["enabled"] is False  # opt-in, like the microphone's
    assert assistant_system["model"] == ""  # empty = the shared model above
    assert assistant_system["system_prompt"].strip()
    assert assistant_system["system_prompt"] != DEFAULTS["assistant"]["system_prompt"]


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


def _config_survives_a_scalar_source_section():
    """The section guard one level deeper, for the two sections #190/#191 added.

    `assistant.system_audio` is a section *inside* a section, and both new ones
    are read where nothing can report a type error: `cfg["system_audio"]
    ["hotkey"]` during hotkey registration, before any window exists, and
    `assistant.profile(cfg["assistant"], source)` on the worker thread after a
    recording is already over. A hand-edited scalar in either place must cost
    that section and nothing else — `_config_survives_corrupt_sections` is the
    same rule for the sections that predate them."""
    import json

    from listen_to_me.config import DEFAULTS, Config

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "system_audio": "off",  # whole section replaced by a scalar
                    # …and the nested profile nulled, next to a sibling key that
                    # has to survive it.
                    "assistant": {"system_audio": None, "model": "mistral"},
                    "filler_filter": "yes",  # unusable scalar → that key's default
                    "filler_phrases": 5,  # a number where the list belongs
                    "max_seconds": 120,  # a valid sibling must still apply
                }
            ),
            encoding="utf-8",
        )
        cfg = Config(path=path)
        assert cfg["max_seconds"] == 120
        assert isinstance(cfg["system_audio"], dict)
        assert cfg["system_audio"] == DEFAULTS["system_audio"]
        assert isinstance(cfg["assistant"]["system_audio"], dict)
        assert cfg["assistant"]["system_audio"] == DEFAULTS["assistant"]["system_audio"]
        assert cfg["assistant"]["model"] == "mistral"
        assert cfg["filler_filter"] == DEFAULTS["filler_filter"]
        assert cfg["filler_phrases"] == DEFAULTS["filler_phrases"]
        # A section that IS a dict still merges key by key: a hotkey set by
        # hand must not cost the cap next to it.
        path.write_text(
            json.dumps(
                {
                    "system_audio": {"hotkey": "<ctrl>+<alt>+s"},
                    "assistant": {"system_audio": {"enabled": True}},
                }
            ),
            encoding="utf-8",
        )
        cfg = Config(path=path)
        assert cfg["system_audio"]["hotkey"] == "<ctrl>+<alt>+s"
        assert cfg["system_audio"]["max_seconds"] == DEFAULTS["system_audio"]["max_seconds"]
        assert isinstance(cfg["system_audio"]["hotkey_mode"], str)  # tray/app read it
        assert cfg["assistant"]["system_audio"]["enabled"] is True
        assert (
            cfg["assistant"]["system_audio"]["system_prompt"]
            == DEFAULTS["assistant"]["system_audio"]["system_prompt"]
        )


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


def _history_search_matches_the_date():
    """Searching the History page by the date a transcript carries.

    Every row shows a ``YYYY-MM-DD HH:MM`` stamp, so a date-shaped term is
    matched against that stamp as well as against the text. The guards matter
    as much as the feature: an ordinary word must never be matched against the
    stamp, and no query that found an entry before may stop finding it."""
    import time as _time

    from listen_to_me.history import _is_stamp_term, entry_timestamp, filter_entries

    # Built from a real local timestamp, because the stamp is rendered in local
    # time — a hard-coded date string would fail in another time zone.
    when = _time.mktime((2026, 9, 5, 14, 30, 0, 0, 0, -1))
    other = _time.mktime((2025, 3, 17, 9, 5, 0, 0, 0, -1))
    entries = [
        {"time": when, "text": "Sprint review notes"},
        {"time": other, "text": "Older dictation about the 2026 budget"},
    ]
    day = entry_timestamp(entries[0])[:10]  # "2026-09-05"
    month = day[:7]  # "2026-09"

    def texts(query):
        return [e["text"] for e in filter_entries(entries, query)]

    assert texts(day) == [entries[0]["text"]]  # the whole day
    assert texts(month) == [entries[0]["text"]]  # a month prefix
    # A date term still matches the text as well — "2026" is written into the
    # second transcript and is the year of the first.
    assert len(texts("2026")) == 2
    # AND over terms holds across the two places: date plus a word.
    assert texts(f"{day} sprint") == [entries[0]["text"]]
    assert texts(f"{day} budget") == []
    # A word is never matched against a stamp, and a single digit is a word.
    assert _is_stamp_term("2026-09") and _is_stamp_term("14:") and _is_stamp_term("09")
    assert not _is_stamp_term("9") and not _is_stamp_term("-") and not _is_stamp_term("--")
    assert not _is_stamp_term("v2026-09") and not _is_stamp_term("")
    # An entry whose timestamp cannot be rendered keeps working: it simply has
    # no stamp to match, and must not raise out of the search.
    assert filter_entries([{"time": "junk", "text": "kept"}], day) == []
    assert filter_entries([{"time": "junk", "text": "kept"}], "kept")[0]["text"] == "kept"


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


def _take_is_warned_about_its_own_cap():
    """The heads-up names the cap the running take really stops at.

    `_check_length_warning` used to read `cfg["max_seconds"]` on every poll
    tick, which was the same number for every take. The two recording sources
    have their own caps (`max_seconds` vs. `system_audio.max_seconds`, 300 vs.
    900 by default), so a system-audio take was warned about a limit that is
    not its own — 30 seconds before nothing happened, and never before the
    limit it actually hits. `_start_recording` stores the cap the recorder was
    opened with, and this reads that.

    Borrowed unbound onto a stub for the reason `_recorder_events_carry_their_
    take` gives: this runs inside the 100 ms poll of a real App."""
    import time

    from listen_to_me.app import STATE_IDLE, STATE_PROCESSING, STATE_RECORDING, App

    class _App:
        _check_length_warning = App._check_length_warning

        def __init__(self, cap, elapsed, state=STATE_RECORDING):
            self.state = state
            self._take_max_seconds = cap
            self._length_warned = False
            self._recording_started = time.monotonic() - elapsed
            # The microphone's cap, deliberately different from every `cap`
            # below: a re-read of this would name the wrong limit.
            self.cfg = {"max_seconds": 300}
            self.messages: list[str] = []

        def notify(self, message, force=False):
            self.messages.append(message)

    system = _App(900, 880)  # a system-audio take, 20 s before its own cap
    system._check_length_warning()
    assert system.messages, "a system-audio take was not warned about its own cap"
    assert "900" in system.messages[0], system.messages[0]
    assert system.messages[0].startswith("20 seconds left"), system.messages[0]
    assert "300" not in system.messages[0], "warned about the microphone's cap"
    # Once per take, not once per poll tick — and latched before the notify, so
    # a failure downstream cannot turn it into one message every 100 ms.
    system._check_length_warning()
    assert len(system.messages) == 1
    assert system._length_warned is True

    # A microphone take is warned about its own 300 s, unchanged.
    mic = _App(300, 280)
    mic._check_length_warning()
    assert mic.messages and "300" in mic.messages[0]
    assert mic.messages[0].startswith("20 seconds left")

    # Nothing outside a running take, and nothing while the cap is still far
    # away — the same two comparisons this rides the event poll for.
    for state in (STATE_IDLE, STATE_PROCESSING):
        idle = _App(900, 880, state=state)
        idle._check_length_warning()
        assert idle.messages == [], state
        assert idle._length_warned is False
    early = _App(900, 5)
    early._check_length_warning()
    assert early.messages == [] and early._length_warned is False
    # A hand-edited cap must fall through, never raise into the poll.
    for bad in (None, "many", float("nan"), 0):
        broken = _App(bad, 880)
        broken._check_length_warning()
        assert broken.messages == [], repr(bad)


def _text_replacements():
    """The user's `find => replace` rules: whole-word and case-insensitive so
    one rule catches the word wherever it lands, the replacement verbatim so it
    always produces the spelling that was typed, and never an exception out of
    the worker thread for a hand-edited rule list."""
    from listen_to_me.app import apply_replacements, parse_replacements
    from listen_to_me.config import DEFAULTS

    assert DEFAULTS["replacements"] == ""  # off until the user writes a rule

    # Syntax: one rule per line, comments and blank lines ignored, a line
    # without the separator skipped instead of failing the whole list.
    rules = parse_replacements(
        "# my words\n\ncuber netes => Kubernetes\nposgres=>PostgreSQL\nbroken line\n"
    )
    assert rules == [("cuber netes", "Kubernetes"), ("posgres", "PostgreSQL")]
    assert parse_replacements("") == [] and parse_replacements(None) == []
    assert parse_replacements("=> nothing to find") == []

    # Case-insensitive, and the replacement is inserted exactly as written —
    # so the sentence-initial occurrence is corrected too, not just the inner one.
    out = apply_replacements("Posgres and posgres.", "posgres => PostgreSQL")
    assert out == "PostgreSQL and PostgreSQL."
    # Whole words only: a rule must not eat the inside of a longer word.
    assert apply_replacements("scala scalable", "scala => Scala") == "Scala scalable"
    # Multi-word search terms and an empty replacement (dropping a filler).
    assert apply_replacements("cuber netes rocks", "cuber netes => Kubernetes") == "Kubernetes rocks"
    assert apply_replacements("so like this", "like =>").strip() == "so  this".strip()
    # Rules run in the order they are written.
    assert apply_replacements("a", "a => b\nb => c") == "c"
    # A term that is not a word at either end still matches (no \b guard there).
    assert apply_replacements("z.b. hier", "z.b. => zum Beispiel") == "zum Beispiel hier"
    # A backslash in the replacement is literal text, not a regex group escape.
    assert apply_replacements("path", "path => C:\\tmp") == "C:\\tmp"

    # Nothing configured, empty text, and untrusted junk all leave the
    # transcript exactly as it was rather than raising into _process.
    assert apply_replacements("unchanged", "") == "unchanged"
    assert apply_replacements("", "a => b") == ""
    for junk in (None, "no separator here", "   ", "=>", "\n\n#\n"):
        assert apply_replacements("keep me", junk) == "keep me"


def _replacement_rules_report_what_was_skipped():
    """The line the Settings page shows under the Text replacements field.

    A mistyped rule used to be dropped with a log warning only, so the field
    looked exactly like one whose rules all work. The status names how many
    rules are in force and which lines were thrown away — and collecting them
    must not change what parse_replacements returns."""
    from listen_to_me.app import (
        _MAX_REPLACEMENT_RULES,
        _MAX_REPORTED_ISSUES,
        describe_replacements,
        parse_replacements,
    )

    # An untouched field says nothing — the placeholder explains the syntax.
    for empty in ("", "   ", None, "# only a comment\n\n"):
        assert describe_replacements(empty) == ""

    # All good: the count, and nothing else.
    assert describe_replacements("a => b") == "1 rule active."
    assert describe_replacements("a => b\nc => d") == "2 rules active."

    # The two ways a line is thrown away, each naming its line number.
    one_bad = describe_replacements("a => b\nposgres -> PostgreSQL")
    assert one_bad.startswith("1 rule active · 1 line ignored:")
    assert "line 2 has no “=>”" in one_bad
    two_bad = describe_replacements("broken\n=> nothing to find\na => b")
    assert "2 lines ignored" in two_bad and "line 1" in two_bad and "line 2" in two_bad
    # Blank lines and comments are not "ignored lines" — they are syntax.
    assert describe_replacements("# note\n\na => b") == "1 rule active."

    # A pasted list of junk stays one line: the first few are named, the rest counted.
    many = describe_replacements("\n".join(f"bad line {n}" for n in range(1, 9)))
    assert "8 lines ignored" in many and "and 5 more" in many
    for named in range(1, _MAX_REPORTED_ISSUES + 1):
        assert f"line {named} has" in many
    assert f"line {_MAX_REPORTED_ISSUES + 1} has" not in many  # counted, not named

    # The cap is its own sentence rather than an "ignored line" — the parser
    # stops at it and cannot know how many lines followed.
    capped = describe_replacements("\n".join(f"w{n} => x" for n in range(_MAX_REPLACEMENT_RULES + 5)))
    assert capped == f"{_MAX_REPLACEMENT_RULES} rules active. Only the first {_MAX_REPLACEMENT_RULES} rules are used."

    # The issue list is append-only bookkeeping: the rules are the same with
    # and without it, which is what lets the status share the parser.
    spec = "a => b\nbroken\nc=>d"
    issues: list[str] = []
    assert parse_replacements(spec, issues) == parse_replacements(spec)
    assert len(issues) == 1


def _filler_filter_drops_a_silent_take():
    """The rule behind #190: a take with no speech comes back as a phrase the
    model invented for silence, and that phrase must not reach the cursor.

    Whisper's training data is subtitle-heavy, so near-silence decodes to a
    closing phrase ("Vielen Dank.", "Thank you.") or a subtitle annotation —
    with high confidence, which is why neither `vad_filter` nor
    `no_speech_threshold` catches it. The filter is deliberately narrow: only a
    match against the WHOLE transcript drops a take, because "vielen Dank" is
    something people really dictate and deleting it out of a sentence would be
    a far worse bug than the one this fixes.

    The bracket rule is the load-bearing half of the comparison and is pinned
    here: brackets survive `normalize`, so the shipped entry `[Musik]` catches
    the annotation while somebody dictating the word `Musik` keeps their word.
    Stripping them makes those two indistinguishable — a wrong answer, not a
    stricter filter."""
    from listen_to_me.config import DEFAULT_FILLER_PHRASES
    from listen_to_me.fillers import EMPTY_TRANSCRIPT, is_filler, normalize

    spec = DEFAULT_FILLER_PHRASES

    # The German and the English phrase, in the punctuation the model writes
    # around them — the returned value is the phrase that matched, so the log
    # can name it.
    assert is_filler("Vielen Dank.", spec) == "vielen dank"
    assert is_filler("  vielen dank!  ", spec) == "vielen dank"
    assert is_filler("„Vielen Dank!“", spec) == "vielen dank"
    assert is_filler("Thank you.", spec) == "thank you"
    assert is_filler("Untertitelung des ZDF, 2020", spec) == "untertitelung des zdf, 2020"
    # A bracketed annotation, which is a non-speech marker and not a word.
    assert is_filler("[Musik]", spec) == "[musik]"
    assert is_filler("(Music)", spec) == "(music)"

    # A real sentence that merely CONTAINS the phrase survives, at either end.
    assert is_filler("Vielen Dank für das Gespräch, ich melde mich morgen.", spec) is None
    assert is_filler("Ich bedanke mich. Vielen Dank.", spec) is None
    assert is_filler("Thank you for the summary of the release notes.", spec) is None
    # …and so does the dictated word whose *annotation* form is on the list.
    # This is the whole reason brackets are kept: without them both normalize
    # to the same string and the spoken word is deleted.
    assert is_filler("Musik", spec) is None
    assert is_filler("Applause", spec) is None
    assert normalize("[Musik]") == "[musik]" and normalize("Musik") == "musik"

    # A transcript with no letter or digit is filler on its own — a silent take
    # decodes to a lone ellipsis or a music glyph just as regularly as to a
    # phrase, and there is nothing to insert either way. Its own marker, so the
    # caller can tell the two cases apart without inventing a list entry.
    for empty in ("...", "♪♪", ".", "—", "[]", "(…)", "", "   ", None):
        assert is_filler(empty, spec) == EMPTY_TRANSCRIPT, repr(empty)
    assert EMPTY_TRANSCRIPT not in spec

    # A broken or non-string list filters nothing rather than raising: this
    # runs on the worker thread between a finished dictation and its
    # insertion, so a hand-edited list may cost the filter, never the text.
    for junk in (None, "", "   ", 12, ["Vielen Dank"], {"a": 1}, object()):
        assert is_filler("Ein ganz normaler diktierter Satz.", junk) is None, repr(junk)
    # A list handed in as a Python list is not a phrase list — str() of it
    # keeps its own brackets and quotes, so it matches nothing.
    assert is_filler("Vielen Dank.", ["Vielen Dank"]) is None


def _filler_phrases_report_what_was_skipped():
    """The line the Settings page shows under the filler phrase field.

    Same contract as `_replacement_rules_report_what_was_skipped` for the field
    next to it, and for the same reason: a line the parser threw away is
    otherwise visible in the log file only, and the field then looks exactly
    like one whose phrases all work. A punctuation-only line is the one worth
    reporting — it could only ever match a transcript that is empty anyway,
    which `is_filler` already covers on its own."""
    from listen_to_me.config import DEFAULT_FILLER_PHRASES
    from listen_to_me.fillers import (
        _MAX_REPORTED_ISSUES,
        describe_filler_phrases,
        parse_filler_phrases,
    )

    # Syntax: one phrase per line, "#" comments and blank lines ignored —
    # the same syntax as the replacements field two cards away.
    assert parse_filler_phrases("# invented phrases\n\nVielen Dank\nThank you!\n") == [
        "vielen dank",
        "thank you",
    ]
    assert parse_filler_phrases("") == [] and parse_filler_phrases(None) == []
    # A line with no letter or digit left in it is skipped and named.
    issues: list[str] = []
    assert parse_filler_phrases("Vielen Dank\n...\n♪♪\n", issues) == ["vielen dank"]
    assert issues == ["line 2 is only punctuation", "line 3 is only punctuation"], issues
    # Phrases that differ only in punctuation are one phrase, not two — a user
    # who wrote both meant one, so the duplicate is dropped without complaint.
    assert parse_filler_phrases("Vielen Dank\nvielen dank!\n„Vielen Dank“") == ["vielen dank"]
    # The issue list is append-only bookkeeping: the phrases are the same with
    # and without it, which is what lets the status share the parser.
    spec = "Vielen Dank\n---\nThank you"
    collected: list[str] = []
    assert parse_filler_phrases(spec, collected) == parse_filler_phrases(spec)
    assert len(collected) == 1

    # An untouched field says nothing — the placeholder explains the syntax.
    for quiet in ("", "   ", None, "# only a comment\n\n"):
        assert describe_filler_phrases(quiet) == "", repr(quiet)
    assert describe_filler_phrases("Vielen Dank") == "1 phrase active."
    assert describe_filler_phrases("Vielen Dank\nThank you") == "2 phrases active."
    # The shipped list has to parse clean: its header is comments and every
    # other line a usable phrase, or a fresh install greets the user with a
    # complaint about a list they never wrote.
    shipped = parse_filler_phrases(DEFAULT_FILLER_PHRASES)
    default_status = describe_filler_phrases(DEFAULT_FILLER_PHRASES)
    assert "ignored" not in default_status, default_status
    assert default_status == f"{len(shipped)} phrases active.", default_status
    assert len(shipped) >= 18, len(shipped)  # 18 today; a deletion is a regression
    assert {"vielen dank", "thank you", "[musik]"} <= set(shipped)

    # The skipped lines, each naming its line number.
    one_bad = describe_filler_phrases("Vielen Dank\n...")
    assert one_bad.startswith("1 phrase active · 1 line ignored:"), one_bad
    assert "line 2 is only punctuation" in one_bad
    # A pasted list of junk stays one line: the first few are named, the rest
    # counted (a list from somewhere else can have dozens of bad lines).
    many = describe_filler_phrases("\n".join("..." for _ in range(8)))
    assert "0 phrases active" in many and "8 lines ignored" in many and "and 5 more" in many
    for named in range(1, _MAX_REPORTED_ISSUES + 1):
        assert f"line {named} is only punctuation" in many
    assert f"line {_MAX_REPORTED_ISSUES + 1} is" not in many  # counted, not named


def _filler_take_inserts_nothing():
    """A hallucinated transcript reaches neither the cursor, the history nor
    the assistant — but only when the take's own audio carried no signal.

    `App._process` is borrowed unbound onto a stub, the way
    `_recorder_events_carry_their_take` borrows `_handle`: a real App needs a
    tray, a recorder and a transcriber. The clip verdict is driven through
    `diagnostics.clip_stats`, which `app._clip_verdict` imports lazily on every
    call — so every case below is exact without numpy and without a real
    recording, and `_clip_verdict`'s own contract (an "unknown" answer instead
    of an exception when it cannot classify at all) is under test with it.

    The case this exists for is the one the phrase list cannot decide alone.
    Two of the shipped phrases ("Vielen Dank", "Thank you") are complete
    sentences people dictate constantly in this project's own default
    language, and dropping one leaves nothing at the cursor, nothing in the
    history and nothing on the clipboard — there is no recovery path from it at
    all. So the clip decides: a phrase on a silent or quiet take is the
    hallucination the filter was written for, the same phrase on a take that
    carried a signal is a dictation and is inserted, and a verdict that could
    not be computed keeps the text as well (fail towards the user's words).

    Three orderings are pinned besides the drop itself. The filter runs before
    `apply_replacements`, or a rule that rewrote the phrase would hide it from
    the filter; it runs before the assistant, because there is nothing to gain
    from paying an LLM to rewrite a sentence nobody spoke; and a take that
    already live-typed text must NOT be filtered — dropping it then leaves the
    typed words on screen while the app reports "no speech" and stores
    nothing, which is worse than the hallucination it was trying to fix."""
    from listen_to_me import assistant as assistant_module
    from listen_to_me import diagnostics as diagnostics_module
    from listen_to_me.app import _NO_SIGNAL_VERDICTS, App, _clip_verdict
    from listen_to_me.audio import SAMPLE_RATE
    from listen_to_me.choices import SOURCE_MIC, SOURCE_SYSTEM
    from listen_to_me.config import Config

    # Membership, not `!= "ok"`: every answer that is not one of these two has
    # to keep the transcript, so growing this tuple is a deliberate decision
    # and not something a new diagnostics verdict can do by accident.
    assert set(_NO_SIGNAL_VERDICTS) == {"silent", "quiet"}, _NO_SIGNAL_VERDICTS

    class _Transcriber:
        def __init__(self, text):
            self.text = text
            self.loads = 0

        def ensure_loaded(self, notify=None, progress=None):
            self.loads += 1

        def transcribe(self, audio, notify=None, progress=None):
            return self.text

    class _Injector:
        def __init__(self):
            self.typed: list[str] = []

        def clipboard_mode(self):
            return "on_failure"

        def type_plain_blocking(self, text):
            self.typed.append(text)
            return ""

    class _History:
        def __init__(self):
            self.stored: list[str] = []

        def add(self, text):
            self.stored.append(text)

    class _Live:
        """The take's LiveTyper, as far as _process reads it."""

        def __init__(self, committed, frames):
            self.committed_text = committed
            self.committed_frames = frames

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return False

        def hand_over(self):
            return ("", bool(self.committed_text))

    class _App:
        _process = App._process

        def __init__(self, cfg, text):
            self.cfg = cfg
            self.transcriber = _Transcriber(text)
            self.injector = _Injector()
            self.history = _History()
            self.inserted: list[str] = []
            # (source, verdict) per report, the arguments the real
            # _notify_no_speech is handed: the verdict is computed once by
            # _process and passed on, and the source decides which device the
            # diagnosis names.
            self.no_speech: list[tuple] = []
            self.posts: list[tuple] = []
            self.messages: list[str] = []

        def notify(self, message, force=False):
            self.messages.append(message)

        def post(self, kind, payload=None):
            self.posts.append((kind, payload))

        def progress(self, *args, **kwargs):
            pass

        def _insert_transcript(self, text):
            self.inserted.append(text)

        def _notify_no_speech(self, audio, source=SOURCE_MIC, verdict=None):
            self.no_speech.append((source, verdict))

    audio = [0.0] * SAMPLE_RATE  # one second: long enough to be transcribed
    refined: list[str] = []

    def _refine(text, acfg):
        refined.append(text)
        return f"refined: {text}"

    # What clip_stats answers for this take. A list, not a real array: the
    # classification is the seam, and building float32 audio for a rule about
    # the *verdict* would tie a headless check to numpy for nothing.
    driven = {"verdict": "silent"}

    def _clip_stats(clip):
        if driven["verdict"] == "unknown":
            # A stripped install without numpy, or an array the classifier
            # chokes on: _clip_verdict answers "unknown" rather than letting
            # it raise through a finished dictation.
            raise RuntimeError("numpy is not installed")
        return {"peak": 0.0, "rms": 0.0, "seconds": 1.0, "verdict": driven["verdict"]}

    real_refine, real_stats = assistant_module.refine, diagnostics_module.clip_stats
    assistant_module.refine = _refine
    diagnostics_module.clip_stats = _clip_stats
    try:
        # The seam itself: whatever the classifier says is this take's verdict,
        # and a classifier that cannot run is "unknown" — never an exception.
        for answer in ("silent", "quiet", "ok", "unknown"):
            driven["verdict"] = answer
            assert _clip_verdict(audio) == answer, answer

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(path=Path(tmp) / "config.json")
            # The assistant is ON, so "never reached" is a fact about the
            # filter rather than about a switched-off feature.
            cfg["assistant"]["enabled"] = True
            # …and a rule that would rewrite the phrase: the filter has to run
            # first, or the rewritten text no longer matches the list.
            cfg["replacements"] = "Vielen Dank => Danke für das Gespräch"

            # --- a phrase on a take that carried no signal ------------------
            for no_signal in _NO_SIGNAL_VERDICTS:
                driven["verdict"] = no_signal
                take = _App(cfg, "Vielen Dank.")
                take._process(audio, None, SOURCE_MIC)
                assert take.inserted == [], (no_signal, take.inserted)
                assert take.history.stored == [], take.history.stored
                assert refined == [], refined
                # Reported like the empty take it really was, with the verdict
                # the decision was made on — computed once, handed over.
                assert take.no_speech == [(SOURCE_MIC, no_signal)], take.no_speech
                # The worker still hands the state machine back: a dropped
                # take must not leave the app in PROCESSING.
                assert ("done", None) in take.posts
                assert ("flash_text", "Vielen Dank.") not in take.posts
            # The source travels with the take, because the diagnosis names a
            # device: a system-audio take must not send the user to their
            # microphone settings.
            driven["verdict"] = "silent"
            system = _App(cfg, "Vielen Dank.")
            system._process(audio, None, SOURCE_SYSTEM)
            assert system.no_speech == [(SOURCE_SYSTEM, "silent")], system.no_speech

            # --- the same phrase on a take that DID carry speech ------------
            # The regression this check exists to catch: a dictated "Vielen
            # Dank." was discarded, and it left nothing anywhere — not at the
            # cursor, not in the history, not on the clipboard.
            cfg["replacements"] = ""
            driven["verdict"] = "ok"
            spoken = _App(cfg, "Vielen Dank.")
            spoken._process(audio, None, SOURCE_MIC)
            assert spoken.no_speech == [], "a phrase on a clip with a signal was dropped"
            assert refined == ["Vielen Dank."], refined
            assert spoken.inserted == ["refined: Vielen Dank."], spoken.inserted
            assert spoken.history.stored == spoken.inserted, spoken.history.stored
            assert ("flash_text", "refined: Vielen Dank.") in spoken.posts

            # --- a verdict that could not be computed at all ----------------
            # Keeps the text: the filter costs a hallucination, the other
            # direction costs the user their words.
            refined.clear()
            driven["verdict"] = "unknown"
            unknown = _App(cfg, "Vielen Dank.")
            unknown._process(audio, None, SOURCE_MIC)
            assert unknown.no_speech == [], "an unclassifiable take was dropped"
            assert unknown.inserted == ["refined: Vielen Dank."], unknown.inserted
            assert unknown.history.stored == unknown.inserted

            # --- a transcript with no letter or digit in it -----------------
            # Dropped whatever the audio says: there is nothing in it anybody
            # can have said, and a lone ellipsis or music glyph at the cursor
            # is not a take somebody wants back.
            for whatever in ("ok", "unknown"):
                driven["verdict"] = whatever
                empty = _App(cfg, "...")
                empty._process(audio, None, SOURCE_MIC)
                assert empty.inserted == [], (whatever, empty.inserted)
                assert empty.history.stored == []
                assert empty.no_speech == [(SOURCE_MIC, whatever)], empty.no_speech

            # --- the switch ------------------------------------------------
            # Off, the hallucination is inserted again even on a silent take,
            # which is exactly the bug #190 is about.
            refined.clear()
            driven["verdict"] = "silent"
            cfg["assistant"]["enabled"] = False
            cfg["filler_filter"] = False
            unfiltered = _App(cfg, "Vielen Dank.")
            unfiltered._process(audio, None, SOURCE_MIC)
            assert unfiltered.inserted == ["Vielen Dank."], unfiltered.inserted
            assert unfiltered.no_speech == []

            # --- a take that already live-typed ----------------------------
            # Append-only typing cannot take anything back, so this take is
            # NOT filtered — it is stored and reported like any other, on a
            # silent clip included.
            cfg["filler_filter"] = True
            typed = _App(cfg, "")
            typed._process(audio, _Live("Vielen Dank.", len(audio)), SOURCE_MIC)
            assert typed.no_speech == [], "a live-typed take must not be dropped"
            assert typed.history.stored == ["Vielen Dank."], typed.history.stored
            assert ("flash_text", "Vielen Dank.") in typed.posts
            # An armed but silent live typer (nothing committed, nothing typed)
            # is not that case — the filter applies to it normally.
            armed = _App(cfg, "Vielen Dank.")
            armed._process(audio, _Live("", 0), SOURCE_MIC)
            assert armed.no_speech == [(SOURCE_MIC, "silent")], armed.no_speech
            assert armed.history.stored == []
    finally:
        assistant_module.refine = real_refine
        diagnostics_module.clip_stats = real_stats


def _assistant_failure_is_actionable():
    """A failing assistant interrupts a real dictation, so its notification has
    to say what to do — not print the `requests` transport chain. The app's own
    wording and an HTTP status survive untouched, and every message says the
    transcript was still inserted."""
    from listen_to_me.app import assistant_failure_message
    from listen_to_me.assistant import AssistantError

    try:
        import requests
    except ImportError:  # stripped-down install — nothing to translate
        return

    # The common case by far: the endpoint (a local Ollama) is not running.
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='localhost', port=11434): Max retries exceeded "
        "with url: /v1/chat/completions (Caused by NewConnectionError(...))"
    )
    message = assistant_failure_message(exc)
    assert "HTTPSConnectionPool" not in message and "NewConnectionError" not in message
    assert "could not be reached" in message
    # The transcript is not lost to this — every wording has to say so.
    assert "raw transcript" in message

    message = assistant_failure_message(requests.exceptions.Timeout())
    assert "did not answer in time" in message and "raw transcript" in message

    # The app's own reason is already written for the user: pass it through.
    message = assistant_failure_message(AssistantError("no model name is set (Settings → Assistant)"))
    assert "no model name is set (Settings → Assistant)" in message
    assert "raw transcript" in message

    # An exception with no message at all still produces a usable sentence
    # rather than "Assistant failed:  Inserting…", and a passed-through reason
    # is punctuated so it does not run into the sentence that follows it.
    message = assistant_failure_message(RuntimeError())
    assert message.count("  ") == 0
    assert "RuntimeError. Inserting" in message
    assert assistant_failure_message(AssistantError("no model name is set")).count("..") == 0


def _missing_microphone_falls_back():
    """A configured microphone that is no longer there costs the device, not
    the dictation: PortAudio indices are positional, so the take falls back to
    the system default — and says so, because a silent swap of the recording
    device is exactly what must not happen."""
    from listen_to_me.choices import resolve_input_device

    devices = [(0, "Built-in Microphone"), (3, "USB Headset")]

    # Present, or the system default anyway: record from it, say nothing.
    assert resolve_input_device(3, devices) == (3, None)
    assert resolve_input_device(0, devices) == (0, None)
    assert resolve_input_device(None, devices) == (None, None)

    # Gone: fall back to the system default with an actionable sentence that
    # names where the microphone is picked again.
    device, note = resolve_input_device(7, devices)
    assert device is None
    assert note and "Settings" in note and "Audio" in note
    assert "system default" in note

    # An enumeration that failed or came back empty cannot tell "gone" from
    # "could not ask" — the configured device is passed through untouched
    # rather than moving a recording off a microphone that works.
    assert resolve_input_device(3, []) == (3, None)

    # `input_device` has a null default, so the config merge stores whatever is
    # in the file, and sounddevice also accepts a device *name*. A value that
    # is not an index is left for PortAudio to resolve instead of being
    # overruled against a list it cannot be compared against.
    assert resolve_input_device("USB Headset", devices) == ("USB Headset", None)
    assert resolve_input_device(True, devices) == (True, None)  # bool is an int subclass

    # The live-enumeration path: a raising list_input_devices is caught and
    # logged, never raised into _start_recording.
    import listen_to_me.audio as audio_mod

    original = audio_mod.list_input_devices
    try:
        audio_mod.list_input_devices = lambda: (_ for _ in ()).throw(RuntimeError("no PortAudio"))
        assert resolve_input_device(3) == (3, None)
    finally:
        audio_mod.list_input_devices = original


def _loopback_device_is_ranked_and_resolved():
    """Which device a system-audio take records from — and the refusal that
    keeps it from recording the room (#191).

    Nothing can ask WASAPI for a loopback stream here (sounddevice 0.5.6
    exposes no loopback option), so the second source records from an ordinary
    PortAudio *input* device that happens to carry the output: "Monitor of …"
    on PipeWire/PulseAudio, "Stereo Mix" or a virtual cable on Windows,
    BlackHole on macOS. Identifying it is name matching, and the ranking is
    data (`LOOPBACK_HINTS`) so an unseen device name is one line instead of a
    branch.

    The contract this pins hardest: **a returned index of None means refuse
    the take**, and it always carries a note. It does NOT mean "the system
    default" the way `choices.resolve_input_device` does — the default input
    *is* a microphone, so falling back to it would record the room while the
    user asked for what the computer plays. That is a wrong result, not a
    degraded one, and nothing about the transcript would give it away. The
    answer is a `LoopbackChoice` for exactly that reason: two of its three
    fields have the shape of `resolve_input_device`'s answer with the opposite
    meaning, so a `device, note = …` unpack has to fail loudly instead of
    silently recording a microphone."""
    from listen_to_me.system_audio import (
        LoopbackChoice,
        loopback_candidates,
        resolve_loopback_device,
        system_audio_help,
    )

    def _profile(index, name):
        # The shape audio.input_device_profiles() returns.
        return {
            "index": index,
            "name": name,
            "hostapi": "ALSA",
            "channels": 2,
            "samplerate": 48000.0,
        }

    mic = _profile(0, "Built-in Microphone")
    stereo_mix = _profile(2, "Stereo Mix (Realtek(R) Audio)")
    monitor = _profile(4, "Monitor of Built-in Audio Analog Stereo")
    hdmi_monitor = _profile(5, "Monitor of HDMI / DisplayPort")
    loopback = _profile(7, "Speakers (Realtek(R) Audio) [Loopback]")

    # A plain microphone scores nothing at all — offering it would be the one
    # device that must never be offered here.
    assert loopback_candidates([mic]) == []
    ranked = loopback_candidates([mic, stereo_mix, monitor])
    assert [c["index"] for c in ranked] == [4, 2], ranked
    assert ranked[0]["hint"] == "monitor of" and ranked[0]["score"] == 90
    assert ranked[1]["hint"] == "stereo mix"
    # "<name> [Loopback]" is the strongest hint there is (a newer PortAudio
    # enumerates every output device again as one) and it trips "loopback" as
    # well, so the weights add up — it outranks Stereo Mix even when it is
    # enumerated after it.
    ranked = loopback_candidates([stereo_mix, loopback])
    assert [c["index"] for c in ranked] == [7, 2], ranked
    assert ranked[0]["score"] == 140 and ranked[0]["hint"] == "[loopback]"
    # The candidate carries its whole profile, which is what the dropdown and
    # the recorder read off it.
    assert ranked[0]["name"] == loopback["name"] and ranked[0]["channels"] == 2
    # Equal scores keep PortAudio's enumeration order, so the auto-pick does
    # not shuffle from call to call.
    assert [c["index"] for c in loopback_candidates([monitor, hdmi_monitor])] == [4, 5]
    assert [c["index"] for c in loopback_candidates([hdmi_monitor, monitor])] == [5, 4]

    profiles = [mic, stereo_mix, monitor]
    answers = []

    def _resolved(configured, devices=profiles):
        choice = resolve_loopback_device(configured, devices)
        assert isinstance(choice, LoopbackChoice), choice
        answers.append(choice)
        return choice

    # A configured index whose device still looks like a loopback capture:
    # that one, and nothing to report.
    kept = _resolved(2)
    assert (kept.index, kept.note, kept.refuse) == (2, None, False), kept
    # Three fields, not two — and that is the whole point of the type. The
    # (index, note) shape belongs to `choices.resolve_input_device`, where a
    # None index means "record from the system default"; here it means
    # "refuse". Copying the wrong sibling has to raise on the first take
    # instead of quietly recording a microphone.
    try:
        device, note = resolve_loopback_device(2, profiles)
    except ValueError:
        pass
    else:
        raise AssertionError("a two-value unpack of LoopbackChoice must not work")

    # Nothing configured: the best candidate, silently — auto-pick is the
    # documented default, not a fallback worth interrupting a take for.
    auto = _resolved(None)
    assert (auto.index, auto.note, auto.refuse) == (4, None, False), auto

    # A configured index that is gone (PortAudio indices are positional, so
    # unplugging one interface re-indexes the rest): the best candidate plus a
    # note naming both and where to pick it again.
    moved = _resolved(9)
    assert (moved.index, moved.refuse) == (4, False), moved
    assert moved.note and "9" in moved.note and "Monitor of" in moved.note
    assert "no longer available" in moved.note and "Settings" in moved.note

    # An index that still EXISTS but no longer scores as a loopback device —
    # the worst outcome this feature has. Accepting it on existence alone
    # recorded the room with nothing reported (ADR-0009 rejects exactly that),
    # so the device found at the index is scored and a name with no hint in it
    # is treated like a missing one.
    reindexed = [_profile(2, "Built-in Microphone"), monitor]
    stale = _resolved(2, reindexed)
    assert (stale.index, stale.refuse) == (4, False), stale
    assert stale.note and "Built-in Microphone" in stale.note, stale.note
    assert "does not look like a loopback device" in stale.note, stale.note
    # …and the note names the device recorded from instead, which is what
    # makes "why is my microphone in this transcript?" answerable.
    assert "Monitor of Built-in Audio" in stale.note, stale.note

    # No candidate at all — the refusal. Never a None index without a note,
    # because the note is the only thing the caller can show instead of
    # recording.
    for configured in (None, 9):
        refused = _resolved(configured, [mic])
        assert refused.index is None, configured
        assert refused.note is not None, "a refused take must carry the reason"
        assert "nothing was recorded" in refused.note, refused.note
        assert system_audio_help() in refused.note  # the part the user has to act on

    # An enumeration that failed or came back empty cannot tell "the device is
    # gone" from "PortAudio could not be asked": the configured index is
    # passed through untouched rather than moved off a device that works.
    blind = _resolved(2, [])
    assert (blind.index, blind.note, blind.refuse) == (2, None, False), blind
    # …while the auto case can only report that nothing was found.
    nothing = _resolved(None, [])
    assert nothing.index is None and nothing.note is not None

    # config.json is untrusted and `device` has a null default, so it carries
    # no type — and a value that is not an index is REFUSED rather than handed
    # to sounddevice. A device *name* buys nothing here (the dropdown only
    # ever writes an index or null, so a non-int is a broken hand-edit), and
    # passing one on has a specific cost: sounddevice validates nothing and
    # `bool` is an int subclass, so `True` resolves to input device 1 — a
    # nonsense config value recording the default microphone.
    for junk in ("Stereo Mix", "Monitor of Built-in Audio", True, 1.5, [4]):
        for devices in (profiles, []):
            junked = _resolved(junk, devices)
            assert junked.index is None, repr(junk)
            assert junked.note and "not a device index" in junked.note, junked.note
            assert repr(junk) in junked.note, junked.note  # so the log names it
            assert "nothing was recorded" in junked.note

    # The flag and the index can never disagree, whichever branch answered:
    # `refuse` is the half a reader cannot misread, the None is what the
    # recorder would act on.
    for answer in answers:
        assert answer.refuse is (answer.index is None), answer
        if answer.refuse:
            assert answer.note is not None, answer


# The four host APIs Windows PortAudio enumerates every endpoint through, in
# its own order, plus the two entries that are not hardware at all. Fixture
# data for the shape the other device fixtures in this file deliberately do not
# have: ONE soundcard, seen four times.
_WINDOWS_HOSTAPIS = [
    {"name": "MME"},
    {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"},
    {"name": "Windows WDM-KS"},
]

# What one output has to look like after the filter, whichever fixture built it.
_ONE_SPEAKER = "Speakers (Realtek(R) Audio)"

# The names that may never reach the user: MME's and DirectSound's
# pseudo-devices (no hardware behind either) and the same speaker under a
# second host API.
_WINDOWS_PHANTOMS = (
    "Microsoft Sound Mapper",
    "Primary Sound Driver",
    "Realtek HD Audio output",
)


def _windows_devices(twin: bool = True) -> list[dict]:
    """One Realtek soundcard as Windows PortAudio really enumerates it: every
    endpoint once per host API (MME, DirectSound, WASAPI, WDM-KS) plus
    "Microsoft Sound Mapper - Output" and "Primary Sound Driver", which are
    pseudo-devices.

    `twin` adds the "<name> [Loopback]" input WASAPI emits for every render
    endpoint with the PortAudio the release build ships (#194) — i.e. the
    machine on which system audio works perfectly. Without it, the machine of
    the #195 report: outputs, and nothing that can record them.
    """
    def device(name, hostapi, inputs, outputs):
        return {
            "name": name,
            "hostapi": hostapi,
            "max_input_channels": inputs,
            "max_output_channels": outputs,
            "default_samplerate": 48000.0,
        }

    devices = [
        device("Microsoft Sound Mapper - Input", 0, 2, 0),
        device("Microphone (Realtek(R) Audio)", 0, 2, 0),
        device("Microsoft Sound Mapper - Output", 0, 0, 2),
        device(_ONE_SPEAKER, 0, 0, 2),
        device("Primary Sound Capture Driver", 1, 2, 0),
        device("Microphone (Realtek(R) Audio)", 1, 2, 0),
        device("Primary Sound Driver", 1, 0, 2),
        device(_ONE_SPEAKER, 1, 0, 2),
        device(_ONE_SPEAKER, 2, 0, 2),
        device("Microphone (Realtek(R) Audio)", 2, 2, 0),
    ]
    if twin:
        devices.append(device(f"{_ONE_SPEAKER} [Loopback]", 2, 2, 0))
    devices += [
        device("Speakers (Realtek HD Audio output)", 3, 0, 2),
        device("Microphone (Realtek HD Audio Mic input)", 3, 2, 0),
    ]
    return devices


def _fake_sounddevice(devices, hostapis, default_hostapi=0, exports_loopback=True):
    """A stand-in `sounddevice` module answering the three questions the device
    code asks — `query_devices()`, `query_hostapis()`, `default.hostapi` — and
    counting the calls, because "did this enumerate?" is itself a contract here
    (`_recording_path_asks_portaudio_nothing`).

    `_libname` / `_lib` stand in for the loaded binary: `describe()` reads
    `PaWasapi_IsLoopback` off it, and its absence is exactly what separates the
    wheel's PortAudio from ours.
    """
    import types

    fake = types.ModuleType("sounddevice")
    fake.calls = {"query_devices": 0, "query_hostapis": 0}

    def query_devices(device=None, kind=None):
        fake.calls["query_devices"] += 1
        return devices if device is None else devices[device]

    def query_hostapis(index=None):
        fake.calls["query_hostapis"] += 1
        return hostapis if index is None else hostapis[index]

    fake.query_devices = query_devices
    fake.query_hostapis = query_hostapis
    fake.default = types.SimpleNamespace(hostapi=default_hostapi)
    fake.get_portaudio_version = lambda: (190700, "PortAudio V19.7.0-devel, revision unknown")
    fake._libname = "C:\\bundle\\portaudio.dll"
    fake._lib = (
        types.SimpleNamespace(PaWasapi_IsLoopback=object())
        if exports_loopback
        else types.SimpleNamespace()
    )
    return fake


@contextlib.contextmanager
def _as_sounddevice(fake, platform="win32"):
    """Install `fake` as the process's `sounddevice` and pretend to be
    `platform`, restoring both.

    A context manager because every user of it has a finally-block to get
    wrong otherwise, and a leaked fake module would make every later check in
    the run enumerate this fixture. `sys.platform` travels with it: the host
    API pick branches on it (WASAPI only exists on Windows), so a Windows
    machine's device list cannot be checked on the CI runner without it — the
    same reason `_load_faked_system_devices` patches it.
    """
    previous = sys.modules.get("sounddevice")
    saved_platform = sys.platform
    sys.modules["sounddevice"] = fake
    sys.platform = platform
    try:
        yield fake
    finally:
        sys.platform = saved_platform
        if previous is None:
            del sys.modules["sounddevice"]
        else:
            sys.modules["sounddevice"] = previous


def _portaudio_counts_one_entry_per_output():
    """Outputs are counted and named ONCE PER PHYSICAL DEVICE, not once per
    host API that lists them — the filter, and the three consumers that were
    wrong without it.

    PortAudio enumerates every endpoint through every host API, so a
    single-soundcard Windows box reports the same speaker four times (MME,
    DirectSound, WASAPI, WDM-KS) plus two pseudo-devices that are not hardware
    at all. Three things read that list, and each produced a false statement
    from it:

    * the System audio hint put the names into prose — a machine where #194
      works perfectly still read “No loopback device was found for “Microsoft
      Sound Mapper - Output”, “Primary Sound Driver” and “Speakers (Realtek HD
      Audio output)”” (the hint half of this is asserted in
      `_system_audio_hint_names_the_outputs_it_cannot_record`, shape 4);
    * `portaudio.describe()`'s ratio read "1 loopback of 6 outputs" for one
      speaker and its twin;
    * the release gate below fails a build that reports outputs but no
      loopback twin — so a runner whose MME phantom output exists while WASAPI
      enumerates no render endpoint would have failed a *correct* build. That
      is the case nobody can reproduce on this runner, which is why it is
      asserted here against a fixture instead.

    WASAPI is picked on Windows rather than PortAudio's own default host API
    (MME here, as on a real machine): only WASAPI emits the "[Loopback]" twins,
    and counting the twins on one host API and the outputs on another is
    exactly how a ratio lies.
    """
    from listen_to_me import audio, portaudio

    for twin in (True, False):
        devices = _windows_devices(twin)
        fake = _fake_sounddevice(devices, _WINDOWS_HOSTAPIS, default_hostapi=0)
        # What the raw enumeration offers, i.e. what a "simplification" back to
        # every device would name: six outputs for one speaker.
        raw = [d["name"] for d in devices if d["max_output_channels"] > 0]
        assert len(raw) == 6, raw
        with _as_sounddevice(fake, "win32"):
            assert portaudio.preferred_hostapi(fake) == (2, "Windows WASAPI")
            outputs = audio.list_output_devices()
            # One entry, the one the user has, at its WASAPI index.
            assert outputs == [(8, _ONE_SPEAKER)], outputs
            for phantom in _WINDOWS_PHANTOMS:
                assert all(phantom not in name for _idx, name in outputs), (phantom, outputs)
            info = portaudio.describe()
            assert info["hostapi"] == "Windows WASAPI", info
            assert info["output_devices"] == 1, info
            assert info["loopback_devices"] == (1 if twin else 0), info
            assert info["loopback_supported"] is True, info
            # The input list is deliberately NOT filtered: it is what devices
            # are picked from, by stored index, so every host API's copy stays.
            names = [p["name"] for p in audio.input_device_profiles()]
            assert len(names) == (7 if twin else 6), names
            assert names.count("Microphone (Realtek(R) Audio)") == 3, names
            assert [p["hostapi"] for p in audio.input_device_profiles()][:2] == [
                "MME", "MME",
            ]

            # The release gate, counted the same way. With the twin it passes
            # and reports the ratio; without it the machine really has an
            # output and no loopback device, which is what the gate is for.
            if twin:
                note = _portaudio_supports_wasapi_loopback()
                assert "1 loopback input(s) for 1 output(s) on Windows WASAPI" in note, note
            else:
                try:
                    _portaudio_supports_wasapi_loopback()
                except AssertionError as exc:
                    assert "1 output device(s) on Windows WASAPI" in str(exc), exc
                else:
                    raise AssertionError("the gate must fail on outputs without a twin")

    # A runner whose only output is an MME/DirectSound phantom while WASAPI
    # enumerates no render endpoint: nothing to count, so the gate SKIPS its
    # device half instead of failing a correct build. This is the one the
    # reviewer could not run on Windows — it is the whole reason the gate and
    # the hint count on the same host API.
    phantom_only = [
        d
        for d in _windows_devices(twin=False)
        if d["hostapi"] != 2 or d["max_output_channels"] == 0
    ]
    assert any(d["max_output_channels"] > 0 for d in phantom_only)
    fake = _fake_sounddevice(phantom_only, _WINDOWS_HOSTAPIS)
    with _as_sounddevice(fake, "win32"):
        assert audio.list_output_devices() == []
        info = portaudio.describe()
        assert info["output_devices"] == 0 and info["loopback_devices"] == 0, info
        note = _portaudio_supports_wasapi_loopback()
        assert "no output device" in note and "Windows WASAPI" in note, note

    # The wheel's own binary, which exports no `PaWasapi_IsLoopback`: the gate
    # fails on its FIRST half, with the reason a release log can act on. Worth
    # asserting here because that half never runs for real on this runner — off
    # Windows the gate skips itself entirely.
    old_binary = _fake_sounddevice(
        _windows_devices(twin=False), _WINDOWS_HOSTAPIS, exports_loopback=False
    )
    with _as_sounddevice(old_binary, "win32"):
        assert portaudio.describe()["loopback_supported"] is False
        try:
            _portaudio_supports_wasapi_loopback()
        except AssertionError as exc:
            assert "PaWasapi_IsLoopback is not reachable" in str(exc), exc
        else:
            raise AssertionError("the gate must fail when the symbol is missing")

    # Off Windows the default host API is the pick — WASAPI does not exist
    # there, and PortAudio's default is what the platform itself considers the
    # one list of devices.
    linux_hostapis = [{"name": "ALSA"}, {"name": "PulseAudio"}]
    linux_devices = [
        {"name": "HDA Intel PCH", "hostapi": 0, "max_input_channels": 2,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        {"name": "pulse", "hostapi": 1, "max_input_channels": 2,
         "max_output_channels": 2, "default_samplerate": 44100.0},
        {"name": "Monitor of Built-in Audio", "hostapi": 1, "max_input_channels": 2,
         "max_output_channels": 0, "default_samplerate": 44100.0},
    ]
    fake = _fake_sounddevice(linux_devices, linux_hostapis, default_hostapi=1)
    with _as_sounddevice(fake, "linux"):
        assert portaudio.preferred_hostapi(fake) == (1, "PulseAudio")
        assert audio.list_output_devices() == [(1, "pulse")]
        assert portaudio.describe()["hostapi"] == "PulseAudio"

    # And a PortAudio that cannot say: "unknown", never "this machine has no
    # outputs". The hint then names nothing (an omitted sentence beats a false
    # one) and the gate skips its device half.
    blind = _fake_sounddevice(_windows_devices(), _WINDOWS_HOSTAPIS)

    def _raise(*args, **kwargs):
        raise RuntimeError("PortAudio cannot be asked")

    blind.query_hostapis = _raise
    blind.default = None  # `sd.default.hostapi` raises AttributeError
    with _as_sounddevice(blind, "win32"):
        assert portaudio.preferred_hostapi(blind) == (None, "")
        assert audio.list_output_devices() == []
        info = portaudio.describe()
        assert info["hostapi"] is None, info
        assert info["output_devices"] == 0 and info["loopback_devices"] == 0, info
        assert any("host API" in reason for reason in info["errors"]), info
        note = _portaudio_supports_wasapi_loopback()
        assert "no host API" in note, note


def _recording_path_asks_portaudio_nothing():
    """`Recorder.start()` must not enumerate devices — the one-per-process
    PortAudio log line lives on the settings path instead.

    start() runs on the Qt main thread (App._start_recording ← _handle ← the
    100 ms drain timer) at the moment the user has pressed the hotkey and is
    about to speak, and with the default `input_device: null` nothing else on
    that path asks PortAudio anything. `portaudio.log_once()` sat here and cost
    the first take of every session a full `sd.query_devices()` — the very
    stall `settings_ui` defers its own enumeration for.

    Two tripwires, because one is not enough. The fixture's `query_devices`
    raises when called at all, which catches any *unguarded* enumeration put
    back on this path — but a diagnostic swallows its own exceptions by
    contract (`describe()` never raises), so the second one is what catches
    that: nothing may have been logged and `_logged` must still be False, i.e.
    `log_once()` did not run here.

    `input_device_profiles()` is where the line moved, and it hands over the
    lists it already holds — asserted by the call count, because a second
    enumeration inside `describe()` would be exactly the stall this is about,
    one page later.
    """
    import logging
    import types

    from listen_to_me import audio, portaudio

    class _Stream:
        def start(self):
            pass

    tripwire = types.ModuleType("sounddevice")
    tripwire.InputStream = lambda **kwargs: _Stream()
    tripwire.CallbackStop = RuntimeError

    def _never(*args, **kwargs):
        raise AssertionError("the recording path must not enumerate devices")

    tripwire.query_devices = _never
    tripwire.query_hostapis = _never

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    saved_state = {
        name: getattr(portaudio, name)
        for name in ("_prepared", "_prepare_note", "_prepare_done", "_logged")
    }
    handler = _Capture()
    saved_level = portaudio.log.level
    portaudio.log.addHandler(handler)
    # The line is INFO and the root logger defaults to WARNING, so without this
    # the capture below would be empty whether or not anything was logged.
    portaudio.log.setLevel(logging.INFO)
    try:
        with _as_sounddevice(tripwire, "win32"):
            portaudio._reset_state()
            recorder = audio.Recorder()
            recorder.start(max_seconds=30)
            recorder._stream = None  # the fake stream holds nothing; skip stop()
            recorder._chunks = []
            assert portaudio._logged is False, "start() logged, so it enumerated"
            assert records == [], [r.getMessage() for r in records]

        fake = _fake_sounddevice(_windows_devices(), _WINDOWS_HOSTAPIS)
        with _as_sounddevice(fake, "win32"):
            portaudio._reset_state()
            assert audio.input_device_profiles()
            # Exactly one enumeration for the page AND the log line: the lists
            # are handed to describe() instead of asked for twice.
            assert fake.calls["query_devices"] == 1, fake.calls
            assert portaudio._logged is True
            lines = [r.getMessage() for r in records if r.levelno == logging.INFO]
            assert len(lines) == 1, lines
            # The host API is named, because "1 of 1" and "1 of 6" are the same
            # machine and a release log cannot tell them apart otherwise.
            assert "1 loopback input device(s) of 1 output(s) on Windows WASAPI" in lines[0]
            assert "portaudio.dll" in lines[0], lines[0]
            # One line per process, however often the page is opened.
            assert audio.input_device_profiles()
            assert fake.calls["query_devices"] == 2, fake.calls  # the page, not the log
            assert len([r for r in records if r.levelno == logging.INFO]) == 1
    finally:
        portaudio.log.removeHandler(handler)
        portaudio.log.setLevel(saved_level)
        for name, value in saved_state.items():
            setattr(portaudio, name, value)


def _bundled_portaudio_can_be_switched_off():
    """`system_audio.bundled_portaudio` — the escape hatch for a bundled
    PortAudio that turns out worse than the one in the `sounddevice` wheel.

    Once our DLL is loaded nothing reverts, so a binary that loads but fails
    `Pa_Initialize` breaks ALL audio in the frozen build — microphone dictation
    included — with no recovery until a new release is dispatched, and nothing
    in CI captures audio with it (the release runner has no audio hardware).
    False therefore has to reach `prepare_library_path()` before it touches
    `PATH`, and everything else has to mean "on":

    * no config file (first run), broken JSON, a config path that cannot be
      opened at all, a missing section, a missing key, a value of the wrong
      type — all keep the shipped default, because an unreadable config must
      never cost the app its start (nor a feature the hand-edit was not about);
    * `0` / `1` are honoured, matching `_coerce`, so the answer here is the one
      a normal `Config` load would give.

    The read happens before `_setup_logging()`, before Qt and before
    `--version` answers, so "never raises" is the hard part and the last case
    is `config.json` replaced by a *directory* — the shape of every "someone
    else holds the file" failure. That the flag paths stay import-light is
    `_cli_flags`' job, not this one's.
    """
    import json

    from listen_to_me import portaudio
    from listen_to_me.config import DEFAULTS, bundled_portaudio_enabled, config_dir
    from listen_to_me.settings_ui import SettingsWindow

    # One default, in DEFAULTS — the fallback literal inside the reader is the
    # last resort if the section is ever renamed, not a second opinion.
    assert DEFAULTS["system_audio"]["bundled_portaudio"] is True

    # A Save must not silently revert the hatch. The Settings window offers no
    # control for it on purpose, so the key survives only because the section
    # is MERGED rather than replaced — `_collect()` does not know it exists,
    # and a `target.update(values)` there would delete a user's recovery lever
    # the first time they pressed Save.
    section = {"hotkey": "", "device": None, "bundled_portaudio": False}
    SettingsWindow._merge_section(section, {"hotkey": "<f9>", "device": 3})
    assert section["bundled_portaudio"] is False, section

    saved_env = {name: os.environ.get(name) for name in ("XDG_CONFIG_HOME", "APPDATA")}
    saved_path = os.environ.get("PATH")
    saved_frozen = getattr(sys, "frozen", None)
    saved_meipass = getattr(sys, "_MEIPASS", None)
    saved_state = {
        name: getattr(portaudio, name)
        for name in ("_prepared", "_prepare_note", "_prepare_done", "_logged")
    }
    sentinel = os.path.join(os.sep, "listen-to-me-no-such-dir")
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as bundle:
        try:
            # Both, so the real config_dir() lands in the temp dir on Windows
            # (APPDATA) as well as on Linux (XDG_CONFIG_HOME) — this check runs
            # in the packaged exe too.
            os.environ["XDG_CONFIG_HOME"] = home
            os.environ["APPDATA"] = home
            path = config_dir() / "config.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            # A bundle that carries the DLL: without the opt-out, PATH changes.
            Path(bundle, portaudio.DLL_NAME).write_bytes(b"")
            sys.frozen = True
            sys._MEIPASS = bundle

            def attempt():
                """What prepare_library_path() does with the config.json that is
                on disk right now."""
                os.environ["PATH"] = sentinel
                portaudio._reset_state()
                return (
                    portaudio.prepare_library_path(),
                    os.environ["PATH"],
                    portaudio._prepare_note,
                    bundled_portaudio_enabled(),
                )

            def prepared(stored):
                """The same, with `stored` written to config.json first — a dict
                as JSON, a string verbatim (a truncated write), None for no
                file at all."""
                if stored is None:
                    if path.exists():
                        path.unlink()
                elif isinstance(stored, str):
                    path.write_text(stored, encoding="utf-8")
                else:
                    path.write_text(json.dumps(stored), encoding="utf-8")
                return attempt()

            # 1 — on: the shipped default, explicit. PATH gets the bundle.
            answer, env, note, flag = prepared({"system_audio": {"bundled_portaudio": True}})
            assert (answer, flag) == (bundle, True), (answer, flag)
            assert env == bundle + os.pathsep + sentinel, env
            assert portaudio.DLL_NAME in note, note

            # 2 — off: PATH untouched, and the note says which key did it, so
            # the one line log_once() prints can be read as an answer.
            answer, env, note, flag = prepared({"system_audio": {"bundled_portaudio": False}})
            assert (answer, env, flag) == (None, sentinel, False), (answer, env, flag)
            assert "bundled_portaudio" in note and "keeps its own PortAudio" in note, note
            # 0/1 mean the same as false/true (the `_coerce` rule), so a
            # hand-edit following a support instruction is not silently ignored.
            assert prepared({"system_audio": {"bundled_portaudio": 0}})[0] is None
            assert prepared({"system_audio": {"bundled_portaudio": 1}})[0] == bundle

            # 3 — everything unreadable is ON: no file, no section, no key,
            # broken JSON, a wrong type.
            for stored in (
                None,
                {},
                {"system_audio": {}},
                {"system_audio": {"hotkey": "<f9>"}},
                {"system_audio": "off"},
                {"system_audio": {"bundled_portaudio": "false"}},
                {"system_audio": {"bundled_portaudio": None}},
                {"system_audio": {"bundled_portaudio": 2}},
                "{ not json at all",
                "",
            ):
                answer, env, note, flag = prepared(stored)
                assert (answer, flag) == (bundle, True), (stored, answer, flag)
                assert env == bundle + os.pathsep + sentinel, (stored, env)

            # 4 — a config path that cannot be read at all must not cost the
            # app its start: the file is a directory here, which is the shape
            # of every "someone else holds it" failure (an AV scanner, an
            # indexer, a half-restored profile).
            path.unlink(missing_ok=True)
            path.mkdir()
            answer, env, note, flag = attempt()
            assert (answer, flag) == (bundle, True), (answer, flag)
            assert env == bundle + os.pathsep + sentinel, env
            path.rmdir()
        finally:
            for name, value in saved_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            for name, value in (("frozen", saved_frozen), ("_MEIPASS", saved_meipass)):
                if value is None:
                    if hasattr(sys, name):
                        delattr(sys, name)
                else:
                    setattr(sys, name, value)
            if saved_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = saved_path
            for name, value in saved_state.items():
                setattr(portaudio, name, value)

    assert os.environ.get("PATH") == saved_path, "the check leaked its fake PATH"


def _portaudio_path_prepend():
    """The PATH prepend that decides WHICH PortAudio `sounddevice` loads
    (#194) — the pure half of it, the half no Windows exe is needed for.

    Four cases, because each is a separate promise. A source install must be
    left completely alone. A frozen build that ships no DLL must be left alone
    too — `sounddevice` then loads its own bundled copy and the app behaves
    exactly as it did before the feature existed. A bundle that does carry the
    DLL gets its directory in *front* of PATH, because a stray portaudio.dll
    earlier on the user's PATH would otherwise be the one that answers. And a
    second call must not grow PATH: `app.main()` calls this, and nothing stops
    a future entry point from calling it as well.

    `sys.frozen` / `sys._MEIPASS` and the module's own state are saved and put
    back, not cleared — inside the packaged exe they carry real values that the
    rest of the self-test run reports on (same reason the updater check
    restores PyInstaller's bootloader variables instead of deleting them).
    """
    from listen_to_me import portaudio

    sentinel = os.path.join(os.sep, "listen-to-me-no-such-dir")
    saved_path = os.environ.get("PATH")
    saved_frozen = getattr(sys, "frozen", None)
    saved_meipass = getattr(sys, "_MEIPASS", None)
    saved_state = {
        name: getattr(portaudio, name)
        for name in ("_prepared", "_prepare_note", "_prepare_done", "_logged")
    }

    def restore():
        for name, value in (("frozen", saved_frozen), ("_MEIPASS", saved_meipass)):
            if value is None:
                if hasattr(sys, name):
                    delattr(sys, name)
            else:
                setattr(sys, name, value)
        if saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = saved_path
        for name, value in saved_state.items():
            setattr(portaudio, name, value)

    # NOTHING in the faked window may import sounddevice — `describe()`
    # especially. sounddevice resolves its DLL once, at import time, from the
    # PATH in force then: importing it while PATH is this fake would pin the
    # wheel's old PortAudio for the whole process and fail the loopback check
    # below on a perfectly good build. So the outcome is read from the module's
    # own note here, and describe() is called only after the restore.
    try:
        # Not frozen: a `pip install -e .` keeps its PATH untouched.
        if hasattr(sys, "frozen"):
            del sys.frozen
        os.environ["PATH"] = sentinel
        portaudio._reset_state()
        assert portaudio.prepare_library_path() is None
        assert os.environ["PATH"] == sentinel
        assert "not a frozen build" in portaudio._prepare_note

        with tempfile.TemporaryDirectory() as tmp:
            # Frozen, but this build shipped no DLL — same promise: nothing
            # changed, and the note says which of the two reasons it was.
            sys.frozen = True
            sys._MEIPASS = tmp
            portaudio._reset_state()
            assert portaudio.prepare_library_path() is None
            assert os.environ["PATH"] == sentinel
            assert portaudio.DLL_NAME in portaudio._prepare_note

            # The DLL is there: its directory goes to the FRONT of PATH. The
            # file stays empty on purpose — it is never loaded, only found by
            # os.path.isfile, and a real DLL in a temp dir would be a loaded
            # binary nobody checked.
            Path(tmp, portaudio.DLL_NAME).write_bytes(b"")
            portaudio._reset_state()
            assert portaudio.prepare_library_path() == tmp
            prepended = os.environ["PATH"]
            assert prepended == tmp + os.pathsep + sentinel, prepended
            assert portaudio._prepared == tmp

            # ...exactly once, however often it is called.
            assert portaudio.prepare_library_path() == tmp
            assert os.environ["PATH"] == prepended, "a second call grew PATH"
    finally:
        restore()

    assert os.environ.get("PATH") == saved_path, "the check leaked its fake PATH"

    # The probe answers with a shape, never an exception: it runs from the
    # recording path and from the settings page, and a diagnostic that throws
    # is worse than none. Without sounddevice every field degrades and the
    # reason is recorded — that is the case the Linux CI job exercises.
    info = portaudio.describe()
    assert {
        "version", "version_number", "library", "loopback_supported",
        "loopback_devices", "output_devices", "bundle_path", "path_note", "errors",
    } <= set(info), info
    assert isinstance(info["loopback_supported"], bool)
    assert isinstance(info["loopback_devices"], int) and isinstance(info["output_devices"], int)
    assert isinstance(info["errors"], list)
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        assert info["version"] is None and info["loopback_supported"] is False, info
        assert info["loopback_devices"] == 0 and info["output_devices"] == 0, info
        assert info["errors"] and "sounddevice" in info["errors"][0], info


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


def _hotkeys_route_to_their_own_source():
    """Two hotkeys, one state machine: a press for one recording source may
    neither stop nor cancel the other one's take (#191).

    The alternative is the worst outcome the two sources have between them. A
    system-audio hotkey pressed during a dictation would end that dictation and
    insert it into whatever window happens to be focused; the microphone hotkey
    would end a recorded meeting the same way. So the press does nothing but say
    why — out loud, because a hotkey that silently does nothing is the one thing
    it must not be.

    `App._handle` is borrowed unbound onto a stub, as
    `_recorder_events_carry_their_take` does it: a real App needs a tray, a
    recorder and a transcriber, while the routing is decided from four
    attributes."""
    from listen_to_me.app import (
        STATE_IDLE,
        STATE_PROCESSING,
        STATE_RECORDING,
        App,
        event_source,
        hotkey_mode,
        source_label,
    )
    from listen_to_me.choices import SOURCE_MIC, SOURCE_SYSTEM

    # The three module functions the routing rests on. Only the system-audio
    # listener names itself; every other surface posts a payload-free toggle,
    # so a payload that is not a source can never route a take to the wrong
    # device.
    assert event_source(SOURCE_SYSTEM) == SOURCE_SYSTEM
    for payload in (None, SOURCE_MIC, "toggle", 7, True, ""):
        assert event_source(payload) == SOURCE_MIC, repr(payload)
    # …and the wording every message about a take is built from: a system-audio
    # take reporting "the microphone stream ended" sends the user to a device
    # that is working fine.
    assert source_label(SOURCE_MIC) == "microphone"
    assert source_label(SOURCE_SYSTEM) == "system audio"
    for unknown in (None, "", "loopback", 3):
        assert source_label(unknown) == "microphone", repr(unknown)
    modes = {"hotkey_mode": "toggle", "system_audio": {"hotkey_mode": "hold"}}
    assert hotkey_mode(modes, SOURCE_MIC) == "toggle"
    assert hotkey_mode(modes, SOURCE_SYSTEM) == "hold"

    class _App:
        # Borrowed unbound: a real App needs a tray, a recorder, a transcriber.
        _handle, _owns_take = App._handle, App._owns_take

        def __init__(self, state=STATE_IDLE, source=SOURCE_MIC):
            self.state, self._recording_id, self._source = state, 2, source
            self.cfg = {
                "hotkey_mode": "toggle",
                "system_audio": {"hotkey_mode": "toggle"},
            }
            self.started: list[str] = []
            self.finished = self.cancelled = 0
            self.messages: list[str] = []

        def notify(self, message, force=False):
            self.messages.append(message)

        def _start_recording(self, source=SOURCE_MIC):
            self.started.append(source)

        def _finish_recording(self):
            self.finished += 1

        def _cancel_recording(self):
            self.cancelled += 1

    # Idle: every toggle starts its own source, and a payload-free one is the
    # microphone — the event the tray, the floating icon and the Home button
    # have always posted.
    for payload, expected in ((None, SOURCE_MIC), (SOURCE_MIC, SOURCE_MIC),
                              (SOURCE_SYSTEM, SOURCE_SYSTEM)):
        app = _App()
        app._handle("toggle", payload)
        assert app.started == [expected], (payload, app.started)

    for running, pressed in ((SOURCE_MIC, SOURCE_SYSTEM), (SOURCE_SYSTEM, SOURCE_MIC)):
        # The toggle both hotkeys and every menu entry post.
        app = _App(state=STATE_RECORDING, source=running)
        app._handle("toggle", pressed)
        assert app.finished == 0, f"a {pressed} toggle stopped the {running} take"
        assert app.started == [] and app.cancelled == 0
        assert app.messages and source_label(running) in app.messages[0], app.messages
        assert "already running" in app.messages[0]
        # The take's own toggle still ends it.
        app._handle("toggle", running)
        assert app.finished == 1

        # …and the hold-mode press/release pair, which is routed by the mode of
        # the hotkey that fired.
        app = _App(state=STATE_RECORDING, source=running)
        app.cfg["hotkey_mode"] = app.cfg["system_audio"]["hotkey_mode"] = "hold"
        app._handle("hotkey_press", pressed)
        assert app.finished == 0 and app.started == []
        assert app.messages and source_label(running) in app.messages[0]
        app._handle("hotkey_release", pressed)
        assert app.finished == 0, f"the {pressed} release ended the {running} take"
        app._handle("hotkey_release", running)
        assert app.finished == 1, "the take's own release must end it"

    # Each source is routed by ITS OWN mode: reading the microphone's "hold"
    # for a system-audio press would start a take whose release never comes,
    # and it would sit there until the length cap cut it off.
    app = _App()
    app.cfg["hotkey_mode"], app.cfg["system_audio"]["hotkey_mode"] = "hold", "toggle"
    app._handle("hotkey_press", SOURCE_SYSTEM)
    assert app.started == [SOURCE_SYSTEM]
    app.state, app._source = STATE_RECORDING, SOURCE_SYSTEM
    app._handle("hotkey_release", SOURCE_SYSTEM)
    assert app.finished == 0, "a toggle-mode release must not end the take"
    app._handle("hotkey_press", SOURCE_SYSTEM)  # …the next press does
    assert app.finished == 1
    # The other way round in the same config: the microphone is push-to-talk.
    app = _App()
    app.cfg["hotkey_mode"], app.cfg["system_audio"]["hotkey_mode"] = "hold", "toggle"
    app._handle("hotkey_press", None)
    assert app.started == [SOURCE_MIC]
    app.state = STATE_RECORDING
    app._handle("hotkey_release", None)
    assert app.finished == 1

    # A press for either source while the previous take is still being
    # transcribed gets the same feedback: the user is speaking into a dead mic,
    # and silence here loses dictation.
    for payload in (None, SOURCE_SYSTEM):
        app = _App(state=STATE_PROCESSING)
        app._handle("toggle", payload)
        assert app.started == [] and app.finished == 0
        assert app.messages and "transcribing" in app.messages[0], app.messages
    # Cancel is not routed by source: it belongs to whatever is running, and
    # both menus offer exactly one "Cancel recording" entry for both sources.
    app = _App(state=STATE_RECORDING, source=SOURCE_SYSTEM)
    app._handle("cancel", None)
    assert app.cancelled == 1


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

    from listen_to_me.config import config_dir

    for flag in ("--help", "-h"):
        code, out, _err = run([flag])
        assert code == 0, f"{flag} exited {code}"
        # Every flag the app accepts has to appear, or the help lies by omission.
        for documented in ("--version", "--selftest", "--help"):
            assert documented in out, f"{flag} does not mention {documented}"
        # The resolved config directory, not just the phrase for it: --help is
        # what someone runs when the GUI will not start, i.e. exactly when the
        # tray menu's "Open config folder" is out of reach.
        assert str(config_dir()) in out, f"{flag} does not name the config dir"

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
    """An enabled assistant that cannot produce a request is refused before one
    goes out — the settings window asks the same question at Save.

    Without this the misconfiguration only surfaces on the worker thread after
    a dictation, as requests' own "Invalid URL '/chat/completions': No scheme
    supplied" attached to a transcript the user already spoke.

    Three things can be missing, and the third one used to be reported nowhere
    at all: a profile with `"enabled": true` and a blank `system_prompt` was
    reported *disabled* by `profile()`, so the feature the user had switched on
    never ran, the settings window skipped it (it asks `profile()`, which had
    already said disabled) and one log line per process was the only trace."""
    from listen_to_me.assistant import AssistantError, config_problem, refine

    good = {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "system_prompt": "punctuate the dictation",
    }
    assert config_problem(good) is None
    assert config_problem({**good, "base_url": ""})[0] == "base_url"
    assert config_problem({**good, "base_url": "   "})[0] == "base_url"
    assert config_problem({})[0] == "base_url"  # a truncated config section
    # The scheme is what requests trips over — "localhost:11434" is not a URL.
    assert config_problem({**good, "base_url": "localhost:11434/v1"})[0] == "base_url"
    assert config_problem({**good, "base_url": "HTTPS://host/v1"}) is None  # case
    assert config_problem({**good, "model": " "})[0] == "model"

    # The third answer: no prompt at all. A request without one tells the
    # endpoint nothing about what to do with the transcript, and a non-string
    # is refused rather than stringified — refine() puts this value straight
    # into the request body, and "5" is not a prompt anybody wrote.
    for missing in ("", "   ", "\n\t", None, 5, ["a prompt"]):
        assert config_problem({**good, "system_prompt": missing}) == (
            "system_prompt",
            "no system prompt is set",
        ), repr(missing)
    truncated = dict(good)
    truncated.pop("system_prompt")
    assert config_problem(truncated)[0] == "system_prompt"

    # The order the three are checked in, which is the order the user has to
    # fill them in: the shared connection first, then the model, then this
    # profile's prompt. A message naming the last empty field instead of the
    # first would send them to a page that is not the problem yet.
    assert config_problem({"base_url": "", "model": "", "system_prompt": ""})[0] == "base_url"
    assert config_problem({**good, "base_url": "host/v1", "system_prompt": ""})[0] == "base_url"
    assert config_problem({**good, "model": "", "system_prompt": ""})[0] == "model"

    # Every reason is a sentence fragment the UI/notification can embed.
    for broken in (
        {**good, "base_url": ""},
        {**good, "model": ""},
        {**good, "system_prompt": ""},
    ):
        reason = config_problem(broken)[1]
        assert reason and reason[0].islower() and not reason.endswith(".")

    # refine() must not reach requests with a broken config — for any of the
    # three, because each one of them fails after the user already spoke.
    for broken, named in (
        ({**good, "base_url": ""}, "base URL"),
        ({**good, "model": ""}, "model name"),
        ({**good, "system_prompt": ""}, "system prompt"),
    ):
        try:
            refine("hello", broken)
        except AssistantError as exc:
            assert named in str(exc), (named, str(exc))
        else:
            raise AssertionError(f"refine accepted an assistant config with no {named}")


def _assistant_profiles_follow_the_source():
    """One connection, two profiles: the microphone's and the second recording
    source's (#191).

    A dictation wants punctuation, a recorded meeting wants minutes — but both
    talk to the same endpoint with the same key, so `base_url`, `api_key`,
    `temperature` and `timeout` stay shared and only the switch, the model and
    the prompt are per source. The top-level `enabled`/`system_prompt`/`model`
    ARE the microphone profile, deliberately not renamed, so no existing
    config.json needs a migration.

    The load-bearing case is a system_audio section that is missing or is not a
    dict (a config written before #191, or a hand-edit): it must report the
    profile DISABLED with an empty prompt, never borrow the microphone's —
    post-processing a recorded meeting with the dictation prompt ("remove
    filler words, do not summarize") is a confidently wrong result, while a
    feature nobody configured staying off is the right one.

    What an *enabled* profile with a blank prompt does is the opposite rule,
    and it lives in `config_problem` now: `profile()` only types the prompt, it
    does not judge it, so the profile stays ON with an empty prompt and the
    problem reaches the user. Answering "disabled" here left a feature the
    user had switched on doing nothing at all, with one log line per process as
    the only trace — and it silenced the settings window too, which asks
    `profile()` before it asks `config_problem`."""
    from listen_to_me.assistant import config_problem, profile
    from listen_to_me.choices import SOURCE_MIC, SOURCE_SYSTEM

    acfg = {
        "enabled": True,
        "base_url": "http://localhost:11434/v1",
        "api_key": "secret",
        "model": "llama3.2",
        "system_prompt": "punctuate the dictation",
        "temperature": 0.2,
        "timeout": 90,
        "system_audio": {
            "enabled": True,
            "model": "qwen2.5:14b",
            "system_prompt": "write the minutes",
        },
    }
    mic, system = profile(acfg, SOURCE_MIC), profile(acfg, SOURCE_SYSTEM)
    assert mic["system_prompt"] == "punctuate the dictation" and mic["model"] == "llama3.2"
    assert system["system_prompt"] == "write the minutes" and system["model"] == "qwen2.5:14b"
    # Flat, so each profile goes straight into config_problem()/refine() — and
    # the connection is the same one for both.
    for resolved in (mic, system):
        assert resolved["base_url"] == acfg["base_url"] and resolved["api_key"] == "secret"
        assert resolved["temperature"] == 0.2 and resolved["timeout"] == 90
        assert resolved["enabled"] is True
        assert config_problem(resolved) is None
    # An empty (or unusable) per-profile model means "the shared one": one
    # endpoint usually serves one model, so this is the documented default.
    for blank in ("", "   ", None, 7):
        borrowed = profile({**acfg, "system_audio": {**acfg["system_audio"], "model": blank}},
                           SOURCE_SYSTEM)
        assert borrowed["model"] == "llama3.2", repr(blank)
    # Each switch is its own — turning the dictation profile off must not take
    # the meeting profile with it, and vice versa.
    assert profile({**acfg, "enabled": False}, SOURCE_SYSTEM)["enabled"] is True
    assert profile({**acfg, "enabled": False}, SOURCE_MIC)["enabled"] is False
    off = {**acfg["system_audio"], "enabled": False}
    assert profile({**acfg, "system_audio": off}, SOURCE_MIC)["enabled"] is True
    assert profile({**acfg, "system_audio": off}, SOURCE_SYSTEM)["enabled"] is False
    # A missing or scalar section: disabled, with no prompt to send. This rule
    # did NOT move — it is what keeps a recorded meeting from being
    # post-processed with the dictation prompt.
    for broken in (None, "nonsense", [1], 0, {}):
        stored = dict(acfg)
        if broken is None:
            stored.pop("system_audio")
        else:
            stored["system_audio"] = broken
        resolved = profile(stored, SOURCE_SYSTEM)
        assert resolved["enabled"] is False, repr(broken)
        assert resolved["system_prompt"] == "", (broken, resolved["system_prompt"])
        assert resolved["system_prompt"] != acfg["system_prompt"]
        # The shared connection still resolves — only the profile is off.
        assert resolved["base_url"] == acfg["base_url"]
    # An enabled profile with no prompt text stays ENABLED — the prompt is
    # only TYPED here, never judged, and config_problem is what reports it in
    # the one place that reaches the user.
    for empty_prompt in ("", "   ", None, 5):
        section = {**acfg["system_audio"], "system_prompt": empty_prompt}
        resolved = profile({**acfg, "system_audio": section}, SOURCE_SYSTEM)
        assert resolved["enabled"] is True, repr(empty_prompt)
        # A str by the time it leaves profile(), because refine() puts this
        # value straight into the request body — and a non-string is emptied
        # rather than stringified ("5" is not a prompt anybody wrote), while a
        # string is passed through untouched instead of being repaired.
        assert isinstance(resolved["system_prompt"], str), repr(empty_prompt)
        assert not resolved["system_prompt"].strip(), repr(empty_prompt)
        if not isinstance(empty_prompt, str):
            assert resolved["system_prompt"] == "", repr(empty_prompt)
        assert config_problem(resolved) == ("system_prompt", "no system prompt is set")
        # Still never the other source's prompt: an unusable value is emptied,
        # not borrowed.
        assert resolved["system_prompt"] != acfg["system_prompt"]
    # The same for the microphone profile, whose keys are the top level.
    for empty_prompt in ("", "  ", None, 5):
        resolved = profile({**acfg, "system_prompt": empty_prompt}, SOURCE_MIC)
        assert resolved["enabled"] is True, repr(empty_prompt)
        assert isinstance(resolved["system_prompt"], str), repr(empty_prompt)
        assert not resolved["system_prompt"].strip(), repr(empty_prompt)
        assert config_problem(resolved)[0] == "system_prompt"
    # "enabled" is read like a bool default in config._coerce, not by
    # truthiness: a stored "false" must not be able to switch it ON.
    for truthy in ("false", "yes", 2, [1]):
        section = {**acfg["system_audio"], "enabled": truthy}
        assert profile({**acfg, "system_audio": section}, SOURCE_SYSTEM)["enabled"] is False
    # The source travels through the event queue as a payload, so anything
    # unrecognized has to read as the microphone rather than as no profile.
    for unknown in ("nonsense", None, ""):
        assert profile(acfg, unknown)["system_prompt"] == "punctuate the dictation"
    # A truncated section only costs what it does not carry.
    assert profile({"system_prompt": "x", "enabled": True}, SOURCE_MIC)["model"] == ""


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


def _recorder_falls_back_to_the_native_format():
    """A device that refuses 16 kHz mono is reopened in its own format and
    converted in the callback — needs numpy, so the full run only.

    A loopback input is usually locked to the output's format (48 kHz stereo)
    and PortAudio does not resample, so an invalid sample rate is not a broken
    device here. What must land in the buffer is 16 kHz mono whatever the
    device did, because everything downstream counts in those frames.

    `sounddevice` is stood in for, exactly as in
    `_recorder_start_failure_resets`: the stand-in refuses 16 kHz mono for the
    loopback device, reports 48 kHz / 2 channels as its native format and
    hands the callback back, so the check can feed it a stereo block. The
    WASAPI hint is stood in for too — `_wasapi_auto_convert` returns None off
    Windows, so on this runner it could not tell the `os_convert` paths apart
    otherwise, and the microphone's unchanged `extra_settings=None` is exactly
    what has to be pinned."""
    import sys as _sys
    import types

    import numpy as np

    from listen_to_me import audio as audio_mod
    from listen_to_me.audio import SAMPLE_RATE, Recorder

    attempts: list[dict] = []
    closed: list[bool] = []

    class _PortAudioError(Exception):
        pass

    class _Stream:
        def __init__(self, kwargs):
            self.kwargs = kwargs
            self.running = False

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

        def close(self):
            closed.append(True)

    def _input_stream(**kwargs):
        attempts.append(kwargs)
        # Device 4 is the loopback input: locked to its own format.
        if kwargs.get("device") == 4 and kwargs.get("samplerate") == SAMPLE_RATE:
            raise _PortAudioError("Invalid sample rate")
        return _Stream(kwargs)

    fake = types.ModuleType("sounddevice")
    fake.InputStream = _input_stream
    fake.CallbackStop = RuntimeError
    fake.PortAudioError = _PortAudioError
    fake.query_devices = lambda device=None, kind=None: {
        "name": "Monitor of Built-in Audio",
        "default_samplerate": 48000.0,
        "max_input_channels": 2,
    }
    sentinel = object()
    previous = _sys.modules.get("sounddevice")
    real_wasapi = audio_mod._wasapi_auto_convert
    _sys.modules["sounddevice"] = fake
    audio_mod._wasapi_auto_convert = lambda sd, device: sentinel
    try:
        recorder = Recorder()
        recorder.start(device=4, max_seconds=60, os_convert=True)
        assert len(attempts) == 2, attempts
        # 16 kHz mono first — what Whisper wants and what the OS converter
        # often delivers outright, so the plain attempt is never skipped.
        assert attempts[0]["samplerate"] == SAMPLE_RATE and attempts[0]["channels"] == 1
        assert attempts[0]["extra_settings"] is sentinel  # the os_convert hint rides along
        # …then the device's own format, at most two channels (they are
        # averaged into mono immediately, so more would only cost bandwidth).
        assert attempts[1]["samplerate"] == 48000 and attempts[1]["channels"] == 2
        assert "extra_settings" not in attempts[1]
        assert recorder.stream_format == (48000, 2)
        assert recorder.resampling is True
        assert recorder.active is True

        # What the callback stores: 16 kHz mono, converted from a stereo block.
        callback = attempts[1]["callback"]
        frames = 4800  # 100 ms at 48 kHz
        t = np.arange(frames, dtype="float64") / 48000.0
        channel = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype("float32")
        callback(np.stack([channel, channel], axis=1), frames, None, 0)
        audio = recorder.stop()
        assert audio.ndim == 1 and audio.dtype == np.dtype("float32")
        assert abs(len(audio) - frames // 3) <= 32, len(audio)  # + the flushed filter tail
        assert 0.2 < float(np.sqrt(np.mean(np.square(audio)))) < 0.3
        assert recorder.active is False and closed

        # The microphone path is what it always was: one attempt, 16 kHz mono,
        # `extra_settings=None` (what sounddevice fills in itself) and no
        # resampler in the callback.
        attempts.clear()
        recorder = Recorder()
        recorder.start(device=None, max_seconds=60)
        assert len(attempts) == 1, attempts
        assert attempts[0]["samplerate"] == SAMPLE_RATE and attempts[0]["channels"] == 1
        assert attempts[0]["extra_settings"] is None
        assert recorder.stream_format == (SAMPLE_RATE, 1)
        assert recorder.resampling is False
        block = np.zeros((1600, 1), dtype="float32")
        attempts[0]["callback"](block, len(block), None, 0)
        audio = recorder.stop()
        assert len(audio) == 1600 and audio.ndim == 1
    finally:
        audio_mod._wasapi_auto_convert = real_wasapi
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


def _theme_accent_text_contrast():
    """A label on the accent fill must be readable — 4.5:1, not 4.28:1.

    The accent buttons carry the primary action of every page (Save, Apply,
    "Download & install", the key picker's OK) and their label is white at the
    app's normal 10 pt, so the WCAG minimum for *normal text* applies: on the
    brand accent that pairing measured 4.28:1 and its hover shade 3.35:1, which
    is why the fill has a token of its own while ``ACCENT`` keeps the borders,
    focus rings and gradients. Pure arithmetic over both schemes, like the
    scroll-bar check above — a render only exercises the host's own scheme.
    """
    from listen_to_me.theme import (
        ACCENT,
        ACCENT_DEEP,
        ACCENT_DOWN,
        ACCENT_FILL,
        ACCENT_HOVER,
        _DARK,
        _LIGHT,
    )

    for name, palette in (("light", _LIGHT), ("dark", _DARK)):
        white = palette["on_accent"]
        for state, fill in (
            ("rest", ACCENT_FILL),
            ("hover", ACCENT_HOVER),
            ("pressed", ACCENT_DOWN),
        ):
            ratio = _contrast(white, fill)
            assert ratio >= 4.5, f"{name} accent label ({state}): {ratio:.2f}:1"
        # ACCENT stays a shape, never a label: fill and outline both have to
        # stay visible against the page — the 3:1 non-text threshold. Headroom
        # is thin there by construction (white on indigo at 4.5:1 forces a fill
        # dark enough to sit close to a dark card: 3.03:1 today), so darkening
        # the fill further needs a lighter outline to carry the boundary.
        for surface in ("window", "base"):
            ratio = _contrast(ACCENT_FILL, palette[surface])
            assert ratio >= 3.0, f"{name} accent fill on {surface}: {ratio:.2f}:1"
            ratio = _contrast(ACCENT, palette[surface])
            assert ratio >= 3.0, f"{name} accent outline on {surface}: {ratio:.2f}:1"
        # The accent as a label: the selected sidebar entry, the footer link on
        # hover, the Help page's links. Each of those surfaces, not just the
        # page background — the sidebar selection is a tinted one.
        for surface in ("accent_soft", "hover", "window", "base"):
            ratio = _contrast(palette["accent_text"], palette[surface])
            assert ratio >= 4.5, f"{name} accent text on {surface}: {ratio:.2f}:1"
    # The hero's record button is white in both schemes (it sits on the accent
    # gradient), so its label needs the light shade whatever the OS says.
    for surface in ("#ffffff", "#eef1ff", "#dbe2fe"):  # rest, hover, pressed
        ratio = _contrast(ACCENT_DEEP, surface)
        assert ratio >= 4.5, f"hero record button on {surface}: {ratio:.2f}:1"


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


def _resampler_converts_without_aliasing():
    """Needs numpy, so this runs only in the full (packaged) self-test.

    A loopback device runs at the output's rate (48 kHz stereo as a rule) and
    PortAudio does not resample, so `audio.py` converts inside its capture
    callback — everything downstream (the frame counter, the length cap, the
    live preview, livetype.py) counts in 16 kHz mono frames. This pins the
    accuracy contract `Resampler` documents, in the same order:

    * the output length, ±1 sample per block and not accumulating over a run
      of unequal blocks (which is what PortAudio really delivers);
    * a flat passband — a 440 Hz sine keeps its level;
    * the anti-alias filter, the reason this is a filter and not a `[::3]`:
      without it a 12 kHz tone folds down to 4 kHz and becomes words nobody
      said. Measured against the naive decimation of the same signal, because
      the absolute number is not the point: the filtered residual is ~38000x
      down while the decimation passes the tone at full level. The tone is
      faded and its ends trimmed — an abruptly starting one carries its own
      broadband click, which dominates the residual (~490x here) and would
      measure the test signal instead of the filter;
    * one conversion per stream, not per block: restarting the interpolator at
      every boundary is a step in the waveform, i.e. a click ~47 times a
      second, which Whisper hears as well as the user does;
    * equal (or unusable) rates are a pass-through, so the microphone path
      pays nothing at all.
    """
    import numpy as np

    from listen_to_me.audio import SAMPLE_RATE
    from listen_to_me.resample import Resampler, downmix_to_mono

    def rms(samples):
        return float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0

    # The mean across channels, not the sum: both channels of a loopback input
    # carry the same programme, and summing them would clip a centred signal.
    stereo = np.array([[0.5, 0.1], [-0.2, 0.4]], dtype="float32")
    mono = downmix_to_mono(stereo)
    assert mono.shape == (2,) and mono.dtype == np.dtype("float32")
    assert abs(float(mono[0]) - 0.3) < 1e-6 and abs(float(mono[1]) - 0.1) < 1e-6
    already_mono = np.array([0.25, -0.5], dtype="float32")
    assert downmix_to_mono(already_mono).tolist() == already_mono.tolist()
    # Eight channels average just as well as two (the recorder opens at most
    # two, but nothing here depends on that).
    assert downmix_to_mono(np.ones((4, 8), dtype="float32")).tolist() == [1.0] * 4

    # Length, block by block and in total.
    res = Resampler(48000, SAMPLE_RATE)
    assert res.passthrough is False
    rng = np.random.default_rng(7)
    total_in = total_out = 0
    for size in (1024, 512, 1024, 333, 2048, 1, 4096):
        out = res.process((rng.standard_normal(size) * 0.1).astype("float32"))
        assert out.dtype == np.dtype("float32") and out.ndim == 1
        assert abs(out.size - size / 3.0) <= 1.0, (size, out.size)
        total_in += size
        total_out += out.size
    assert abs(total_out - total_in / 3.0) <= 1.0, (total_out, total_in / 3.0)
    # The filter's ring-out, which is otherwise cut off the end of every take.
    tail = res.flush()
    assert 0 < tail.size <= 32, tail.size
    assert res.flush().size == 0, "flush must be idempotent (a double stop())"

    # Passband: the level a 440 Hz sine comes out at.
    t = np.arange(48000, dtype="float64") / 48000.0
    sine = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype("float32")

    def convert(signal, sizes=(1024,)):
        resampler = Resampler(48000, SAMPLE_RATE)
        blocks, offset, step = [], 0, 0
        while offset < signal.size:
            size = sizes[step % len(sizes)]
            blocks.append(resampler.process(signal[offset : offset + size]))
            offset += size
            step += 1
        return np.concatenate(blocks)

    ratio = rms(convert(sine)) / rms(sine)
    assert 0.9 < ratio < 1.1, ratio

    # Anti-aliasing: 12 kHz is above the 16 kHz destination's Nyquist and must
    # be attenuated, not folded into the band Whisper reads.
    ramp = np.minimum(np.arange(sine.size), sine.size - 1 - np.arange(sine.size)) / 4800.0
    faded = np.minimum(1.0, ramp)
    tone = (0.3 * np.sin(2 * np.pi * 12000.0 * t) * faded).astype("float32")
    filtered = convert(tone)[1600:-1600]  # drop the fades, measure the steady state
    aliased = tone[::3][1600:-1600]  # what a decimation without the filter gives
    assert rms(aliased) > 0.05, rms(aliased)  # the tone is there at full level …
    assert rms(filtered) * 1000 < rms(aliased), (rms(filtered), rms(aliased))

    # Block by block is one conversion: the FIR tail, the last filtered sample
    # and the fractional read position survive the boundary.
    one_shot = Resampler(48000, SAMPLE_RATE).process(sine)
    chunked = convert(sine, sizes=(700, 1024, 333, 2048, 61))
    assert chunked.size == one_shot.size, (chunked.size, one_shot.size)
    assert float(np.max(np.abs(chunked - one_shot))) < 1e-6

    # Equal rates: no filter, no interpolation, no group delay.
    same = Resampler(SAMPLE_RATE, SAMPLE_RATE)
    assert same.passthrough is True
    block = (rng.standard_normal(777) * 0.1).astype("float32")
    assert same.process(block).tolist() == block.tolist()
    assert same.flush().size == 0
    # Nonsense rates (a device that reported none) degrade to that instead of
    # dividing by zero inside a callback.
    for bad in ((0, SAMPLE_RATE), (SAMPLE_RATE, 0), (-1, SAMPLE_RATE)):
        assert Resampler(*bad).passthrough is True, bad
    # Upsampling needs no pre-filter — one would only add its group delay.
    up = Resampler(8000, SAMPLE_RATE)
    assert up.passthrough is False
    assert abs(up.process(np.zeros(1000, dtype="float32")).size - 2000) <= 2
    assert up.flush().size == 0


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


def _compute_type_resolution():
    """"auto" for device/compute type resolves against what CTranslate2
    reports — int8 on the CPU (never the float32 that "default" widened the
    float16 presets to), float16 on a GPU that supports it — and every probe
    failure falls back to CTranslate2's own resolution instead of raising.
    Uses a fake ctranslate2 module so the check needs no GPU and no real
    install."""
    import sys
    import types

    from listen_to_me.transcriber import resolve_runtime

    def fake(gpus: int, **supported):
        mod = types.ModuleType("ctranslate2")
        mod.get_cuda_device_count = lambda: gpus
        mod.get_supported_compute_types = lambda device, index=0: supported[device]
        return mod

    previous = sys.modules.get("ctranslate2")
    try:
        cpu_only = {"cpu": ["float32", "int16", "int8", "int8_float32"]}
        sys.modules["ctranslate2"] = fake(0, **cpu_only)
        assert resolve_runtime("auto", "auto") == ("cpu", "int8")
        assert resolve_runtime("cpu", "auto") == ("cpu", "int8")
        assert resolve_runtime("cpu", "float32") == ("cpu", "float32")  # explicit wins
        assert resolve_runtime("cuda", "float16") == ("cuda", "float16")  # not probed
        # A CPU without int8 support gets float32, never a type it lacks.
        sys.modules["ctranslate2"] = fake(0, cpu=["float32", "int16"])
        assert resolve_runtime("auto", "auto") == ("cpu", "float32")

        # A GPU takes float16 when supported (accuracy), int8 on an old card.
        sys.modules["ctranslate2"] = fake(
            1, cuda=["float32", "float16", "int8_float16", "int8"], **cpu_only
        )
        assert resolve_runtime("auto", "auto") == ("cuda", "float16")
        assert resolve_runtime("cpu", "auto") == ("cpu", "int8")  # forced CPU keeps int8
        sys.modules["ctranslate2"] = fake(1, cuda=["float32", "int8"], **cpu_only)
        assert resolve_runtime("auto", "auto") == ("cuda", "int8")

        # Probe failures hand the decision back to CTranslate2 — the previous
        # behaviour — instead of failing a load that would have worked.
        def broken(*_a, **_k):
            raise RuntimeError("CUDA driver version is insufficient")

        mod = fake(0, **cpu_only)
        mod.get_cuda_device_count = broken
        sys.modules["ctranslate2"] = mod
        assert resolve_runtime("auto", "auto") == ("auto", "default")
        assert resolve_runtime("auto", "int8") == ("auto", "int8")
        mod = fake(0, **cpu_only)
        mod.get_supported_compute_types = broken
        sys.modules["ctranslate2"] = mod
        assert resolve_runtime("cpu", "auto") == ("cpu", "default")
        sys.modules["ctranslate2"] = None  # import fails → nothing resolved
        assert resolve_runtime("auto", "auto") == ("auto", "default")
    finally:
        if previous is None:
            sys.modules.pop("ctranslate2", None)
        else:
            sys.modules["ctranslate2"] = previous


def _openvino_pipeline_properties():
    """The OpenVINO compile cache is requested for the GPU/NPU only, lives
    under the custom model folder when one is set (the config dir otherwise),
    and an uncreatable cache dir degrades to no properties instead of raising.
    Pure path logic — openvino stays unimported."""
    from listen_to_me.transcriber_openvino import _pipeline_properties

    assert _pipeline_properties("CPU", None) == {}
    with tempfile.TemporaryDirectory() as tmp:
        props = _pipeline_properties("GPU", tmp)
        cache = Path(props["CACHE_DIR"])
        assert cache.is_dir() and cache.parent == Path(tmp) and cache.name == "openvino-cache"
        assert _pipeline_properties("NPU", tmp)["CACHE_DIR"] == str(cache)
        # A file where the cache dir should go → mkdir fails → no properties.
        blocker = Path(tmp) / "blocked"
        blocker.write_text("not a directory")
        assert _pipeline_properties("GPU", blocker) == {}


def _config_redacts_secrets_in_warnings():
    """An unusable value under a credential key is reported by type and length
    only. `_coerce` logs the stored value verbatim so a hand-edit can be found
    in the log — under `assistant.api_key` that verbatim value IS the secret
    (or a mangled attempt at one), copied into a world-readable log file."""
    import json
    import logging

    from listen_to_me import config
    from listen_to_me.config import DEFAULTS, Config

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    config.log.addHandler(handler)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"assistant": {"api_key": ["sk-live-SECRET-VALUE"], "timeout": "abc"}}),
                encoding="utf-8",
            )
            cfg = Config(path=path)
    finally:
        config.log.removeHandler(handler)
    assert cfg["assistant"]["api_key"] == DEFAULTS["assistant"]["api_key"]
    assert "SECRET-VALUE" not in "\n".join(records), records
    assert any("api_key" in m and "list" in m for m in records), records
    # Not a blanket rule: a harmless key still names its value, which is what
    # makes the warning actionable for every other hand-edit.
    assert any("timeout" in m and "'abc'" in m for m in records), records
    for key in ("api_key", "auth_token", "client_secret", "Password", "hf_token"):
        assert config._is_sensitive_key(key), key
    assert not config._is_sensitive_key("max_seconds")


def _config_clamps_out_of_range_values():
    """A stored number outside the range the Settings page offers is clamped
    where it is consumed — once per key in the log — instead of failing later:
    `"max_seconds": 1e9` grew the recorder's chunk list without bound,
    `"timeout": 0` raised inside urllib3 on every dictation. The assistant is
    exercised through a faked `requests` (absent in the light CI env) — the same
    fake also covers the bounds around its response body, since the clamped
    timeout is what they are measured against."""
    import logging
    import types

    from listen_to_me import assistant, config
    from listen_to_me.config import clamp_setting

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    config.log.addHandler(handler)
    for key in ("selftest.max", "selftest.temp", "assistant.timeout", "assistant.temperature"):
        config._clamp_warned.discard(key)
    try:
        assert clamp_setting("selftest.max", 1e9, 10, 3600) == 3600
        assert clamp_setting("selftest.max", 3, 10, 3600) == 10
        assert clamp_setting("selftest.max", 300, 10, 3600) == 300
        assert clamp_setting("selftest.temp", 7, 0.0, 2.0) == 2.0
        assert clamp_setting("selftest.temp", -1, 0.0, 2.0) == 0.0
        # Not comparable: untouched and unreported — the consumer's own
        # conversion is what says so.
        assert clamp_setting("selftest.text", "abc", 5, 600) == "abc"
        assert [m for m in records if "selftest.max" in m and "3600" in m], records
        assert len([m for m in records if "selftest.max" in m]) == 1, "once per key"
        assert not [m for m in records if "selftest.text" in m]

        sent: list[dict] = []
        body = b'{"choices": [{"message": {"content": "refined"}}]}'

        class _Response:
            def raise_for_status(self):
                pass

            def iter_content(self, size):
                # In two pieces, so the size cap and the deadline are both
                # checked more than once per response.
                yield body[:10]
                yield body[10:]

            def close(self):
                pass

        def _post(url, json=None, headers=None, timeout=None, verify=None, stream=None):
            sent.append({"payload": json, "timeout": timeout, "stream": stream})
            return _Response()

        fake = types.ModuleType("requests")
        fake.post = _post
        saved = sys.modules.get("requests")
        sys.modules["requests"] = fake
        try:
            acfg = {
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.2",
                "system_prompt": "fix it",
                "temperature": 9,
                "timeout": 0,
            }
            assert assistant.refine("hello", acfg) == "refined"
            assert sent[0]["timeout"] == 5.0, sent
            assert sent[0]["payload"]["temperature"] == 2.0, sent
            assert isinstance(sent[0]["timeout"], float)
            # Streamed, or neither the size cap nor the wall clock below can
            # apply — requests would have buffered the whole body already.
            assert sent[0]["stream"] is True, sent
            # A body that never stops is refused instead of parking the
            # `process` worker (and with it App.state) forever.
            body = b"x" * (assistant._MAX_RESPONSE_BYTES + 1)
            try:
                assistant.refine("hello", acfg)
            except assistant.AssistantError as exc:
                assert "exceeded" in str(exc), exc
            else:
                raise AssertionError("refine accepted an unbounded response body")
            # A body that is not JSON at all names the assistant, not urllib3.
            body = b"<html>502 Bad Gateway</html>"
            try:
                assistant.refine("hello", acfg)
            except assistant.AssistantError as exc:
                assert "did not return JSON" in str(exc), exc
            else:
                raise AssertionError("refine accepted a non-JSON response")
        finally:
            if saved is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = saved
        assert [m for m in records if "assistant.timeout" in m], records
        assert [m for m in records if "assistant.temperature" in m], records
    finally:
        config.log.removeHandler(handler)


def _mute_targets_are_validated():
    """A malformed mute target costs itself, not the feature. The targets list
    is stored wholesale (no `_coerce` inside it), and `"hotkey": 120` in ONE
    target used to raise on `.strip()` for every state change — so no target
    muted at all, with nothing but a stack trace in the log. Each broken entry
    is skipped with one warning, and the user hears about it once."""
    import logging

    from listen_to_me import integrations
    from listen_to_me.config import Config
    from listen_to_me.integrations import MuteIntegrations, target_problem

    good = {"name": "Discord", "enabled": True, "mode": "toggle", "hotkey": "<ctrl>+<shift>+m"}
    assert target_problem(good) is None
    assert target_problem({**good, "mode": "hold"}) is None
    for broken in (
        {**good, "hotkey": 120},
        {**good, "mode": "sometimes"},
        {**good, "mode": None},
        {**good, "enabled": "yes"},
        {**good, "enabled": 1},
        {**good, "name": 7},
        "Discord",
        None,
    ):
        assert target_problem(broken), f"accepted {broken!r}"

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    notices: list[str] = []
    handler = _Capture()
    integrations.log.addHandler(handler)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(path=Path(tmp) / "config.json")
            cfg["integrations"]["mute_while_recording"] = True
            cfg["integrations"]["targets"] = [
                {**good, "hotkey": 120},  # the AttributeError case
                good,
                {**good, "name": "Zoom", "enabled": "yes"},
                {**good, "name": "Slack", "enabled": False, "hotkey": None},  # off: nobody's business
                "OBS",
                {**good, "name": "Teams", "hotkey": "   "},  # no keybind: nothing to send, no complaint
            ]
            mute = MuteIntegrations(cfg, notify=notices.append)
            assert mute._active_targets() == [good]
            assert mute._active_targets() == [good]  # a second read: same answer, no second report
            cfg["integrations"]["targets"] = "Discord"  # not even a list
            assert mute._active_targets() == []
    finally:
        integrations.log.removeHandler(handler)
    warnings = [m for m in records if "malformed" in m]
    assert len(warnings) == 3, warnings
    assert any("#1 (Discord)" in m and '"hotkey"' in m for m in warnings), warnings
    assert len(notices) == 1 and "Settings → Integrations" in notices[0], notices


def _mute_keybind_hold_mode_guard():
    """A toggle-mode mute keybind is not tapped while a hold-mode recording
    hotkey with modifiers is held — it would end the recording or reach the
    target widened. A tap presses AND releases its whole chord while the hotkey
    is still down: the shipped defaults (Ctrl+Alt+Space, Discord's
    Ctrl+Shift+M) share Ctrl, so the tap's Ctrl release hits the app's own hold
    listener and the take ends a second after it started; a chord sharing no
    key is delivered as Ctrl+Alt+<chord>. Hold-mode targets only press at start
    and release after the take, so they keep working. The decision is a pure
    function; the worker body runs against a faked pynput."""
    import enum
    import types

    from listen_to_me.config import Config
    from listen_to_me.integrations import MuteIntegrations, _hold_mode_skip_reason as reason

    ctrl, alt, shift, space, m, f9 = "ctrl", "alt", "shift", "space", "m", "f9"
    default = {ctrl, alt, space}
    assert reason(default, True, [ctrl, shift, m], "toggle"), "shared Ctrl: the release ends the take"
    assert reason(default, True, [shift, m], "toggle"), "no shared key, but tapped under Ctrl+Alt"
    assert reason({f9}, False, [ctrl, shift, m], "toggle") is None, "the recommended setup"
    assert reason({f9}, False, [ctrl, f9], "toggle"), "shares F9 with a modifier-free hotkey"
    assert reason(default, True, [ctrl, shift, m], "hold") is None, "hold targets keep working"
    assert reason(default, True, [shift, m], "hold") is None

    class _KeyCode:
        def __init__(self, vk=None, char=None):
            self.vk, self.char = vk, char

        @classmethod
        def from_vk(cls, vk):
            return cls(vk=vk)

        def __eq__(self, other):
            return isinstance(other, _KeyCode) and (self.vk, self.char) == (other.vk, other.char)

        def __hash__(self):
            return hash((self.vk, self.char))

        def __repr__(self):
            return f"KeyCode(vk={self.vk}, char={self.char!r})"

    class _Key(enum.Enum):
        ctrl = _KeyCode(vk=0xA2)
        alt = _KeyCode(vk=0xA4)
        shift = _KeyCode(vk=0xA0)
        space = _KeyCode(vk=0x20)
        f9 = _KeyCode(vk=0x78)

    class _HotKey:
        @staticmethod
        def parse(combo):
            keys = []
            for token in combo.split("+"):
                token = token.strip()
                if token.startswith("<") and token.endswith(">"):
                    if not hasattr(_Key, token[1:-1]):
                        raise ValueError(token)
                    keys.append(getattr(_Key, token[1:-1]))
                elif len(token) == 1:
                    keys.append(_KeyCode(char=token))
                else:
                    raise ValueError(token)
            return keys

    events: list = []

    class _Controller:
        def press(self, key):
            events.append(("press", key))

        def release(self, key):
            events.append(("release", key))

    keyboard = types.ModuleType("pynput.keyboard")
    keyboard.Controller, keyboard.HotKey, keyboard.Key, keyboard.KeyCode = (
        _Controller, _HotKey, _Key, _KeyCode,
    )
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard
    saved = {name: sys.modules.get(name) for name in ("pynput", "pynput.keyboard")}
    sys.modules["pynput"], sys.modules["pynput.keyboard"] = pynput, keyboard

    def pressed():
        return [key for kind, key in events if kind == "press"]

    def activate(mute, targets):
        events.clear()
        mute.reset()  # synchronous: releases a previous run's keys
        with mute._lock:
            generation = mute._bump()
        events.clear()
        mute._activate(generation, targets)

    notices: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(path=Path(tmp) / "config.json")
            cfg["hotkey_mode"] = "hold"  # with the default <ctrl>+<alt>+<space>
            cfg["integrations"]["mute_while_recording"] = True
            cfg["integrations"]["targets"] = [
                {"name": "Discord", "enabled": True, "mode": "toggle", "hotkey": "<ctrl>+<shift>+m"},
                {"name": "Zoom", "enabled": True, "mode": "toggle", "hotkey": "<shift>+a"},
                {"name": "OBS", "enabled": True, "mode": "hold", "hotkey": "<shift>+<f9>"},
            ]
            mute = MuteIntegrations(cfg, notify=notices.append)
            targets = mute._active_targets()
            assert len(targets) == 3

            activate(mute, targets)
            assert pressed() == [_Key.shift, _Key.f9], events  # the hold target, nothing else
            assert not [e for e in events if e[0] == "release"], "nothing may be tapped"
            assert mute._toggles == [] and len(mute._held) == 2
            assert len(notices) == 2, notices
            for notice, name in zip(notices, ("Discord", "Zoom")):
                assert notice.startswith(f"Mute for {name} is skipped in hold mode"), notice
                assert "<f9>" in notice and "toggle mode" in notice, notice
            assert "shares keys" in notices[0] and "modifier keys are held" in notices[1], notices

            activate(mute, targets)  # the next take: skipped again, said once
            assert pressed() == [_Key.shift, _Key.f9]
            assert len(notices) == 2, "the notification must not repeat per take"

            # Toggle mode releases the hotkey before the keybind goes out — no guard.
            cfg["hotkey_mode"] = "toggle"
            activate(mute, targets)
            assert len(mute._toggles) == 2 and ("release", _Key.ctrl) in events, events

            # Hold mode with a modifier-free hotkey: the chords go out as configured.
            cfg["hotkey_mode"], cfg["hotkey"] = "hold", "<f9>"
            activate(mute, targets)
            assert len(mute._toggles) == 2 and len(mute._held) == 2, events
            assert len(notices) == 2
            mute.reset()
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _injector_waits_for_quiet_modifiers():
    """Ctrl+V and simulated typing wait for the stop-hotkey chord to be let go,
    like every other injection path already did — and refuse rather than send
    a chord the held keys would corrupt (Ctrl+Alt+V pastes nothing, typed text
    under Ctrl is shortcuts). The transcript stays on the clipboard for the
    caller's "press Ctrl+V" message, unless `clipboard_copy = "off"` promised
    it would not. pynput and pyperclip are faked (no X display on CI)."""
    import contextlib
    import threading
    import time
    import types

    from listen_to_me import injector
    from listen_to_me.injector import Injector, ModifierHeldError, wait_for_quiet_modifiers

    events: list = []

    class _Controller:
        def press(self, key):
            events.append(("press", key))

        def release(self, key):
            events.append(("release", key))

        def type(self, text):
            events.append(("type", text))

        @contextlib.contextmanager
        def pressed(self, *keys):
            for key in keys:
                self.press(key)
            try:
                yield
            finally:
                for key in reversed(keys):
                    self.release(key)

    class _Clipboard:
        stored = "before"

        def copy(self, text):
            self.stored = text

        def paste(self):
            return self.stored

    keyboard = types.ModuleType("pynput.keyboard")
    keyboard.Controller = _Controller
    keyboard.Key = types.SimpleNamespace(ctrl="ctrl", cmd="cmd")
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard
    clip = _Clipboard()
    saved = {name: sys.modules.get(name) for name in ("pynput", "pynput.keyboard", "pyperclip")}
    sys.modules.update({"pynput": pynput, "pynput.keyboard": keyboard, "pyperclip": clip})
    original_down = injector.modifiers_down
    original_timeout = injector._INSERT_SETTLE_TIMEOUT_S
    cfg = {"injection_mode": "paste", "restore_clipboard": True, "clipboard_copy": "on_failure"}

    def refused(config, text="hello"):
        try:
            Injector(config).insert(text)
        except ModifierHeldError:
            return True
        return False

    try:
        injector._INSERT_SETTLE_TIMEOUT_S = 0.05
        injector.modifiers_down = lambda: True
        # Held past the timeout: no chord, no typing fallback (it would run into
        # the same key), and the transcript is left for the recovery message.
        assert refused(cfg), "a chord was sent under a held modifier"
        assert events == [], events
        assert clip.stored == "hello", "the transcript must stay on the clipboard"
        clip.stored = "before"
        assert refused({**cfg, "clipboard_copy": "off"})
        assert clip.stored == "before", '"off" promises dictated text never lingers'
        assert refused({**cfg, "injection_mode": "type"})
        assert events == [], "typing under a held modifier is shortcuts, not text"

        # Let go in time: the chord goes out and the old content is put back.
        injector._INSERT_SETTLE_TIMEOUT_S = 2.0
        held = [True]
        injector.modifiers_down = lambda: held[0]
        threading.Timer(0.02, lambda: held.__setitem__(0, False)).start()
        clip.stored = "before"
        assert Injector(cfg).insert("hello") is False  # restored → not on the clipboard
        modifier = "cmd" if sys.platform == "darwin" else "ctrl"
        assert events[:2] == [("press", modifier), ("press", "v")], events
        assert clip.stored == "before"

        # A quiet keyboard (and every non-Windows run) waits not at all.
        injector.modifiers_down = lambda: False
        started = time.monotonic()
        assert wait_for_quiet_modifiers(5.0) is True
        assert time.monotonic() - started < 0.05
    finally:
        injector.modifiers_down = original_down
        injector._INSERT_SETTLE_TIMEOUT_S = original_timeout
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _updater_caps_the_download_size():
    """A release download is bounded by the size the API reported (plus slack)
    or by a hard ceiling: a body that announces more is refused before the
    first byte, one that keeps streaming past the cap is cut off — and the
    partial file is gone either way, so a misbehaving server or proxy cannot
    fill the disk next to the running exe. requests is faked (light CI env)."""
    import types

    from listen_to_me import updater

    asset_url = "https://github.com/fo0/listen-to-me/releases/download/v1/ListenToMe.exe"
    responses: list = []

    class _Response:
        def __init__(self, headers, chunks):
            self.headers, self.chunks, self.url = headers, chunks, asset_url

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=0):
            return iter(self.chunks)

    fake = types.ModuleType("requests")
    fake.get = lambda url, **kwargs: responses.pop(0)
    fake.exceptions = types.SimpleNamespace(SSLError=type("SSLError", (Exception,), {}))
    saved = sys.modules.get("requests")
    sys.modules["requests"] = fake
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "asset.exe"
            responses.append(_Response({"Content-Length": "2000"}, [b"x" * 2000]))
            try:
                updater.download_asset(asset_url, dest, max_bytes=1000)
                raise AssertionError("an oversized Content-Length was accepted")
            except ValueError as exc:
                assert "2000" in str(exc) and "1000" in str(exc), exc
            assert not dest.exists(), "nothing may be written for a refused download"

            responses.append(_Response({}, [b"x" * 600, b"x" * 600]))  # no Content-Length
            try:
                updater.download_asset(asset_url, dest, max_bytes=1000)
                raise AssertionError("a body streaming past the cap was accepted")
            except ValueError:
                pass
            assert not dest.exists(), "the partial file must be removed"

            responses.append(_Response({"Content-Length": "12"}, [b"listen-to-me"]))
            cap = updater.download_cap(12)
            assert updater.download_asset(asset_url, dest, max_bytes=cap) == dest
            assert dest.read_bytes() == b"listen-to-me"
    finally:
        if saved is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = saved
    assert updater.download_cap(1000) == 1050
    for unusable in (None, 0, -5, "x"):
        assert updater.download_cap(unusable) == updater._MAX_DOWNLOAD_BYTES, unusable
    assert issubclass(updater.DownloadTooLarge, ValueError)  # existing callers catch that


def _recorder_counts_dropped_buffers():
    """PortAudio's input-overflow status means frames the device produced were
    lost — words missing from the transcript with no trace but a DEBUG line.
    One WARNING per take, a count the caller can name next to an empty
    transcript, and a fresh count for the next take. sounddevice is faked and
    the buffers are stand-ins, so this runs without numpy or a microphone."""
    import logging
    import sys as _sys
    import types

    from listen_to_me import audio
    from listen_to_me.audio import Recorder

    class _Stream:
        def __init__(self, callback=None, **_kwargs):
            self.callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    class _Buffer:  # what the callback keeps: anything with .copy()
        def copy(self):
            return self

    class _Status:
        def __bool__(self):
            return True

        def __str__(self):
            return "input overflow"

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    opened: list[_Stream] = []

    def _input_stream(**kwargs):
        stream = _Stream(**kwargs)
        opened.append(stream)
        return stream

    fake = types.ModuleType("sounddevice")
    fake.InputStream = _input_stream
    fake.CallbackStop = RuntimeError
    previous = _sys.modules.get("sounddevice")
    _sys.modules["sounddevice"] = fake
    handler = _Capture()
    audio.log.addHandler(handler)
    try:
        recorder = Recorder()
        assert recorder.dropped_buffers == 0
        recorder.start(max_seconds=30)
        callback = opened[-1].callback
        callback(_Buffer(), 160, None, None)  # a clean buffer counts nothing
        for _ in range(3):
            callback(_Buffer(), 160, None, _Status())
        assert recorder.dropped_buffers == 3
        warnings = [r for r in records if r.levelno == logging.WARNING and "dropped" in r.getMessage()]
        assert len(warnings) == 1, [r.getMessage() for r in records]
        assert "input overflow" in warnings[0].getMessage()
        recorder._stream = None  # the fake stream holds nothing; skip stop()'s numpy path
        recorder._chunks = []
        assert recorder.dropped_buffers == 3, "the count must survive until the next take"
        recorder.start(max_seconds=30)
        assert recorder.dropped_buffers == 0, "start() must reset the count"
        callback = opened[-1].callback
        callback(_Buffer(), 160, None, _Status())
        assert len([r for r in records if r.levelno == logging.WARNING]) == 2, "one per take"
        recorder._stream = None
        recorder._chunks = []
        # The memory backstop: a cap above the Settings maximum is held there.
        recorder.start(max_seconds=10**9)
        assert recorder._max_frames == audio.MAX_RECORDING_SECONDS * audio.SAMPLE_RATE
        recorder._stream = None
        recorder._chunks = []
    finally:
        audio.log.removeHandler(handler)
        if previous is None:
            del _sys.modules["sounddevice"]
        else:
            _sys.modules["sounddevice"] = previous


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
    from listen_to_me.theme import ACCENT_FILL, _DARK, _LIGHT

    for name, palette in (("light", _LIGHT), ("dark", _DARK)):
        ratio = _contrast(palette["disabled_bg"], ACCENT_FILL)
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
        self.transcriber = _StubTranscriber()
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


class _StubTranscriber:
    """What the Settings window reads off App.transcriber: the backend and the
    (device, precision) pair of the loaded model — None while nothing is."""

    def __init__(self):
        self.backend = "faster-whisper"
        self.runtime: tuple | None = None


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

            # "Pause hotkey" carries the app's pause state, re-read when the
            # menu opens like everything else on it — the tick is the only
            # thing telling a paused app apart from a broken one, and an App
            # that refuses the pause (mid-recording) has to be able to put it
            # back. getattr's default keeps a stub without the flag unticked.
            stub.state = "idle"
            overlay.show_menu(QPoint(0, 0))
            overlay._menu.hide()
            assert not overlay._act_pause.isChecked()
            stub.hotkey_paused = True
            overlay.show_menu(QPoint(0, 0))
            overlay._menu.hide()
            assert overlay._act_pause.isChecked()
            stub.posts.clear()
            overlay._act_pause.trigger()
            assert stub.posts == [("toggle_hotkey_pause",)], stub.posts
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


def _source_aware_controls_stop_their_take():
    """Every control that can end a take names the take that is running and
    posts the toggle for *that* source (#191).

    The bug this exists for is a control labelled "Stop recording" that posts
    the other source's toggle: App refuses a toggle for one source while the
    other records (it must — the alternative inserts a recorded meeting into
    the window a dictation was meant for), so such a control does nothing but
    produce "A system audio recording is already running". Three surfaces can
    end a take — the tray menu, the floating icon and the Home hero — and each
    one is asserted against both sources, plus the tray status line, which used
    to name the microphone combination while system audio was recording: the
    one key that does not stop what is running.

    The App stub carries `recording_source` as a plain attribute; the real App
    exposes it as a property, and every surface reads it through `getattr` with
    the microphone as the default (`Tray._source`)."""
    from listen_to_me import tray as tray_module
    from listen_to_me.choices import SOURCE_MIC, SOURCE_SYSTEM
    from listen_to_me.overlay import Overlay
    from listen_to_me.settings_ui import SettingsWindow
    from listen_to_me.theme import apply_theme
    from listen_to_me.tray import _SYSTEM_START_LABEL, _SYSTEM_STOP_LABEL

    qapp = _ensure_qapp()
    apply_theme(qapp)
    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        stub.cfg["system_audio"]["hotkey"] = "<ctrl>+<alt>+<shift>+<space>"

        # --- the tray menu -------------------------------------------------
        tray = tray_module.Tray(stub)
        tray.start()
        try:
            assert tray._act_toggle.text() == "Start recording"
            assert tray._act_system.text() == _SYSTEM_START_LABEL

            # A microphone take turns the first entry into a "Stop" …
            stub.state = "recording"
            stub.recording_source = SOURCE_MIC
            tray.set_state("recording")
            assert tray._act_toggle.text() == "Stop recording (insert text)"
            assert tray._act_system.text() == _SYSTEM_START_LABEL
            # … a system-audio take the other one, and both name the source:
            # with two start entries in one menu a bare "Stop recording" would
            # not say which of the two takes it ends.
            stub.recording_source = SOURCE_SYSTEM
            tray.set_state("recording")
            assert tray._act_toggle.text() == "Start recording"
            assert tray._act_system.text() == _SYSTEM_STOP_LABEL
            # The entry that says "Stop" is the one whose click App accepts.
            stub.posts.clear()
            tray._act_system.trigger()
            assert stub.posts == [("toggle", SOURCE_SYSTEM)], stub.posts
            stub.posts.clear()
            tray._act_toggle.trigger()
            assert stub.posts == [("toggle",)], stub.posts

            # The status line, and with it the tooltip: the running source's
            # own combination, from system_audio.hotkey.
            label = tray_module.state_label(
                "recording", stub.cfg, elapsed=72, source=SOURCE_SYSTEM
            )
            assert label == (
                "Recording system audio 1:12… press Ctrl+Alt+Shift+Space to stop"
            ), label
            assert tray_module.state_label("recording", stub.cfg, source=SOURCE_SYSTEM) == (
                "Recording system audio… press Ctrl+Alt+Shift+Space to stop"
            )
            assert "Ctrl+Alt+Space to stop" not in label, "named the dictation hotkey"
            # …and the tray really goes through it, on both paths that render it.
            tray.set_state("recording")
            assert "system audio" in tray._act_state.text()
            assert "Ctrl+Alt+Shift+Space" in tray._act_state.text(), tray._act_state.text()
            tray.set_elapsed(72)
            assert tray._act_state.text() == label, tray._act_state.text()
            # Hold mode stops on release — per source, because the two modes
            # are configured separately.
            stub.cfg["system_audio"]["hotkey_mode"] = "hold"
            assert "release Ctrl+Alt+Shift+Space to stop" in tray_module.state_label(
                "recording", stub.cfg, source=SOURCE_SYSTEM
            )
            # An empty combination is how the second source is switched off, so
            # such a take was started from a menu entry: say what is recording
            # and invent no key.
            stub.cfg["system_audio"]["hotkey"] = ""
            for elapsed, expected in ((None, "Recording system audio…"),
                                      (72, "Recording system audio 1:12…")):
                assert tray_module.state_label(
                    "recording", stub.cfg, elapsed=elapsed, source=SOURCE_SYSTEM
                ) == expected
            # The microphone wording is untouched by all of it, and the source
            # changes the *recording* status only — idle is about starting a
            # dictation, whose hotkey is the microphone's.
            assert tray_module.state_label("recording", stub.cfg) == (
                "Recording… press Ctrl+Alt+Space to stop"
            )
            assert tray_module.state_label("idle", stub.cfg, source=SOURCE_SYSTEM) == (
                "Idle — press Ctrl+Alt+Space to record"
            )
            assert tray_module.state_label("processing", stub.cfg, source=SOURCE_SYSTEM) == (
                tray_module._STATE_LABELS["processing"]
            )
            stub.cfg["system_audio"]["hotkey"] = "<ctrl>+<alt>+<shift>+<space>"
        finally:
            tray.stop()

        # --- the floating icon ---------------------------------------------
        overlay = Overlay(stub)
        try:
            stub.state = "recording"
            stub.recording_source = SOURCE_SYSTEM
            overlay.set_state("recording")
            assert overlay._act_toggle.text() == _SYSTEM_STOP_LABEL
            # The start entry steps aside while a take runs: the entry above is
            # already the stop entry, and a second one would only earn App's
            # refusal — on a context menu hanging off a 64 px icon.
            assert not overlay._act_system.isVisible()
            assert overlay.toggle_source() == SOURCE_SYSTEM
            stub.posts.clear()
            overlay.post_toggle()  # what a click on the icon itself does
            assert stub.posts == [("toggle", SOURCE_SYSTEM)], stub.posts
            # The one control that never leaves the screen says which source.
            assert "system audio" in overlay.win.toolTip()
            assert "system audio" in overlay.win.accessibleDescription()

            # A microphone take keeps every wording it ever had, and its click
            # stays the payload-free toggle every other surface posts.
            stub.recording_source = SOURCE_MIC
            overlay.set_state("recording")
            assert overlay._act_toggle.text() == "Stop recording (insert text)"
            assert overlay.toggle_source() == SOURCE_MIC
            stub.posts.clear()
            overlay.post_toggle()
            assert stub.posts == [("toggle",)], stub.posts
            assert "system audio" not in overlay.win.toolTip()

            # Idle: the icon's click is the dictation control (the second
            # source has its own entry to start from), and that entry posts
            # its own toggle — this menu is the only way to start such a take
            # with no hotkey configured for it.
            stub.state = "idle"
            overlay.set_state("idle")
            assert overlay.toggle_source() == SOURCE_MIC
            assert overlay._act_system.isVisible()
            assert overlay._act_system.text() == _SYSTEM_START_LABEL
            stub.posts.clear()
            overlay._act_system.trigger()
            assert stub.posts == [("toggle", SOURCE_SYSTEM)], stub.posts
        finally:
            overlay.destroy()

        # --- the Home hero -------------------------------------------------
        window = SettingsWindow(stub)
        try:
            stub.state = "recording"
            stub.recording_source = SOURCE_SYSTEM
            window.set_app_state("recording")
            assert window.home.record_button.text() == "Stop && insert (system audio)"
            assert "system audio" in window.home.record_button.toolTip()
            # "speak now" drops with the source: this take records what the
            # computer plays, so asking for speech would ask for the one thing
            # that is not being recorded.
            assert window.home.state_label.text() == "Recording system audio"
            window.set_app_elapsed(72)
            assert window.home.state_label.text() == "Recording system audio 1:12"
            stub.posts.clear()
            window.home._last_toggle = 0.0  # the hero's 400 ms click debounce
            window.home.record_button.click()
            assert stub.posts == [("toggle", SOURCE_SYSTEM)], stub.posts

            stub.recording_source = SOURCE_MIC
            window.set_app_state("recording")
            assert window.home.record_button.text() == "Stop && insert"
            assert window.home.state_label.text() == "Recording — speak now"
            stub.posts.clear()
            window.home._last_toggle = 0.0
            window.home.record_button.click()
            assert stub.posts == [("toggle",)], stub.posts
        finally:
            window.deleteLater()
        stub.state = "idle"
        qapp.processEvents()


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


def _settings_window_edits_the_new_options():
    """The Settings surfaces of #190/#191: the filler phrase list on the Engine
    page, the "System audio" card on the Audio page, and the second assistant
    profile.

    Four ways this can be broken without anything looking wrong. An editable
    phrase list whose filter is off has to read as inactive, or it looks
    exactly like one in force. `_collect()` is the only path to disk, so a key
    missing from it is a setting that cannot be saved at all — and the second
    assistant profile must not collect a connection of its own, which would be
    one server to configure twice. `_validate` refuses two listeners on one
    chord (pynput delivers the press to both and app.py then registers
    neither), while an empty combination is the documented "off" and must never
    be reported. And the loopback device has to survive a Save from a window
    whose Audio page was never opened: the dropdown holds a placeholder until
    then, and answering from it would drop the device the user picked.

    `Hotkeys` is stood in for exactly as in `_gui_construction`: the real
    parser imports pynput, which needs an X display the CI runner has not
    got."""
    from listen_to_me import settings_ui as _settings_module
    from listen_to_me.settings_ui import SettingsWindow
    from listen_to_me.theme import apply_theme

    app = _ensure_qapp()
    apply_theme(app)

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        window = SettingsWindow(stub)

        # --- the filler phrase list ----------------------------------------
        assert window.chk_filler.isChecked() is True  # DEFAULTS: the filter is on
        window.chk_filler.setChecked(False)
        assert not window.filler_edit.isEnabled()
        assert not window.filler_reset_button.isEnabled()
        assert not window.filler_status.isEnabled()
        window.chk_filler.setChecked(True)
        assert window.filler_edit.isEnabled() and window.filler_reset_button.isEnabled()
        # The status under the field is live while the list is typed, and
        # announced with the field rather than only as a label beside it (the
        # replacements field two cards away has the same contract).
        window.filler_edit.setPlainText("Vielen Dank\n...")
        status = window.filler_status.text()
        assert "1 phrase active" in status and "line 2 is only punctuation" in status, status
        assert window.filler_edit.accessibleDescription() == status
        window.filler_edit.setPlainText("")
        assert window.filler_status.isHidden()

        # --- where a recorded playback would be sent ------------------------
        # The disclosure belongs to the tick, so it follows the field it is
        # about with no Save in between: the endpoint is configured two cards
        # above, and whoever switches this on has to be able to read where the
        # recording goes while they are doing it. (The wording itself is
        # `assistant destination names where a recording goes`.)
        window.chk_a_sys_enabled.setChecked(False)
        window.a_url_edit.setText("http://localhost:11434/v1")
        hint = window._a_destination_hint
        assert "stays on it" in hint.text(), hint.text()
        window.a_url_edit.setText("https://api.example.com/v1")
        assert "leaves this machine" in hint.text(), hint.text()
        assert "api.example.com" in hint.text()
        # Nothing was saved in between: the sentence is resolved from the
        # field on screen, not from the stored config.
        assert window._collect()["assistant"]["base_url"] == "https://api.example.com/v1"
        assert window.cfg["assistant"]["base_url"] != "https://api.example.com/v1"
        # Never hidden and never greyed out while the profile is off — off is
        # exactly the state the decision gets made in, and a disclosure that
        # only appears after the tick is one the tick could not use. The tense
        # carries the state instead.
        assert not hint.isHidden() and hint.isEnabled()
        assert hint.text().startswith("Switched on,"), hint.text()
        # The sentence is also the switch's accessible description: a sibling
        # label is not announced with the widget it belongs to, and this one
        # belongs to that checkbox.
        assert window.chk_a_sys_enabled.accessibleDescription() == hint.text()
        window.chk_a_sys_enabled.setChecked(True)
        assert not hint.isHidden()
        assert hint.text().startswith("The transcript of every recorded playback"), hint.text()
        assert window.chk_a_sys_enabled.accessibleDescription() == hint.text()
        # Plain text, never Qt's AutoText guess: the host comes out of a text
        # field, so a value with a "<" in it would otherwise be rendered as
        # markup (the History page's transcript rows have the same rule).
        assert hint.textFormat() == _settings_module.Qt.TextFormat.PlainText
        window.a_url_edit.setText("<b>ollama</b>.example.com")
        assert "<b>" not in hint.text(), hint.text()  # no host to quote at all
        window.chk_a_sys_enabled.setChecked(False)
        window.a_url_edit.setText(window.cfg["assistant"]["base_url"])

        # --- _collect(): every new key round-trips --------------------------
        window.chk_filler.setChecked(False)
        window.filler_edit.setPlainText("Vielen Dank\nThank you")
        window.sys_hotkey_edit.setText("<ctrl>+<alt>+<shift>+<space>")
        window.rb_sys_hold.setChecked(True)
        window.sys_max_seconds_spin.setValue(1200)
        window.chk_a_sys_enabled.setChecked(True)
        window.a_sys_model_edit.setText("qwen2.5:14b")
        window.a_sys_prompt_edit.setPlainText("write the minutes")
        values = window._collect()
        assert values["filler_filter"] is False
        # No fallback to the shipped list: an emptied field is a legitimate
        # "filter nothing", and the checkbox is the off switch.
        assert values["filler_phrases"] == "Vielen Dank\nThank you"
        assert values["system_audio"] == {
            "hotkey": "<ctrl>+<alt>+<shift>+<space>",
            "hotkey_mode": "hold",
            "device": None,
            "max_seconds": 1200,
        }, values["system_audio"]
        assert values["assistant"]["system_audio"] == {
            "enabled": True,
            "model": "qwen2.5:14b",
            "system_prompt": "write the minutes",
        }, values["assistant"]["system_audio"]
        # The connection stays shared — a base_url/api_key of its own here
        # would be a second endpoint to configure for one server.
        assert set(values["assistant"]["system_audio"]) == {"enabled", "model", "system_prompt"}
        # An empty model override is stored verbatim ("use the shared one"),
        # unlike the prompt, which falls back to its default.
        window.a_sys_model_edit.setText("")
        window.a_sys_prompt_edit.setPlainText("")
        collected = window._collect()["assistant"]["system_audio"]
        assert collected["model"] == ""
        assert collected["system_prompt"] == _settings_module.DEFAULT_SYSTEM_AUDIO_PROMPT
        # Every new key is part of the unsaved-changes snapshot too, or Save
        # would not know it changed.
        assert window._collect() != window._saved_snapshot
        window.chk_filler.setChecked(True)
        window.filler_edit.setPlainText(window.cfg["filler_phrases"])
        window.sys_hotkey_edit.setText(window.cfg["system_audio"]["hotkey"])
        window.rb_sys_toggle.setChecked(True)
        window.sys_max_seconds_spin.setValue(window.cfg["system_audio"]["max_seconds"])
        window.chk_a_sys_enabled.setChecked(False)
        window.a_sys_prompt_edit.setPlainText(
            window.cfg["assistant"]["system_audio"]["system_prompt"]
        )
        assert window._collect() == window._saved_snapshot

        # --- the loopback device survives a Save ----------------------------
        # Not enumerated at construction (PortAudio can stall for hundreds of
        # ms before anything is on screen), so until the Audio page is first
        # opened the *config* has to answer for the dropdown.
        assert window._sys_devices_loaded is False
        window.cfg["system_audio"]["device"] = 7
        assert window._selected_system_device() == 7
        assert window._collect()["system_audio"]["device"] == 7
        # A stored value that is not an index reads as "Automatic": the null
        # default carries no type, so config.py hands a hand-edit back
        # untouched (bool is an int subclass and is not a device).
        for junk in ("Stereo Mix", True, None, 1.5):
            window.cfg["system_audio"]["device"] = junk
            assert window._selected_system_device() is None, repr(junk)
        # …and it survives the visit that fills the dropdown, even when the
        # device is not there right now: PortAudio indices are positional, so
        # falling back to "Automatic" would drop the choice on the next Save.
        window.cfg["system_audio"]["device"] = 7
        window._show_page("Audio")
        app.processEvents()
        assert window._sys_devices_loaded is True
        assert window._selected_system_device() == 7
        assert window._collect()["system_audio"]["device"] == 7
        # With no loopback device found the card says so — every take would be
        # refused with nothing captured, and nothing else on the page would
        # explain it (there is no PortAudio in the light run, so this is the
        # zero-candidate case).
        if window._sys_candidates == 0:
            from listen_to_me.system_audio import system_audio_help

            hint = window._sys_audio_hint.text()
            assert "No loopback device" in hint, hint
            assert system_audio_help() in hint

        # --- _validate(): one chord cannot drive two listeners --------------
        class _FakeHotkeys:
            valid = ("<ctrl>+<alt>+<space>", "<ctrl>+<alt>+<shift>+<space>")

            @classmethod
            def validate(cls, combo):
                return combo in cls.valid

            @classmethod
            def combo_flags(cls, combo):
                return (True, True)

            @staticmethod
            def equal(combo_a, combo_b):
                return combo_a == combo_b

        class _FakeCriticalBox:
            StandardButton = _settings_module.QMessageBox.StandardButton
            shown: list = []

            @classmethod
            def critical(cls, *args, **_kwargs):
                cls.shown.append(args[-1])

        real_hotkeys, real_box = _settings_module.Hotkeys, _settings_module.QMessageBox
        _settings_module.Hotkeys = _FakeHotkeys
        _settings_module.QMessageBox = _FakeCriticalBox
        try:
            window.hotkey_edit.setText("<ctrl>+<alt>+<space>")
            # Empty: the second source is off, and Save must not report it.
            window.sys_hotkey_edit.setText("")
            assert window._validate(window._collect()) is True
            assert not _FakeCriticalBox.shown, _FakeCriticalBox.shown
            assert not window._sys_hotkey_error.text()
            # Its own combination: accepted.
            window.sys_hotkey_edit.setText("<ctrl>+<alt>+<shift>+<space>")
            assert window._validate(window._collect()) is True
            assert not window._sys_hotkey_error.text()
            # The microphone's: refused, naming both — the inline reason under
            # the field says the same thing while it is being typed, because a
            # label is not announced to a screen reader whose focus is on the
            # Save button that refused.
            window.sys_hotkey_edit.setText("<ctrl>+<alt>+<space>")
            assert window._validate(window._collect()) is False
            assert _FakeCriticalBox.shown and "same combination" in _FakeCriticalBox.shown[-1]
            assert "Same combination" in window._sys_hotkey_error.text()
            # A combination that does not parse is refused like the
            # microphone's, and never silently kept.
            _FakeCriticalBox.shown.clear()
            window.sys_hotkey_edit.setText("nonsense")
            assert window._validate(window._collect()) is False
            assert "Invalid system audio hotkey" in _FakeCriticalBox.shown[-1]
            assert "not a valid combination" in window._sys_hotkey_error.text()
        finally:
            _settings_module.Hotkeys, _settings_module.QMessageBox = real_hotkeys, real_box
            window.sys_hotkey_edit.setText(window.cfg["system_audio"]["hotkey"])

        window.deleteLater()
        app.processEvents()


def _system_audio_profiles(names):
    """The shape `audio.input_device_profiles()` returns, for a list of device
    names. The index is the enumeration order, exactly as PortAudio hands it
    out — which is what makes a stored index positional in the first place."""
    return [
        {
            "index": index,
            "name": name,
            "hostapi": "WASAPI",
            "channels": 2,
            "samplerate": 48000.0,
        }
        for index, name in enumerate(names)
    ]


def _load_faked_system_devices(window, inputs, outputs, platform):
    """Fill `window`'s system-audio dropdown from injected device lists, as if
    PortAudio and the platform said so. Returns
    `system_audio.system_audio_help()` for that platform — the sentence the
    card's hint has to carry verbatim.

    Both enumerations are patched on `listen_to_me.audio`, because
    `_load_system_devices` imports them inside its own body — the same lazy
    import that keeps PortAudio off the constructor path. `sys.platform` is
    patched around the call and put straight back: the hint's actionable half
    is `system_audio_help()`, which branches on the platform, so a Windows
    machine's card cannot be checked on the Linux CI runner without saying so.
    (`_portaudio_path_prepend` does the same with `sys.frozen`, for the same
    reason.)
    """
    from listen_to_me import audio
    from listen_to_me.system_audio import system_audio_help

    saved = (audio.input_device_profiles, audio.list_output_devices, sys.platform)
    audio.input_device_profiles = lambda: _system_audio_profiles(inputs)
    audio.list_output_devices = lambda: list(enumerate(outputs))
    sys.platform = platform
    try:
        window._load_system_devices()
        return system_audio_help()
    finally:
        audio.input_device_profiles, audio.list_output_devices, sys.platform = saved


def _load_real_system_devices(window, devices, hostapis, platform="win32"):
    """Fill `window`'s system-audio dropdown through the REAL enumeration —
    `audio.list_output_devices()` and `audio.input_device_profiles()` against a
    stand-in `sounddevice` — instead of patching those two out the way
    `_load_faked_system_devices` does.

    Both helpers are needed. Injecting profiles is how the *wording* is checked
    against a machine shape (three of them, above); this one is the only way to
    check the *enumeration* the wording is built from, and the enumeration is
    what named PortAudio's host-API duplicates as "your outputs".
    """
    from listen_to_me.system_audio import system_audio_help

    with _as_sounddevice(_fake_sounddevice(devices, hostapis), platform):
        window._load_system_devices()
        return system_audio_help()


def _system_audio_rows(window):
    """Every row of the system-audio dropdown as a dict: `text`, `selectable`,
    `enabled` and `announce` (what a screen reader reads instead of the text).

    Read off the combo's own model, because those flags are what Qt itself
    consults: its arrow-key walk skips a row without `ItemIsSelectable`, and
    its popup refuses a click on one that is not enabled. Asserting the flags
    is therefore asserting the behaviour, without a pixel in it.
    """
    from PySide6.QtCore import Qt

    combo = window.sys_device_combo
    model = combo.model()
    rows = []
    for row in range(combo.count()):
        index = model.index(row, 0)
        flags = model.flags(index)
        rows.append(
            {
                "text": combo.itemText(row),
                "selectable": bool(flags & Qt.ItemFlag.ItemIsSelectable),
                "enabled": bool(flags & Qt.ItemFlag.ItemIsEnabled),
                "announce": model.data(index, Qt.ItemDataRole.AccessibleTextRole),
            }
        )
    return rows


def _system_audio_picker_reads_as_an_output_picker():
    """What the "System audio" dropdown offers, on the three machine shapes
    that matter (#195).

    The complaint: the card is headed "System audio", and on a Windows machine
    without "Stereo Mix" the list under it was a flat row of microphones —
    "vor allen Dingen fehlen mir da meine Audio-Ausgabegeräte". PortAudio
    records from inputs only, so an output device can never *be* in this list;
    what was fixable is that the list now says which half of it records the
    computer and which half does not, and says so out loud when the first half
    is empty instead of leaving the microphones to read as the answer.

    Two groups, each introduced by a row that nothing can choose. That is the
    load-bearing part: a pickable heading parses to no index, so choosing it
    would silently switch the device back to "Automatic" on the next Save —
    which is why every non-selectable row is put through
    `input_device_from_label` here as well.

    Every rule #191 established is re-asserted, because each is a way to write
    the wrong device without anything looking wrong: the matched *fragment* is
    shown and the score never is, an unsaved on-screen pick survives a
    Refresh, a configured device that is currently absent keeps a parseable row
    of its own, and a window whose Audio page was never opened still saves the
    stored index.
    """
    from listen_to_me.choices import input_device_from_label
    from listen_to_me.settings_ui import (
        _SYS_GROUP_ABSENT,
        _SYS_GROUP_LOOPBACK,
        _SYS_GROUP_OTHER,
        _SYS_NO_LOOPBACK_ROW,
        _SYSTEM_AUDIO_AUTO,
        SettingsWindow,
        _loopback_output_name,
        _sys_device_label,
    )
    from listen_to_me.theme import apply_theme

    # No heading may ever parse to a device index — nor may "Automatic", which
    # is the same promise the list has kept since #191.
    for label in (
        _SYSTEM_AUDIO_AUTO,
        _SYS_GROUP_LOOPBACK,
        _SYS_GROUP_OTHER,
        _SYS_GROUP_ABSENT,
        _SYS_NO_LOOPBACK_ROW,
    ):
        assert ":" not in label, label
        assert input_device_from_label(label) is None, label

    # The output a loopback device belongs to, read out of its own name — the
    # user thinks in outputs, and the mechanism marker is noise in front of
    # the only words they recognize. Where the name carries no mapping, none
    # is invented: a made-up one promises a take comes from an output that
    # nothing in the system connects it to.
    assert _loopback_output_name(
        {"name": "Monitor of Built-in Audio Analog Stereo", "hint": "monitor of"}
    ) == "Built-in Audio Analog Stereo"
    assert _loopback_output_name(
        {"name": "Monitor von Lautsprecher (Realtek)", "hint": "monitor von"}
    ) == "Lautsprecher (Realtek)"
    assert _loopback_output_name(
        {"name": "Speakers (Realtek(R) Audio) [Loopback]", "hint": "[loopback]"}
    ) == "Speakers (Realtek(R) Audio)"
    for nothing in (
        {"name": "Stereo Mix (Realtek(R) Audio)", "hint": "stereo mix"},
        {"name": "CABLE Output (VB-Audio Virtual Cable)", "hint": "cable output"},
        {"name": "BlackHole 2ch", "hint": "blackhole"},
        {"name": "[Loopback]", "hint": "[loopback]"},  # nothing left of the name
        {"name": "Built-in Microphone"},  # not a candidate at all: no hint key
    ):
        assert _loopback_output_name(nothing) is None, nothing
    # A row never carries the score. It is a sum of LOOPBACK_HINTS weights, not
    # a percentage: "140" beside a device name reads as a confidence and is
    # not one.
    scored = {"index": 7, "name": "Speakers [Loopback]", "hint": "[loopback]", "score": 140}
    assert "140" not in _sys_device_label(scored), _sys_device_label(scored)
    assert "score" not in _sys_device_label(scored).casefold()

    app = _ensure_qapp()
    apply_theme(app)

    def rows_after(window, inputs, outputs, platform):
        _load_faked_system_devices(window, inputs, outputs, platform)
        rows = _system_audio_rows(window)
        # Whatever the shape: nothing unpickable may parse to an index, the
        # first row is always "Automatic", and the current row is a real
        # answer rather than a heading Qt happened to land on.
        assert rows[0]["text"] == _SYSTEM_AUDIO_AUTO and rows[0]["selectable"]
        for row in rows:
            if not row["selectable"]:
                assert input_device_from_label(row["text"]) is None, row
                assert not row["enabled"], row  # greyed out, and announced as such
        assert window.sys_device_combo.currentIndex() >= 0
        assert rows[window.sys_device_combo.currentIndex()]["selectable"]
        return rows

    def texts(rows):
        return [row["text"] for row in rows]

    def group_at(rows, heading):
        """The selectable rows between `heading` and the next heading."""
        labels = texts(rows)
        # A heading that is missing entirely is the `_sys_add_unselectable`
        # read-back having dropped it: it stayed pickable, so no heading was
        # left rather than a pickable one. Named, because a bare ValueError
        # from the lookup below would not say that.
        assert heading in labels, (heading, labels)
        start = labels.index(heading) + 1
        group = []
        for row in rows[start:]:
            if not row["selectable"] and row["text"]:
                break  # the next heading
            if row["text"]:
                group.append(row["text"])
        return group

    with tempfile.TemporaryDirectory() as tmp:
        window = SettingsWindow(_StubApp(Path(tmp)))
        try:
            # --- shape 1: Windows, no Stereo Mix, no cable — the report -----
            rows = rows_after(
                window,
                ["Microphone (Realtek(R) Audio)", "Microphone Array (Intel Smart Sound)"],
                ["Speakers (Realtek(R) Audio)", "Jabra SPEAK 410 USB"],
                "win32",
            )
            headings = [row for row in rows if row["text"] == _SYS_GROUP_LOOPBACK]
            assert len(headings) == 1, texts(rows)
            heading = headings[0]
            assert not heading["selectable"] and not heading["enabled"], heading
            # A screen reader must not read a heading as one of the choices:
            # disabled already says "unavailable", and this says what it is.
            assert heading["announce"] == f"Group heading. {_SYS_GROUP_LOOPBACK}", heading
            # The empty group keeps its heading and says so, rather than
            # letting the microphones below read as the answer.
            assert group_at(rows, _SYS_GROUP_LOOPBACK) == [], rows
            assert _SYS_NO_LOOPBACK_ROW in texts(rows), texts(rows)
            assert texts(rows).index(_SYS_NO_LOOPBACK_ROW) < texts(rows).index(_SYS_GROUP_OTHER)
            # The microphones are offered, under a heading that says they are
            # microphones — and nothing above that heading pretends otherwise.
            assert group_at(rows, _SYS_GROUP_OTHER) == [
                "0: Microphone (Realtek(R) Audio)",
                "1: Microphone Array (Intel Smart Sound)",
            ], rows
            other = texts(rows).index(_SYS_GROUP_OTHER)
            assert all(
                input_device_from_label(row["text"]) is None
                for row in rows[:other]
            ), texts(rows[:other])
            # A separator introduces each group: Qt draws the line, the row
            # above carries the words.
            assert any(not row["text"] and not row["selectable"] for row in rows)

            # --- shape 2: Windows with the newer PortAudio's twins (#194) ---
            rows = rows_after(
                window,
                [
                    "Microphone (Realtek(R) Audio)",
                    "Speakers (Realtek(R) Audio) [Loopback]",
                    "Jabra SPEAK 410 USB [Loopback]",
                    "Stereo Mix (Realtek(R) Audio)",
                ],
                ["Speakers (Realtek(R) Audio)", "Jabra SPEAK 410 USB"],
                "win32",
            )
            loopbacks = group_at(rows, _SYS_GROUP_LOOPBACK)
            # The list now reads as the output picker the user expected: the
            # twins first (the strongest hint there is, and it trips "loopback"
            # as well, so the weights add up past Stereo Mix), each labelled
            # with the OUTPUT it records and not with the marker.
            assert loopbacks == [
                "1: Speakers (Realtek(R) Audio)  — records this output, matched “[loopback]”",
                "2: Jabra SPEAK 410 USB  — records this output, matched “[loopback]”",
                "3: Stereo Mix (Realtek(R) Audio)  — loopback input, matched “stereo mix”",
            ], loopbacks
            assert _SYS_NO_LOOPBACK_ROW not in texts(rows)
            # Every candidate row is still parseable, which is what Save reads.
            assert [input_device_from_label(text) for text in loopbacks] == [1, 2, 3]
            assert group_at(rows, _SYS_GROUP_OTHER) == ["0: Microphone (Realtek(R) Audio)"]

            # An unsaved pick survives a Refresh — repopulating from the saved
            # config would silently revert the device just chosen. Stereo Mix,
            # deliberately: it is the row the Linux shape below has no index
            # for, which is what the absent-device rule is about.
            window.sys_device_combo.setCurrentText(loopbacks[2])
            assert window._selected_system_device() == 3
            rows = rows_after(
                window,
                [
                    "Microphone (Realtek(R) Audio)",
                    "Speakers (Realtek(R) Audio) [Loopback]",
                    "Jabra SPEAK 410 USB [Loopback]",
                    "Stereo Mix (Realtek(R) Audio)",
                ],
                ["Speakers (Realtek(R) Audio)", "Jabra SPEAK 410 USB"],
                "win32",
            )
            assert window._selected_system_device() == 3
            assert window._collect()["system_audio"]["device"] == 3

            # --- shape 3: Linux, PulseAudio/PipeWire monitor sources --------
            rows = rows_after(
                window,
                [
                    "Built-in Microphone",
                    "Monitor of Built-in Audio Analog Stereo",
                    "Monitor of HDMI / DisplayPort",
                ],
                ["Built-in Audio Analog Stereo", "HDMI / DisplayPort", "USB Speaker"],
                "linux",
            )
            assert group_at(rows, _SYS_GROUP_LOOPBACK) == [
                "1: Built-in Audio Analog Stereo  — records this output, matched “monitor of”",
                "2: HDMI / DisplayPort  — records this output, matched “monitor of”",
            ], rows
            assert group_at(rows, _SYS_GROUP_OTHER) == ["0: Built-in Microphone"]
            # "Monitor of ..." is a source name, not what the user calls the
            # device — the primary label is the output, the mechanism is the
            # secondary half of the row.
            assert not any(
                text.split(":", 1)[1].strip().startswith("Monitor of")
                for text in group_at(rows, _SYS_GROUP_LOOPBACK)
            ), rows
            # The pick from shape 2 is gone from this machine: it stays as a
            # parseable row of its own under its own heading, because PortAudio
            # indices are positional and falling back to "Automatic" would drop
            # the choice on the next Save.
            assert window._selected_system_device() == 3, texts(rows)
            assert "3: (not available right now)" in texts(rows), texts(rows)
            absent = texts(rows).index(_SYS_GROUP_ABSENT)
            assert texts(rows)[absent + 1] == "3: (not available right now)"
        finally:
            window.deleteLater()
            app.processEvents()

    # A Save from a window whose Audio page was never opened writes back the
    # stored index: until the first visit the dropdown holds only the
    # placeholder, and answering from it would drop the user's device.
    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        stub.cfg["system_audio"]["device"] = 7
        window = SettingsWindow(stub)
        try:
            assert window._sys_devices_loaded is False
            assert window._collect()["system_audio"]["device"] == 7
            # …and it is still 7 after the visit that fills the dropdown from a
            # machine where index 7 does not exist.
            rows = _system_audio_rows(window)
            _load_faked_system_devices(window, ["Built-in Microphone"], ["Speakers"], "win32")
            assert window._collect()["system_audio"]["device"] == 7
            assert "7: (not available right now)" == window.sys_device_combo.currentText()
        finally:
            window.deleteLater()
            app.processEvents()


def _system_audio_hint_names_the_outputs_it_cannot_record():
    """The sentence the report was actually missing (#195): the card names the
    outputs this machine has, says that none of them can be recorded directly,
    and gives the platform's fix — in the order the user acts in.

    A dropdown that can only ever offer input devices is not wrong, but on its
    own it is unusable: someone looking for "Speakers (Realtek)" has to read
    that their outputs exist, that this build cannot record them, what to do
    about it, and that pressing Refresh afterwards is the last step. The fix
    itself comes from `system_audio.system_audio_help()` and is asserted to be
    embedded verbatim — one wording in one place, because the notification
    that refuses a take carries the same one and two drifting copies are how a
    user follows the one that no longer matches their system.

    Bounded, too: a machine with fifteen outputs must grow the hint by a count,
    not by twelve device names.
    """
    from listen_to_me.settings_ui import (
        _SYS_OUTPUTS_NAMED,
        SettingsWindow,
        _output_list_phrase,
        _outputs_without_loopback,
    )
    from listen_to_me.theme import apply_theme

    # Which outputs are named: the ones no candidate resolves to. A candidate
    # that maps to no output at all ("Stereo Mix") covers nothing — it may
    # carry the output the user wants, but nothing in its name says which.
    monitor = {"name": "Monitor of Built-in Audio Analog Stereo", "hint": "monitor of"}
    stereo_mix = {"name": "Stereo Mix (Realtek(R) Audio)", "hint": "stereo mix"}
    outputs = ["Built-in Audio Analog Stereo", "HDMI / DisplayPort"]
    assert _outputs_without_loopback(outputs, [monitor]) == ["HDMI / DisplayPort"]
    assert _outputs_without_loopback(outputs, [stereo_mix]) == outputs
    assert _outputs_without_loopback(outputs, []) == outputs
    assert _outputs_without_loopback([], [monitor]) == []
    # Windows' MME host API truncates device names to 31 characters, so the
    # output entry and its loopback twin agree only on a prefix.
    truncated = {"name": "Speakers (High Definition Audi [Loopback]", "hint": "[loopback]"}
    assert _outputs_without_loopback(["Speakers (High Definition Audio Device)"], [truncated]) == []
    # …but a prefix of three characters is not a pairing, it is a collision.
    assert _outputs_without_loopback(["USB"], [{"name": "USB Speaker [Loopback]",
                                                "hint": "[loopback]"}]) == ["USB"]

    # An empty list is a landmine, not an impossibility: `quoted[-1]` raised
    # IndexError. Its only caller is guarded by `if missing:` today, which is
    # exactly why the guard belongs in the function — the next caller reads the
    # signature, and nothing in it says the list may not be empty.
    assert _output_list_phrase([]) == ""
    assert _output_list_phrase([], limit=0) == ""
    assert _output_list_phrase(["A"]) == "“A”"
    assert _output_list_phrase(["A", "B"]) == "“A” and “B”"
    assert _output_list_phrase(["A", "B", "C"]) == "“A”, “B” and “C”"
    assert _SYS_OUTPUTS_NAMED == 3  # the wording above is bounded by this
    assert _output_list_phrase(["A", "B", "C", "D", "E"]) == "“A”, “B”, “C” and 2 more"

    app = _ensure_qapp()
    apply_theme(app)
    many = [f"Output {n}" for n in range(1, 16)]

    with tempfile.TemporaryDirectory() as tmp:
        window = SettingsWindow(_StubApp(Path(tmp)))
        try:
            # --- shape 1: Windows, no candidate — the reported case ---------
            help_text = _load_faked_system_devices(
                window,
                ["Microphone (Realtek(R) Audio)"],
                ["Speakers (Realtek(R) Audio)", "Jabra SPEAK 410 USB"],
                "win32",
            )
            assert "Stereo Mix" in help_text, help_text  # the platform took effect
            hint = window._sys_audio_hint.text()
            assert window._sys_candidates == 0
            assert "⚠ No loopback device was found" in hint, hint
            assert (
                "Your outputs are “Speakers (Realtek(R) Audio)” and “Jabra SPEAK 410 USB” "
                "— none of them can be recorded directly on this build." in hint
            ), hint
            assert help_text in hint, hint
            # The order the user acts in: what is missing, then how to get it,
            # then the Refresh that picks it up without a restart.
            assert hint.index("Your outputs are") < hint.index(help_text) < hint.index(
                "Then press “Refresh”"
            ), hint
            assert "no restart needed" in hint, hint

            # --- shape 2: every output twinned (#194) — nothing to complain --
            help_text = _load_faked_system_devices(
                window,
                [
                    "Microphone (Realtek(R) Audio)",
                    "Speakers (Realtek(R) Audio) [Loopback]",
                    "Jabra SPEAK 410 USB [Loopback]",
                ],
                ["Speakers (Realtek(R) Audio)", "Jabra SPEAK 410 USB"],
                "win32",
            )
            hint = window._sys_audio_hint.text()
            assert window._sys_candidates == 2
            assert "⚠" not in hint, hint
            assert "Your outputs are" not in hint and "cannot be recorded" not in hint, hint
            assert "Then press “Refresh”" not in hint, hint
            # The platform's fix stays on screen even so: picking the monitor
            # that belongs to the output actually in use is the part users get
            # wrong.
            assert help_text in hint, hint

            # --- shape 3: Linux monitors, one output without one ------------
            help_text = _load_faked_system_devices(
                window,
                ["Built-in Microphone", "Monitor of Built-in Audio Analog Stereo"],
                ["Built-in Audio Analog Stereo", "USB Speaker"],
                "linux",
            )
            hint = window._sys_audio_hint.text()
            assert "Monitor of" in help_text and "PipeWire" in help_text, help_text
            assert window._sys_candidates == 1
            assert "⚠" not in hint, hint
            # Named, and in the singular: there is a loopback device, just not
            # for this output.
            assert (
                "No loopback device was found for “USB Speaker” — that output cannot "
                "be recorded directly on this build." in hint
            ), hint
            assert help_text in hint, hint

            # --- shape 4: one soundcard, four host APIs (the filter) --------
            # PortAudio lists every endpoint once per host API, plus two
            # pseudo-devices. Unfiltered, this machine's hint read “No loopback
            # device was found for “Microsoft Sound Mapper - Output”, “Primary
            # Sound Driver” and “Speakers (Realtek HD Audio output)”” — while
            # #194 was working perfectly. Two of those the user does not have;
            # the third is the same speaker under WDM-KS.
            help_text = _load_real_system_devices(
                window, _windows_devices(twin=True), _WINDOWS_HOSTAPIS
            )
            hint = window._sys_audio_hint.text()
            assert window._sys_candidates == 1, window._sys_candidates
            assert window._sys_missing_outputs == [], window._sys_missing_outputs
            assert "cannot be recorded" not in hint and "Your outputs are" not in hint, hint
            for phantom in _WINDOWS_PHANTOMS:
                assert phantom not in hint, (phantom, hint)
            assert help_text in hint, hint

            # …and with no twin, the reported machine: ONE output named, the
            # one that exists, not six entries for one speaker.
            help_text = _load_real_system_devices(
                window, _windows_devices(twin=False), _WINDOWS_HOSTAPIS
            )
            hint = window._sys_audio_hint.text()
            assert window._sys_candidates == 0
            assert window._sys_missing_outputs == [_ONE_SPEAKER], window._sys_missing_outputs
            assert (
                f"Your outputs are “{_ONE_SPEAKER}” — none of them can be recorded "
                "directly on this build." in hint
            ), hint
            for phantom in _WINDOWS_PHANTOMS:
                assert phantom not in hint, (phantom, hint)
            assert "and 3 more" not in hint, hint  # the bound spent on duplicates

            # --- bounded: three outputs vs fifteen of the same names --------
            _load_faked_system_devices(window, ["Microphone"], many[:3], "win32")
            few_hint = window._sys_audio_hint.text()
            _load_faked_system_devices(window, ["Microphone"], many, "win32")
            many_hint = window._sys_audio_hint.text()
            assert "“Output 1”, “Output 2”, “Output 3” and 12 more" in many_hint, many_hint
            assert "Output 15" not in many_hint, many_hint
            # Twelve more devices, at most a handful of characters more text.
            assert len(many_hint) - len(few_hint) <= 20, (len(few_hint), len(many_hint))
        finally:
            window.deleteLater()
            app.processEvents()


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

        # The microphone list is enumerated on the first visit to the Audio
        # page, not during construction (PortAudio can stall for hundreds of
        # ms before anything is on screen). Until then the dropdown holds only
        # the placeholder, so the *config* has to answer for it — reading the
        # placeholder would make Save drop the stored microphone.
        assert window._devices_loaded is False
        window.cfg["input_device"] = 3
        assert window._selected_input_device() == 3
        window.cfg["input_device"] = None
        window._show_page("Audio")
        app.processEvents()
        assert window._devices_loaded is True
        window._show_page("Home")

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

        # The take clock the tray and the floating icon carry, on the hero as
        # well: the biggest recording control the app has kept a frozen
        # "Recording" for the whole take. Same format_duration as the other two
        # surfaces, so one second cannot render three ways.
        assert window.home.state_label.text() == "Recording — speak now"
        window.set_app_elapsed(72)
        assert window.home.state_label.text() == "Recording 1:12 — speak now"
        # A value that isn't a clock reads 0:00 rather than raising inside
        # App's poll timer; None means "no tick yet" and keeps the wording the
        # headline had before the first one.
        window.set_app_elapsed(-3)
        assert window.home.state_label.text() == "Recording 0:00 — speak now"
        window.set_app_elapsed(None)
        assert window.home.state_label.text() == "Recording — speak now"
        window.set_app_elapsed(72)

        window.set_app_state("processing")
        assert not window.home.record_button.isEnabled()
        # A tick that lands just after the take ended must not re-label the
        # hero with a stopped counter.
        window.set_app_elapsed(99)
        assert window.home.state_label.text() == "Transcribing…"
        window.set_app_state("idle")
        assert window.home.record_button.isEnabled()
        assert window.home.cancel_button.isHidden()
        window.set_app_elapsed(99)
        assert window.home.state_label.text() == "Ready to dictate"
        # The next take starts from the wording without a clock again.
        window.set_app_state("recording")
        assert window.home.state_label.text() == "Recording — speak now"
        window.set_app_state("idle")

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
        from listen_to_me.settings_ui import (
            _A_TEST_IDLE,
            _A_TEST_LABEL,
            _A_TESTING_LABEL,
        )

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
            (
                lambda: window._on_assistant_tested(
                    window._assistant_gen, "This is a test of the assistant."
                ),
                "test of the assistant",
            ),
            (
                lambda: window._on_assistant_test_failed(
                    window._assistant_gen, "Connection refused"
                ),
                "Connection refused",
            ),
        ):
            window._assistant_busy = True
            window.a_test_button.setEnabled(False)
            window.a_test_button.setText(_A_TESTING_LABEL)
            window.a_test_cancel_button.setEnabled(True)
            drive()
            assert not window._assistant_busy
            assert window.a_test_button.isEnabled()
            assert window.a_test_button.text() == _A_TEST_LABEL
            assert not window.a_test_cancel_button.isEnabled()
            assert expected in window.a_test_status.text(), window.a_test_status.text()

        # Cancel detaches the waiting worker rather than aborting it: the
        # request is blocked in a single HTTP call with a timeout of up to
        # 600 s behind it, so the answer still arrives — against a generation
        # that has moved on. It must not overwrite what the user is now
        # reading, and the button must come back either way. Without the
        # generation guard the stale reply would land in the status line
        # minutes after the test was called off.
        window._assistant_busy = True
        window.a_test_button.setEnabled(False)
        window.a_test_button.setText(_A_TESTING_LABEL)
        window.a_test_cancel_button.setEnabled(True)
        stale = window._assistant_gen
        window._cancel_assistant_test()
        assert not window._assistant_busy
        assert window.a_test_button.isEnabled()
        assert not window.a_test_cancel_button.isEnabled()
        assert "cancelled" in window.a_test_status.text().lower(), window.a_test_status.text()
        window._on_assistant_tested(stale, "a late answer nobody is waiting for")
        assert "late answer" not in window.a_test_status.text(), window.a_test_status.text()
        window._on_assistant_test_failed(stale, "a late failure nobody is waiting for")
        assert "late failure" not in window.a_test_status.text(), window.a_test_status.text()

        # Cancel with nothing running is a no-op, not a status line claiming a
        # test was called off (the window-close path calls it unconditionally).
        window.a_test_status.setText(_A_TEST_IDLE)
        window._cancel_assistant_test()
        assert window.a_test_status.text() == _A_TEST_IDLE, window.a_test_status.text()

        # "Reset to default…" asks before discarding an edited system prompt.
        # It is free text with no second copy anywhere, setPlainText drops the
        # undo history with it, and the button sits directly above the box it
        # overwrites. An unedited prompt has nothing to lose and resets at once
        # — which is what keeps the flash-only behaviour it was built for.
        from listen_to_me import settings_ui as _settings_module
        from listen_to_me.config import DEFAULT_ASSISTANT_PROMPT as _DEFAULT_PROMPT
        from listen_to_me.settings_ui import _A_PROMPT_RESET_LABEL
        from PySide6.QtWidgets import QMessageBox as _RealPromptBox

        assert _A_PROMPT_RESET_LABEL.endswith("…"), (
            "the label must promise the confirmation it now performs"
        )

        class _FakePromptBox:
            StandardButton = _RealPromptBox.StandardButton
            answer = _RealPromptBox.StandardButton.No
            asked = 0

            @classmethod
            def question(cls, *_args, **_kwargs):
                cls.asked += 1
                return cls.answer

        real_prompt_box = _settings_module.QMessageBox
        _settings_module.QMessageBox = _FakePromptBox
        prompt_before = window.a_prompt_edit.toPlainText()
        try:
            window.a_prompt_edit.setPlainText("Only ever answer in rhyming couplets.")
            window._reset_prompt()  # declined
            assert _FakePromptBox.asked == 1
            assert "rhyming" in window.a_prompt_edit.toPlainText(), (
                "a declined reset threw the edited prompt away anyway"
            )
            _FakePromptBox.answer = _RealPromptBox.StandardButton.Yes
            window._reset_prompt()  # confirmed
            assert _FakePromptBox.asked == 2
            assert window.a_prompt_edit.toPlainText() == _DEFAULT_PROMPT
            # Already the default: no question, still resets and flashes.
            window._reset_prompt()
            assert _FakePromptBox.asked == 2, "asked about a reset with nothing to lose"
            assert window.a_prompt_edit.toPlainText() == _DEFAULT_PROMPT
        finally:
            # Hand the page back as it was found: a later check compares
            # _collect() against the saved snapshot, and a prompt left
            # rewritten here would surface there as an unrelated failure.
            window.a_prompt_edit.setPlainText(prompt_before)
            _settings_module.QMessageBox = real_prompt_box

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
        # "matches", not "contains": a term can now match the row's date as
        # well as its text, so the empty state must not promise otherwise.
        assert "No transcript matches" in _history_text()
        assert window.history_clear_button.isEnabled()  # entries exist, only hidden
        # "Export…" writes what is listed and "Copy all" copies it, so a
        # filtered-to-empty list has nothing to hand out — an enabled Export
        # would produce an empty file, an enabled Copy all a silent no-op.
        assert not window.history_export_button.isEnabled()
        assert not window.history_copy_all_button.isEnabled()
        window.history_filter_edit.clear()
        window._refresh_history()
        assert "2 transcripts" in window.history_count_label.text()
        assert "A stored transcript" in _history_text()
        assert window.history_export_button.isEnabled()
        assert window.history_copy_all_button.isEnabled()
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
            assert not window.history_copy_all_button.isEnabled()
            assert "No transcripts yet" in _history_text()

            # The Home page renders the same store, and used to promise "your
            # dictations will show up here" whatever the reason it was empty —
            # including the one where nothing will ever be stored again.
            def _home_recent_text() -> str:
                return " ".join(
                    label.text()
                    for label in window.home._recent_frame.findChildren(QLabel)
                )

            window.home._refresh_recent()
            assert "No transcripts yet" in _home_recent_text()
            stub.cfg["history_enabled"] = False
            try:
                window.home._refresh_recent()
                assert "History is off" in _home_recent_text()
            finally:
                stub.cfg["history_enabled"] = True
            # A store that could not be read must not read as an empty one.
            assert "Could not read" in window.home._empty_recent_text(True)
        finally:
            stub.history = stored_history
            window._refresh_history()
            window.home._refresh_recent()
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
        # Same for the live-typing box on the General page, which used to
        # explain itself in the tooltip only.
        assert not window._live_typing_hint.isHidden()
        assert "Parakeet" in window._live_typing_hint.text(), window._live_typing_hint.text()
        window.backend_combo.setCurrentIndex(0)  # back to faster-whisper
        assert window.language_combo.isEnabled() and window.initial_prompt_edit.isEnabled()
        assert window.model_combo.isEnabled() and window.chk_live_typing.isEnabled()
        assert "Parakeet" not in window._speech_hint.text()
        assert window._live_typing_hint.isHidden()

        # The Text replacements field reports what its rules actually do, live
        # while they are typed. An untouched field stays silent, a working rule
        # is counted, and a mistyped one is named instead of being dropped into
        # the log file only — which is the whole point of the line.
        window.replacements_edit.setPlainText("")
        assert window.replacements_status.isHidden()
        window.replacements_edit.setPlainText("posgres => PostgreSQL")
        assert not window.replacements_status.isHidden()
        assert window.replacements_status.text() == "1 rule active."
        window.replacements_edit.setPlainText("posgres => PostgreSQL\ncuber netes -> Kubernetes")
        status = window.replacements_status.text()
        assert "1 rule active" in status and "line 2 has no “=>”" in status, status
        # Announced with the field, not only as a label beside it.
        assert window.replacements_edit.accessibleDescription() == status
        window.replacements_edit.setPlainText("")

        # Live typing + hold mode + a modifier chord (or a bare character key):
        # App skips live typing for such a take with nothing but a log line.
        # The General page says so under the box while the combination is
        # entered, and Save refuses it the way it refuses an invalid hotkey.
        # The real parser imports pynput, which the light run must not (no X
        # display on the CI runner), so Hotkeys is stood in for with the
        # verdicts _hotkey_default_valid checks against the real one.
        from listen_to_me import settings_ui as _settings_module

        class _FakeHotkeys:
            flags = {
                "<ctrl>+<alt>+<space>": (True, True),
                "<f9>": (False, False),
                "a": (False, True),
            }

            @classmethod
            def validate(cls, combo):
                return combo in cls.flags

            @classmethod
            def combo_flags(cls, combo):
                return cls.flags.get(combo, (True, True))

            @staticmethod
            def equal(combo_a, combo_b):
                return combo_a == combo_b

        class _FakeCriticalBox:
            StandardButton = _settings_module.QMessageBox.StandardButton
            shown: list = []

            @classmethod
            def critical(cls, *args, **_kwargs):
                cls.shown.append(args[-1])

        real_hotkeys, real_box = _settings_module.Hotkeys, _settings_module.QMessageBox
        _settings_module.Hotkeys, _settings_module.QMessageBox = _FakeHotkeys, _FakeCriticalBox
        saved_hotkey = window.hotkey_edit.text()
        try:
            problem = window._live_typing_problem
            assert problem("<ctrl>+<alt>+<space>", "toggle") is None
            assert problem("<ctrl>+<alt>+<space>", "hold") is not None
            assert problem("<f9>", "hold") is None
            assert problem("a", "toggle") is not None
            assert problem("not a hotkey", "hold") is None  # the hotkey check owns that error
            window.chk_live_typing.setChecked(True)
            window.rb_hold.setChecked(True)
            assert not window._live_typing_hint.isHidden()
            assert "modifier" in window._live_typing_hint.text(), window._live_typing_hint.text()
            values = window._collect()
            assert values["live_typing"] and values["hotkey_mode"] == "hold"
            assert window._validate(values) is False
            assert _FakeCriticalBox.shown and "modifier" in _FakeCriticalBox.shown[0]
            window.hotkey_edit.setText("<f9>")  # modifier-free: allowed again
            assert window._live_typing_hint.isHidden()
            assert window._validate(window._collect()) is True
            window.hotkey_edit.setText(saved_hotkey)
            window.rb_toggle.setChecked(True)
            window.chk_live_typing.setChecked(False)
        finally:
            _settings_module.Hotkeys, _settings_module.QMessageBox = real_hotkeys, real_box
            window.hotkey_edit.setText(saved_hotkey)
            window.rb_toggle.setChecked(True)
            window.chk_live_typing.setChecked(False)
        assert window._live_typing_hint.isHidden()

        # A live OS light/dark switch repaints the code-drawn icons (the palette
        # and QSS are theme.py's job): they used to keep the colours they were
        # built with until the window was reopened.
        quick_button, _quick_glyph = window.home._glyph_buttons[0]
        themed = quick_button.icon().pixmap(20, 20).toImage()
        window.home.restyle_icons("#ff0000", "#00ff00")
        assert quick_button.icon().pixmap(20, 20).toImage() != themed
        window._on_color_scheme_changed()
        assert not quick_button.icon().isNull()
        assert not window.nav.item(window._nav_row["Engine"]).icon().isNull()
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
        # A blank row has nothing to lose and goes without a question — which
        # is also why the line above can call this unpatched: a modal box here
        # would hang this run.
        window._remove_target_row(row)
        assert row not in window._target_rows

        # A configured row is asked about first. It carries the app's mute
        # keybind, normally looked up in that app's own settings, and there is
        # no undo once Save writes the shortened list.
        from PySide6.QtWidgets import QMessageBox as _RealRemoveBox

        class _FakeRemoveBox:
            StandardButton = _RealRemoveBox.StandardButton
            answer = _RealRemoveBox.StandardButton.No
            asked: list = []

            @classmethod
            def question(cls, *args, **_kwargs):
                cls.asked.append(args[2])  # (parent, title, text, buttons, default)
                return cls.answer

        real_remove_box = _settings_module.QMessageBox
        _settings_module.QMessageBox = _FakeRemoveBox
        try:
            window._add_target_row(
                {"name": "Discord", "enabled": True, "mode": "hold", "hotkey": "<ctrl>+<alt>+m"}
            )
            configured = window._target_rows[-1]
            assert configured.remove_button.text().endswith("…"), (
                "the label must promise the confirmation it now performs"
            )
            window._remove_target_row(configured)  # declined
            assert configured in window._target_rows, "a declined Remove dropped the row"
            assert _FakeRemoveBox.asked and "Discord" in _FakeRemoveBox.asked[-1], (
                _FakeRemoveBox.asked
            )
            _FakeRemoveBox.answer = _RealRemoveBox.StandardButton.Yes
            window._remove_target_row(configured)  # confirmed
            assert configured not in window._target_rows

            # A keybind hotkey_label() cannot parse renders as nothing, so the
            # question must name the app alone rather than trailing an empty
            # pair of brackets.
            window._add_target_row(
                {"name": "", "enabled": True, "mode": "hold", "hotkey": "not-a-combo"}
            )
            unparseable = window._target_rows[-1]
            window._remove_target_row(unparseable)
            assert "()" not in _FakeRemoveBox.asked[-1], _FakeRemoveBox.asked[-1]
            assert unparseable not in window._target_rows
        finally:
            _settings_module.QMessageBox = real_remove_box

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
        # effects stay suppressed: the Engine hardware probe would race the
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
        assert window.stack.currentIndex() == window._engine_index

        # A window taller than its screen is brought back inside it, minimum
        # included — a 1366x768 laptop at 125 % scaling offers 614 logical
        # pixels of height, which puts the Save/Cancel row under the taskbar.
        # Height only: the pages sit in scroll areas, so a short window costs a
        # scroll, while a narrow one clips the forms (asserted just above).
        avail_h = window.screen().availableGeometry().height()
        window.setMinimumSize(window.minimumWidth(), avail_h + 200)
        window.resize(window.width(), avail_h + 200)
        window._screen_clamped = False
        window._clamp_to_screen()
        app.processEvents()
        assert window.minimumHeight() <= avail_h, window.minimumHeight()
        assert window.height() <= avail_h, window.height()
        window.setMinimumSize(840, 600)

        window._show_page("General")
        window.hide()

        # Status-card formatters: every probe shape renders a clear verdict.
        fmt_cuda = window._format_cuda_status
        assert fmt_cuda({"available": True, "count": 1, "error": None}).startswith("✓")
        assert fmt_cuda({"available": False, "count": 0, "error": None}).startswith("✗")
        assert fmt_cuda({"available": False, "count": 0, "error": "no ctranslate2"}).startswith("✗")
        # The verdict names the backend it is about — "faster-whisper can use
        # it" under a Parakeet setup read as if the selected engine could not.
        gpu = {"available": True, "count": 1, "error": None}
        assert "the faster-whisper backend" in fmt_cuda(gpu)
        assert "the Parakeet backend" in fmt_cuda(gpu, "parakeet")
        assert "Parakeet" in fmt_cuda({"available": False, "count": 0, "error": None}, "parakeet")
        assert "OpenVINO" in fmt_cuda(gpu, "openvino")
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
            "backend": "faster-whisper",
        }
        window._on_hw_done(1, probe)  # stale → dropped
        assert window.hw_cuda_label.text() == "Not checked yet."
        window._on_hw_done(2, probe)
        assert window.hw_cuda_label.text().startswith("✗") and not window._hw_busy

        # "Running on": the device + precision the loaded model really uses,
        # read off the app's transcriber on the main thread — nothing to show
        # before the first load, afterwards the resolved pair, flagged when the
        # config left the choice to "auto" (the question the line answers).
        assert "nothing loaded yet" in window.hw_runtime_label.text()
        stub.transcriber.runtime = ("cpu", "int8")
        window._refresh_runtime_status()
        running = window.hw_runtime_label.text()
        assert running == "CPU · int8 (auto)", running
        stub.cfg.data["device"], stub.cfg.data["compute_type"] = "cpu", "int8"
        window._refresh_runtime_status()
        assert window.hw_runtime_label.text() == "CPU · int8", window.hw_runtime_label.text()
        stub.cfg.data["device"], stub.cfg.data["compute_type"] = "auto", "auto"
        stub.transcriber.runtime = None
        window._refresh_runtime_status()
        assert "nothing loaded yet" in window.hw_runtime_label.text()
        fmt_runtime = window._format_runtime_status
        assert fmt_runtime(("GPU", "int8"), ("auto", "int8")) == "GPU · int8 (auto)"
        assert fmt_runtime(("cuda", "float16"), ("cuda", "float16")) == "CUDA · float16"
        assert "engine" in fmt_runtime(("auto", "default"), ("auto", "auto"))

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
            "running on": window.hw_runtime_label,
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


def _no_speech_report_names_its_own_source():
    """A take that produced no text names the device that delivered nothing
    (#191) — and the microphone wording stays what the rest of the app
    documents, character for character.

    A system-audio take whose loopback device carried digital silence used to
    read "No sound reached the microphone — check the input device … and
    whether the microphone is muted": that sends the user to a device, and a
    setting, that is working perfectly, while the fixes for this source are
    different ones (nothing was playing, the wrong monitor is selected, Stereo
    Mix is enabled but not routed). Same class of bug as the wording
    `stream_died` and `auto_stop` already fixed.

    The sentence being right is only half of it, so `App._notify_no_speech` is
    borrowed unbound onto a stub as well: the source has to reach the wording
    from the take, and the verdict the caller already computed has to be the
    one it reports.

    Whether the message is *forced* is part of that job: a take whose clip
    carried no signal names a device problem that is fixed in seconds once
    something says so, so it is forced past the notification settings — and the
    verdicts it forces for are the filler filter's own `_NO_SIGNAL_VERDICTS`,
    read from the module rather than kept as a second copy of the same two
    strings."""
    from listen_to_me import app as app_module
    from listen_to_me import diagnostics as diagnostics_module
    from listen_to_me.app import App
    from listen_to_me.choices import SOURCE_MIC, SOURCE_SYSTEM
    from listen_to_me.diagnostics import no_speech_message
    from listen_to_me.system_audio import system_audio_help

    # The microphone wording, written out rather than probed: it is the
    # sentence README.md and the Help page describe, and a diagnosis that
    # drifts is one the documentation no longer matches.
    mic_silent = (
        "No sound reached the microphone — check the input device under "
        "Settings → Audio and whether the microphone is muted."
    )
    mic_quiet = (
        "The microphone signal was too quiet to recognize anything — move "
        "closer to it or raise its input volume (Settings → Audio)."
    )
    assert no_speech_message("silent") == mic_silent
    assert no_speech_message("quiet") == mic_quiet
    assert no_speech_message("silent", source=SOURCE_MIC) == mic_silent
    assert no_speech_message("quiet", source=SOURCE_MIC) == mic_quiet

    # The second source gets its own two, and neither may send the user to a
    # microphone setting.
    sys_silent = no_speech_message("silent", source=SOURCE_SYSTEM)
    sys_quiet = no_speech_message("quiet", source=SOURCE_SYSTEM)
    for message in (sys_silent, sys_quiet):
        assert "microphone" not in message.lower(), message
        assert "system audio" in message.lower(), message
        assert "Settings → Audio" in message, message
    assert sys_silent != sys_quiet
    # …and the silent one carries the platform's own "how to get a loopback
    # device" sentence, from the single place that wording lives.
    assert system_audio_help() in sys_silent, sys_silent

    # A verdict the classifier could not produce falls back to the generic
    # sentence for both sources: a diagnosis is the one thing this must never
    # invent.
    generic = "No speech detected."
    for verdict in ("ok", "unknown", "", "Silent", "QUIET", None):
        for source in (SOURCE_MIC, SOURCE_SYSTEM):
            assert no_speech_message(verdict, source=source) == generic, (verdict, source)
    # An unregistered source reads as the microphone, like every other message
    # about a take (choices.known_source logs it on the way through).
    for unknown in ("loopback", "", None, 3):
        assert no_speech_message("silent", source=unknown) == mic_silent, repr(unknown)

    class _Recorder:
        stream_format = "48000 Hz, 2 ch, float32"
        resampling = True
        dropped_buffers = 0

    class _App:
        # Borrowed unbound: a real App needs a tray, a recorder and a
        # transcriber, while this path reads three attributes off one.
        _notify_no_speech = App._notify_no_speech

        def __init__(self):
            self.recorder = _Recorder()
            self.notified: list[tuple[str, bool]] = []

        def notify(self, message, force=False):
            self.notified.append((message, force))

    driven = {"verdict": "silent"}
    real_stats = diagnostics_module.clip_stats
    diagnostics_module.clip_stats = lambda clip: {
        "peak": 0.0, "rms": 0.0, "seconds": 1.0, "verdict": driven["verdict"],
    }
    try:
        # The take's source decides the wording …
        app = _App()
        app._notify_no_speech([], SOURCE_SYSTEM, "silent")
        assert app.notified == [(sys_silent, True)], app.notified
        app = _App()
        app._notify_no_speech([], SOURCE_MIC, "quiet")
        assert app.notified == [(mic_quiet, True)], app.notified
        # … and the microphone is the default, which is what every caller that
        # predates the second source relies on.
        app = _App()
        app._notify_no_speech([], verdict="silent")
        assert app.notified == [(mic_silent, True)], app.notified
        # A caller that computed no verdict leaves it best-effort here: the
        # statistics decide the wording, and failing to compute them costs the
        # diagnosis, never the message.
        driven["verdict"] = "quiet"
        app = _App()
        app._notify_no_speech([], SOURCE_SYSTEM)
        assert app.notified == [(sys_quiet, True)], app.notified
        # Forced only for the verdicts that name a fixable device problem —
        # "no speech" itself stays an ordinary notification.
        for quiet_verdict in ("ok", "unknown"):
            assert quiet_verdict not in app_module._NO_SIGNAL_VERDICTS, quiet_verdict
            app = _App()
            app._notify_no_speech([], SOURCE_MIC, quiet_verdict)
            assert app.notified == [(generic, False)], app.notified
        # …and every verdict that *is* one of them is forced, with the wording
        # diagnostics gives that verdict.
        for verdict in app_module._NO_SIGNAL_VERDICTS:
            app = _App()
            app._notify_no_speech([], SOURCE_MIC, verdict)
            expected = (no_speech_message(verdict, source=SOURCE_MIC), True)
            assert app.notified == [expected], (verdict, app.notified)
        # The set it reads is the filler filter's gate, not a second literal
        # holding the same two strings: driven through the module constant, so
        # a check that would pass just as well with two copies goes red here.
        # A verdict added to the tuple therefore cannot leave the notification
        # disagreeing with the transcript that was dropped for it.
        real_verdicts = app_module._NO_SIGNAL_VERDICTS
        try:
            app_module._NO_SIGNAL_VERDICTS = ("quiet", "muted")
            for forced in ("quiet", "muted"):
                app = _App()
                app._notify_no_speech([], SOURCE_MIC, forced)
                assert app.notified[-1][1] is True, (forced, app.notified)
            # The other half of the rule stays where it is: the *wording* is
            # diagnostics.no_speech_message's own membership test, so a verdict
            # this app has learned and that module has not reads as the generic
            # sentence — forced, but generic (the comment at the call site says
            # so, and this is the behaviour it warns about).
            assert app.notified == [(generic, True)], app.notified
            # "silent" is no longer in the tuple, so it is no longer forced.
            app = _App()
            app._notify_no_speech([], SOURCE_MIC, "silent")
            assert app.notified == [(mic_silent, False)], app.notified
        finally:
            app_module._NO_SIGNAL_VERDICTS = real_verdicts
        # Dropped buffers are a third reason for an empty transcript and the
        # one the recorder can count: named where the user is already being
        # told the take came back empty, and only there.
        app = _App()
        app.recorder.dropped_buffers = 4
        app._notify_no_speech([], SOURCE_MIC, "ok")
        message, force = app.notified[-1]
        assert message.startswith(generic) and "4 audio buffers were dropped" in message
        assert "overloaded" in message and force is False
        # The stream format stays out of the notification: it is what somebody
        # debugs from the log file, and it says nothing to the user reading it.
        assert "48000" not in message and "float32" not in message
    finally:
        diagnostics_module.clip_stats = real_stats


def _an_unknown_source_is_logged_not_answered_silently():
    """A recording source the app does not know is answered *and* logged; the
    payload-free one is answered silently, on purpose (#191).

    `choices.known_source` is the registry the routing goes through:
    `app.event_source` picks the source an event belongs to, `app.hotkey_mode`
    reads that source's own config section, `choices.source_label` names it.
    All three used to fall through to the microphone for anything they did not
    recognize. For a payload-free `post("toggle")` that is the right answer —
    the tray, the floating icon and the Home button have always posted one and
    it means the microphone — but it was also the answer for a source that
    exists and is simply not listed: a third source would be recorded from the
    wrong device, read from the wrong config section and called "microphone"
    in every notification, with no exception and no log line anywhere.

    So the fall-through stays (a hotkey press has to start something, and a
    take that is really running has to be described somehow) and it is pinned
    here so nobody "fixes" it into a refusal — while a value that *names*
    something unregistered is logged once, which is what keeps the guess from
    being invisible."""
    import logging

    from listen_to_me import app as app_module
    from listen_to_me import choices as choices_module
    from listen_to_me.app import _HOTKEY_SECTIONS, event_source, hotkey_mode
    from listen_to_me.choices import (
        SOURCE_MIC,
        SOURCE_SYSTEM,
        SOURCES,
        known_source,
        source_label,
    )

    # Every registered source resolves to itself, to a label of its own and to
    # a hotkey section of its own. A source missing from either table is the
    # silent wrong answer both registries exist to stop: it would be named
    # after the microphone, and routed by the microphone's mode — which is how
    # a hold-mode take ends up waiting for a release event nobody posts.
    assert SOURCES == (SOURCE_MIC, SOURCE_SYSTEM), SOURCES
    assert set(_HOTKEY_SECTIONS) == set(SOURCES), _HOTKEY_SECTIONS
    assert _HOTKEY_SECTIONS[SOURCE_MIC] is None  # the top level, where it always was
    assert _HOTKEY_SECTIONS[SOURCE_SYSTEM] == "system_audio"
    labels = {source: source_label(source) for source in SOURCES}
    assert labels == {SOURCE_MIC: "microphone", SOURCE_SYSTEM: "system audio"}, labels
    assert len(set(labels.values())) == len(SOURCES), "two sources with one name"
    for source in SOURCES:
        assert known_source(source) == source
        assert event_source(source) == source
    cfg = {"hotkey_mode": "toggle", "system_audio": {"hotkey_mode": "hold"}}
    assert hotkey_mode(cfg, SOURCE_MIC) == "toggle"
    assert hotkey_mode(cfg, SOURCE_SYSTEM) == "hold"

    records: list[tuple[int, str]] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append((record.levelno, record.getMessage()))

    handler = _Capture()
    choices_module.log.addHandler(handler)
    app_module.log.addHandler(handler)
    # Module state: the values already named, so one of them is reported once
    # instead of on every notification about the take.
    already_logged = choices_module._UNKNOWN_SOURCES_LOGGED
    choices_module._UNKNOWN_SOURCES_LOGGED = set()
    try:
        # No source named at all — the documented, silent case. This is the
        # payload every surface but the system-audio listener posts.
        assert known_source(None) is None
        assert event_source(None) == SOURCE_MIC
        assert source_label(None) == "microphone"
        assert hotkey_mode(cfg, None) == "toggle"
        assert records == [], records

        # A value that names something unregistered: answered the same way,
        # never silently.
        for unknown in ("loopback", "sytem", "SYSTEM", 7, True, ""):
            records.clear()
            assert known_source(unknown) is None, repr(unknown)
            assert event_source(unknown) == SOURCE_MIC, repr(unknown)
            assert source_label(unknown) == "microphone", repr(unknown)
            assert hotkey_mode(cfg, unknown) == "toggle", repr(unknown)
            assert records, f"{unknown!r} was answered with nothing in the log"
            # Once per value, however many messages the take produces — this
            # runs on every notification, and a log nobody reads is as good as
            # no log at all.
            assert len(records) == 1, records
            level, message = records[0]
            assert level >= logging.WARNING, records
            assert repr(unknown) in message, (unknown, message)
            assert "microphone" in message, message
        # An unhashable payload cannot raise inside a notification path (the
        # registry is compared by ==, and the log is keyed by repr).
        records.clear()
        assert source_label(["mic"]) == "microphone"
        assert known_source({"source": "mic"}) is None
        assert len(records) == 2, records

        # A REGISTERED source with no hotkey section of its own is a wiring
        # mistake, not untrusted input — so it is loud, but it still answers:
        # reading the microphone's mode is wrong, and crashing the event drain
        # that calls this would be worse.
        records.clear()
        real_sections = app_module._HOTKEY_SECTIONS
        app_module._HOTKEY_SECTIONS = {SOURCE_MIC: None}
        try:
            assert hotkey_mode(cfg, SOURCE_SYSTEM) == "toggle"
        finally:
            app_module._HOTKEY_SECTIONS = real_sections
        assert records and any(level >= logging.ERROR for level, _m in records), records
        assert any(SOURCE_SYSTEM in message for _level, message in records), records
    finally:
        choices_module.log.removeHandler(handler)
        app_module.log.removeHandler(handler)
        choices_module._UNKNOWN_SOURCES_LOGGED = already_logged


def _only_a_microphone_take_mutes_other_apps():
    """The mute integration belongs to a dictation, and only to one (#191).

    Muting Discord for the duration of a take exists to keep a dictation out
    of a call. A system-audio take has no dictation to hide — it *is* recording
    that call — so activating there mutes the user in the meeting they just
    started recording, for up to the 900 s cap, with nothing on screen
    explaining it. It would also mis-fire twice over, because
    `integrations._hold_mode_hotkey` reads `cfg["hotkey_mode"]` /
    `cfg["hotkey"]`, always the MICROPHONE's: with mic=toggle and system=hold
    its guard sees no held chord and taps toggle keybinds through the
    physically held system-audio chord — the corruption that guard was written
    to prevent — while the reverse pair skips targets with a forced
    notification about a hotkey nobody is holding.

    The deactivation stays unconditional, and that is the second half of the
    rule: it is the cleanup path, it is a no-op when nothing was activated,
    and no cleanup path may be the thing that leaves a target app stuck muted.

    `App._set_state` is borrowed unbound onto a stub, as the `_handle` and
    `_process` checks do it — and the transitions it drives besides the
    integration are asserted with it, because `App.state` is the single source
    of truth and the tray, the overlay and the mute targets move together."""
    from listen_to_me.app import STATE_IDLE, STATE_PROCESSING, STATE_RECORDING, App
    from listen_to_me.choices import SOURCE_MIC, SOURCE_SYSTEM

    class _Integrations:
        def __init__(self):
            self.calls: list[str] = []
            self.fail = False

        def on_recording_start(self):
            self.calls.append("start")
            if self.fail:
                raise RuntimeError("the mute keybind worker died")

        def on_recording_stop(self):
            self.calls.append("stop")
            if self.fail:
                raise RuntimeError("the mute keybind worker died")

    class _Tray:
        def __init__(self):
            self.states: list[str] = []

        def set_state(self, state):
            self.states.append(state)

    class _Overlay:
        def __init__(self):
            self.states: list[str] = []

        def set_state(self, state):
            self.states.append(state)

    class _App:
        _set_state = App._set_state

        def __init__(self, source=SOURCE_MIC, state=STATE_IDLE):
            self.state = state
            if source is not None:
                self._source = source
            self.integrations = _Integrations()
            self.tray = _Tray()
            self.overlay = _Overlay()
            self._settings_window = None
            self.cleared = 0

        def _clear_progress(self):
            self.cleared += 1

    # A microphone take: muted for exactly the duration of the recording.
    take = _App(SOURCE_MIC)
    take._set_state(STATE_RECORDING)
    assert take.integrations.calls == ["start"], take.integrations.calls
    take._set_state(STATE_PROCESSING)
    assert take.integrations.calls == ["start", "stop"], take.integrations.calls
    # Every face of the state machine moved with it, and every transition ends
    # a download display that was running for the previous state.
    assert take.state == STATE_PROCESSING
    assert take.tray.states == [STATE_RECORDING, STATE_PROCESSING]
    assert take.overlay.states == take.tray.states
    assert take.cleared == 2

    # A system-audio take: nothing is muted at all …
    take = _App(SOURCE_SYSTEM)
    take._set_state(STATE_RECORDING)
    assert take.integrations.calls == [], take.integrations.calls
    assert take.tray.states == [STATE_RECORDING] and take.state == STATE_RECORDING

    # … and the cleanup still runs on every exit from RECORDING, for both
    # sources: finish, cancel, too-short and auto-stop all come through here,
    # and a no-op deactivation is cheaper than a target left muted.
    for source in (SOURCE_MIC, SOURCE_SYSTEM):
        for leaving in (STATE_PROCESSING, STATE_IDLE):
            take = _App(source, state=STATE_RECORDING)
            take._set_state(leaving)
            assert take.integrations.calls == ["stop"], (source, leaving, take.integrations.calls)

    # A second RECORDING transition is not a second activation (the mute would
    # be held one deeper than the recording that owns it).
    take = _App(SOURCE_MIC, state=STATE_RECORDING)
    take._set_state(STATE_RECORDING)
    assert take.integrations.calls == [], take.integrations.calls
    # …and a transition between two states that are not RECORDING touches
    # neither side.
    take = _App(SOURCE_MIC, state=STATE_PROCESSING)
    take._set_state(STATE_IDLE)
    assert take.integrations.calls == [], take.integrations.calls

    # A take with no source at all is the microphone: `_source` only exists
    # once a take has started, and `_take_source` defaults for exactly that.
    take = _App(None)
    take._set_state(STATE_RECORDING)
    assert take.integrations.calls == ["start"], take.integrations.calls

    # An integration that raises may not abort the transition — the state is
    # what the tray, the overlay and the next hotkey press all read, and a
    # mute helper failing must not leave the app between two states.
    for source, state, target in (
        (SOURCE_MIC, STATE_IDLE, STATE_RECORDING),
        (SOURCE_MIC, STATE_RECORDING, STATE_IDLE),
    ):
        take = _App(source, state=state)
        take.integrations.fail = True
        take._set_state(target)
        assert take.state == target and take.tray.states == [target]
        assert take.integrations.calls, "the integration was not even called"


def _the_parsers_bound_the_lines_they_walk():
    """Both hand-edited lists stop walking at a line ceiling — and say so.

    The entry caps cannot bound the work, and that is why there are two of
    them: a blank line, a `#` comment, a duplicate and a punctuation-only line
    are each skipped *before* the entry cap is consulted, so a pasted list of
    200 000 of them produced no entry at all, the cap never fired, and the
    whole file was walked after every dictation on the worker thread the user
    is waiting for — and again on every keystroke in the settings field, which
    re-parses with no debounce. The `issues` lists have their own cap for the
    same reason: they used to grow with the file, building strings nobody could
    ever see.

    The ceiling, never a timing: a wall-clock assertion would go red on a
    loaded CI runner for reasons that have nothing to do with this rule. And
    the status line has to name the truncation, because a prefix reported as
    the whole list is the same silent shortening in a different place."""
    from listen_to_me.app import _MAX_COLLECTED_ISSUES as _MAX_RULE_ISSUES
    from listen_to_me.app import (
        _MAX_REPLACEMENT_LINES,
        _MAX_REPLACEMENT_RULES,
        describe_replacements,
        parse_replacements,
    )
    from listen_to_me.fillers import _MAX_COLLECTED_ISSUES as _MAX_PHRASE_ISSUES
    from listen_to_me.fillers import (
        _MAX_FILLER_LINES,
        _MAX_FILLER_PHRASES,
        describe_filler_phrases,
        parse_filler_phrases,
    )

    # Four lines per entry, so a fully commented, blank-line-separated list of
    # the maximum number of entries still fits underneath the ceiling.
    assert _MAX_FILLER_LINES == _MAX_FILLER_PHRASES * 4
    assert _MAX_REPLACEMENT_LINES == _MAX_REPLACEMENT_RULES * 4

    # --- the filler phrase list ------------------------------------------
    # Nothing in this spec counts towards the phrase cap: one phrase, then
    # comments, punctuation-only lines and duplicates of it, forever.
    junk = "\n".join(["Vielen Dank", "# a comment", "...", "Vielen Dank"] * 3000)
    assert len(junk.splitlines()) > _MAX_FILLER_LINES * 5
    issues: list[str] = []
    counts: dict = {}
    assert parse_filler_phrases(junk, issues, counts) == ["vielen dank"]
    assert counts["unread_lines"] is True, counts
    # Exactly the junk inside the ceiling, and not one line more.
    assert counts["ignored"] == _MAX_FILLER_LINES // 4, counts
    # The strings kept for the status stop at their own cap; the rest are
    # counted, which is all the status needs to stay exact.
    assert len(issues) == _MAX_PHRASE_ISSUES, len(issues)
    status = describe_filler_phrases(junk)
    assert f"{_MAX_FILLER_LINES // 4} lines ignored" in status, status
    assert f"and {_MAX_FILLER_LINES // 4 - _MAX_PHRASE_ISSUES} more" in status, status
    assert f"Only the first {_MAX_FILLER_LINES} lines are read." in status, status

    # The ceiling itself: a phrase on the last line the parser reads is in
    # force, the same phrase one line further down is never seen.
    head = ["# filler"] * (_MAX_FILLER_LINES - 1)
    counts = {}
    assert parse_filler_phrases("\n".join([*head, "Vielen Dank"]), None, counts) == ["vielen dank"]
    # Being handed the line past the ceiling is the proof that one exists, so
    # a spec of exactly _MAX_FILLER_LINES lines is parsed whole and says so.
    assert counts["unread_lines"] is False, counts
    counts = {}
    assert parse_filler_phrases("\n".join([*head, "# filler", "Vielen Dank"]), None, counts) == []
    assert counts["unread_lines"] is True, counts
    # A walk that was cut short still reports itself, even with nothing to
    # report about the part it read: 200 000 lines of comments produce no
    # phrase and no bad line, and staying quiet about them is the shortening
    # the sentence exists to prevent.
    unread = describe_filler_phrases("\n".join(["# filler"] * (_MAX_FILLER_LINES + 1)))
    assert unread == (
        f"0 phrases active. Only the first {_MAX_FILLER_LINES} lines are read."
    ), unread

    # --- the replacement rules -------------------------------------------
    # Same shape: one rule, then comments, blank lines and lines with no "=>"
    # in them — none of which reach the rule cap.
    rule_junk = "\n".join(["a => b"] + ["# a comment", "posgres -> PostgreSQL", ""] * 2000)
    assert len(rule_junk.splitlines()) > _MAX_REPLACEMENT_LINES * 2
    issues = []
    counts = {}
    rules = parse_replacements(rule_junk, issues, counts)
    assert rules == [("a", "b")], rules
    assert counts["unread_lines"] is True, counts
    assert len(issues) == _MAX_RULE_ISSUES, len(issues)
    status = describe_replacements(rule_junk)
    # "50+" once the collection cap was hit: the parser stopped collecting
    # there and does not know the real total, and a count that quietly
    # understates is worse than one that admits where it stops.
    assert f"{_MAX_RULE_ISSUES}+ lines ignored" in status, status
    assert f"Only the first {_MAX_REPLACEMENT_LINES} lines are read." in status, status
    # The ceiling: a rule on the last line read is in force, one line further
    # down is not read at all.
    head = ["# rule"] * (_MAX_REPLACEMENT_LINES - 1)
    counts = {}
    assert parse_replacements("\n".join([*head, "a => b"]), None, counts) == [("a", "b")]
    # Being handed the line past the ceiling is the proof that one exists, so a
    # spec of exactly _MAX_REPLACEMENT_LINES lines is read whole and says so.
    assert counts["unread_lines"] is False, counts
    counts = {}
    assert parse_replacements("\n".join([*head, "# rule", "a => b"]), None, counts) == []
    assert counts["unread_lines"] is True, counts
    # The same cut-short walk with nothing to report about the part it read —
    # the half that used to stay silent. `describe_replacements` returned ""
    # here, because its early return fired on "no rules and no bad lines"
    # before the ceiling was ever mentioned, so a pasted file whose every line
    # is a comment past the ceiling said nothing at all. Both parsers now
    # answer the same input the same way.
    rule_unread = describe_replacements("\n".join(["# rule"] * (_MAX_REPLACEMENT_LINES + 1)))
    assert rule_unread == (
        f"0 rules active. Only the first {_MAX_REPLACEMENT_LINES} lines are read."
    ), rule_unread
    # Both caps are their own sentence, and only one of them fires: whichever
    # ceiling came first is the one that says what happened to the rest.
    over_the_rule_cap = "\n".join(f"w{n} => x" for n in range(_MAX_REPLACEMENT_RULES + 5))
    capped = describe_replacements(over_the_rule_cap)
    assert capped.endswith(f"Only the first {_MAX_REPLACEMENT_RULES} rules are used."), capped
    assert f"{_MAX_REPLACEMENT_LINES} lines" not in capped, capped
    phrase_capped = describe_filler_phrases(
        "\n".join(f"phrase {n}" for n in range(_MAX_FILLER_PHRASES + 5))
    )
    assert phrase_capped.endswith(
        f"Only the first {_MAX_FILLER_PHRASES} phrases are used."
    ), phrase_capped
    assert f"{_MAX_FILLER_LINES} lines" not in phrase_capped, phrase_capped


def _assistant_destination_names_where_a_recording_goes():
    """The disclosure on the System audio assistant card: where the transcript
    of a recorded playback would be sent.

    The defaults are safe — `assistant.system_audio.enabled` ships off — but
    the consequence of switching it on is invisible at the switch: the endpoint
    is configured two cards above, so a base URL entered months ago for
    dictation cleanup quietly becomes the destination for a recording of other
    people. `_endpoint_destination` is static and pure so the wording can be
    checked without a window; the live refresh is asserted in `settings window
    edits the new options`.

    Two rules the sentence must never break. Only the host is ever rendered —
    a base URL may carry credentials in its userinfo and this label sits in a
    window people screenshot — and a URL it cannot read gets a neutral
    sentence rather than a claim about where the audio goes."""
    from listen_to_me.settings_ui import SettingsWindow

    destination = SettingsWindow._endpoint_destination

    # Loopback: the recording never leaves the machine. The test is
    # `assistant._warn_if_key_travels_in_clear`'s, down to the `.localhost`
    # suffix rule and the IP literals — the same question decides there
    # whether the API key leaves this computer and here whether the recording
    # does, and two differently-wrong copies would be worse than one.
    for url in (
        "http://localhost:11434/v1",
        "http://LOCALHOST:11434/v1",
        "http://ollama.localhost/v1",
        "http://127.0.0.1:11434/v1",
        "https://127.9.9.9/v1",
        "http://[::1]:8080/v1",
    ):
        for enabled in (True, False):
            text = destination(url, enabled=enabled)
            assert "this computer" in text and "stays on it" in text, (url, text)
            assert "leaves this machine" not in text, (url, text)
            assert "unencrypted" not in text, (url, text)

    # A remote host: it leaves the machine, and the sentence says so.
    remote = destination("https://api.example.com/v1", enabled=True)
    assert "“api.example.com”" in remote, remote
    assert "not this computer" in remote and "leaves this machine" in remote
    # https is not called out — only the wire that really is in the clear.
    assert "unencrypted" not in remote, remote
    plain = destination("http://api.example.com/v1", enabled=True)
    assert "leaves this machine" in plain and "plain http" in plain
    assert "unencrypted" in plain, plain
    # A remote IP literal is remote too (the loopback test is by address, not
    # by "it looks like a name").
    assert "leaves this machine" in destination("http://198.51.100.7/v1", enabled=True)

    # Only the host, never the URL and never the credentials in it.
    secret = destination("https://alice:s3cr3t@api.example.com/v1", enabled=False)
    assert "“api.example.com”" in secret, secret
    assert "s3cr3t" not in secret and "alice" not in secret, secret
    assert "https://" not in secret and "/v1" not in secret, secret

    # The tense carries the switch: the sentence is never hidden while the
    # profile is off, because off is exactly the state the decision is made in
    # — and a disclosure that appears only after the tick is one the tick could
    # not use.
    off = destination("https://api.example.com/v1", enabled=False)
    assert off.startswith("Switched on, this sends the transcript"), off
    assert remote.startswith("The transcript of every recorded playback is sent to"), remote
    # Same destination either way — only the tense may differ.
    assert off.endswith(remote.split("to ", 1)[1]), off

    # Nothing set, and something unreadable: a neutral sentence, and never a
    # destination claim. "http://[oops" makes urlparse itself raise (an
    # unclosed IPv6 literal), which must not be what breaks the page.
    for nothing in ("", "   ", None):
        text = destination(nothing, enabled=True)
        assert "No API base URL is set" in text, text
        assert "nowhere for a transcript to go" in text, text
    for unreadable in ("http://[oops", "http://", "localhost:11434/v1", "not a url"):
        text = destination(unreadable, enabled=True)
        assert "names no host" in text, (unreadable, text)
        assert "check it before switching this on" in text, (unreadable, text)
    for blind in ("", "   ", None, "http://[oops", "http://", "not a url"):
        for enabled in (True, False):
            text = destination(blind, enabled=enabled)
            assert "stays on it" not in text, (blind, text)
            assert "leaves this machine" not in text, (blind, text)
            assert "“" not in text, (blind, text)  # no host to quote


def _save_refuses_an_assistant_profile_with_no_prompt():
    """Save refuses an enabled assistant profile that cannot produce a
    request, names the profile it means, and puts the caret in the field the
    message talked about.

    Both halves were wrong before. A blank prompt was reported nowhere at all
    (`assistant._gate` read such a profile as disabled, so `_validate` skipped
    it and one log line per process was the only trace), and every answer that
    was not `base_url` landed on the MODEL field — so the one message about a
    prompt pointed at a box that was already filled in. With two profiles on
    the page that matters twice over: the message has to say *which* one, and
    the caret is what a screen reader follows, since focus is otherwise still
    on the Save button that refused.

    `Hotkeys` and `QMessageBox` are stood in for as in `settings window edits
    the new options`: the real parser imports pynput, which needs an X display
    the CI runner has not got, and a modal box would hang this run."""
    from listen_to_me import settings_ui as _settings_module
    from listen_to_me.settings_ui import SettingsWindow
    from listen_to_me.theme import apply_theme

    app = _ensure_qapp()
    apply_theme(app)

    class _FakeHotkeys:
        @staticmethod
        def validate(combo):
            return True

        @staticmethod
        def combo_flags(combo):
            return (True, True)

        @staticmethod
        def equal(combo_a, combo_b):
            return combo_a == combo_b

    class _FakeCriticalBox:
        StandardButton = _settings_module.QMessageBox.StandardButton
        shown: list = []

        @classmethod
        def critical(cls, *args, **_kwargs):
            cls.shown.append(args[-1])

    with tempfile.TemporaryDirectory() as tmp:
        stub = _StubApp(Path(tmp))
        window = SettingsWindow(stub)
        real_hotkeys, real_box = _settings_module.Hotkeys, _settings_module.QMessageBox
        _settings_module.Hotkeys = _FakeHotkeys
        _settings_module.QMessageBox = _FakeCriticalBox
        try:
            # Both profiles on, both usable: nothing to report.
            values = window._collect()
            values["assistant"] = {
                "enabled": True,
                "base_url": "http://localhost:11434/v1",
                "api_key": "",
                "model": "llama3.2",
                "system_prompt": "punctuate the dictation",
                "temperature": 0.2,
                "timeout": 90,
                "system_audio": {
                    "enabled": True,
                    "model": "",
                    "system_prompt": "write the minutes",
                },
            }
            assert window._validate(values) is True
            assert not _FakeCriticalBox.shown, _FakeCriticalBox.shown

            def _refused(broken, named, reason, field):
                _FakeCriticalBox.shown.clear()
                collected = window._collect()
                collected["assistant"] = broken
                assert window._validate(collected) is False, (named, reason)
                message = _FakeCriticalBox.shown[-1]
                assert f"“{named}”" in message, message
                assert reason in message, message
                # The page the field is on, and the field itself: focus is
                # what scrolls it into view and what a screen reader reads.
                assert window.focusWidget() is field, (named, reason)

            good = values["assistant"]
            # A blank prompt, per profile — and never the other profile's box.
            for blank in ("", "   ", None, 5):
                _refused(
                    {**good, "system_prompt": blank},
                    "Microphone dictation",
                    "no system prompt is set",
                    window.a_prompt_edit,
                )
                _refused(
                    {**good, "system_audio": {**good["system_audio"], "system_prompt": blank}},
                    "System audio",
                    "no system prompt is set",
                    window.a_sys_prompt_edit,
                )
            # A profile that is switched off may stay half-configured, like a
            # disabled mute row — and the two are checked separately, because
            # the connection is shared: the microphone profile being off does
            # not make a missing base URL harmless for the other one.
            assert window._validate(
                {
                    **window._collect(),
                    "assistant": {**good, "enabled": False, "system_prompt": ""},
                }
            ) is True
            _refused(
                {
                    **good,
                    "enabled": False,
                    "system_prompt": "",
                    "system_audio": {**good["system_audio"], "system_prompt": ""},
                },
                "System audio",
                "no system prompt is set",
                window.a_sys_prompt_edit,
            )
            # The two answers whose field is NOT the profile's own box: the
            # base URL is the shared one on the Connection card, and a model
            # that is only missing from the shared field has to be filled in
            # there — an empty per-profile override means "use the shared
            # one", so pointing at the override would name a box whose empty
            # value is correct.
            _refused(
                {**good, "base_url": ""},
                "Microphone dictation",
                "no API base URL is set",
                window.a_url_edit,
            )
            _refused(
                {**good, "base_url": "localhost:11434"},
                "Microphone dictation",
                "must start with http:// or https://",
                window.a_url_edit,
            )
            _refused(
                {**good, "model": ""},
                "Microphone dictation",
                "no model name is set",
                window.a_model_edit,
            )
            _refused(
                {**good, "enabled": False, "model": ""},
                "System audio",
                "no model name is set",
                window.a_model_edit,
            )
        finally:
            _settings_module.Hotkeys, _settings_module.QMessageBox = real_hotkeys, real_box
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
            # A check may return a string to have it land in the report: that
            # is how a check that could not mean anything here (no
            # sounddevice, not Windows) says so instead of reading as a plain
            # OK, and how one worth a value — the PortAudio version the exe
            # loaded — puts it where the release log is read. Anything else a
            # check returns is ignored; the import probes below return modules.
            note = fn()
            suffix = f" — {note}" if isinstance(note, str) and note else ""
            lines.append(f"OK   {name}{suffix}")
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
    ("config survives a scalar source section", _config_survives_a_scalar_source_section),
    ("config guards scalar types", _config_guards_scalar_types),
    ("config read failure never costs the file", _config_read_failure_never_costs_the_file),
    ("config factory reset", _config_factory_reset),
    ("history normalizes entries", _history_normalizes_entries),
    ("history latest transcript", _history_latest_transcript),
    ("history search matching", _history_search_matching),
    ("history search matches the date", _history_search_matches_the_date),
    ("history deletes one entry", _history_delete_one_entry),
    ("history export format", _history_export_format),
    ("CLI flags", _cli_flags),
    ("recording length warning", _recording_length_warning),
    ("take is warned about its own cap", _take_is_warned_about_its_own_cap),
    ("text replacements", _text_replacements),
    ("replacement rules report what was skipped", _replacement_rules_report_what_was_skipped),
    ("filler filter drops a silent take", _filler_filter_drops_a_silent_take),
    ("filler phrases report what was skipped", _filler_phrases_report_what_was_skipped),
    ("filler take inserts nothing", _filler_take_inserts_nothing),
    ("the parsers bound the lines they walk", _the_parsers_bound_the_lines_they_walk),
    ("missing microphone falls back", _missing_microphone_falls_back),
    ("loopback device is ranked and resolved", _loopback_device_is_ranked_and_resolved),
    ("PortAudio DLL path is prepended only in a frozen bundle", _portaudio_path_prepend),
    ("the bundled PortAudio can be switched off", _bundled_portaudio_can_be_switched_off),
    ("outputs are counted once per device, not once per host API",
     _portaudio_counts_one_entry_per_output),
    ("the recording path asks PortAudio nothing", _recording_path_asks_portaudio_nothing),
    ("assistant failure is actionable", _assistant_failure_is_actionable),
    ("empty transcript names the microphone", _empty_transcript_names_the_microphone),
    ("no-speech report names its own source", _no_speech_report_names_its_own_source),
    ("recorder events carry their take", _recorder_events_carry_their_take),
    ("hotkeys route to their own source", _hotkeys_route_to_their_own_source),
    ("an unknown source is logged, not answered silently",
     _an_unknown_source_is_logged_not_answered_silently),
    ("assistant config is checked", _assistant_config_is_checked),
    ("assistant profiles follow the source", _assistant_profiles_follow_the_source),
    ("assistant destination names where a recording goes",
     _assistant_destination_names_where_a_recording_goes),
    ("recorder start failure resets", _recorder_start_failure_resets),
    ("injector paste fallback", _injector_paste_falls_back_to_typing),
    ("injector clipboard policy", _injector_clipboard_policy),
    ("clipboard copy is announced", _clipboard_copy_is_announced),
    ("copy button reports a failure", _copy_button_reports_failure),
    ("theme scrollbar contrast", _theme_scrollbar_contrast),
    ("theme accent text contrast", _theme_accent_text_contrast),
    ("theme assets stay out of shared temp", _theme_assets_stay_out_of_shared_temp),
    ("mute integrations no-op", _integrations_noop),
    ("only a microphone take mutes other apps", _only_a_microphone_take_mutes_other_apps),
    ("mute keybind uses virtual keys", _mute_keybind_uses_virtual_keys),
    ("mute keybind waits for the hotkey", _mute_keybind_waits_for_the_hotkey),
    ("mute keybind survives a superseded stop", _mute_keybind_survives_a_superseded_stop),
    ("mute keybind worker failure is logged", _mute_keybind_worker_failure_is_logged),
    ("mute presets are usable", _mute_presets_are_usable),
    ("mute targets are validated", _mute_targets_are_validated),
    ("mute keybind hold-mode guard", _mute_keybind_hold_mode_guard),
    ("injector waits for quiet modifiers", _injector_waits_for_quiet_modifiers),
    ("config redacts secrets in warnings", _config_redacts_secrets_in_warnings),
    ("config clamps out-of-range values", _config_clamps_out_of_range_values),
    ("updater caps the download size", _updater_caps_the_download_size),
    ("recorder counts dropped buffers", _recorder_counts_dropped_buffers),
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
    ("compute type resolution", _compute_type_resolution),
    ("openvino pipeline properties", _openvino_pipeline_properties),
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
    ("source-aware controls stop their take", _source_aware_controls_stop_their_take),
    ("settings window edits the new options", _settings_window_edits_the_new_options),
    ("system audio picker reads as an output picker",
     _system_audio_picker_reads_as_an_output_picker),
    ("system audio hint names the outputs it cannot record",
     _system_audio_hint_names_the_outputs_it_cannot_record),
    ("save refuses an assistant profile with no prompt",
     _save_refuses_an_assistant_profile_with_no_prompt),
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


def _portaudio_supports_wasapi_loopback():
    """What the release build's own portaudio.dll promises (#194): WASAPI
    loopback, so *any* output device can be captured — no "Stereo Mix", no
    virtual cable. This is the only check that can catch a DLL built without
    WASAPI, or a bundle whose DLL was never picked up, and it can only run on
    the built exe: the Linux CI job installs no sounddevice and has no WASAPI
    at all (its monitor sources are a different mechanism, already covered by
    "loopback device is ranked and resolved").

    Two halves, and the failure message says which one gave way plus the
    version string that answered — this check exists to be read out of a
    release build's self-test log, where nobody can re-run it interactively.
    The device half is skipped on a machine with no output device (a CI runner
    with no audio hardware has nothing to enumerate a loopback for), so it
    reports what it could not test instead of failing on it.

    Both counts come from ONE host API (`portaudio.preferred_hostapi`, WASAPI
    here) and the message names it. Counted across all of them, a runner
    reporting an MME or DirectSound pseudo-output while WASAPI enumerates no
    render endpoint would fail this gate on a perfectly correct build — the
    ratio has to be "loopback twins of WASAPI outputs", because only WASAPI
    emits the twins. A host API that cannot be resolved is reported as such,
    for the same reason: not counted is not the same as none there.
    """
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        return "SKIPPED: sounddevice is not installed"
    if not sys.platform.startswith("win"):
        return f"SKIPPED: WASAPI loopback is Windows-only, this is {sys.platform}"
    from listen_to_me import portaudio

    info = portaudio.describe()
    version = info.get("version") or "unknown"
    where = f"loaded {info.get('library')!r}, {info.get('path_note')}"
    if not info.get("loopback_supported"):
        raise AssertionError(
            f"PaWasapi_IsLoopback is not reachable in the loaded library ({version}) — "
            f"the bundled {portaudio.DLL_NAME} was not loaded, or was built without "
            f"WASAPI. {where}, errors={info.get('errors')}"
        )
    hostapi = info.get("hostapi")
    if not hostapi:
        return (
            f"{version} supports loopback; no host API could be resolved, so no device "
            f"was counted ({where}, errors={info.get('errors')})"
        )
    outputs = int(info.get("output_devices") or 0)
    loopbacks = int(info.get("loopback_devices") or 0)
    if outputs and not loopbacks:
        raise AssertionError(
            f"The loaded library ({version}) exports PaWasapi_IsLoopback but enumerated "
            f"no input device carrying the '[Loopback]' marker, although the machine "
            f"reports {outputs} output device(s) on {hostapi} — loopback enumeration is "
            f"missing. {where}"
        )
    if not outputs:
        return f"{version} supports loopback; no output device on {hostapi} to enumerate one for"
    return f"{version}, {loopbacks} loopback input(s) for {outputs} output(s) on {hostapi}"


_FULL_EXTRA = [
    ("default hotkey parses", _hotkey_default_valid),
    ("audio band levels", _band_levels),
    ("resampler converts without aliasing", _resampler_converts_without_aliasing),
    ("recorder falls back to the native format", _recorder_falls_back_to_the_native_format),
    ("clip stats verdicts", _clip_stats_verdicts),
    ("insecure hub client builds", _insecure_hub_client_builds),
    ("PortAudio supports WASAPI loopback", _portaudio_supports_wasapi_loopback),
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
