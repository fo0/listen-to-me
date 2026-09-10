"""Recording what the computer PLAYS, through a loopback/monitor input device.

The second global hotkey (#191) records the machine's own output — a call, a
meeting, a video — instead of the microphone. The capture reads from a
perfectly ordinary PortAudio *input* device that the OS already provides:

* Linux (PulseAudio/PipeWire): every sink has a "Monitor of <sink>" source, so
  there is always a candidate.
* Windows: "Stereo Mix" / "What U Hear" on most onboard audio — present but
  disabled by default (Sound Control Panel → Recording → Show Disabled
  Devices) — or a virtual cable ("CABLE Output" from VB-CABLE, "VoiceMeeter
  Out").
* macOS: nothing built in. A virtual output device has to be installed
  (BlackHole, Soundflower, Rogue Amoeba Loopback).

Why through a device at all, rather than asking WASAPI for a loopback stream
of the output directly: the shipped stack cannot. sounddevice 0.5.6 exposes no
loopback option, and the PortAudio binary in its Windows wheel is
V19.7.0-devel, which does not export `PaWasapi_IsLoopback`. A newer PortAudio
additionally enumerates every output device a second time as "<name>
[Loopback]" — so the ranking below scores that suffix highest although today's
binary never emits it, and the day the wheel carries a newer PortAudio the
auto-pick simply gets better with no code change.

Qt-free, and `audio` is imported lazily inside the functions, so these rules
stay testable headless and `--version` / `--selftest` pull in no PortAudio.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)


# Name fragments that identify a loopback/monitor capture device, each with the
# weight it contributes to a candidate's score — the ranking is data, so a
# device name nobody has seen yet is one line here instead of a branch in the
# matcher. Fragments are lowercase; the device name is casefolded before the
# comparison. Where each group comes from:
#
# * "<name> [Loopback]" — a newer PortAudio enumerates every *output* device a
#   second time as a loopback input: the strongest hint there is. Matched on
#   purpose although the PortAudio binary in today's sounddevice wheel
#   (V19.7.0-devel) never emits it — the day it does, this keeps working.
# * "Monitor of …" / "Monitor von …" — PulseAudio/PipeWire give every sink a
#   monitor source, so Linux always has a candidate. The localized spelling is
#   listed because that label comes from the desktop, not from us.
# * Stereo Mix / What U Hear — Windows onboard audio: usually present, but
#   disabled by default (system_audio_help says how to enable it). CABLE Output
#   / VoiceMeeter Out are the Windows virtual cables to fall back to when the
#   chipset has none.
# * BlackHole / Soundflower, plus bare "loopback" for Rogue Amoeba's Loopback —
#   macOS, which ships no loopback device at all. Bare "loopback" carries the
#   lowest weight: it is also a substring of the "[Loopback]" suffix above and
#   of unrelated product names.
LOOPBACK_HINTS = [
    ("[loopback]", 100),
    ("monitor of", 90),
    ("monitor von", 90),
    ("stereo mix", 70),
    ("stereomix", 70),
    ("stereo-mix", 70),
    ("what u hear", 70),
    ("cable output", 60),
    ("voicemeeter out", 60),
    ("blackhole", 60),
    ("soundflower", 60),
    ("loopback", 40),
]


def _loopback_score(name: str) -> tuple[int, str | None]:
    """The summed LOOPBACK_HINTS weight of `name` plus the strongest fragment
    that matched — (0, None) for a device that looks like a plain microphone.

    Overlapping fragments add up on purpose: "Speakers (Realtek) [Loopback]"
    matches both "[loopback]" and "loopback", and a name that trips two hints
    is a safer bet than one that trips a single weak one.
    """
    lowered = (name or "").casefold()
    score = 0
    best: tuple[int, str] | None = None
    for fragment, weight in LOOPBACK_HINTS:
        if fragment not in lowered:
            continue
        score += weight
        if best is None or weight > best[0]:
            best = (weight, fragment)
    return score, best[1] if best else None


def loopback_candidates(profiles: list[dict] | None = None) -> list[dict]:
    """The input devices that look like a loopback capture, best first.

    Each entry is that device's `audio.input_device_profiles` profile plus
    "score" (the weight that matched) and "hint" (the fragment that matched).
    The hint is what lets the UI say *why* a device is offered — "Monitor of
    Built-in Audio" is not self-explanatory to someone who never chose it.

    `profiles` is injectable so the rule is testable headlessly, the same
    reason :func:`choices.resolve_input_device` takes `devices`; left out, the
    live list is enumerated. Never raises: a failed enumeration is logged and
    yields no candidates, which every caller has to handle anyway — a machine
    can simply have no loopback device.
    """
    if profiles is None:
        try:
            from .audio import input_device_profiles

            profiles = input_device_profiles()
        except Exception:
            log.exception("could not list audio devices to look for a loopback capture")
            return []
    ranked: list[tuple[int, int, dict]] = []
    for position, profile in enumerate(profiles):
        score, hint = _loopback_score(str(profile.get("name") or ""))
        if score <= 0:
            continue
        ranked.append((-score, position, {**profile, "score": score, "hint": hint}))
    # Equal scores keep PortAudio's enumeration order, so the device offered
    # matches the one the dropdown lists first and does not shuffle per call.
    ranked.sort(key=lambda entry: entry[:2])
    return [candidate for _score, _position, candidate in ranked]


def system_audio_help() -> str:
    """How to get a loopback device on this platform.

    One wording in one place: the same sentence goes into the notification
    that explains a refused take and into the Settings hint shown before one
    is ever attempted. Two drifting copies of an instruction are how a user
    ends up following the one that no longer matches their system.
    """
    if sys.platform.startswith("win"):
        return (
            "Enable “Stereo Mix” in the Windows sound control panel (Recording tab → "
            "right-click → Show Disabled Devices), or install a virtual audio cable "
            "such as VB-CABLE and play through it."
        )
    if sys.platform == "darwin":
        return (
            "macOS has no loopback device of its own — install a virtual output "
            "device such as BlackHole and route the playback through it."
        )
    return (
        "Select the “Monitor of …” source that belongs to your output device — "
        "PulseAudio and PipeWire provide one for every output."
    )


def resolve_loopback_device(
    configured: int | None, profiles: list[dict] | None = None
) -> tuple[int | None, str | None]:
    """The device a system-audio take records from, plus the sentence to show
    when that is not the one the user configured (None = nothing to report).

    **A returned index of None means "refuse to start the take" — it does NOT
    mean "record from the system default".** That is the one way this contract
    deliberately differs from :func:`choices.resolve_input_device`, where None
    means exactly that. The system default input *is* a microphone: falling
    back to it here would record the room while the user asked for what the
    computer plays. That is a wrong result, not a degraded one — it would put
    a conversation in the room into a transcript the user believes came from a
    meeting, and nothing about the text would give that away. So a None index
    always carries a non-None, actionable note, and the caller shows the note
    instead of recording.

    Which device it is:

    * a configured index that still exists — that one, nothing to report;
    * nothing configured ("device": null) — the best of
      :func:`loopback_candidates`, with no note: auto-pick is the documented
      default, not a fallback worth interrupting a take for (it is logged);
    * a configured index that is gone — PortAudio indices are positional, so
      unplugging one interface re-indexes the rest — the best candidate
      instead, plus a note naming both;
    * no candidate at all — no index, and a note naming the fix.

    `profiles` is injectable for headless tests. An enumeration that fails or
    comes back empty passes a configured index through untouched, exactly as
    :func:`choices.resolve_input_device` does: it cannot tell "the device is
    gone" from "PortAudio could not be asked", and only the auto case can then
    report that nothing was found. A `configured` value that is not an index
    is passed through unvalidated for the same reason as there — config.json
    is untrusted, the null default carries no type information, and a device
    *name* is something PortAudio resolves itself. (`bool` is an int subclass,
    and `True` is not a device.)
    """
    is_index = isinstance(configured, int) and not isinstance(configured, bool)
    if configured is not None and not is_index:
        return configured, None
    if profiles is None:
        try:
            from .audio import input_device_profiles

            profiles = input_device_profiles()
        except Exception:
            log.exception("could not check whether the system-audio device still exists")
            profiles = []
    if is_index and (
        not profiles or any(profile.get("index") == configured for profile in profiles)
    ):
        return configured, None
    candidates = loopback_candidates(profiles)
    if not candidates:
        if is_index:
            return None, (
                f"The device selected for system audio (index {configured}) is no longer "
                "available and no other loopback device was found — nothing was recorded. "
                + system_audio_help()
            )
        return None, (
            "No device for recording what the computer plays was found — nothing was "
            "recorded. " + system_audio_help()
        )
    best = candidates[0]
    if is_index:
        return best["index"], (
            f"The device selected for system audio (index {configured}) is no longer "
            f"available — recording from “{best.get('name')}” instead. Pick it again "
            "under Settings → Audio."
        )
    log.info(
        "system audio: auto-selected input device %s (%r, matched %r)",
        best["index"], best.get("name"), best.get("hint"),
    )
    return best["index"], None
