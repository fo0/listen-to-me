"""Optional transcript post-processing through an OpenAI-compatible API.

Works with any endpoint that speaks the /chat/completions protocol —
a local Ollama (http://localhost:11434/v1), LM Studio, llama.cpp server,
OpenWebUI, or a hosted API.
"""

from __future__ import annotations

import json
import logging
import time

from . import netutil
from .config import clamp_setting

log = logging.getLogger(__name__)

# The ranges the Settings → Assistant spin boxes offer; hand-edited values
# outside them are clamped at the request (see config.clamp_setting).
_TIMEOUT_RANGE = (5, 600)
_TEMPERATURE_RANGE = (0.0, 2.0)

# How much of a response is ever read, and in which pieces. `requests`' own
# `timeout` bounds a single socket read, not the transfer, and `Response.json()`
# buffers a body of any size — so an endpoint that dribbles one byte every few
# seconds, or answers with a gigabyte, never trips the timeout and parks the
# `process` worker thread for good. `App.state` then stays "processing" until
# the app is restarted, and every hotkey press until then is refused. The
# configured timeout therefore doubles as a wall clock over the whole read.
# 1 MiB is far above a refined dictation (a few KiB) and far below anything
# that could exhaust memory.
_MAX_RESPONSE_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 8192


class AssistantError(RuntimeError):
    pass


def _read_body(response, deadline: float) -> bytes:
    """The response body, capped at `_MAX_RESPONSE_BYTES` and given up on once
    `deadline` (a `time.monotonic()` value) has passed.

    Both limits raise `AssistantError`, which is what the caller in
    ``app._process`` already turns into "assistant failed" plus the raw
    transcript — the dictation still lands at the cursor.
    """
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(_READ_CHUNK_BYTES):
        if chunk:
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_RESPONSE_BYTES:
                raise AssistantError(
                    f"the assistant response exceeded {_MAX_RESPONSE_BYTES // 1024} KiB"
                )
        # Checked per chunk, including the empty keep-alive ones: a stalled
        # transfer is exactly a stream that keeps arriving without finishing.
        if time.monotonic() > deadline:
            raise AssistantError("the assistant did not finish its response in time")
    return b"".join(chunks)


# The connection is shared by both recording sources (see profile()).
_SHARED_KEYS = ("base_url", "api_key", "temperature", "timeout")

_prompt_warned: set[str] = set()


def _gate(key: str, enabled, system_prompt) -> tuple[bool, str]:
    """One profile's `(enabled, system prompt)`, each as the type it claims.

    `enabled` is read the way ``config._coerce`` reads a bool default — a real
    bool or the unambiguous 0/1 of a hand-edit, never plain truthiness, so a
    stored ``"enabled": "false"`` cannot turn the feature ON (re-checked here
    because a dict built by hand never passed that merge). A blank or
    non-string prompt switches the profile off and is named once per key and
    process: a request with no system prompt tells the endpoint nothing about
    what to do with the transcript, and the user pays for the answer with the
    wait after a recording that is already over — while a log line per take
    would bury the log, as in _warn_if_key_travels_in_clear.
    """
    on = enabled if isinstance(enabled, bool) else (isinstance(enabled, int) and enabled == 1)
    prompt = system_prompt if isinstance(system_prompt, str) else ""
    if on and not prompt.strip():
        on = False
        if key not in _prompt_warned:
            _prompt_warned.add(key)
            log.warning(
                "config key %r carries no prompt text — assistant post-processing "
                "stays off for this recording source (Settings → Assistant)",
                key,
            )
    return (on, prompt)


def profile(acfg: dict, source: str = "mic") -> dict:
    """The `assistant` section resolved for one recording source — flat, so it
    goes straight into `config_problem()` and `refine()`.

    The microphone hotkey and the system-audio one (#191) want opposite things
    from the assistant: a dictation wants punctuation and filler removal, a
    recorded meeting minutes or a summary. What they do not want twice is the
    connection — one endpoint, one key, one timeout — so `base_url`, `api_key`,
    `temperature` and `timeout` stay shared, and only the switch, the model and
    the prompt are per source. The top-level `enabled`/`system_prompt`/`model`
    ARE the microphone profile (not renamed, so no existing config.json needs a
    migration); `acfg["system_audio"]` holds the other one, and any `source`
    but "system" is the microphone — a plain string, because app.py imports
    this module and an enum would need a third one to live in.

    An unreadable profile is reported DISABLED, never repaired from the other
    one: post-processing a recorded meeting with the dictation prompt is a
    confidently wrong result, while a feature nobody configured staying off is
    the right one. Nothing here raises — a hand-edited config.json may cost the
    assistant, never the transcript already waiting for it.
    """
    # Only the shared keys the caller really stored: a value invented here
    # would shadow refine()'s own fallbacks for temperature and timeout.
    prof = {key: acfg[key] for key in _SHARED_KEYS if key in acfg}
    shared_model = acfg.get("model", "")
    if source == "system":
        # A missing section (a config hand-written before #191) or a scalar
        # where it belongs reads as switched off with an empty prompt, so not
        # even a caller that ignores `enabled` can send the dictation prompt to
        # a recorded meeting. config._merge already logs that shape and keeps
        # the defaults — this is the last line of defence, not the report.
        stored = acfg.get("system_audio")
        section = stored if isinstance(stored, dict) else {}
        key = "assistant.system_audio.system_prompt"
        # A blank model means "use the shared one" by design (one endpoint
        # usually serves one), so an unusable value falls back to it as well —
        # unlike the prompt, which has no right value to fall back to.
        model = section.get("model")
        model = (model.strip() if isinstance(model, str) else "") or shared_model
    else:
        section, key, model = acfg, "assistant.system_prompt", shared_model
    enabled, prompt = _gate(key, section.get("enabled"), section.get("system_prompt"))
    return {**prof, "enabled": enabled, "model": model, "system_prompt": prompt}


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
    deadline = time.monotonic() + float(timeout)
    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=float(timeout),
        verify=netutil.verify(),
        # Streamed on purpose: it is what makes the body boundable in size and
        # against the deadline (see _read_body). Without it requests buffers
        # the whole response before this line returns.
        stream=True,
    )
    try:
        response.raise_for_status()
        raw = _read_body(response, deadline)
    finally:
        response.close()
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        # An HTML error page from a reverse proxy, or a base_url pointing at
        # something that is not an API at all. `requests` raised its own
        # decode error here before; naming it as an assistant problem keeps
        # the notification actionable.
        raise AssistantError(f"the assistant did not return JSON: {raw[:200]!r}") from exc
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
