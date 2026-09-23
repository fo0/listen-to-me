"""Qt hotkey capture dialog.

The Qt-key → pynput-token mapping lives in keymap.py (QtCore only, so it stays
testable headless). Tooltips are native via QWidget.setToolTip elsewhere.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .hotkeys import Hotkeys
from .keymap import MOD_ORDER, MODIFIER_KEY_TOKENS, allowed_standalone, key_token, pretty_keys

log = logging.getLogger(__name__)


class HotkeyCaptureDialog(QDialog):
    """Modal dialog: press the desired combination. A combo ending in a normal
    key is captured on that key press; a modifier-only combo (e.g. Ctrl+Alt) is
    confirmed with the OK button, or with Enter once the modifiers are released.
    Returns a pynput combo string or None."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_combo: str | None = None
        # Currently physically-held modifier tokens.
        self._held: list[str] = []
        # Snapshot of the held modifiers, kept even after release so a
        # modifier-only combo can be confirmed with OK.
        self._captured: list[str] = []

        self.setWindowTitle("Set hotkey")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)

        title = QLabel("Press the key combination you want to use.")
        title.setStyleSheet("font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._display = QLabel("…")
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display.setStyleSheet("font-size: 20px; padding: 8px;")
        layout.addWidget(self._display)

        hint = QLabel(
            "Hold the modifiers (Ctrl / Alt / Shift / Win), then press the final key —\n"
            "the combination is applied immediately. For a modifier-only combo\n"
            "(e.g. Ctrl + Alt) press the modifiers, release them and press Enter\n"
            "or click OK.  Esc cancels."
        )
        hint.setProperty("role", "hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._ok_button = QPushButton("OK")
        self._ok_button.setEnabled(False)
        self._ok_button.setProperty("accent", True)
        self._ok_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ok_button.clicked.connect(self._confirm)
        cancel = QPushButton("Cancel")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self._ok_button)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    @classmethod
    def ask(cls, parent=None) -> str | None:
        dialog = cls(parent)
        dialog.exec()
        return dialog.result_combo

    # ------------------------------------------------------------ events

    def event(self, e: QEvent) -> bool:
        # Intercept every key event (including Tab and app shortcuts) so any
        # combination can be captured instead of triggering focus moves.
        t = e.type()
        if t == QEvent.Type.KeyPress:
            self._on_press(e)
            return True
        if t == QEvent.Type.KeyRelease:
            self._on_release(e)
            return True
        if t == QEvent.Type.ShortcutOverride:
            e.accept()
            return True
        return super().event(e)

    def _on_press(self, e: QKeyEvent) -> None:
        if e.isAutoRepeat():
            return
        key = int(e.key())
        if key == int(Qt.Key.Key_Escape):
            self.reject()
            return
        if key in MODIFIER_KEY_TOKENS:
            token = MODIFIER_KEY_TOKENS[key]
            if token not in self._held:
                self._held.append(token)
            # Snapshot so a modifier-only combo survives the key release.
            self._captured = list(self._held)
            self._update_display()
            return
        if (
            key in (int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter))
            and not self._held
            and len(self._captured) >= 2
        ):
            # The keyboard's way to OK: both buttons are NoFocus (every key is
            # captured), so a modifier-only combo was mouse-only. Enter with a
            # modifier still held stays a capture ("Ctrl+Alt+Enter"), and a bare
            # Enter was always refused, so no combination is lost to this.
            self._confirm()
            return
        token = key_token(key, e.text())
        if token is None:
            self._set_display("(unsupported key — try another)", refusal=True)
            return
        mods = [m for m in MOD_ORDER if m in self._held]
        if not mods and not allowed_standalone(token):
            # A modifier-less printable/editing key would fire on ordinary typing.
            self._set_display(
                "(add a modifier — Ctrl / Alt / Shift / Win — or use an F-key)", refusal=True
            )
            return
        combo = "+".join(mods + [token])
        if not Hotkeys.validate(combo):
            self._set_display(f"({combo} is not a valid combination)", refusal=True)
            return
        self.result_combo = combo
        self.accept()

    def _on_release(self, e: QKeyEvent) -> None:
        if e.isAutoRepeat():
            return
        token = MODIFIER_KEY_TOKENS.get(int(e.key()))
        if token and token in self._held:
            self._held.remove(token)
            self._update_display()

    def _confirm(self) -> None:
        """Apply a modifier-only combo (e.g. Ctrl+Alt) selected via the OK button
        or Enter."""
        mods = [m for m in MOD_ORDER if m in self._captured]
        if len(mods) < 2:
            # A single modifier alone would fire on every ordinary keypress.
            self._set_display("(hold at least two modifiers — e.g. Ctrl + Alt)", refusal=True)
            return
        combo = "+".join(mods)
        if not Hotkeys.validate(combo):
            self._set_display(f"({combo} is not a valid combination)", refusal=True)
            return
        self.result_combo = combo
        self.accept()

    def _set_display(self, text: str, *, refusal: bool = False) -> None:
        """Show `text` in the big display line, styled as an error when it is a
        refusal. A refusal replaces the combination in the same 20 px line, and
        "(unsupported key — try another)" set like a captured "Ctrl + Alt + …"
        reads as a result; `QLabel[role="error"]` (theme.py) exists precisely
        so an inline failure cannot be mistaken for the text beside it."""
        self._display.setText(text)
        role = "error" if refusal else ""
        if self._display.property("role") != role:
            self._display.setProperty("role", role)
            # A dynamic property only restyles once the style re-polishes.
            self._display.style().unpolish(self._display)
            self._display.style().polish(self._display)

    def _update_display(self) -> None:
        mods = [m for m in MOD_ORDER if m in self._captured]
        # keymap.pretty_keys is the one key-cap renderer — the Home page, tray
        # and floating icon all go through it. Spelling the caps by hand here
        # made this the only surface showing the Windows key as "Cmd" while
        # every other one says "Win".
        pretty = " + ".join(pretty_keys("+".join(mods)))
        self._set_display((pretty + " + …") if pretty else "…")
        # Enable OK once a modifier-only combo (>= 2 modifiers) is selected.
        self._ok_button.setEnabled(len(mods) >= 2)
