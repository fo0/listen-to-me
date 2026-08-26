"""App-wide "ignore SSL certificates" switch for corporate proxies.

Corporate proxies often intercept HTTPS with a self-signed certificate that
Python's trust store does not know, which makes every outbound TLS connection
fail — the Whisper model download from Hugging Face, the update check on
GitHub and the optional assistant API alike. ``cfg["insecure_ssl"]`` turns
certificate verification off app-wide as an explicit, off-by-default opt-in
for exactly that environment. While it is on, connections are still encrypted
but no longer authenticated (a man-in-the-middle would not be detected) —
that trade-off is the user's informed choice.

**The switch covers every outbound connection, the updater included**
(ADR-0006, superseding ADR-0002): model downloads, the assistant, the GitHub
releases API and the exe download. A switch that half of the app's network
paths ignore only looks like it works — behind an intercepting proxy the
updater would keep failing with no way out. The update path stays the most
dangerous one (its download replaces the running program), so it keeps the
checks that do not depend on the certificate — the HTTPS/GitHub host allowlist
and the size/sha256 verification — logs every unverified request, and the
Settings confirmation says so before the download starts.

Qt-free, and ``urllib3``/``huggingface_hub``/``httpx`` are only imported once
the switch is actually enabled, so ``--version`` and the headless smoke test
stay fast.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_insecure = False
# Whether the huggingface_hub client factory currently matches _insecure. A
# failed reconfiguration leaves it False so the next apply_insecure_ssl call
# (every settings save) retries instead of no-opping until restart.
_hub_synced = True


def verify() -> bool:
    """Value for the ``verify=`` parameter of the app's ``requests`` calls
    (the assistant and the updater): False while the insecure-SSL switch is
    on."""
    return not _insecure


def describe_error(exc: BaseException) -> str:
    """One sentence a user can act on, for a failed outbound request.

    ``requests`` renders an unreachable host as its whole transport chain —
    ``HTTPSConnectionPool(host='api.github.com', port=443): Max retries
    exceeded with url: … (Caused by NewConnectionError(…))`` — and the settings
    window put that verbatim into a one-line status label: a stack-trace
    fragment where a next step belongs.

    Only the transport failures are translated. The app's own errors
    (``AssistantError``, ``UpdateTrustError``) and an HTTP status raised by
    ``raise_for_status`` already carry wording written for the user, so they
    pass through untouched — as does anything else, which keeps this safe to
    wrap around a broad ``except``.

    Qt-free, and ``requests`` is imported only once there is an exception to
    describe, so nothing here is on the ``--version`` / smoke-test path.
    """
    try:
        import requests
    except Exception:  # requests not installed — nothing to recognise
        return str(exc) or exc.__class__.__name__
    errors = requests.exceptions
    # SSLError and ConnectTimeout are both ConnectionError subclasses, so the
    # specific cases have to be asked first.
    if isinstance(exc, errors.SSLError):
        return (
            "the TLS certificate could not be verified. Behind a corporate proxy "
            "that intercepts HTTPS, switch “Ignore SSL certificate errors” on in "
            "Settings → General → Network."
        )
    if isinstance(exc, errors.Timeout):
        return "the server did not answer in time. Check that it is running, then try again."
    if isinstance(exc, errors.ConnectionError):
        return (
            "the server could not be reached. Check the address and your network "
            "connection (a proxy or firewall may be blocking it)."
        )
    if isinstance(exc, (errors.MissingSchema, errors.InvalidURL)):
        return "the address is not a usable URL — it has to start with http:// or https://."
    return str(exc) or exc.__class__.__name__


def apply_insecure_ssl(enabled: bool) -> None:
    """Apply ``cfg["insecure_ssl"]``: turn TLS certificate verification off
    (or back on) for every outbound HTTPS connection the app makes.

    Called at startup and after every settings save, so toggling works without
    a restart. Covers the assistant's and the updater's ``requests`` calls via
    :func:`verify` and the Hugging Face model downloads of both transcription
    backends via ``huggingface_hub.configure_http_backend``. urllib3's
    per-request InsecureRequestWarning is silenced while enabled — the switch
    itself is logged once instead (the update path logs every unverified
    request of its own).
    """
    global _insecure, _hub_synced
    enabled = bool(enabled)
    if enabled == _insecure and _hub_synced:
        return
    changed = enabled != _insecure
    _insecure = enabled
    if enabled and changed:
        log.warning(
            "insecure_ssl enabled — TLS certificates are NOT verified "
            "(model downloads, assistant, updates)"
        )
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            log.debug("could not silence urllib3 InsecureRequestWarning", exc_info=True)
    try:
        _configure_huggingface(enabled)
    except ImportError:
        # huggingface_hub not installed (stripped dev/CI environment): the
        # requests call sites still honour the switch; nothing to reconfigure.
        # In the app it is always present (a faster-whisper dependency).
        log.debug("huggingface_hub not available — skipping its SSL reconfiguration")
        _hub_synced = True
    except Exception:
        # Marked out of sync so every later call retries — an unlucky first
        # attempt must not pin the wrong client factory until restart.
        _hub_synced = False
        if enabled:
            # Model downloads keep verifying certificates; the requests call
            # sites still honour the switch.
            log.exception("could not reconfigure huggingface_hub SSL verification")
        else:
            # The insecure client factory installed earlier stays active: hub
            # model downloads may keep SKIPPING verification although the user
            # just turned it back on. Retried on the next settings save.
            # (The assistant's requests calls verify again either way.)
            log.exception(
                "insecure_ssl disabled, but huggingface_hub could not be "
                "reconfigured — model downloads may keep skipping TLS "
                "verification; retrying on the next settings save"
            )
        return
    else:
        _hub_synced = True
    if not enabled:
        # Logged only after the hub reconfiguration succeeded — before that
        # the line would assert a restoration that hasn't happened yet.
        log.info("insecure_ssl disabled — TLS certificate verification restored")


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
