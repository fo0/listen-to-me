"""Start-with-the-system integration for Windows, Linux and macOS."""

from __future__ import annotations

import logging
import os
import shlex
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


def _quote_join(args: list[str]) -> str:
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in args)


def _launch_command() -> str:
    return _quote_join(_launch_args())


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
    return stored_command() is not None


def stored_command() -> str | None:
    """The launch command the OS currently has on file for us.

    ``None`` means there is no autostart entry at all. An empty string means an
    entry exists but its command could not be read (corrupt or hand-edited
    file) — present but broken, which :func:`sync` repairs like a stale path.
    """
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as key:
                value, _kind = winreg.QueryValueEx(key, RUN_NAME)
        except FileNotFoundError:
            return None
        return str(value or "")
    if sys.platform == "darwin":
        path = _macos_plist_path()
        if not path.exists():
            return None
        import plistlib

        try:
            with open(path, "rb") as fh:
                data = plistlib.load(fh)
            return _quote_join([str(arg) for arg in data.get("ProgramArguments") or []])
        except Exception:
            log.warning("could not read the autostart plist %s", path, exc_info=True)
            return ""
    path = _linux_desktop_path()
    if not path.exists():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Exec="):
                return line[len("Exec="):].strip()
    except OSError:
        log.warning("could not read the autostart entry %s", path, exc_info=True)
    return ""


def needs_refresh() -> bool:
    """True when an autostart entry exists but would start the wrong program."""
    stored = stored_command()
    return stored is not None and _refresh_reason(stored) is not None


def sync(desired: bool) -> None:
    """Best-effort: make the OS autostart state match the config value.

    Runs at startup and after every settings save, so it doubles as the repair
    pass for an entry that outlived a program-file move (see
    :func:`_refresh_reason`); :func:`enable` overwrites on all three platforms.
    """
    try:
        stored = stored_command()
        if not desired:
            if stored is not None:
                disable()
        elif stored is None:
            enable()
        else:
            reason = _refresh_reason(stored)
            if reason:
                log.info("refreshing autostart entry — %s", reason)
                enable()
    except Exception:
        log.exception("could not update autostart state")


def _split_command(text: str) -> list[str]:
    """Split a stored command line back into its arguments.

    ``posix=False`` on Windows keeps backslashes intact (a posix split would eat
    them as escapes) at the price of leaving quotes on the tokens, hence the
    strip. A hand-edited entry with unbalanced quotes falls back to a plain
    whitespace split instead of raising.
    """
    try:
        parts = shlex.split(text or "", posix=sys.platform != "win32")
    except ValueError:
        parts = (text or "").split()
    return [stripped for part in parts if (stripped := part.strip('"'))]


def _normalized(parts: list[str]) -> list[str]:
    """Compare-friendly form: separators normalized, case folded on Windows."""
    return [os.path.normcase(os.path.normpath(part)) for part in parts]


def _refresh_reason(stored: str) -> str | None:
    """Why a *present* autostart entry must be rewritten — None when it may stay.

    Two situations are repaired automatically, both of them the aftermath of an
    update that changed where the program file lives:

    * the registered target no longer exists (exe renamed, moved or deleted) —
      the OS would start nothing at all, while Settings still shows the option
      as enabled, because the entry itself is still there;
    * registered target and ours are both frozen builds but different files (a
      manually downloaded ``ListenToMe-<date>-<time>-win64.exe`` dropped next to
      the old one) — the OS would keep starting the previous version.

    A *different kind* of launch whose target still exists is deliberately left
    alone: running from a source checkout must not hijack an installed build's
    entry, or vice versa. The in-app updater needs none of this — it moves the
    download onto the running exe's own path, so the registered command stays
    correct across a self-update.
    """
    stored_parts = _split_command(stored)
    current = _launch_args()
    if _normalized(stored_parts) == _normalized(current):
        return None
    if not stored_parts:
        return "the registered command is empty"
    target = Path(stored_parts[0])
    if not target.exists():
        return f"the registered program {target} no longer exists"
    if len(stored_parts) == 1 and len(current) == 1:
        # A single argument is our frozen-build form; a source launch always
        # carries "-m listen_to_me" on top of the interpreter path.
        return f"another build is registered ({target})"
    return None


def _linux_desktop_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "autostart" / "listen-to-me.desktop"


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.fo0.listen-to-me.plist"
