"""System tray icon and menu (QSystemTrayIcon)."""

from __future__ import annotations

import logging
import webbrowser

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import APP_NAME, REPO_URL
from .history import entry_timestamp
from .keymap import hotkey_label
from .qtutil import tray_icon

log = logging.getLogger(__name__)

# How many of the latest transcripts the tray lists, and how much of one fits
# on a menu line before it is elided.
_RECENT_LIMIT = 5
_RECENT_CHARS = 56

# Started from the OS autostart, the app can be up before the shell's
# notification area is: the icon is then silently dropped and never appears.
_RETRY_MS = 2000
_RETRY_LIMIT = 30  # ~1 minute of logging in is enough for any machine

_STATE_LABELS = {
    "idle": "Idle — press the hotkey to record",
    "recording": "Recording…",
    "processing": "Transcribing…",
}

# Shown instead of the idle status while the global hotkey is suspended: an app
# that looks idle while its hotkey does nothing is indistinguishable from a
# broken one, and this line is the first place anyone looks.
_PAUSED_LABEL = "Hotkey paused — switch it back on in this menu"


def format_duration(seconds) -> str:
    """`seconds` as ``m:ss`` — ``h:mm:ss`` once a take passes the hour.

    Deliberately unshakeable about its input: it renders a value derived from a
    clock into a label that is rebuilt every second inside the app's poll
    timer, and a status line must never be the thing that raises there. A
    negative value (a clock read before the take was stamped) and anything
    unusable read 0:00.
    """
    try:
        total = int(float(seconds))
    except (TypeError, ValueError, OverflowError):
        return "0:00"
    total = max(0, total)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def recent_entry_label(entry: dict, max_chars: int = _RECENT_CHARS) -> str:
    """One menu line for a stored transcript: its text on a single line, elided.

    A menu item is one line whatever the dictation did, so the line breaks a
    dictated paragraph carries are folded into spaces rather than dropping the
    text after the first one. Qt reads a single ``&`` as the mnemonic marker
    and would swallow it while underlining the next letter — the entry would
    then advertise text it does not contain, so every ``&`` is doubled.

    str(): history.json is untrusted input and the store's own normalization
    is not this function's to assume.
    """
    text = " ".join(str(entry.get("text", "")).split())
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text.replace("&", "&&")


def state_label(state: str, cfg, elapsed=None, paused: bool = False) -> str:
    """The tray's one-line status, naming the combination that acts on it.

    "Press the hotkey" is the one thing the tray can't assume the user knows:
    it is configurable, it was chosen once in a wizard, and the tray icon is
    exactly where someone looks after forgetting it. Spelling it out costs a
    lookup per state change and saves opening the settings window.

    `elapsed` (seconds) puts the running take's clock into the recording
    status, `paused` replaces the idle status while the global hotkey is
    suspended. Both are opt-in per call rather than read from the app, so every
    caller that only knows the state keeps the wording it always had — and so
    the label stays a pure function of its arguments.

    Falls back to the generic wording when the combination can't be rendered
    (an empty or unusable `hotkey` in the config) — never to a raw pynput
    token in the middle of a sentence.
    """
    if paused and state == "idle":
        # Naming the hotkey here would be a lie: pressing it does nothing.
        return _PAUSED_LABEL
    generic = _STATE_LABELS.get(state, state)
    if state == "recording" and elapsed is not None:
        # A speaker has no clock, and the take has a cap: without this the only
        # feedback about a running recording was the heads-up 30 s before it.
        generic = f"Recording {format_duration(elapsed)}…"
    if state not in ("idle", "recording"):
        return generic
    try:
        combo = hotkey_label(cfg["hotkey"])
        hold = cfg["hotkey_mode"] == "hold"
    except Exception:
        log.debug("could not render the hotkey for the tray status", exc_info=True)
        return generic
    if not combo:
        return generic
    if state == "recording":
        # Hold mode stops on release, so "press it again" would be wrong.
        return f"{generic} {'release' if hold else 'press'} {combo} to stop"
    return f"Idle — press {combo} to record"


class Tray:
    def __init__(self, app):
        self.app = app
        self._icon = None
        self._menu = None
        self._act_state = None
        self._act_toggle = None
        self._act_cancel = None
        self._act_pause = None
        self._act_overlay = None
        self._recent_menu = None
        self._retry_timer = None
        self._retries = 0
        # Text of a running download; while set it owns the tooltip and
        # the status line (see set_progress).
        self._progress: str | None = None

    def start(self) -> None:
        app = self.app
        idle_label = state_label("idle", app.cfg)
        self._icon = QSystemTrayIcon(tray_icon("idle"))
        self._icon.setToolTip(f"{APP_NAME} — {idle_label}")

        menu = QMenu()
        self._menu = menu

        self._act_state = QAction(idle_label, menu)
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

        act_copy = QAction("Copy last transcript", menu)
        act_copy.setToolTip("Put the text of the most recent recording back on the clipboard.")
        act_copy.triggered.connect(lambda: app.post("copy_last"))
        menu.addAction(act_copy)

        # …and the ones before it. Reaching the second-newest transcript meant
        # opening Settings and walking the sidebar to History — four steps for
        # a dictation that is two minutes old.
        self._recent_menu = QMenu("Recent transcripts", menu)
        self._recent_menu.setToolTipsVisible(True)
        # Filled when it opens, not when it is built: the recording worker
        # appends to the history while this menu sits idle, so a list built at
        # startup would be stale within one dictation.
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        act_recent = menu.addMenu(self._recent_menu)
        act_recent.setToolTip("Copy any of the last few transcripts back to the clipboard.")
        # QMenu ignores its actions' tooltips unless asked — without this the
        # hints above would exist but never render on any platform.
        menu.setToolTipsVisible(True)
        menu.addSeparator()

        self._act_pause = QAction("Pause hotkey", menu)
        self._act_pause.setCheckable(True)
        self._act_pause.setChecked(bool(getattr(app, "hotkey_paused", False)))
        self._act_pause.setToolTip(
            "Stop the global hotkey from firing until you switch it back on — "
            "for a game or another app that needs the same keys. The "
            "combination itself is kept, and the pause is forgotten on restart."
        )
        self._act_pause.triggered.connect(lambda: app.post("toggle_hotkey_pause"))
        menu.addAction(self._act_pause)

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
        act_project.triggered.connect(self._open_project_page)
        menu.addAction(act_project)

        act_help = QAction("Help / Troubleshooting", menu)
        act_help.triggered.connect(lambda: app.post("help"))
        menu.addAction(act_help)
        menu.addSeparator()

        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(lambda: app.post("quit"))
        menu.addAction(act_quit)

        self._icon.setContextMenu(menu)
        # Left click / double click the tray icon: open the main window.
        self._icon.activated.connect(self._on_activated)
        self._icon.show()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning(
                "no system tray available yet — retrying for %d s",
                _RETRY_MS * _RETRY_LIMIT // 1000,
            )
            self._retries = 0
            self._retry_timer = QTimer()
            self._retry_timer.timeout.connect(self._retry_show)
            self._retry_timer.start(_RETRY_MS)

    def _fill_recent_menu(self) -> None:
        """(Re-)build the "Recent transcripts" submenu from the history file.

        Runs on the Qt main thread every time the submenu opens. A history that
        cannot be read is named as such instead of showing an empty list: an
        app that offers nothing looks the same as one that stored nothing,
        which is the one thing this must not do.
        """
        menu = self._recent_menu
        if menu is None:
            return
        menu.clear()
        try:
            entries = self.app.history.entries()[:_RECENT_LIMIT]
        except Exception:
            log.exception("could not read the transcript history for the tray menu")
            failed = menu.addAction("Could not read the history")
            failed.setEnabled(False)
            return
        if not entries:
            empty = menu.addAction("No transcripts yet")
            empty.setEnabled(False)
            return
        for entry in entries:
            text = str(entry.get("text", ""))
            action = menu.addAction(recent_entry_label(entry))
            stamp = entry_timestamp(entry)
            # The label is elided and stripped of its line breaks — the tooltip
            # carries when it was dictated, which is how two similar-looking
            # transcripts are told apart.
            action.setToolTip(
                f"{stamp} — copy this transcript" if stamp else "Copy this transcript"
            )
            action.triggered.connect(
                lambda _checked=False, t=text: self.app.post("copy_text", t)
            )

    def _open_project_page(self) -> None:
        # The settings footer reports a failed browser launch — the tray entry
        # must not stay a silent no-op either (no handler registered, or
        # BROWSER pointing nowhere).
        if not webbrowser.open(REPO_URL):
            self.app.notify(f"Could not open the browser — visit {REPO_URL}", force=True)

    def _retry_show(self) -> None:
        """Re-add the icon once the notification area exists.

        At logon the app (started by the OS autostart) can beat the shell to
        it: the icon is dropped, `show()` above was a no-op and the app runs
        with no visible sign at all — the classic "it's not there after a
        reboot". Qt reports isVisible() == True either way, so the tray
        availability is what we poll, and hide()/show() forces a fresh
        registration instead of a no-op.
        """
        self._retries += 1
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._stop_retry()
            try:
                self._icon.hide()
                self._icon.show()
                self.set_state(self.app.state)
                # Inside the try: logged after a *successful* re-add only — a
                # success line next to the failure above would mislead exactly
                # the "icon isn't there after reboot" diagnosis.
                log.info("system tray became available — icon re-added")
            except Exception:
                log.debug("re-adding the tray icon failed", exc_info=True)
            return
        if self._retries >= _RETRY_LIMIT:
            self._stop_retry()
            log.warning("still no system tray — falling back to a window")
            try:
                if not self.app.cfg["overlay"]["enabled"]:
                    # Without tray icon and without the floating icon there is
                    # nothing left to see: open the main window so the app is
                    # reachable at all.
                    self.app.post("settings")
            except Exception:
                log.debug("tray fallback failed", exc_info=True)

    def _stop_retry(self) -> None:
        if self._retry_timer is not None:
            self._retry_timer.stop()
            self._retry_timer = None

    def _on_activated(self, reason) -> None:
        """Left-click or double-click the icon: open the main window.

        Both reasons, not one of them — Windows delivers a double-click as
        Trigger followed by DoubleClick, and someone who "clicks the icon"
        means the same thing either way. `_open_settings` raises an already
        open window instead of building a second one, so the duplicate event
        costs nothing.

        This used to toggle a recording. Starting one is what the hotkey is
        for: it fires from whatever field the text should land in, whereas
        reaching for the tray has already moved the focus away from it. A stray
        click that silently starts a take is the worse of the two failure
        modes, so the click opens the window and the menu's "Start recording"
        stays the explicit route.

        The floating icon (`overlay.py`) deliberately keeps the toggle on its
        left click, and that is not an inconsistency to iron out: it is built
        not to accept focus, so clicking it leaves the caret in the field the
        transcript is meant for. The tray icon has no such guarantee — the
        shell's notification area takes the activation.
        """
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.app.post("settings")

    def set_state(self, state: str) -> None:
        if self._icon is None:
            return
        # Rebuilt on every state change rather than cached, so a hotkey changed
        # in the settings shows up here as soon as apply_settings() calls in.
        paused = self._paused()
        label = state_label(state, self.app.cfg, paused=paused)
        self._icon.setIcon(tray_icon(state))
        # A download outlives the state change that started it (the model is
        # fetched during "processing"), so it keeps the line it is on.
        self._icon.setToolTip(f"{APP_NAME} — {self._progress or label}")
        self._act_state.setText(self._progress or label)
        self._act_toggle.setText(
            "Stop recording (insert text)" if state == "recording" else "Start recording"
        )
        self._act_cancel.setVisible(state == "recording")
        # Re-read rather than left to the click that toggled it: App refuses to
        # pause during a recording, and the tick must then go back where it was.
        self._act_pause.setChecked(paused)
        self._act_overlay.setChecked(bool(self.app.cfg["overlay"]["enabled"]))

    def _paused(self) -> bool:
        """Whether the app currently has its global hotkey suspended. getattr:
        the self-test's App stub predates the flag and only knows the state."""
        return bool(getattr(self.app, "hotkey_paused", False))

    def set_elapsed(self, seconds) -> None:
        """Put the running take's clock into the status line and the tooltip.

        Separate from `set_state` because this runs once a second: set_state
        also rebuilds the tray icon and every menu label, none of which the
        clock changes. Reads the state back from the app so a tick that arrives
        just after a recording ended renders the new state's wording instead of
        a frozen counter.
        """
        if self._icon is None or self._act_state is None:
            return
        label = state_label(
            self.app.state, self.app.cfg, elapsed=seconds, paused=self._paused()
        )
        self._icon.setToolTip(f"{APP_NAME} — {self._progress or label}")
        self._act_state.setText(self._progress or label)

    def set_progress(self, text: str | None) -> None:
        """Show a running download in the tooltip and the status line, or drop
        it and go back to the state wording (#110).

        The floating icon can be switched off, and the tray is then the only
        place a multi-minute model download is visible at all.

        Only the two lines that change are touched — this fires a couple of
        times a second for minutes, and set_state() re-renders the tray icon
        through Pillow and rebuilds every menu label on each call. The end of
        the download goes through set_state once, to restore all of it.
        """
        self._progress = text or None
        if self._icon is None:
            return
        if self._progress is None:
            self.set_state(self.app.state)
            return
        self._icon.setToolTip(f"{APP_NAME} — {self._progress}")
        if self._act_state is not None:
            self._act_state.setText(self._progress)

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
        self._stop_retry()
        if self._icon is not None:
            try:
                self._icon.hide()
            except Exception:
                log.debug("error hiding tray icon", exc_info=True)
