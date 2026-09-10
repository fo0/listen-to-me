"""Home page: the entry hub of the main window.

Shows the live recording state with a start/stop control, the configured
hotkeys as key caps — the microphone's, plus the system-audio one when that
second recording source is switched on (#191) — an at-a-glance summary of the
active setup (engine/model, language, microphone), quick actions into the
relevant settings pages and the most recent transcripts. Pure presentation:
every action either posts an event to App (start/stop/cancel) or navigates the
owning window's sidebar — no state of its own beyond the widgets.

Nothing here assumes a take is a microphone take: the hero names the source
that is actually recording and posts the toggle for *that* source, because App
refuses a microphone toggle while system audio is running — a hero that posted
one anyway could not stop the recording it is displaying.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .choices import (
    SOURCE_MIC,
    SOURCE_SYSTEM,
    SYSTEM_DEFAULT_DEVICE,
    input_device_choices,
    language_label,
)
from .glyphs import glyph_icon
from .keymap import pretty_keys
from .qtutil import copy_with_feedback, elastic_label

# From the tray, like the floating icon does: the take clock is rendered on
# three surfaces now and they must never disagree about the same second.
# (tray.py imports nothing from this module — no cycle.)
from .tray import format_duration

log = logging.getLogger(__name__)

# How many of the latest transcripts the Home page shows; the full list lives
# on the History page.
_RECENT_LIMIT = 3
# Hard cap per shown transcript — QLabel has no automatic elide and a huge
# dictation would blow the card up.
_RECENT_CHARS = 160

_BACKEND_SHORT = {
    "faster-whisper": "faster-whisper",
    "openvino": "OpenVINO",
    "parakeet": "Parakeet",
}

# The hero button's tooltip while it starts a take. Set per state, not once at
# construction: the same button becomes the "Stop" of whichever take is
# running, and "Start a recording now" on a button labelled "Stop & insert" is
# not terse, it is wrong.
_START_TOOLTIP = (
    "Start a recording now — same as pressing the global hotkey. "
    "The text is inserted at the cursor of the focused field."
)


class _StatCard(QFrame):
    """A clickable at-a-glance card that navigates to a settings page.

    It is a real control, not decoration, so it behaves like one: it takes
    keyboard focus (the style sheet rings it, like every button) and Space /
    Enter activate it. Without that the card is reachable by mouse only — a
    keyboard user can neither see nor trigger it, and a screen reader
    announces an unnamed frame. The accessible name carries the card's title
    because the visible heading is a sibling label, not a real label relation.
    """

    def __init__(self, title: str, on_click):
        super().__init__()
        self.setProperty("card", "stat")
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{title} — open in Settings")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(4)
        head = QLabel(title.upper())
        head.setProperty("role", "cardTitle")
        box.addWidget(head)
        self.value = QLabel("")
        self.value.setProperty("role", "cardValue")
        self.value.setWordWrap(True)
        box.addWidget(self.value)
        self.detail = QLabel("")
        self.detail.setProperty("role", "hint")
        self.detail.setWordWrap(True)
        box.addWidget(self.detail)
        box.addStretch(1)

    def sync_accessible_description(self) -> None:
        """Carry what the card currently shows into what a screen reader reads.

        The accessible name is the fixed title ("Microphone — open in
        Settings"); the value and the detail below it are sibling labels of a
        focusable frame, not a label relation, so a card announced by its name
        alone never names the microphone, the model or the language it exists
        to report — the one piece of information the card carries. Called by
        HomePage._refresh_stats after every value it writes.
        """
        parts = (self.value.text().strip(), self.detail.text().strip())
        self.setAccessibleDescription(" — ".join(part for part in parts if part))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._on_click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Accepting the event matters as much as handling it: the owning
        # window is a QDialog, so an unhandled Return would fall through to
        # its default button (Save) instead of opening the settings page.
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            self._on_click()
            return
        super().keyPressEvent(event)


class HomePage(QWidget):
    """Built by SettingsWindow as its first page. `window` provides `.app`
    (App or the self-test stub), `.cfg` and `._show_page(title)`."""

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._app = window.app
        self.cfg = window.cfg
        self._state = "idle"
        # Seconds of the running take, or None before the first tick of one —
        # see set_elapsed.
        self._elapsed = None
        # (input_device config value, label) — device enumeration goes through
        # PortAudio and can stall for hundreds of ms on flaky drivers, so it
        # runs once per device value, not on every Home visit / Apply.
        self._mic_cache: tuple[object, str] | None = None
        # Debounces the hero record button (monotonic seconds of the last
        # accepted click) — see _toggle.
        self._last_toggle = 0.0

        from .theme import ACCENT, tokens

        colors = tokens()

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        wrap.addWidget(scroll)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        scroll.setWidget(inner)

        # Hero: live state + hotkey + the primary record control. ------------
        hero = QFrame()
        hero.setObjectName("hero")
        hero.setProperty("state", "idle")  # QSS switches the gradient per state
        self._hero = hero
        hv = QHBoxLayout(hero)
        hv.setContentsMargins(22, 20, 22, 20)
        hv.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.state_label = QLabel("")
        self.state_label.setObjectName("heroState")
        self.state_label.setWordWrap(True)
        left.addWidget(self.state_label)
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("heroHint")
        self.hint_label.setWordWrap(True)
        left.addWidget(self.hint_label)
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        self._chips_row = chips_row
        chips_wrap = QHBoxLayout()
        chips_wrap.addLayout(chips_row)
        chips_wrap.addStretch(1)
        left.addSpacing(4)
        left.addLayout(chips_wrap)
        # The second recording source's key caps (#191) get their own row: two
        # combinations on one line would read as one long chord. A container
        # widget rather than a bare layout, so hiding it takes its spacing with
        # it — with the system-audio hotkey empty (the default) this hero has to
        # look exactly as it always did.
        self._sys_chips_wrap = QWidget()
        sys_wrap = QHBoxLayout(self._sys_chips_wrap)
        sys_wrap.setContentsMargins(0, 4, 0, 0)
        sys_wrap.setSpacing(6)
        self._sys_chips_row = QHBoxLayout()
        self._sys_chips_row.setSpacing(6)
        sys_wrap.addLayout(self._sys_chips_row)
        sys_wrap.addStretch(1)
        self._sys_chips_wrap.setVisible(False)
        left.addWidget(self._sys_chips_wrap)
        left.addStretch(1)
        hv.addLayout(left, 1)

        buttons = QVBoxLayout()
        buttons.addStretch(1)
        # Deliberately one button with two sources: it starts a microphone take
        # and stops whichever take is running. A second button for *starting* a
        # system-audio one would be a third surface to keep in sync — the tray
        # menu carries that entry — while App refuses a second take anyway as
        # long as one runs.
        self.record_button = QPushButton("Start recording")
        self.record_button.setObjectName("recordBtn")
        self.record_button.setAutoDefault(False)
        self.record_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_button.setToolTip(_START_TOOLTIP)
        self.record_button.clicked.connect(self._toggle)
        buttons.addWidget(self.record_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("heroCancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setToolTip("Discard the running recording — nothing is inserted.")
        self.cancel_button.clicked.connect(lambda: self._app.post("cancel"))
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        hv.addLayout(buttons)
        layout.addWidget(hero)

        # At a glance: what setup a recording would use right now. -----------
        layout.addWidget(self._section("At a glance"))
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.card_model = _StatCard("Engine & model", lambda: window._show_page("Engine"))
        self.card_language = _StatCard("Language", lambda: window._show_page("Engine"))
        self.card_mic = _StatCard("Microphone", lambda: window._show_page("Audio"))
        for card in (self.card_model, self.card_language, self.card_mic):
            card.setToolTip("Click to change this in Settings.")
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        # Quick actions: jump straight to the relevant settings page. --------
        layout.addWidget(self._section("Quick actions"))
        actions = QGridLayout()
        actions.setSpacing(10)
        quick = [
            ("keyboard", "Change hotkey", "General", "Pick the global key combination and its mode."),
            ("wave", "Model && engine", "Engine", "Choose the speech model, backend and device."),
            ("mic", "Test microphone", "Audio", "Record 3 seconds and check the input level."),
            ("layers", "Overlay && preview", "Overlay", "The floating icon and transcript preview."),
            ("download", "Check for updates", "Updates", "See and install newer releases."),
            ("help", "Help && tips", "Help", "Troubleshooting and how-tos."),
        ]
        # (button, glyph name) of every code-painted icon, so a live OS
        # light/dark switch can repaint them in the new palette (the QSS is
        # re-applied by theme.py, but a pixmap keeps the colours it was built
        # with) — see restyle_icons.
        self._glyph_buttons: list[tuple[QPushButton, str]] = []
        for i, (glyph, label, page, tip) in enumerate(quick):
            button = QPushButton(f"  {label}")
            button.setProperty("quick", True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(glyph_icon(glyph, colors["muted"], ACCENT))
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked=False, p=page: self._go(p))
            self._glyph_buttons.append((button, glyph))
            actions.addWidget(button, i // 3, i % 3)
        # The seventh action, and the only conditional one: the second hotkey
        # lives on Audio, next to the loopback device and the length cap it
        # shares a card with, so "Change hotkey" above (General) cannot lead
        # there. Same "keyboard" glyph on purpose — one hotkey action per
        # source. Built once and added to / removed from the grid by
        # _refresh_system_action; parented to `inner` so it is a hidden child
        # of this page, never a stray top-level window, while it is out.
        self._actions = actions
        self._sys_action = QPushButton("  System audio hotkey", inner)
        self._sys_action.setProperty("quick", True)
        self._sys_action.setAutoDefault(False)
        self._sys_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sys_action.setIcon(glyph_icon("keyboard", colors["muted"], ACCENT))
        self._sys_action.setToolTip(
            "The hotkey that records what the computer plays, with its loopback "
            "device and its own length cap."
        )
        self._sys_action.setVisible(False)
        self._sys_action.clicked.connect(lambda: self._go("Audio"))
        self._glyph_buttons.append((self._sys_action, "keyboard"))
        # Whether that button is currently in the grid — the add/remove is
        # skipped unless the setting actually changed (refresh runs on every
        # visit to this page).
        self._sys_action_shown = False
        for col in range(3):
            actions.setColumnStretch(col, 1)
        layout.addLayout(actions)

        # Recent transcripts. -------------------------------------------------
        recent_head = QHBoxLayout()
        recent_head.addWidget(self._section("Recent transcripts"))
        recent_head.addStretch(1)
        open_history = QPushButton("Open history")
        open_history.setProperty("quick", True)
        open_history.setAutoDefault(False)
        open_history.setCursor(Qt.CursorShape.PointingHandCursor)
        open_history.setIcon(glyph_icon("clock", colors["muted"], ACCENT))
        open_history.clicked.connect(lambda: self._go("History"))
        self._glyph_buttons.append((open_history, "clock"))
        recent_head.addWidget(open_history)
        layout.addLayout(recent_head)

        self._recent_frame = QFrame()
        self._recent_frame.setProperty("card", "stat")
        self._recent_layout = QVBoxLayout(self._recent_frame)
        self._recent_layout.setContentsMargins(14, 10, 14, 10)
        self._recent_layout.setSpacing(8)
        layout.addWidget(self._recent_frame)

        layout.addStretch(1)
        self.refresh()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setProperty("role", "section")
        return label

    def restyle_icons(self, color: str, selected_color: str) -> None:
        """Repaint the quick-action icons in the given colours. Called by
        SettingsWindow when the OS light/dark scheme changed — the stylesheet
        follows automatically, code-painted pixmaps do not."""
        for button, glyph in self._glyph_buttons:
            button.setIcon(glyph_icon(glyph, color, selected_color))

    def _go(self, page: str) -> None:
        try:
            self._window._show_page(page)
        except Exception:
            log.exception("could not open page %r", page)

    def _system_setting(self, key: str, fallback: str) -> str:
        """One string out of `cfg["system_audio"]`, never raising.

        config.json is untrusted on-disk input: a hand-edited one can leave a
        scalar where the section belongs (config._merge keeps the defaults and
        logs it, so this is belt and braces) or a null where a combination
        belongs. Anything that is not a string is the fallback — for `hotkey`
        that means "off", the right answer for a value that is no combination.
        """
        try:
            value = self.cfg["system_audio"][key]
        except Exception:
            log.debug("could not read system_audio.%s for the Home page", key, exc_info=True)
            return fallback
        return value if isinstance(value, str) else fallback

    def _source(self) -> str:
        """Which source the app's running (or most recent) take records from.
        getattr for the reason tray._source spells out: the self-test's App
        stub predates the second source, and a hero label must never be what
        breaks against it."""
        return getattr(self._app, "recording_source", SOURCE_MIC)

    @staticmethod
    def _source_name(source: str) -> str:
        """How the app names a recording source ("microphone" / "system audio").

        Lazily imported, like settings_ui borrows `describe_replacements`: the
        wording is worth sharing with app.py — the hero and the notification
        about the same take must not name it two ways — its import graph isn't.
        """
        from .app import source_label

        return source_label(source)

    def _toggle(self) -> None:
        """Post the start/stop toggle, debounced: a double-click emits two
        clicked signals before the 100 ms event poll runs, which would queue
        start + stop back to back and end in "Recording too short".

        Posted for the source of the *running* take, like the tray's two
        entries: App refuses a microphone toggle while system audio is
        recording ("A system audio recording is already running — stop that one
        first."), so a plain toggle would leave this button unable to stop the
        take it is labelled for. With nothing running it starts a microphone
        take — the payload-less toggle every surface posts (app.event_source).
        """
        now = time.monotonic()
        if now - self._last_toggle < 0.4:
            return
        self._last_toggle = now
        if self._state == "recording" and self._source() == SOURCE_SYSTEM:
            self._app.post("toggle", SOURCE_SYSTEM)
            return
        self._app.post("toggle")

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Re-read config + history into the cards. Called when the page is
        shown, after settings were applied and when a recording finished.

        Everything the second recording source shows here hangs off this — its
        key caps, its quick action and (via set_state) its line in the hero —
        so switching it on in Settings updates the page as soon as
        SettingsWindow._apply_values calls in, with no restart."""
        self._refresh_chips()
        self._refresh_system_action(bool(self._system_setting("hotkey", "")))
        self._refresh_stats()
        self._refresh_recent()
        self.set_state(getattr(self._app, "state", "idle"))

    @staticmethod
    def _clear_layout(layout) -> None:
        """Remove and delete every widget in `layout`. Detach + hide first:
        a deleteLater'd widget keeps painting until the event loop deletes
        it, which leaves visible ghosts when the layout is rebuilt twice in
        one event-loop pass (e.g. page change + state change)."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _source_caption(text: str) -> QLabel:
        """The dimmed label that names which source a key-cap row belongs to.

        `heroHint` is theme.py's only dimmed-on-the-gradient label style, and
        it already follows the red recording state — so the caption cannot end
        up as bright as the caps it explains. This only picks the hook; the
        styling stays in theme.py.
        """
        label = QLabel(text)
        label.setObjectName("heroHint")
        return label

    def _fill_caps(self, row, combo: str, caption: str) -> None:
        """Render `combo` into `row` as key caps, followed by `caption`.

        One renderer for both hotkeys — keymap.pretty_keys stays the single
        source of a cap label, here as on the tray and the floating icon. An
        empty `combo` renders nothing, and an empty `caption` is left out: with
        one row there is nothing to confuse it with, so the hero keeps the bare
        caps it always showed.
        """
        for cap in pretty_keys(combo):
            chip = QLabel(cap)
            chip.setObjectName("keycap")
            row.addWidget(chip)
        if caption:
            row.addWidget(self._source_caption(caption))

    def _refresh_chips(self) -> None:
        self._clear_layout(self._chips_row)
        self._clear_layout(self._sys_chips_row)
        system = self._system_setting("hotkey", "")
        # Captions only once there really are two rows, and taken from the same
        # labels App's notifications use, so this page cannot name a source
        # differently than the message about it does.
        mic_caption = self._source_name(SOURCE_MIC).capitalize() if system else ""
        sys_caption = self._source_name(SOURCE_SYSTEM).capitalize() if system else ""
        self._fill_caps(self._chips_row, self.cfg["hotkey"], mic_caption)
        self._fill_caps(self._sys_chips_row, system, sys_caption)
        self._sys_chips_wrap.setVisible(bool(system))

    def _refresh_system_action(self, configured: bool) -> None:
        """Show the "System audio hotkey" quick action exactly while that
        source is on.

        Added to and removed from the grid rather than hidden in place: the off
        state has to be the same two-row block of six actions it always was,
        and that is a guarantee about our own layout instead of a bet on how
        Qt sizes a row whose only widget is hidden.
        """
        if configured == self._sys_action_shown:
            return
        if configured:
            self._actions.addWidget(self._sys_action, 2, 0)
            self._sys_action.setVisible(True)
        else:
            # Hidden before it is removed: a widget taken out of a layout keeps
            # its geometry and would go on painting where the row used to be.
            self._sys_action.setVisible(False)
            self._actions.removeWidget(self._sys_action)
        self._sys_action_shown = configured

    def _refresh_stats(self) -> None:
        backend = self.cfg["backend"]
        if backend == "parakeet":
            self.card_model.value.setText("Parakeet TDT 0.6b v3")
            self.card_model.detail.setText("25 languages, auto-detected")
        else:
            model = str(self.cfg["model"])
            self.card_model.value.setText(model.rsplit("/", 1)[-1])
            self.card_model.detail.setText(_BACKEND_SHORT.get(backend, backend))
        if backend == "parakeet":
            # The language setting does not apply to Parakeet — it always
            # auto-detects; showing the configured Whisper language here
            # would be wrong.
            self.card_language.value.setText("Auto-detect")
            self.card_language.detail.setText("Parakeet detects the language itself")
        else:
            self.card_language.value.setText(language_label(self.cfg["language"]))
            self.card_language.detail.setText(
                "fixed for better accuracy" if self.cfg["language"] != "auto" else "detected per recording"
            )
        device = self.cfg["input_device"]
        if self._mic_cache is not None and self._mic_cache[0] == device:
            current = self._mic_cache[1]
        else:
            try:
                _values, current = input_device_choices(device)
            except Exception:
                log.exception("could not resolve the input device label")
                current = SYSTEM_DEFAULT_DEVICE
            # Cache only a meaningful resolution. A configured index that
            # falls back to "System default" (mic unplugged, driver hiccup)
            # must be retried on the next refresh, or the wrong label would
            # stick for the whole session after the device comes back.
            if device is None or current != SYSTEM_DEFAULT_DEVICE:
                self._mic_cache = (device, current)
        # Drop the "<index>: " prefix — the number means nothing here.
        self.card_mic.value.setText(current.split(": ", 1)[-1])
        try:  # a hand-edited config value must not break the Home page
            max_seconds = int(float(self.cfg["max_seconds"]))
        except (TypeError, ValueError):
            max_seconds = 300
        self.card_mic.detail.setText(f"max. {max_seconds} s per recording")
        # One pass at the end rather than after each branch above: every card
        # is written on some path through this method, and a description left
        # behind by the previous refresh would be read out as the current one.
        for card in (self.card_model, self.card_language, self.card_mic):
            card.sync_accessible_description()

    def _empty_recent_text(self, unreadable: bool) -> str:
        """Which of the three empty states this panel is actually in.

        All three used to read "No transcripts yet — your dictations will show
        up here", which is wrong twice over. A history that cannot be read
        looked exactly like one that stored nothing — the same trap the tray's
        recent-transcripts submenu names out loud, because an app that offers
        nothing must not look like one that kept nothing. And the promise that
        dictations will show up here is a plain lie once the history is
        switched off: nothing will ever be stored, and the setting that decides
        it is two pages away with nothing pointing at it.

        The History page already tells the last two apart; this is its wording,
        one panel over, so the two can never describe the same store
        differently.
        """
        if unreadable:
            return "Could not read the transcript history."
        try:
            enabled = bool(self.cfg["history_enabled"])
        except Exception:
            # A hand-edited config must not decide this panel's fate: the
            # optimistic wording is the one that is right on a fresh install.
            log.debug("could not read history_enabled for the Home page", exc_info=True)
            enabled = True
        if not enabled:
            return (
                "History is off — new transcripts are not stored. Turn on "
                "“Keep a history of transcribed text” in Settings → History "
                "to collect them."
            )
        return "No transcripts yet — the text of your next dictation shows up here."

    def _refresh_recent(self) -> None:
        self._clear_layout(self._recent_layout)
        entries = []
        unreadable = False
        try:
            entries = self._app.history.entries()[:_RECENT_LIMIT]
        except Exception:
            log.exception("could not read the transcript history")
            unreadable = True
        if not entries:
            empty = QLabel(self._empty_recent_text(unreadable))
            empty.setProperty("role", "hint")
            empty.setWordWrap(True)
            self._recent_layout.addWidget(empty)
            return
        for i, entry in enumerate(entries):
            if i:
                divider = QFrame()
                divider.setProperty("role", "divider")
                divider.setFixedHeight(1)
                self._recent_layout.addWidget(divider)
            self._recent_layout.addWidget(self._recent_row(entry))

    def _recent_row(self, entry: dict) -> QWidget:
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(10)
        body = QVBoxLayout()
        body.setSpacing(2)
        stamp = ""
        when = entry.get("time")
        if when:
            # Broad tuple on purpose: float() raises TypeError on a non-numeric
            # value and localtime() OverflowError on an out-of-range one — a
            # corrupt history.json must never prevent this window from opening
            # (this runs during SettingsWindow construction).
            try:
                stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(when)))
            except (TypeError, ValueError, OverflowError, OSError):
                stamp = ""
        stamp_label = QLabel(stamp)
        stamp_label.setProperty("role", "hint")
        body.addWidget(stamp_label)
        raw = str(entry.get("text", ""))
        # Flattened/truncated for the label only — Copy hands back the raw
        # transcript with its line breaks, exactly like the History page.
        flat = raw.replace("\n", " ")
        shown = flat if len(flat) <= _RECENT_CHARS else flat[:_RECENT_CHARS].rstrip() + "…"
        text_label = QLabel(shown)
        # Plain text, never Qt's AutoText guess — the transcript is untrusted
        # input (history.json is hand-editable, and an assistant response
        # arrives verbatim). A first line that looks like markup would be
        # rendered as HTML instead of shown, so the row would display something
        # other than the text its Copy button hands back.
        text_label.setTextFormat(Qt.TextFormat.PlainText)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # A wrapping label demands its longest unbreakable word as minimum
        # width — one long URL/token in a transcript would clip every card on
        # the Home page (its scroll area has no horizontal scrollbar).
        elastic_label(text_label)
        body.addWidget(text_label)
        rh.addLayout(body, 1)
        copy_btn = QPushButton("Copy")
        copy_btn.setAutoDefault(False)
        copy_btn.setToolTip("Put the full transcript back on the clipboard.")
        # One "Copy" per listed transcript: without a per-row name a screen
        # reader announces the same button three times over, and the timestamp
        # above it is a sibling label, not a label relation (see _StatCard).
        copy_btn.setAccessibleName(
            f"Copy the transcript from {stamp}" if stamp else "Copy this transcript"
        )
        copy_btn.clicked.connect(lambda _checked=False, t=raw, b=copy_btn: self._copy(t, b))
        rh.addWidget(copy_btn, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _copy(self, text: str, button: QPushButton) -> None:
        # Reports a failed clipboard write on the button — see copy_with_feedback.
        copy_with_feedback(text, button)

    # ------------------------------------------------------------------ state

    def _recording_state_text(self) -> str:
        """The hero headline of a running take, with its clock once one has
        ticked. Same wording and same `format_duration` as the tray and the
        floating icon, so the three surfaces cannot render one second three
        ways.

        The source is named while system audio is recording, and "speak now"
        drops with it: that take records what the computer plays, so telling
        the user to speak would ask for the one thing that is not being
        recorded."""
        system = self._source() == SOURCE_SYSTEM
        head = f"Recording {self._source_name(SOURCE_SYSTEM)}" if system else "Recording"
        if self._elapsed is not None:
            head = f"{head} {format_duration(self._elapsed)}"
        return head if system else f"{head} — speak now"

    def set_elapsed(self, seconds) -> None:
        """Count the running take up in the hero headline, once a second.

        The tray status and the floating icon have carried this clock since the
        take-length cap became visible on them; the Home hero — the biggest,
        most explicit recording control the app has, and the one open in front
        of someone who dictates from the window — kept a frozen "Recording"
        for the whole take. Fed by App's 100 ms poll through
        SettingsWindow.set_app_elapsed.

        Ignored unless a take is actually running: a tick that lands just after
        one ended must not re-label an idle hero with a stopped counter.
        """
        if self._state != "recording":
            return
        self._elapsed = seconds
        self.state_label.setText(self._recording_state_text())

    def _idle_hint(self, mode_hint: str) -> str:
        """The hero's idle line: which hotkey to press, and in which mode.

        With the second source off this is the single sentence it always was.
        With it on the first hotkey is named — two of them and an unqualified
        "the hotkey" leaves the reader guessing which one this page means — and
        one more sentence says what the other one does. Shortened to "the same
        way" when both run in the same mode, which is the default pair, so a
        summary does not spell one mode out twice.
        """
        if not self._system_setting("hotkey", ""):
            return f"Press the hotkey in any app. {mode_hint}"
        system_mode = self._system_setting("hotkey_mode", "toggle")
        plays = f"The {self._source_name(SOURCE_SYSTEM)} hotkey records what the computer plays"
        if system_mode == self.cfg["hotkey_mode"]:
            tail = f"{plays}, the same way."
        elif system_mode == "hold":
            tail = f"{plays} while the keys are held."
        else:
            tail = f"{plays} — press once to start, again to insert."
        return f"Press the {self._source_name(SOURCE_MIC)} hotkey in any app. {mode_hint} {tail}"

    def set_state(self, state: str) -> None:
        """Mirror the app state into the hero card. Called via
        SettingsWindow.set_app_state on every state transition."""
        previous, self._state = self._state, state
        # A new state owns a fresh clock: leaving "recording" drops the
        # counter, entering it starts from the wording without one until the
        # first tick arrives.
        self._elapsed = None
        if self._hero.property("state") != state:
            # Re-polish so the QSS picks up the state-dependent gradient.
            self._hero.setProperty("state", state)
            style = self._hero.style()
            for widget in (self._hero, self.record_button):
                style.unpolish(widget)
                style.polish(widget)
        mode_hint = (
            "Hold the keys while you speak — release to insert."
            if self.cfg["hotkey_mode"] == "hold"
            else "Press once to start, press again to insert."
        )
        if state == "recording":
            source = self._source()
            name = self._source_name(source)
            self.state_label.setText(self._recording_state_text())
            self.hint_label.setText("Stop to transcribe and insert the text at the cursor.")
            # Which take this stops belongs on the button, not only in the
            # headline: the microphone's label stays what it was, the second
            # source names itself so the parenthesis and the posted event
            # (see _toggle) always agree about what is being stopped.
            self.record_button.setText(
                "Stop && insert" if source == SOURCE_MIC else f"Stop && insert ({name})"
            )
            self.record_button.setToolTip(
                f"Stop the running {name} recording — the transcript is inserted "
                "at the cursor of the focused field."
            )
            self.record_button.setEnabled(True)
            self.cancel_button.setVisible(True)
        elif state == "processing":
            self.state_label.setText("Transcribing…")
            self.hint_label.setText("The text is inserted at the cursor in a moment.")
            self.record_button.setText("Transcribing…")
            self.record_button.setToolTip(_START_TOOLTIP)
            self.record_button.setEnabled(False)
            self.cancel_button.setVisible(False)
        else:
            self.state_label.setText("Ready to dictate")
            self.hint_label.setText(self._idle_hint(mode_hint))
            self.record_button.setText("Start recording")
            self.record_button.setToolTip(_START_TOOLTIP)
            self.record_button.setEnabled(True)
            self.cancel_button.setVisible(False)
            if previous in ("recording", "processing") and self.isVisible():
                # A finished recording may have added a transcript. Only on a
                # real transition — refresh() already rebuilt the list, and
                # entries() re-reads the history file each call. Only while
                # actually on screen: a closed window keeps receiving state
                # (App replaces it on the next open) and a background page is
                # refreshed by _on_page_changed when it is shown again.
                self._refresh_recent()
