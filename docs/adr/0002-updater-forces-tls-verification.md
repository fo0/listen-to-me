# ADR-0002: The updater is carved out of the `insecure_ssl` switch

- **Status:** Accepted
- **Date:** 2026-07-27
- **Decider(s):** user + agent
- **Tags:** security, network, updater

## Context

The app ships an `insecure_ssl` option that disables TLS certificate verification, because corporate TLS-inspecting proxies otherwise block Hugging Face model downloads and the optional assistant endpoint outright. The switch is implemented centrally in `netutil.py` (requests `verify=` plus the huggingface_hub client factory).

The in-app updater (`updater.py`) uses the same HTTP stack: it queries the GitHub Releases API and downloads an `.exe` that then **replaces the running program file**. If the global switch also covered that path, a user who enabled it to get past a proxy would silently accept any certificate for the code-update channel. The digest GitHub returns cannot close the gap — it arrives in the same API response as the download URL, so an attacker able to forge one can forge both.

## Decision

We will keep the updater outside the `insecure_ssl` switch. Every request in `updater.py` goes through `_verified_get`, which forces `verify=True` regardless of configuration. A certificate failure raises `UpdateTrustError` carrying a user-facing explanation, never a silent no-op or a fallback to an unverified retry.

## Consequences

### Positive

- The one network path that can execute code on the user's machine is always authenticated.
- The failure is explicit and explainable rather than silent, so a user behind a breaking proxy learns why updates do not work.

### Negative / Trade-offs

- Users behind a TLS-inspecting proxy can use the model downloads and the assistant but **cannot** use the in-app updater; they have to download the release manually.
- One HTTP helper in the codebase deliberately does not honor a global setting — a reader who does not know why could "fix" it. Locked in by the `updater forces TLS verification` gui_smoke check.

### Neutral

- Model downloads and assistant traffic remain covered by the switch; the carve-out is narrow by design.

## Alternatives Considered

- **Let `insecure_ssl` cover everything, verify the download by digest** — rejected: the digest ships in the same response as the URL, so it authenticates nothing against an attacker who controls the connection.
- **A second, separate "insecure updates too" switch** — rejected: it makes the dangerous option available in one click and the explanation would have to fit in a checkbox label.
- **Disable the updater entirely when `insecure_ssl` is on** — rejected: indistinguishable from a broken updater; the explicit `UpdateTrustError` is more useful.

## References

- `src/listen_to_me/updater.py` (`_verified_get`, `UpdateTrustError`), `src/listen_to_me/netutil.py`
- Issue #20
