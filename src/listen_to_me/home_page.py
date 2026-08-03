"""Home page: the entry hub of the main window.

Shows the live recording state with a start/stop control, the configured
hotkey as key caps, an at-a-glance summary of the active setup (engine/model,
language, microphone), quick actions into the relevant settings pages and the
most recent transcripts. Pure presentation: every action either posts an
event to App (start/stop/cancel) or navigates the owning window's sidebar —
no state of its own beyond the widgets.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QTimer
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

from .choices import SYSTEM_DEFAULT_DEVICE, input_device_choices, language_label
from .glyphs import glyph_icon
from .keymap import pretty_keys
from .qtutil import copy_to_clipboard

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
        left.addStretch(1)
        hv.addLayout(left, 1)

        buttons = QVBoxLayout()
        buttons.addStretch(1)
        self.record_button = QPushButton("Start recording")
        self.record_button.setObjectName("recordBtn")
        self.record_button.setAutoDefault(False)
        self.record_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_button.setToolTip(
            "Start a recording now — same as pressing the global hotkey. "
            "The text is inserted at the cursor of the focused field."
        )
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
        self.card_model = _StatCard("Engine & model", lambda: window._show_page("Whisper"))
        self.card_language = _StatCard("Language", lambda: window._show_page("General"))
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
            ("wave", "Model && engine", "Whisper", "Choose the speech model, backend and device."),
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

    def _toggle(self) -> None:
        """Post the start/stop toggle, debounced: a double-click emits two
        clicked signals before the 100 ms event poll runs, which would queue
        start + stop back to back and end in "Recording too short"."""
        now = time.monotonic()
        if now - self._last_toggle < 0.4:
            return
        self._last_toggle = now
        self._app.post("toggle")

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Re-read config + history into the cards. Called when the page is
        shown, after settings were applied and when a recording finished."""
        self._refresh_chips()
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

    def _refresh_chips(self) -> None:
        self._clear_layout(self._chips_row)
        for cap in pretty_keys(self.cfg["hotkey"]):
            chip = QLabel(cap)
            chip.setObjectName("keycap")
            self._chips_row.addWidget(chip)

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

    def _refresh_recent(self) -> None:
        self._clear_layout(self._recent_layout)
        entries = []
        try:
            entries = self._app.history.entries()[:_RECENT_LIMIT]
        except Exception:
            log.exception("could not read the transcript history")
        if not entries:
            empty = QLabel("No transcripts yet — your dictations will show up here.")
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
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(text_label)
        rh.addLayout(body, 1)
        copy_btn = QPushButton("Copy")
        copy_btn.setAutoDefault(False)
        copy_btn.setToolTip("Put the full transcript back on the clipboard.")
        copy_btn.clicked.connect(lambda _checked=False, t=raw, b=copy_btn: self._copy(t, b))
        rh.addWidget(copy_btn, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _copy(self, text: str, button: QPushButton) -> None:
        if not text:
            return
        if copy_to_clipboard(text):
            button.setText("Copied ✓")

            def restore():
                try:  # the window (and this button) may be gone by now
                    button.setText("Copy")
                except RuntimeError:
                    pass

            QTimer.singleShot(1200, restore)

    # ------------------------------------------------------------------ state

    def set_state(self, state: str) -> None:
        """Mirror the app state into the hero card. Called via
        SettingsWindow.set_app_state on every state transition."""
        previous, self._state = self._state, state
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
            self.state_label.setText("Recording — speak now")
            self.hint_label.setText("Stop to transcribe and insert the text at the cursor.")
            self.record_button.setText("Stop && insert")
            self.record_button.setEnabled(True)
            self.cancel_button.setVisible(True)
        elif state == "processing":
            self.state_label.setText("Transcribing…")
            self.hint_label.setText("The text is inserted at the cursor in a moment.")
            self.record_button.setText("Transcribing…")
            self.record_button.setEnabled(False)
            self.cancel_button.setVisible(False)
        else:
            self.state_label.setText("Ready to dictate")
            self.hint_label.setText(f"Press the hotkey in any app. {mode_hint}")
            self.record_button.setText("Start recording")
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
