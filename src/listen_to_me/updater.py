"""In-app updater driven by GitHub Releases.

Checks the repo's releases, exposes the ones newer than the running build (so
the user can pick which to jump to) together with their changelogs, and — on a
frozen Windows build — downloads the new executable and swaps it in on restart.

No Qt here: the settings page drives this from a worker thread and marshals the
results back to the UI.

Every request in this module forces TLS certificate verification on, even while
``cfg["insecure_ssl"]`` is enabled — see :class:`UpdateTrustError`.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
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


def format_size(num_bytes: int | None) -> str:
    """A release asset's size for the UI ("198.4 MB", "512 KB").

    The portable build is a few hundred MB, so a bare percentage during the
    download says nothing about how long it will take — the UI shows the sizes
    next to it. Binary units (what the OS reports), one decimal from MB up,
    empty string when the size is unknown so callers can just skip it."""
    if not num_bytes or num_bytes < 0:
        return ""
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            if unit == "KB":
                return f"{size:.0f} KB"
            return f"{size:.1f} {unit}"
        size /= 1024
    return ""  # unreachable: the loop returns on "GB"


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
    asset_size: int | None = None
    asset_digest: str | None = None  # e.g. "sha256:<hex>" from the releases API

    @property
    def version(self) -> tuple[int, ...]:
        return parse_version(self.tag)

    @property
    def date(self) -> str:
        return (self.published_at or "")[:10]

    @property
    def title(self) -> str:
        return self.name or self.tag


def _pick_asset(assets: list[dict]) -> dict:
    """Prefer the Windows .exe asset; fall back to the first asset."""
    for asset in assets:
        if (asset.get("name") or "").lower().endswith(".exe"):
            return asset
    return assets[0] if assets else {}


class UpdateTrustError(Exception):
    """A request on the update path could not be authenticated.

    Unlike the model downloads and the assistant, the updater never honours
    ``cfg["insecure_ssl"]``: what it fetches replaces the running program, so an
    unauthenticated response would let whoever intercepts the connection execute
    code on this machine — and the asset digest is no defence, because it comes
    from the very same API response. The corporate-proxy escape hatch therefore
    stops here, and this error carries a ready-to-show explanation so the UI can
    say why instead of failing silently.
    """


def _trust_error() -> UpdateTrustError:
    """The message shown when the update path's certificate check fails.

    Names the insecure-SSL switch only while it is actually on — that is the
    case where the user would otherwise expect it to have covered this too.
    """
    hint = ""
    if not netutil.verify():
        hint = (
            ' "Ignore SSL certificate errors" deliberately does not cover updates:'
            " an update replaces the program file, so it has to come from a"
            " connection that is authenticated, not just encrypted."
        )
    return UpdateTrustError(
        f"could not verify GitHub's TLS certificate.{hint}"
        " Download the release manually from the release page instead."
    )


def _verified_get(url: str, **kwargs):
    """``requests.get`` with certificate verification forced on.

    Every network call in this module goes through here, so the update path
    stays authenticated regardless of the app-wide insecure-SSL switch.
    """
    import requests

    try:
        return requests.get(url, verify=True, **kwargs)
    except requests.exceptions.SSLError as exc:
        log.warning("update aborted — GitHub's TLS certificate could not be verified")
        raise _trust_error() from exc


def fetch_releases(timeout: float = 10.0, include_prerelease: bool = False) -> list[Release]:
    """All published releases, newest first. Raises on network/HTTP errors, and
    ``UpdateTrustError`` when the certificate could not be verified."""
    url = _API_URL.format(owner_repo=_owner_repo())
    resp = _verified_get(
        url,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
        params={"per_page": 100},
    )
    resp.raise_for_status()
    releases: list[Release] = []
    for item in resp.json():
        if item.get("draft"):
            continue
        if item.get("prerelease") and not include_prerelease:
            continue
        asset = _pick_asset(item.get("assets") or [])
        releases.append(
            Release(
                tag=item.get("tag_name", "") or "",
                name=item.get("name", "") or "",
                body=item.get("body", "") or "",
                published_at=item.get("published_at", "") or "",
                html_url=item.get("html_url", "") or "",
                prerelease=bool(item.get("prerelease")),
                asset_url=asset.get("browser_download_url"),
                asset_name=asset.get("name"),
                asset_size=asset.get("size"),
                asset_digest=asset.get("digest"),
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


def release_page_url(release: Release) -> str:
    """The release's own page, or the project page when that URL isn't one we
    trust.

    ``html_url`` is whatever the GitHub API response carried, and the UI hands
    it to ``webbrowser.open`` — which passes anything with a scheme on to the
    OS URL handler, so a non-HTTPS or non-GitHub value there would be a launch
    vector rather than a broken link. Same host check the download path uses.
    """
    url = getattr(release, "html_url", "") or ""
    try:
        _require_trusted_url(url)
    except ValueError:
        log.warning("ignoring an untrusted release page URL %r — opening %s", url, REPO_URL)
        return REPO_URL
    return url


class DownloadCancelled(Exception):
    """Raised by download_asset when the caller's is_cancelled turns True —
    distinct from a real failure so the UI can say "cancelled", not "failed"."""


def download_asset(
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int], None] | None = None,
    timeout: float = 30.0,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Stream a release asset to `dest`. progress_cb(done, total) is called as it
    downloads (total is 0 when the server sends no Content-Length).
    ``is_cancelled`` (optional) is polled between chunks; returning True aborts
    with DownloadCancelled — the caller cleans up the partial file. Raises
    ``UpdateTrustError`` when the certificate could not be verified."""
    _require_trusted_url(url)

    dest = Path(dest)
    with _verified_get(url, stream=True, timeout=timeout) as resp:
        # requests follows redirects — including cross-host and https→http
        # ones — so re-check the URL the transfer actually came from, not just
        # the one we started at.
        _require_trusted_url(resp.url)
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                if is_cancelled is not None and is_cancelled():
                    raise DownloadCancelled()
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb(done, total)
    return dest


def verify_download(
    path: Path, expected_size: int | None = None, expected_digest: str | None = None
) -> None:
    """Check a finished download against the release asset's metadata; raises
    ValueError on a mismatch. A truncated or proxy-mangled download would
    otherwise get swapped in and the app dies on its next start. Size always
    comes with the API response; the "sha256:<hex>" digest exists on newer
    assets (absent or unknown formats are skipped, best effort).

    This proves integrity, not authenticity: the expected digest arrives in the
    same API response as the download URL, so both move together if that
    response is forged. Authenticity comes from :func:`_verified_get` keeping
    the certificate check on for both requests."""
    path = Path(path)
    actual_size = path.stat().st_size
    if expected_size and actual_size != expected_size:
        raise ValueError(f"incomplete download: got {actual_size} of {expected_size} bytes")
    algo, _, want = (expected_digest or "").partition(":")
    if algo.strip().lower() == "sha256" and want:
        import hashlib

        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_DOWNLOAD_CHUNK), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != want.strip().lower():
            raise ValueError("download failed the sha256 integrity check")


def target_exe() -> Path:
    """Path of the currently running executable (the file to replace)."""
    return Path(sys.executable)


def download_path_for(target: Path | None = None) -> Path:
    """Where to download the new exe: next to the target (same volume → atomic
    move) with a distinct name."""
    target = target or target_exe()
    return target.with_name(target.stem + ".update.exe")


_STALE_SCRIPT_MAX_AGE = 24 * 3600  # seconds


def cleanup_stale_update(target: Path | None = None, temp_dir: Path | None = None) -> None:
    """Best-effort removal of leftovers from an earlier update attempt.

    A cancelled/crashed download, or a swap whose retrying move never won,
    leaves ``<exe>.update.exe`` next to the target; a killed swapper cmd can
    leave its batch in the temp dir. Called once at startup — a successful
    swap has moved the download away by then, so whatever remains is garbage.
    Recent batches are kept: the one that just relaunched us may still be
    executing its final self-delete line.
    """
    try:
        leftover = download_path_for(target)
        if leftover.exists():
            leftover.unlink()
            log.info("removed stale update download: %s", leftover)
    except OSError:
        log.warning("could not remove stale update download", exc_info=True)
    base = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    cutoff = time.time() - _STALE_SCRIPT_MAX_AGE
    try:
        for bat in base.glob("listen-to-me-update-*.bat"):
            try:
                if bat.stat().st_mtime < cutoff:
                    bat.unlink()
                    log.info("removed stale update script: %s", bat)
            except OSError:
                pass
    except OSError:
        pass


def _swap_script(new_exe: Path, target: Path) -> str:
    """The batch that swaps the exe and relaunches. Retries the move until the
    old exe is unlocked (this process has exited); gives up after ~1 minute.

    - chcp 65001: embedded paths are written as UTF-8 and may be non-ASCII
      (e.g. C:\\Users\\Müller\\...); this makes cmd read them correctly.
    - ping (not timeout) for the sleep: timeout aborts without a console handle.
    - %% escaping: % is legal in Windows paths and cmd expands %…% sequences
      even inside double quotes — an unescaped path would mangle the move.
    """
    new_q = str(new_exe).replace("%", "%%")
    target_q = str(target).replace("%", "%%")
    parent_q = str(target.parent).replace("%", "%%")
    return (
        "@echo off\r\n"
        "chcp 65001 >NUL\r\n"
        "setlocal\r\n"
        "set /a n=0\r\n"
        ":retry\r\n"
        f'move /Y "{new_q}" "{target_q}" >NUL 2>&1\r\n'
        "if not errorlevel 1 goto done\r\n"
        "set /a n+=1\r\n"
        "if %n% GEQ 60 goto done\r\n"
        "ping -n 2 127.0.0.1 >NUL\r\n"
        "goto retry\r\n"
        ":done\r\n"
        # /D: give the new instance the exe's folder as cwd, same as a manual
        # start from Explorer (the batch itself runs wherever the old app was).
        f'start "" /D "{parent_q}" "{target_q}"\r\n'
        'del "%~f0"\r\n'
    )


def _swap_env() -> dict[str, str]:
    """Environment for the swapper chain (cmd -> batch -> relaunched exe).

    Since PyInstaller 6.9 the bootloader treats a spawned copy of the frozen
    exe as a *worker subprocess* and lets it reuse this process's unpacked
    _MEI directory — which the dying bootloader deletes on exit. The relaunched
    updated exe then crashes on startup ('Failed to load Python DLL' / missing
    modules) even though the very same file starts fine by hand.
    PYINSTALLER_RESET_ENVIRONMENT=1 is the documented way to force a fresh
    top-level start; stripping _MEIPASS2/_PYI_* covers bootloader generations
    that key off those inherited variables directly.
    """
    env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2" and not k.startswith("_PYI_")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


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
    subprocess.Popen(
        ["cmd", "/c", str(bat)], creationflags=0x08000000, close_fds=True, env=_swap_env()
    )
    log.info("update swap scheduled: %s -> %s", new_exe, target)
