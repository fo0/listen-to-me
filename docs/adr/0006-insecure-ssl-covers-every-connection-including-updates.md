# ADR-0006: The `insecure_ssl` switch covers every connection, updates included

- **Status:** Accepted — supersedes ADR-0002
- **Date:** 2026-08-11
- **Decider(s):** user
- **Tags:** security, network, updater

## Context

ADR-0002 carved the in-app updater out of the `insecure_ssl` switch: `updater.py` forced `verify=True` for the GitHub Releases API call and the exe download regardless of the setting, on the grounds that the download replaces the running program file and the asset digest cannot close the gap (it arrives in the same API response as the download URL).

The carve-out is technically sound and it makes the option useless in the environment it exists for. A user only enables `insecure_ssl` because a corporate proxy intercepts HTTPS with a certificate the app does not trust — and that proxy sits in front of `api.github.com` exactly as it sits in front of Hugging Face. So the one setting labelled "Ignore SSL certificate errors" would fix the model download and the assistant and leave the update check failing, with an error message explaining that the option the user just enabled deliberately does not apply here. The workaround ADR-0002 offers — download the release manually from the release page — runs over the same intercepted connection through the same browser, so the user ends up trusting the same proxy anyway, just without the app's host allowlist and digest check.

The owner has decided that a switch which does not cover all of the app's network paths is not worth having, and that the residual risk belongs to whoever turns it on.

## Decision

We will route every request in `updater.py` through `_get`, which passes `verify=netutil.verify()` — the same app-wide value the assistant and the huggingface_hub client factory use. With `insecure_ssl` off (the default) nothing changes: GitHub's certificate is verified and a failure still raises `UpdateTrustError` with a user-facing explanation. With it on, the update path is unauthenticated like every other connection the app makes.

The checks that do not depend on the certificate stay in force and become the update path's remaining defences:

- **HTTPS + GitHub host allowlist** (`_require_trusted_url`) on the download URL **and** on the URL the transfer actually came from after redirects.
- **Size and SHA256 verification** of the finished download against the release metadata (integrity, not authenticity).
- **Every unverified update request is logged** — a log line is the only trace left once the swap has happened.
- **The install confirmation dialog names the risk** while the switch is on, so the last step before replacing the program file is an informed one.

## Consequences

### Positive

- The option does what its label says: one switch, all outbound connections. Behind an intercepting proxy the updater works instead of failing with an explanation the user cannot act on.
- One less special case for a reader of `netutil.py` / `updater.py` to hold in their head, and no "why does this one helper ignore the global setting" trap.
- The user is told what they are trading, at the moment it matters (the install dialog), not only in a checkbox tooltip they ticked on some earlier day.

### Negative / Trade-offs — the accepted risk

- **This is a real security regression, accepted knowingly.** While `insecure_ssl` is on, whoever can intercept the connection can serve the release listing and the `.exe` that replaces the running program. The digest is no defence — it comes from the same response — so this is remote code execution for a man-in-the-middle, on a machine whose user opted in.
- The blast radius is the whole app: the swapped exe runs with the user's rights at every subsequent start.
- The remaining checks are structural, not cryptographic. The host allowlist keeps the transfer on a GitHub host as the response claims it to be — against an attacker who controls the TLS session, it constrains the shape of the attack, not the attacker.
- Users who enable the switch only for the model download now also lose update authenticity, without a way to keep the two apart.

### Mitigations that remain in force

- **Off by default**, and it stays an explicit opt-in with a warning in Settings, the Help page and the README.
- Host allowlist on both the initial and the post-redirect URL; size + SHA256 check before anything is swapped in.
- `WARNING`-level log entry for every update request that runs without verification.
- The install confirmation dialog spells out that the download is not authenticated while the switch is on.
- Nothing else about the update path changes: it is still user-initiated (or an explicit check), still refuses non-HTTPS and non-GitHub hosts, and still cleans up partial downloads.

### Neutral

- ADR-0002 stays in the repo as history, marked superseded.
- The `updater forces TLS verification` self-test check is replaced by `updater follows the insecure-SSL switch`, which asserts both directions — verification on by default, off while the switch is on — plus the redirect host check and the `UpdateTrustError` message. A hardcoded `verify=` on either side is still a test failure.

## Alternatives Considered

- **Keep ADR-0002 as-is** — rejected by the owner: the switch exists for intercepting proxies, and behind one of those the updater is exactly as broken as everything else it does fix.
- **A second, separate "insecure updates too" checkbox** — rejected (as in ADR-0002, for the same reason plus one): it makes the dangerous option a one-click affair, the explanation does not fit a checkbox label, and a user who already accepted the risk for every other connection gains nothing from a second confirmation surface. The install dialog carries that warning instead, where it is unavoidable.
- **Disable the updater entirely while `insecure_ssl` is on** — rejected: indistinguishable from a broken updater, and it leaves the user on an old build with no in-app path forward.
- **Sign the release asset and verify the signature in-app** — not rejected on merit, and the only real fix: a signature verified against a key shipped in the binary would make the certificate irrelevant for this path. Out of scope here (key management, CI signing, key rotation); if it is ever built, a superseding ADR should re-tighten this decision to "verification off is fine because the payload is signed".

## References

- Supersedes `docs/adr/0002-updater-forces-tls-verification.md`
- `src/listen_to_me/updater.py` (`_get`, `_require_trusted_url`, `verify_download`, `UpdateTrustError`), `src/listen_to_me/netutil.py`
- `src/listen_to_me/selftest.py` (`updater follows the insecure-SSL switch`)
- Issue #20 (the original carve-out)
