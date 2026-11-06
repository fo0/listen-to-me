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
of the output directly: sounddevice 0.5.6 exposes no loopback option, so the
only way in is a device. Which devices exist then depends on the PortAudio
binary that answers, and since #194 that differs between the two builds:

* **Released Windows exe:** it ships its own newer `portaudio.dll` (ADR-0010,
  `portaudio.py`), which enumerates every WASAPI render endpoint a second time
  as a "<name> [Loopback]" input. So every output has a candidate, "Stereo
  Mix" or a virtual cable is needed for nothing, and the ranking below picks
  the twin because "[loopback]" is its strongest hint.
* **Source install / non-Windows build:** `sounddevice` loads the PortAudio
  inside its own wheel. That binary is V19.7.0-devel and does not export
  `PaWasapi_IsLoopback`; it emits no "[Loopback]" twin at all, which is why
  the Windows list above (Stereo Mix, virtual cable) is what a `pip install`
  has to work with. The same is true of a released exe whose bundled DLL was
  turned off through `system_audio.bundled_portaudio`.

The version string cannot tell the two binaries apart — both report
`V19.7.0-devel` — which is the reason `portaudio.py` exists and reports the
loaded *file* instead. Nothing in this module branches on any of it: the
ranking is name matching, so it is the same code either way and simply finds
more candidates on the build that enumerates more.

Qt-free, and `audio` is imported lazily inside the functions, so these rules
stay testable headless and `--version` / `--selftest` pull in no PortAudio.
"""

from __future__ import annotations

import logging
import sys
from typing import NamedTuple

log = logging.getLogger(__name__)


# Name fragments that identify a loopback/monitor capture device, each with the
# weight it contributes to a candidate's score — the ranking is data, so a
# device name nobody has seen yet is one line here instead of a branch in the
# matcher. Fragments are lowercase; the device name is casefolded before the
# comparison. Where each group comes from:
#
# * "<name> [Loopback]" — a newer PortAudio enumerates every *output* device a
#   second time as a loopback input: the strongest hint there is, and what the
#   released Windows exe actually sees since it ships such a binary (#194).
#   The PortAudio in the sounddevice wheel — every source install — never
#   emits it, so both builds keep working off this one list.
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
# How many output devices the hint spells out by name before it counts the
# rest. A studio interface can expose a dozen, and a hint that grows into a
# paragraph is one nobody reads.
OUTPUTS_NAMED = 3
# The shortest name half that may stand in for a whole output name when a
# loopback device is matched to its output. Windows' MME host API truncates
# device names to 31 characters, so "Monitor of <long output name>" and the
# output itself agree only on a prefix — but a prefix of two or three
# characters would pair devices that have nothing to do with each other.
_OUTPUT_PREFIX_MIN = 8


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


def loopback_output_name(candidate: dict) -> str | None:
    """The OUTPUT device a loopback candidate records, read out of its own
    name — or None where the name carries no such mapping (#195).

    "Monitor of Built-in Audio Analog Stereo" and "Speakers (Realtek) [Loopback]"
    both carry the output they belong to, and the user thinks in outputs: the
    mechanism marker is display noise in front of the only word they recognize.
    Keyed on the fragment `loopback_candidates` reports as "hint", so this
    never keeps a second list of markers — a prefix hint names the output
    after it, the suffix hint names it before.

    "Stereo Mix", "CABLE Output" and "BlackHole" carry no output name at all,
    and none is invented for them: a made-up mapping would promise that a take
    comes from a specific output when nothing in the system says so.
    """
    name = str(candidate.get("name") or "").strip()
    hint = str(candidate.get("hint") or "")
    if not name or not hint:
        return None
    lowered = name.casefold()
    if hint in ("monitor of", "monitor von"):
        cut = lowered.find(hint)
        if cut >= 0:
            return name[cut + len(hint):].strip(" :–—-") or None
    if hint == "[loopback]":
        cut = lowered.rfind(hint)
        if cut >= 0:
            return name[:cut].strip(" :–—-") or None
    return None


def device_label(profile: dict) -> str:
    """One row of the system-audio dropdown: "<index>: <what the user thinks
    this is>", plus why it is offered when it is a loopback candidate.

    The index prefix is load-bearing — `choices.input_device_from_label` parses
    it back and Save writes exactly what that returns, so it stays first and
    stays the only ":" this function can put in front of the name.

    A candidate is labelled with the *output* it records where its name says
    so, and with the name fragment that identified it — never with its score,
    which is a sum of weights and not a percentage ("170" says nothing;
    “monitor of” says why this row is here). Where no output can be read out
    of the name the raw device name stays, marked as a loopback input rather
    than as an output it may not be.
    """
    index = profile.get("index")
    name = str(profile.get("name") or f"Device {index}")
    hint = profile.get("hint")
    if not hint:
        return f"{index}: {name}"
    output = loopback_output_name(profile)
    if output:
        return f"{index}: {output}  — records this output, matched “{hint}”"
    return f"{index}: {name}  — loopback input, matched “{hint}”"


def outputs_without_loopback(outputs: list[str], candidates: list[dict]) -> list[str]:
    """The output devices no loopback candidate covers — the ones the hint has
    to name, because they are what the user came to the card to pick (#195).

    An output counts as covered when some candidate's name resolves to it
    (`loopback_output_name`). Matched on equality or on a prefix of at least
    `_OUTPUT_PREFIX_MIN` characters: Windows' MME host API truncates device
    names to 31 characters, so the output entry and the loopback entry of one
    device can differ in their tail while naming the same hardware.

    Order is PortAudio's, so the hint lists the outputs in the order the
    Windows sound panel does. A candidate that maps to no output at all
    ("Stereo Mix") covers nothing — it may well carry the output the user
    wants, but nothing in its name says which, and this list is only used to
    say what cannot be recorded *directly*.
    """
    covered = [
        name.strip().casefold()
        for name in (loopback_output_name(candidate) for candidate in candidates)
        if name and name.strip()
    ]
    missing: list[str] = []
    for output in outputs:
        key = str(output or "").strip()
        if not key:
            continue
        folded = key.casefold()
        if any(
            folded == other
            or (
                min(len(folded), len(other)) >= _OUTPUT_PREFIX_MIN
                and (folded.startswith(other) or other.startswith(folded))
            )
            for other in covered
        ):
            continue
        missing.append(key)
    return missing


def output_list_phrase(names: list[str], limit: int = OUTPUTS_NAMED) -> str:
    """“A”, “B” and 7 more — a bounded enumeration for the hint.

    Bounded on purpose: the sentence has to be readable on a machine with two
    outputs and on one with fifteen, and the count carries the rest. Quoted
    because an output name can be a whole phrase ("Speakers (Realtek(R)
    Audio)") that would otherwise dissolve into the sentence around it.

    An empty list gives an empty string rather than an `IndexError` on
    `quoted[-1]`. Its only caller today is guarded by `if missing:`, which is
    exactly why the guard belongs here: nothing about the signature says the
    list may not be empty, and the next caller reads the signature.
    """
    if not names:
        return ""
    quoted = [f"“{name}”" for name in names[:limit]]
    rest = len(names) - len(quoted)
    if rest > 0:
        quoted.append(f"{rest} more")
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


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


class LoopbackChoice(NamedTuple):
    """What a system-audio take should do — the answer of
    :func:`resolve_loopback_device`.

    Three fields rather than the obvious two, because two had the exact shape
    of :func:`choices.resolve_input_device`'s answer — ``(index, note)`` — with
    the *opposite* meaning for a None index: refuse the take here, record from
    the system default there. The two functions no longer sit in one module
    where a reader sees them side by side, and the next caller (a "Test system
    audio" button next to the existing "Test microphone" is the obvious one) is
    where the wrong sibling gets copied from. ``device, note =
    resolve_loopback_device(...)`` now raises ``ValueError: too many values to
    unpack`` on the very first system-audio take instead of silently recording
    a microphone.

    `refuse` is True exactly when `index` is None: the flag is the half a
    reader cannot misread, the None is what the recorder would act on.
    """

    index: int | None
    note: str | None
    refuse: bool


def _stale_index_phrase(configured, found: dict | None) -> str:
    """How a note names a configured index that must not be recorded from:
    either gone, or still there but no longer a loopback device.

    Both halves are named on purpose — the device now sitting at the index is
    what makes "why is my microphone in this transcript?" answerable, and it is
    the same sentence's job to say which device is used instead.
    """
    where = f"The device selected for system audio (index {configured})"
    if found is None:
        return f"{where} is no longer available"
    return f"{where} is now “{found.get('name')}”, which does not look like a loopback device"


def resolve_loopback_device(
    configured: int | None, profiles: list[dict] | None = None
) -> LoopbackChoice:
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
    instead of recording. `LoopbackChoice.refuse` says the same thing in a
    field the caller cannot mistake for its sibling's meaning; the docstring is
    no longer the only guard.

    Which device it is:

    * a configured index that still points at a device that *looks* like a
      loopback capture — that one, nothing to report;
    * nothing configured ("device": null) — the best of
      :func:`loopback_candidates`, with no note: auto-pick is the documented
      default, not a fallback worth interrupting a take for (it is logged);
    * a configured index that is gone, or that now carries a device with no
      loopback hint in its name — PortAudio indices are positional, so
      unplugging one interface moves the stored index onto whatever device
      follows, a microphone included — the best candidate instead, plus a note
      naming the device found there *and* the one recorded from;
    * no candidate at all — no index, and a note naming the fix.

    The score check is what stops the worst outcome the feature has: an index
    that still exists is not the device it was chosen for, so accepting it on
    existence alone recorded the room with `note` left at None — nothing said,
    nothing to notice, the transcript stored as the computer's audio (ADR-0009
    rejects exactly that). A device whose name carries no hint at all is
    therefore treated like a missing one. It costs the take that a loopback
    device with an unheard-of name would have delivered — a note names it and
    LOOPBACK_HINTS takes one line to learn it, which is the direction of the
    two errors this has to choose between.

    `profiles` is injectable for headless tests. An enumeration that fails or
    comes back empty passes a configured index through untouched, exactly as
    :func:`choices.resolve_input_device` does: it cannot tell "the device is
    gone" from "PortAudio could not be asked", so it cannot score anything
    either, and only the auto case can then report that nothing was found.

    A `configured` value that is not an index is refused, which is where this
    parts company with `input_device` a second time: a device *name* buys
    nothing here (the settings dropdown only ever writes an index or null, so a
    non-int is a broken hand-edit, not a name for PortAudio to resolve), and
    handing one on has a specific cost — `bool` is an int subclass, sounddevice
    validates nothing, and `True` therefore resolves to input device 1, i.e. a
    nonsense config value records the default microphone.
    """
    if configured is not None and (
        not isinstance(configured, int) or isinstance(configured, bool)
    ):
        log.warning("system_audio.device is %r, which is not a device index", configured)
        return LoopbackChoice(
            None,
            f"The device selected for system audio is not a device index ({configured!r}) — "
            "nothing was recorded. Pick the device again under Settings → Audio.",
            True,
        )
    is_index = configured is not None
    if profiles is None:
        try:
            from .audio import input_device_profiles

            profiles = input_device_profiles()
        except Exception:
            log.exception("could not check whether the system-audio device still exists")
            profiles = []
    if is_index and not profiles:
        return LoopbackChoice(configured, None, False)
    at_index = None
    if is_index:
        at_index = next(
            (profile for profile in profiles if profile.get("index") == configured), None
        )
        if at_index is not None and _loopback_score(str(at_index.get("name") or ""))[0] > 0:
            return LoopbackChoice(configured, None, False)
    candidates = loopback_candidates(profiles)
    if not candidates:
        if is_index:
            return LoopbackChoice(
                None,
                f"{_stale_index_phrase(configured, at_index)} and no other loopback device "
                "was found — nothing was recorded. " + system_audio_help(),
                True,
            )
        return LoopbackChoice(
            None,
            "No device for recording what the computer plays was found — nothing was "
            "recorded. " + system_audio_help(),
            True,
        )
    best = candidates[0]
    if is_index:
        log.warning(
            "system audio: configured index %s is %r — recording from %s (%r) instead",
            configured, None if at_index is None else at_index.get("name"),
            best["index"], best.get("name"),
        )
        return LoopbackChoice(
            best["index"],
            f"{_stale_index_phrase(configured, at_index)} — recording from "
            f"“{best.get('name')}” instead. Pick it again under Settings → Audio.",
            False,
        )
    log.info(
        "system audio: auto-selected input device %s (%r, matched %r)",
        best["index"], best.get("name"), best.get("hint"),
    )
    return LoopbackChoice(best["index"], None, False)
