"""In-app updater driven by GitHub Releases.

Checks the repo's releases, exposes the ones newer than the running build (so
the user can pick which to jump to) together with their changelogs, and — on a
frozen Windows build — downloads the new executable and swaps it in on restart.

No Qt here: the settings page drives this from a worker thread and marshals the
results back to the UI.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import REPO_URL, __version__, netutil

log = logging.getLogger(__name__)

_API_URL = "https://api.github.com/repos/{owner_repo}/releases"
_DOWNLOAD_CHUNK = 256 * 1024


def _owner_repo() -> str:
    """'owner/name' parsed from REPO_URL (e.g. fo0/listen-to-me)."""
    return REPO_URL.rstrip("/").split("github.com/", 1)[-1]


def parse_version(text: str) -> tuple[int, ...]:
    """Turn a tag/version string into a comparable tuple of ints.

    Handles 'v2026.07.19.11', '2026.07.19.11' and the dev '0.0.0.dev0' by just
    picking out the integer groups. Returns (0,) when there are none.
    """
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def current_version() -> tuple[int, ...]:
    return parse_version(__version__)


def is_frozen() -> bool:
    """True in a PyInstaller build (where sys.executable is our own binary)."""
    return bool(getattr(sys, "frozen", False))


def can_self_update() -> bool:
    """Whether we can replace our own binary. Only the frozen Windows single-file
    build supports the swap; elsewhere the UI offers the release page instead."""
    return is_frozen() and sys.platform == "win32"


@dataclass
class Release:
    tag: str
    name: str
    body: str
    published_at: str
    html_url: str
    prerelease: bool
    asset_url: str | None
    asset_name: str | None

    @property
    def version(self) -> tuple[int, ...]:
        return parse_version(self.tag)

    @property
    def date(self) -> str:
        return (self.published_at or "")[:10]

    @property
    def title(self) -> str:
        return self.name or self.tag


def _pick_asset(assets: list[dict]) -> tuple[str | None, str | None]:
    """Prefer the Windows .exe asset; fall back to the first asset."""
    for asset in assets:
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            return asset.get("browser_download_url"), name
    if assets:
        first = assets[0]
        return first.get("browser_download_url"), first.get("name")
    return None, None


def fetch_releases(timeout: float = 10.0, include_prerelease: bool = False) -> list[Release]:
    """All published releases, newest first. Raises on network/HTTP errors."""
    import requests

    url = _API_URL.format(owner_repo=_owner_repo())
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
        params={"per_page": 100},
        verify=netutil.verify(),
    )
    resp.raise_for_status()
    releases: list[Release] = []
    for item in resp.json():
        if item.get("draft"):
            continue
        if item.get("prerelease") and not include_prerelease:
            continue
        asset_url, asset_name = _pick_asset(item.get("assets") or [])
        releases.append(
            Release(
                tag=item.get("tag_name", "") or "",
                name=item.get("name", "") or "",
                body=item.get("body", "") or "",
                published_at=item.get("published_at", "") or "",
                html_url=item.get("html_url", "") or "",
                prerelease=bool(item.get("prerelease")),
                asset_url=asset_url,
                asset_name=asset_name,
            )
        )
    releases.sort(key=lambda r: r.version, reverse=True)
    return releases


def newer_releases(releases: list[Release], current: tuple[int, ...] | None = None) -> list[Release]:
    """Releases strictly newer than the running build, newest first."""
    cur = current_version() if current is None else current
    return [r for r in releases if r.version > cur]


def latest_release(releases: list[Release]) -> Release | None:
    return releases[0] if releases else None


def _require_trusted_url(url: str) -> None:
    """Defence in depth: only ever download over HTTPS from GitHub hosts. The URL
    already comes from the TLS-authenticated API of the pinned repo, so this just
    guards against a surprising redirect target being handed in."""
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    trusted = host == "github.com" or host.endswith(".github.com") or host.endswith(
        ".githubusercontent.com"
    )
    if parsed.scheme != "https" or not trusted:
        raise ValueError(f"refusing to download from an untrusted URL: {url!r}")


def download_asset(url: str, dest: Path, progress_cb=None, timeout: float = 30.0) -> Path:
    """Stream a release asset to `dest`. progress_cb(done, total) is called as it
    downloads (total is 0 when the server sends no Content-Length)."""
    _require_trusted_url(url)
    import requests

    dest = Path(dest)
    with requests.get(url, stream=True, timeout=timeout, verify=netutil.verify()) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb(done, total)
    return dest


def target_exe() -> Path:
    """Path of the currently running executable (the file to replace)."""
    return Path(sys.executable)


def download_path_for(target: Path | None = None) -> Path:
    """Where to download the new exe: next to the target (same volume → atomic
    move) with a distinct name."""
    target = target or target_exe()
    return target.with_name(target.stem + ".update.exe")


def _swap_script(new_exe: Path, target: Path) -> str:
    """The batch that swaps the exe and relaunches. Retries the move until the
    old exe is unlocked (this process has exited); gives up after ~1 minute.

    - chcp 65001: embedded paths are written as UTF-8 and may be non-ASCII
      (e.g. C:\\Users\\Müller\\...); this makes cmd read them correctly.
    - ping (not timeout) for the sleep: timeout aborts without a console handle.
    """
    return (
        "@echo off\r\n"
        "chcp 65001 >NUL\r\n"
        "setlocal\r\n"
        "set /a n=0\r\n"
        ":retry\r\n"
        f'move /Y "{new_exe}" "{target}" >NUL 2>&1\r\n'
        "if not errorlevel 1 goto done\r\n"
        "set /a n+=1\r\n"
        "if %n% GEQ 60 goto done\r\n"
        "ping -n 2 127.0.0.1 >NUL\r\n"
        "goto retry\r\n"
        ":done\r\n"
        f'start "" "{target}"\r\n'
        'del "%~f0"\r\n'
    )


def apply_update_windows(new_exe: Path, target: Path | None = None) -> None:
    """Swap the running exe with `new_exe` and relaunch it (Windows only). The
    caller MUST quit the app right after, so the detached batch's retrying move
    can succeed once the old exe is unlocked."""
    target = target or target_exe()
    new_exe = Path(new_exe)
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / f"listen-to-me-update-{pid}.bat"
    # write_bytes: text mode would translate the \r\n literals to \r\r\n on Windows.
    bat.write_bytes(_swap_script(new_exe, target).encode("utf-8"))
    # CREATE_NO_WINDOW: hidden console (no flashing window, console tools work);
    # the child still outlives this process.
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000, close_fds=True)
    log.info("update swap scheduled: %s -> %s", new_exe, target)
