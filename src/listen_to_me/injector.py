"""Insert text at the current cursor position of the focused window."""

from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger(__name__)


class Injector:
    def __init__(self, cfg):
        self.cfg = cfg

    def insert(self, text: str) -> None:
        if not text:
            return
        if self.cfg["injection_mode"] == "type":
            self._type(text)
        else:
            self._paste(text)
        log.info("inserted %d chars via %s", len(text), self.cfg["injection_mode"])

    def _type(self, text: str) -> None:
        from pynput.keyboard import Controller

        Controller().type(text)

    def _paste(self, text: str) -> None:
        import pyperclip
        from pynput.keyboard import Controller, Key

        previous = None
        if self.cfg["restore_clipboard"]:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None

        pyperclip.copy(text)
        time.sleep(0.15)  # give the clipboard time to settle

        keyboard = Controller()
        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with keyboard.pressed(modifier):
            keyboard.press("v")
            keyboard.release("v")

        if previous is not None:
            time.sleep(0.3)  # let the target application read the clipboard first
            try:
                pyperclip.copy(previous)
            except Exception:
                log.debug("could not restore clipboard", exc_info=True)
