"""App-wide "ignore SSL certificates" switch for corporate proxies.

Corporate proxies often intercept HTTPS with a self-signed certificate that
Python's trust store does not know, which makes every outbound TLS connection
fail — the Whisper model download from Hugging Face, the update check on
GitHub and the optional assistant API alike. ``cfg["insecure_ssl"]`` turns
certificate verification off app-wide as an explicit, off-by-default opt-in
for exactly that environment. While it is on, connections are still encrypted
but no longer authenticated (a man-in-the-middle would not be detected) —
that trade-off is the user's informed choice, including for the updater's exe
download, which additionally stays pinned to HTTPS GitHub URLs.

Qt-free, and ``urllib3``/``huggingface_hub``/``httpx`` are only imported once
the switch is actually enabled, so ``--version`` and the headless smoke test
stay fast.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_insecure = False


def verify() -> bool:
    """Value for the ``verify=`` parameter of the app's ``requests`` calls
    (updater, assistant): False while the insecure-SSL switch is on."""
    return not _insecure


def apply_insecure_ssl(enabled: bool) -> None:
    """Apply ``cfg["insecure_ssl"]``: turn TLS certificate verification off
    (or back on) for every outbound HTTPS connection the app makes.

    Called at startup and after every settings save, so toggling works without
    a restart. Covers the ``requests`` call sites (updater, assistant) via
    :func:`verify` and the Hugging Face model downloads of both transcription
    backends via ``huggingface_hub.configure_http_backend``. urllib3's
    per-request InsecureRequestWarning is silenced while enabled — the switch
    itself is logged once instead.
    """
    global _insecure
    enabled = bool(enabled)
    if enabled == _insecure:
        return
    _insecure = enabled
    if enabled:
        log.warning(
            "insecure_ssl enabled — TLS certificates are NOT verified "
            "(model downloads, update check, assistant)"
        )
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            log.debug("could not silence urllib3 InsecureRequestWarning", exc_info=True)
    else:
        log.info("insecure_ssl disabled — TLS certificate verification restored")
    try:
        _configure_huggingface(enabled)
    except ImportError:
        # huggingface_hub not installed (stripped dev/CI environment): the
        # requests call sites still honour the switch; nothing to reconfigure.
        # In the app it is always present (a faster-whisper dependency).
        log.debug("huggingface_hub not available — skipping its SSL reconfiguration")
    except Exception:
        # Unexpected (e.g. an API change): model downloads keep verifying
        # certificates; the requests call sites still honour the switch.
        log.exception("could not reconfigure huggingface_hub SSL verification")


def _configure_huggingface(enabled: bool) -> None:
    """Route huggingface_hub (the model downloads of both backends) through
    clients without certificate verification — or back to its default.

    huggingface_hub >= 1.0 is httpx-based and configured via
    ``set_client_factory``; older versions are requests-based and use
    ``configure_http_backend``. Both reset the shared session internally, so
    a toggle takes effect immediately. Raises ImportError only when
    huggingface_hub is not installed at all.
    """
    try:
        from huggingface_hub import set_client_factory  # >= 1.0 (httpx)
    except ImportError:
        _configure_huggingface_legacy(enabled)
        return
    if enabled:
        set_client_factory(_insecure_hub_client)
        return
    try:
        from huggingface_hub.utils._http import default_client_factory
    except ImportError:  # private location moved — use an equivalent client
        set_client_factory(_default_hub_client)
    else:
        set_client_factory(default_client_factory)


def _insecure_hub_client():
    """Client factory for huggingface_hub >= 1.0: verification off."""
    return _build_hub_client(verify=False)


def _default_hub_client():
    """Client factory for huggingface_hub >= 1.0: default-equivalent client,
    used to restore verification when the hub's own factory can't be found."""
    return _build_hub_client(verify=True)


def _build_hub_client(verify: bool):
    """An ``httpx.Client`` mirroring huggingface_hub's default factory
    (redirects on, no timeout, the hub's request event hook when importable)
    with an explicit ``verify`` — httpx pins the TLS settings at client
    creation, so toggling always needs a fresh client."""
    import httpx  # a hard dependency of huggingface_hub >= 1.0

    kwargs: dict = {"verify": verify, "follow_redirects": True, "timeout": None}
    try:
        from huggingface_hub.utils._http import hf_request_event_hook

        kwargs["event_hooks"] = {"request": [hf_request_event_hook]}
    except ImportError:
        pass
    return httpx.Client(**kwargs)


def _configure_huggingface_legacy(enabled: bool) -> None:
    """huggingface_hub < 1.0 (requests-based): configure_http_backend."""
    from huggingface_hub import configure_http_backend

    if enabled:
        configure_http_backend(backend_factory=_insecure_session)
    else:
        configure_http_backend()  # restore the default session factory


def _insecure_session():
    """Session factory for huggingface_hub < 1.0: verification off."""
    import requests

    session = requests.Session()
    session.verify = False
    return session
