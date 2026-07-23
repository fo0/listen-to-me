"""Single-instance guard plus a tiny loopback "show yourself" channel.

Why the guard is no longer the TCP port bind it used to be: on Windows
machines with Hyper-V/WSL/Docker, chunks of the ephemeral port range are
reserved as "administered port exclusions" (`netsh int ipv4 show
excludedportrange`). A bind() inside such a range can fail although nothing
is running — the app then refused to start, silently in a --windowed build —
or, worse, *succeed for several processes at once*, which let several
instances run side by side. Kernel primitives have exact semantics instead:
a named mutex on Windows, an flock()-ed file in the config dir on POSIX.

The loopback socket remains, but only as the channel through which a second
launch tells the running instance to show itself (settings window + overlay
re-assert). Losing the port degrades that ping — never the guard itself.

Qt-free by design so the guard is exercisable by the headless self-test.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

PORT = 52697  # the former lock port, now only the activate-ping channel
_MUTEX_NAME = "ListenToMe.SingleInstance"
_LOCK_FILENAME = "instance.lock"
# The token identifies our own app on the port: anything else that happens to
# own or probe the port (port scanners, a foreign app) never triggers a ping.
_ACTIVATE_TOKEN = b"LISTEN-TO-ME ACTIVATE\n"
_PING_TIMEOUT = 2.0
_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Holds the OS-level claim for the process lifetime and (optionally)
    serves activation pings from later launches."""

    def __init__(self, port: int, mutex_handle=None, lock_file=None):
        self._port = port
        self._mutex = mutex_handle  # Windows: kernel mutex HANDLE
        self._lock_file = lock_file  # POSIX: open + flock()-ed file object
        self._server: socket.socket | None = None

    def start_server(self, on_activate) -> int | None:
        """Listen for activation pings from later launches.

        `on_activate` runs on the accept thread — pass something thread-safe
        (e.g. ``lambda: app.post("activate")``). Returns the bound port, or
        None when the port is unavailable (the guard itself still holds)."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", self._port))
            server.listen(2)
        except OSError:
            log.warning(
                "activation port %d is unavailable (reserved or in use) — a "
                "second launch cannot bring this instance to the front",
                self._port,
            )
            try:
                server.close()
            except OSError:
                pass
            return None
        self._server = server
        threading.Thread(
            target=self._serve, args=(server, on_activate), name="single-instance", daemon=True
        ).start()
        return server.getsockname()[1]

    @staticmethod
    def _serve(server: socket.socket, on_activate) -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return  # socket closed by release() / interpreter teardown
            try:
                conn.settimeout(_PING_TIMEOUT)
                data = b""
                while len(data) < len(_ACTIVATE_TOKEN):
                    chunk = conn.recv(len(_ACTIVATE_TOKEN) - len(data))
                    if not chunk:
                        break
                    data += chunk
                if data == _ACTIVATE_TOKEN:
                    conn.sendall(b"OK\n")
                    on_activate()
                else:
                    log.debug("ignoring a foreign connection on the activation port")
            except Exception:
                log.debug("handling an activation ping failed", exc_info=True)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def release(self) -> None:
        """Free the claim early (used by tests; at runtime the OS releases
        everything when the process exits)."""
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._lock_file is not None:
            try:
                self._lock_file.close()
            except OSError:
                pass
            self._lock_file = None
        if self._mutex is not None:
            try:
                import ctypes

                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._mutex)
            except Exception:
                log.debug("closing the instance mutex failed", exc_info=True)
            self._mutex = None


def acquire(
    port: int = PORT,
    lock_dir: Path | None = None,
    mutex_name: str = _MUTEX_NAME,
) -> SingleInstance | None:
    """Claim single-instance ownership (keep the returned object alive for the
    whole process). Returns None when another instance already owns the claim —
    that instance has then been pinged to show itself.

    If the OS primitive itself is unavailable (mutex creation or lock-file open
    failed — both pathological), the app still starts, just unguarded: refusing
    to run at all would be the worse failure mode for a desktop tool.
    """
    if sys.platform == "win32":
        mutex = _acquire_mutex(mutex_name)
        if mutex is None:
            notify_running_instance(port)
            return None
        return SingleInstance(port, mutex_handle=mutex or None)
    lock_file = _acquire_lock_file(lock_dir)
    if lock_file is None:
        notify_running_instance(port)
        return None
    return SingleInstance(port, lock_file=lock_file or None)


def notify_running_instance(port: int = PORT) -> bool:
    """Ask the already-running instance to show itself. True when it
    acknowledged the ping (best effort — the caller exits either way)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_PING_TIMEOUT) as conn:
            conn.settimeout(_PING_TIMEOUT)
            conn.sendall(_ACTIVATE_TOKEN)
            reply = b""
            while len(reply) < 3:
                chunk = conn.recv(3 - len(reply))
                if not chunk:
                    break
                reply += chunk
            return reply == b"OK\n"
    except OSError:
        log.debug("could not ping the running instance", exc_info=True)
        return False


def _acquire_mutex(name: str):
    """Windows named mutex — the canonical single-instance primitive, immune
    to the port-reservation quirks that broke the socket lock. Returns the
    handle (claimed), None (another process holds it), or 0 (API failure —
    run unguarded)."""
    import ctypes
    import ctypes.wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.LPCWSTR,
    )
    kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        log.warning(
            "CreateMutexW failed (error %d) — running without the single-instance guard",
            ctypes.get_last_error(),
        )
        return 0
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def _acquire_lock_file(lock_dir: Path | None):
    """POSIX: exclusive flock() on a file in the config dir. The kernel drops
    the lock when the process dies, so a crash never leaves a stale claim.
    Returns the open file (claimed), None (another process holds it), or 0
    (file unusable — run unguarded)."""
    import fcntl

    from .config import config_dir

    directory = lock_dir if lock_dir is not None else config_dir()
    path = directory / _LOCK_FILENAME
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # "a+" so opening never truncates the holder's pid note below.
        handle = open(path, "a+", encoding="utf-8")
    except OSError:
        log.warning("cannot open %s — running without the single-instance guard", path)
        return 0
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None  # genuinely held by another process
    except OSError:
        # flock itself unsupported here (e.g. an NFS home without lockd):
        # never mistake that for "already running" — start unguarded instead.
        handle.close()
        log.warning("flock on %s unavailable — running without the single-instance guard", path)
        return 0
    try:  # a pid note for humans debugging a stuck lock; irrelevant to the lock
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except OSError:
        pass
    return handle
