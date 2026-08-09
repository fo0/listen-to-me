"""Start-with-the-system integration for Windows, Linux and macOS.

Registering the entry is only half the job: every failure mode here is silent
by nature — the OS starts (or doesn't start) a program long after anyone is
watching, and a windowed build has no console to complain to. So everything
below is written to be *verifiable*: :func:`enable` reads its own write back,
:func:`sync` returns why the OS state still doesn't match the wish, and
:func:`describe` renders that state for the Settings page.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_NAME = "ListenToMe"
_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Windows keeps the on/off switch of "Task Manager → Startup apps" in a second
# key under the same value name. An entry disabled there is never started, and
# nothing in the Run key itself shows it — rewriting the Run value (which is
# all "enable autostart" used to do) does not clear it either.
_WIN_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"

_CREATE_NO_WINDOW = 0x08000000  # keeps the import probe from flashing a console
# The probe only starts an interpreter and imports our own tiny __init__, so it
# is a fraction of a second — but it runs on the Qt main thread during startup,
# and a timeout here would stall the whole app. Giving up early is free: an
# unfinished probe reports no problem at all.
_PROBE_TIMEOUT = 5

_probe_done = False  # module-level cache: the probe spawns a process
_probe_problem: str | None = None


class AutostartError(RuntimeError):
    """Registering with the OS did not take (and would have failed silently)."""


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


def _desktop_exec_value(args: list[str]) -> str:
    """`args` as a Desktop Entry ``Exec=`` value, escaped per the spec.

    ``%`` introduces field codes and must be doubled even inside quotes; an
    argument containing a reserved character is double-quoted with ``"``,
    ``` ` ```, ``$`` and ``\\`` backslash-escaped inside. Written unescaped, a
    path like ``~/100%projects/venv`` produces an entry the session never
    launches while reading it back compares healthy — the silent failure this
    module exists to prevent. :func:`stored_command` inverts the ``%%`` so the
    stored↔current compare keeps working.
    """
    reserved = " \t\n\"'\\><~|&;$*?#()`"
    parts = []
    for arg in args:
        escaped = arg
        if any(ch in escaped for ch in reserved):
            inner = (
                escaped.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("$", "\\$")
                .replace("`", "\\`")
            )
            escaped = f'"{inner}"'
        parts.append(escaped.replace("%", "%%"))
    return " ".join(parts)


def _launch_command() -> str:
    return _quote_join(_launch_args())


def enable(clear_block: bool = True) -> None:
    """Register the app with the OS autostart.

    ``clear_block`` also switches a Windows entry that was turned off in Task
    Manager → Startup apps back on. It is the user's explicit save that does
    that (see :func:`sync`) — an app silently re-enabling itself behind the OS
    switch on every start would be exactly the wrong kind of persistent.

    Raises :class:`AutostartError` when the entry is not readable back
    afterwards: a write that quietly does nothing looks identical to a working
    registration until the next reboot doesn't start the app.
    """
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
        if clear_block:
            _clear_os_block()
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
            f"Exec={_desktop_exec_value(_launch_args())}\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    stored = stored_command()
    if not stored:
        raise AutostartError("the entry could not be written")
    log.info("autostart enabled (%s)", stored)


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
                # Undo the field-code doubling of _desktop_exec_value; the
                # quoting/backslashes are undone by _split_command (shlex).
                return line[len("Exec="):].strip().replace("%%", "%")
    except OSError:
        log.warning("could not read the autostart entry %s", path, exc_info=True)
    return ""


def sync(desired: bool, repair_block: bool = False) -> str | None:
    """Best-effort: make the OS autostart state match the config value.

    Runs at startup and after every settings save, so it doubles as the repair
    pass for an entry that outlived a program-file move (see
    :func:`_refresh_reason`); :func:`enable` overwrites on all three platforms.

    Returns ``None`` when the app will really be started at the next logon, or
    a short user-facing reason why it will not. The caller surfaces that —
    "enabled in Settings, absent after the reboot" was the failure this whole
    module has to make impossible to hit silently.

    ``repair_block`` is set by the settings save (an explicit user action) and
    additionally re-enables an entry that Windows had switched off.
    """
    try:
        stored = stored_command()
        if not desired:
            if stored is not None:
                disable()
            return None
        reason = "no entry was registered" if stored is None else _refresh_reason(stored)
        if reason is None and repair_block and blocked():
            reason = "Windows had switched the entry off"
        if reason:
            # The reason names only the file (it is shown in Settings), so the
            # full previous command goes into the log for debugging.
            log.info("writing the autostart entry — %s (was: %s)", reason, stored or "nothing")
            enable(clear_block=repair_block)
        return _blocking_problem()
    except Exception as exc:
        log.exception("could not update autostart state")
        return f"the entry could not be written ({exc})"


def _blocking_problem() -> str | None:
    """What still stands between a registered entry and a running app."""
    if blocked():
        return (
            "Windows has it switched off in Task Manager → Startup apps. "
            "Save the settings again to switch it back on"
        )
    return launch_problem()


def blocked() -> bool:
    """Windows only: the entry exists but is switched off in Task Manager →
    Startup apps. The Run value looks perfectly healthy in that state — this
    flag alone decides whether Windows ever starts it."""
    return _is_blocked(_approved_flag())


def _approved_flag() -> bytes | None:
    """The raw StartupApproved record for our entry (None = no record, which
    Windows reads as enabled)."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_APPROVED_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_NAME)
    except FileNotFoundError:
        return None  # neither the key nor the value has to exist
    except OSError:
        log.warning("could not read the startup approval state", exc_info=True)
        return None
    return bytes(value) if isinstance(value, (bytes, bytearray)) else None


def _is_blocked(flag: bytes | None) -> bool:
    """Decode a StartupApproved record: the first byte carries the state, even
    = enabled (2, 6), odd = disabled (3, 5, 9 — by the user or by Windows).
    The remaining bytes are a FILETIME of the last change, which we neither
    read nor have to write."""
    return bool(flag) and flag[0] % 2 == 1


def _clear_os_block() -> None:
    """Drop the StartupApproved record so Windows starts the entry again.

    Deleting is deliberate: no record at all is the state of every freshly
    added Run entry, so we don't have to fabricate the enabled-with-timestamp
    bytes Task Manager writes."""
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _WIN_APPROVED_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except FileNotFoundError:
        return  # no key, no value — nothing was blocking us
    except OSError:
        log.warning("could not clear the startup approval state", exc_info=True)
        return
    log.info("cleared the Windows startup block for %s", RUN_NAME)


def launch_problem() -> str | None:
    """Why the registered command would not actually start the app.

    Only a source checkout can get this wrong, and it does so invisibly: with
    ``PYTHONPATH=src python -m listen_to_me`` the package is importable in
    *this* process only. The OS starts the registered command with a bare
    environment, the import fails, and a windowed interpreter has no console to
    show the traceback in — logging in simply does nothing.

    Probed by asking the interpreter itself (once per process, never for a
    frozen build). ``None`` also means "could not tell" — never block enabling
    autostart over a probe that didn't run.
    """
    global _probe_done, _probe_problem

    if getattr(sys, "frozen", False) or not sys.executable:
        return None
    if _probe_done:
        return _probe_problem
    _probe_done = True
    env = {key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"}
    kwargs = {"creationflags": _CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        # cwd = the interpreter's own folder: `-c` puts the working directory
        # on sys.path, which would import the very checkout we are testing for.
        result = subprocess.run(
            [sys.executable, "-c", "import listen_to_me"],
            env=env,
            cwd=str(Path(sys.executable).parent),
            capture_output=True,
            timeout=_PROBE_TIMEOUT,
            **kwargs,
        )
    except Exception:
        log.debug("could not probe whether the app is importable", exc_info=True)
        return None
    if result.returncode != 0:
        _probe_problem = (
            "a bare interpreter cannot import the app, so the registered command "
            "would start nothing. Install it into the environment "
            "(pip install -e .) or use the packaged build"
        )
        log.warning("autostart would not work from here: %s", _probe_problem)
    return _probe_problem


def describe(desired: bool) -> tuple[bool, str]:
    """(healthy, one-line status) of the OS autostart entry for the UI.

    An empty string means "nothing worth saying" — no entry, and none wanted.
    Program paths are shortened to their file name: a full Windows path has no
    spaces to wrap at, and a label that cannot wrap sets a minimum width the
    scroll area honours — which silently clips every card on the page at the
    right edge. The caller shows the full command as a tooltip instead.
    """
    try:
        stored = stored_command()
        where = _os_label()
        if stored is None and not desired:
            return True, ""  # nothing registered, nothing wanted
        problem = _blocking_problem()
        if stored is None:
            if problem:
                return False, f"⚠ {problem[0].upper()}{problem[1:]}."
            return True, f"Not registered with {where} yet — save to register."
        if problem:
            return False, f"⚠ Registered, but {problem}."
        reason = _refresh_reason(stored)
        if reason:
            return False, f"⚠ The registered entry is stale — {reason}. Save to repair it."
        if not desired:
            return True, f"Still registered with {where} — save to remove the entry."
        return True, f"Registered with {where}: {short_command(stored)}"
    except Exception:
        log.debug("could not describe the autostart state", exc_info=True)
        return True, ""


def short_command(text: str) -> str:
    """A stored command with the program path reduced to its file name.

    ``"C:\\…\\ListenToMe.exe"`` → ``ListenToMe.exe``, and a source launch stays
    recognizable as ``pythonw.exe -m listen_to_me``. Enough to tell which build
    is registered without dragging a 200 px path into the layout.
    """
    parts = _split_command(text)
    if not parts:
        return text.strip()
    return " ".join([Path(parts[0]).name, *parts[1:]])


def _os_label() -> str:
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    return "your desktop session"


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
        # File name only: the reason is shown in the Settings status line, and
        # a full path there cannot wrap (see describe()). The complete command
        # stays in the log and in the label's tooltip.
        return f"the registered program {target.name} no longer exists"
    if len(stored_parts) == 1 and len(current) == 1:
        # A single argument is our frozen-build form; a source launch always
        # carries "-m listen_to_me" on top of the interpreter path.
        return f"another build is registered ({target.name})"
    return None


def _linux_desktop_path() -> Path:
    # `or`, not a .get() default: a set-but-empty XDG_CONFIG_HOME counts as
    # unset per the XDG spec — Path("") would target a CWD-relative autostart/
    # directory that no session ever reads.
    base = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    return base / "autostart" / "listen-to-me.desktop"


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.fo0.listen-to-me.plist"
