"""Start-with-the-system integration for Windows, Linux and macOS."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_NAME = "ListenToMe"
_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_args() -> list[str]:
    if getattr(sys, "frozen", False):  # PyInstaller build
        return [sys.executable]
    python = Path(sys.executable)
    if sys.platform == "win32" and python.name.lower() == "python.exe":
        windowless = python.with_name("pythonw.exe")
        if windowless.exists():
            python = windowless
    return [str(python), "-m", "listen_to_me"]


def _launch_command() -> str:
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in _launch_args())


def enable() -> None:
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
    elif sys.platform == "darwin":
        import plistlib

        path = _macos_plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            plistlib.dump(
                {
                    "Label": "com.fo0.listen-to-me",
                    "ProgramArguments": _launch_args(),
                    "RunAtLoad": True,
                },
                fh,
            )
    else:
        path = _linux_desktop_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Listen To Me\n"
            f"Exec={_launch_command()}\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    log.info("autostart enabled")


def disable() -> None:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass
    elif sys.platform == "darwin":
        _macos_plist_path().unlink(missing_ok=True)
    else:
        _linux_desktop_path().unlink(missing_ok=True)
    log.info("autostart disabled")


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as key:
                winreg.QueryValueEx(key, RUN_NAME)
            return True
        except FileNotFoundError:
            return False
    if sys.platform == "darwin":
        return _macos_plist_path().exists()
    return _linux_desktop_path().exists()


def sync(desired: bool) -> None:
    """Best-effort: make the OS autostart state match the config value."""
    try:
        if desired and not is_enabled():
            enable()
        elif not desired and is_enabled():
            disable()
    except Exception:
        log.exception("could not update autostart state")


def _linux_desktop_path() -> Path:
    import os

    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "autostart" / "listen-to-me.desktop"


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.fo0.listen-to-me.plist"
