"""Optional transcript post-processing through an OpenAI-compatible API.

Works with any endpoint that speaks the /chat/completions protocol —
a local Ollama (http://localhost:11434/v1), LM Studio, llama.cpp server,
OpenWebUI, or a hosted API.
"""

from __future__ import annotations

import logging

from . import netutil
from .config import clamp_setting

log = logging.getLogger(__name__)

# The ranges the Settings → Assistant spin boxes offer; hand-edited values
# outside them are clamped at the request (see config.clamp_setting).
_TIMEOUT_RANGE = (5, 600)
_TEMPERATURE_RANGE = (0.0, 2.0)


class AssistantError(RuntimeError):
    pass


def config_problem(acfg: dict) -> tuple[str, str] | None:
    """Why `acfg` cannot produce a request, as `(config key, reason)` — or None.

    The assistant is the one feature whose misconfiguration is invisible until
    it is too late: it runs on the worker thread *after* a dictation, so an
    empty or scheme-less `base_url` surfaces as "Assistant failed (Invalid URL
    '/chat/completions': No scheme supplied)" once the recording is already
    done. Naming the problem up front — at Save, and again before the request
    goes out — turns that into something the user can act on.

    Qt-free on purpose: the settings window and the worker thread both ask,
    and the rule belongs to neither of them.
    """
    url = str(acfg.get("base_url") or "").strip()
    if not url:
        return ("base_url", "no API base URL is set")
    if not url.lower().startswith(("http://", "https://")):
        return ("base_url", "the API base URL must start with http:// or https://")
    if not str(acfg.get("model") or "").strip():
        return ("model", "no model name is set")
    return None


_plaintext_key_warned = False


def _warn_if_key_travels_in_clear(url: str, api_key: str) -> None:
    """Say so, once, when the API key would leave this machine unencrypted.

    A plain-HTTP `base_url` is allowed on purpose — the documented default is a
    local Ollama, and a loopback endpoint never puts anything on a wire. A
    *remote* http:// endpoint does: the `Authorization: Bearer …` header and
    the whole transcript then travel in the clear, readable by anyone on the
    path. Refusing that would break legitimate internal gateways that are only
    reachable over http, so this only reports it — the user's own network, the
    user's call.

    Once per process: refine() runs after every dictation and this must not
    bury the log. Failing open (a URL urlparse cannot read is simply not
    warned about) — config_problem() has already vetted the scheme, and a
    warning helper must never be what breaks a dictation.
    """
    global _plaintext_key_warned
    if _plaintext_key_warned or not api_key:
        return
    import ipaddress
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "http":
            return
        host = (parsed.hostname or "").lower()
        if host == "localhost" or host.endswith(".localhost"):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass  # a hostname, not a literal address — not loopback
    except ValueError:
        return
    _plaintext_key_warned = True
    log.warning(
        "the assistant API key is sent to %s over plain HTTP — the key and every "
        "transcript travel unencrypted; use https:// for a remote endpoint",
        host or url,
    )


def refine(text: str, acfg: dict) -> str:
    problem = config_problem(acfg)
    if problem is not None:
        # A hand-edited config never passed through the settings window's
        # check — say what is missing instead of letting requests explain it.
        # Before the import, so the reason survives a stripped-down install.
        raise AssistantError(f"{problem[1]} (Settings → Assistant)")

    _warn_if_key_travels_in_clear(acfg["base_url"], str(acfg.get("api_key") or ""))

    import requests

    url = acfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if acfg.get("api_key"):
        headers["Authorization"] = f"Bearer {acfg['api_key']}"
    # Clamped, not rejected: a `timeout` of 0 raises deep inside urllib3 on
    # every dictation and a temperature of 7 is refused by the server — both
    # after the user already spoke. The clamp names the key once in the log.
    temperature = clamp_setting(
        "assistant.temperature", acfg.get("temperature", 0.2), *_TEMPERATURE_RANGE
    )
    timeout = clamp_setting("assistant.timeout", acfg.get("timeout", 120), *_TIMEOUT_RANGE)
    payload = {
        "model": acfg["model"],
        "temperature": float(temperature),
        "messages": [
            {"role": "system", "content": acfg["system_prompt"]},
            {"role": "user", "content": text},
        ],
    }
    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=float(timeout),
        verify=netutil.verify(),
    )
    response.raise_for_status()
    data = response.json()
    try:
        result = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        # TypeError included on purpose: a body that is not an object at all
        # (a bare list or string — an error page that happens to be JSON, a
        # base_url pointing at something else entirely) fails on the very first
        # subscript. Without it the user is shown "list indices must be
        # integers" instead of the response that caused it.
        raise AssistantError(f"unexpected API response: {data!r:.200}") from exc
    if not result:
        raise AssistantError("assistant returned an empty response")
    log.info("assistant refined %d -> %d chars", len(text), len(result))
    return result
