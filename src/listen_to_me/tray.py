"""System tray icon and menu (QSystemTrayIcon)."""

from __future__ import annotations

import logging
import webbrowser

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import APP_NAME, REPO_URL
from .qtutil import tray_icon

log = logging.getLogger(__name__)

_STATE_LABELS = {
    "idle": "Idle — press the hotkey to record",
    "recording": "Recording…",
    "processing": "Transcribing…",
}


class Tray:
    def __init__(self, app):
        self.app = app
        self._icon = None
        self._menu = None
        self._act_state = None
        self._act_toggle = None
        self._act_cancel = None
        self._act_overlay = None

    def start(self) -> None:
        app = self.app
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("no system tray available — tray icon/menu will not be shown")

        self._icon = QSystemTrayIcon(tray_icon("idle"))
        self._icon.setToolTip(f"{APP_NAME} — {_STATE_LABELS['idle']}")

        menu = QMenu()
        self._menu = menu

        self._act_state = QAction(_STATE_LABELS["idle"], menu)
        self._act_state.setEnabled(False)
        menu.addAction(self._act_state)
        menu.addSeparator()

        self._act_toggle = QAction("Start recording", menu)
        self._act_toggle.triggered.connect(lambda: app.post("toggle"))
        menu.addAction(self._act_toggle)

        self._act_cancel = QAction("Cancel recording", menu)
        self._act_cancel.triggered.connect(lambda: app.post("cancel"))
        self._act_cancel.setVisible(False)
        menu.addAction(self._act_cancel)
        menu.addSeparator()

        self._act_overlay = QAction("Show floating icon", menu)
        self._act_overlay.setCheckable(True)
        self._act_overlay.setChecked(bool(app.cfg["overlay"]["enabled"]))
        self._act_overlay.triggered.connect(lambda: app.post("toggle_overlay"))
        menu.addAction(self._act_overlay)

        act_settings = QAction("Settings…", menu)
        act_settings.triggered.connect(lambda: app.post("settings"))
        menu.addAction(act_settings)

        act_updates = QAction("Check for updates…", menu)
        act_updates.triggered.connect(lambda: app.post("updates"))
        menu.addAction(act_updates)

        act_config = QAction("Open config folder", menu)
        act_config.triggered.connect(lambda: app.post("open_config"))
        menu.addAction(act_config)

        act_project = QAction("Project page", menu)
        act_project.triggered.connect(lambda: webbrowser.open(REPO_URL))
        menu.addAction(act_project)

        act_help = QAction("Help / Troubleshooting", menu)
        act_help.triggered.connect(lambda: app.post("help"))
        menu.addAction(act_help)
        menu.addSeparator()

        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(lambda: app.post("quit"))
        menu.addAction(act_quit)

        self._icon.setContextMenu(menu)
        # Left click / double click the tray icon: start/stop like the default item.
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    def _on_activated(self, reason) -> None:
        # Double-click only (matches the original tray default action) so a
        # stray single left-click doesn't start a recording.
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.app.post("toggle")

    def set_state(self, state: str) -> None:
        if self._icon is None:
            return
        label = _STATE_LABELS.get(state, state)
        self._icon.setIcon(tray_icon(state))
        self._icon.setToolTip(f"{APP_NAME} — {label}")
        self._act_state.setText(label)
        self._act_toggle.setText(
            "Stop recording (insert text)" if state == "recording" else "Start recording"
        )
        self._act_cancel.setVisible(state == "recording")
        self._act_overlay.setChecked(bool(self.app.cfg["overlay"]["enabled"]))

    def notify(self, message: str, force: bool = False) -> None:
        """Show a desktop notification. `force` bypasses the user setting (errors)."""
        if self._icon is None:
            return
        if not force and not self.app.cfg["notifications"]:
            return
        try:
            self._icon.showMessage(APP_NAME, message)
        except Exception:
            log.debug("notification failed", exc_info=True)

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.hide()
            except Exception:
                log.debug("error hiding tray icon", exc_info=True)
