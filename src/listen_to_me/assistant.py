"""Optional transcript post-processing through an OpenAI-compatible API.

Works with any endpoint that speaks the /chat/completions protocol —
a local Ollama (http://localhost:11434/v1), LM Studio, llama.cpp server,
OpenWebUI, or a hosted API.
"""

from __future__ import annotations

import logging

from . import netutil

log = logging.getLogger(__name__)


class AssistantError(RuntimeError):
    pass


def refine(text: str, acfg: dict) -> str:
    import requests

    url = acfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if acfg.get("api_key"):
        headers["Authorization"] = f"Bearer {acfg['api_key']}"
    payload = {
        "model": acfg["model"],
        "temperature": float(acfg.get("temperature", 0.2)),
        "messages": [
            {"role": "system", "content": acfg["system_prompt"]},
            {"role": "user", "content": text},
        ],
    }
    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=float(acfg.get("timeout", 120)),
        verify=netutil.verify(),
    )
    response.raise_for_status()
    data = response.json()
    try:
        result = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise AssistantError(f"unexpected API response: {data!r:.200}") from exc
    if not result:
        raise AssistantError("assistant returned an empty response")
    log.info("assistant refined %d -> %d chars", len(text), len(result))
    return result
