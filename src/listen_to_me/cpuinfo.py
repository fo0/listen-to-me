"""CPU topology: how many physical and performance cores this machine has.

The app's one place for questions about the processor itself — the thread
count faster-whisper decodes with (``cfg["cpu_threads"]``), and what the
engine recommendation (``autoconfig``) weighs: the cores, whether the CPU has
AVX2, and its name for the sentence that explains the choice.

faster-whisper's ``cpu_threads=0`` leaves CTranslate2 at its fixed default of
4 threads, whatever the machine: too few for a desktop CPU with more cores
than that, and blind to what the cores are. The logical processor count would
be no better: hyper-threads share one core's execution units, so counting
them adds threads that only contend with each other, and on a hybrid CPU
(Intel 12th gen and later, Apple Silicon) the efficiency cores are several
times slower than the performance cores — a decode split evenly across both
waits for its slowest share. The performance cores are the useful number.

Everything is answered in-process — ``GetLogicalProcessorInformationEx``,
``IsProcessorFeaturePresent`` and the registry on Windows, sysfs and
``/proc/cpuinfo`` on Linux, ``sysctlbyname`` via ctypes on macOS — never by
starting ``wmic``, PowerShell or ``sysctl``: a subprocess flashes a console
window in the windowed Windows build and costs a process start for a number
that never changes while the app runs. Each probe runs once per process
(``functools.lru_cache``).

Never raises: any platform the probes cannot read degrades to
``os.cpu_count()`` for the core counts — the number every caller would have
used without this module — and to None ("unknown") for AVX2 and the name.
Stdlib-only and Qt-free, so it is exercisable headless.
"""

from __future__ import annotations

import functools
import logging
import os
import struct
import sys

log = logging.getLogger(__name__)

# The most threads a configured cpu_threads value is ever honoured with — far
# above any desktop CPU, low enough that a hand-edited 10**6 cannot ask
# CTranslate2 for a million threads.
MAX_CPU_THREADS = 64

# Upper bound for the automatic choice. A Whisper decode stops scaling well
# before this (memory bandwidth, not arithmetic, is the limit beyond it), and
# the rest of the machine — the app being dictated into — keeps some cores.
_AUTO_MAX_THREADS = 8
# CTranslate2's own default (intra_threads=0 → min(4, logical processors)).
_AUTO_MIN_THREADS = 4

# LOGICAL_PROCESSOR_RELATIONSHIP.RelationProcessorCore: one record per core.
_RELATION_PROCESSOR_CORE = 0
_ERROR_INSUFFICIENT_BUFFER = 122

# IsProcessorFeaturePresent feature numbers (winnt.h). SSSE3 through AVX-512F
# (36–41) arrived together; a Windows build that predates them reports False
# for all of them, which is "not asked", not "missing".
_PF_SSSE3_INSTRUCTIONS_AVAILABLE = 36
_PF_AVX2_INSTRUCTIONS_AVAILABLE = 40

# platform.machine() spellings of 32- and 64-bit x86 (lowercased).
_X86_MACHINES = frozenset({"x86_64", "amd64", "x64", "x86", "i386", "i486", "i586", "i686"})

_CPU_NAME_KEY = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"


def logical_cpus() -> int:
    """Logical processors the OS reports (hyper-threads included), at least 1."""
    return max(1, os.cpu_count() or 1)


def _parse_windows_cores(buffer: bytes) -> tuple[int, int] | None:
    """(cores, performance cores) out of a GetLogicalProcessorInformationEx
    buffer for RelationProcessorCore, or None when it holds no core record.

    The buffer is a run of variable-length SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX
    records: DWORD Relationship, DWORD Size, then the PROCESSOR_RELATIONSHIP
    whose first two bytes are Flags and EfficiencyClass. A higher efficiency
    class is a faster core; a non-hybrid CPU reports 0 for every core, which
    makes all of them "performance" cores — the right answer there. Split out
    of the ctypes call so the parsing is testable on any platform.
    """
    classes: list[int] = []
    offset = 0
    while offset + 10 <= len(buffer):
        relationship, size, _flags, efficiency = struct.unpack_from("<IIBB", buffer, offset)
        if size <= 0:
            break  # a malformed record would loop forever
        if relationship == _RELATION_PROCESSOR_CORE:
            classes.append(efficiency)
        offset += size
    if not classes:
        return None
    best = max(classes)
    return len(classes), sum(1 for value in classes if value == best)


def _windows_topology() -> tuple[int, int] | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel32.GetLogicalProcessorInformationEx
    query.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    length = wintypes.DWORD(0)
    # The first call only asks for the size the records need.
    if query(_RELATION_PROCESSOR_CORE, None, ctypes.byref(length)):
        return None
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or not length.value:
        return None
    buffer = ctypes.create_string_buffer(length.value)
    if not query(_RELATION_PROCESSOR_CORE, buffer, ctypes.byref(length)):
        return None
    return _parse_windows_cores(buffer.raw[: length.value])


def _parse_cpulist(text: str) -> set[int]:
    """The CPU numbers of a sysfs cpulist ("0-3,8,10-11")."""
    cpus: set[int] = set()
    for part in text.strip().split(","):
        if not part:
            continue
        low, _, high = part.partition("-")
        cpus.update(range(int(low), int(high or low) + 1))
    return cpus


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="ascii") as fh:
            return fh.read().strip()
    except (OSError, ValueError):
        return None


def _linux_topology(root: str = "/sys/devices/system/cpu") -> tuple[int, int] | None:
    """(physical cores, performance cores) from sysfs.

    A core is identified by its sibling list — every hyper-thread of one core
    reports the same one — counted over the CPUs this process may run on, so a
    container or a ``taskset`` limit is respected. The performance cores are
    the ones with the highest ``cpu_capacity`` (big.LITTLE ARM), else the ones
    in the ``cpu_core`` PMU's list (Intel hybrid on x86), else all of them.
    """
    try:
        allowed = os.sched_getaffinity(0)
    except (AttributeError, OSError):
        allowed = None
    cores: dict[str, set[int]] = {}
    capacity: dict[str, int] = {}
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in names:
        if not (name.startswith("cpu") and name[3:].isdigit()):
            continue
        cpu = int(name[3:])
        if allowed is not None and cpu not in allowed:
            continue
        topology = os.path.join(root, name, "topology")
        siblings = _read(os.path.join(topology, "core_cpus_list")) or _read(
            os.path.join(topology, "thread_siblings_list")
        )
        if not siblings:
            continue  # offline CPUs have no topology to read
        cores.setdefault(siblings, set()).add(cpu)
        value = _read(os.path.join(root, name, "cpu_capacity"))
        if value and value.isdigit():
            capacity[siblings] = max(capacity.get(siblings, 0), int(value))
    if not cores:
        return None
    if capacity and len(capacity) == len(cores) and len(set(capacity.values())) > 1:
        best = max(capacity.values())
        return len(cores), sum(1 for value in capacity.values() if value == best)
    p_list = _read("/sys/devices/cpu_core/cpus")
    if p_list:
        try:
            p_cpus = _parse_cpulist(p_list)
        except ValueError:
            p_cpus = set()
        performance = sum(1 for cpus in cores.values() if cpus & p_cpus)
        if performance:
            return len(cores), performance
    return len(cores), len(cores)


@functools.lru_cache(maxsize=None)
def _macos_sysctlbyname():
    import ctypes

    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    except OSError:
        libc = ctypes.CDLL(None)  # the process's own images, libSystem among them
    function = libc.sysctlbyname
    function.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    function.restype = ctypes.c_int
    return function


def _macos_sysctl_raw(name: str) -> int | None:
    """An integer sysctl as stored (0 included), None when there is no such key."""
    import ctypes

    sysctlbyname = _macos_sysctlbyname()
    value = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    if sysctlbyname(name.encode("ascii"), ctypes.byref(value), ctypes.byref(size), None, 0):
        return None  # -1: no such key (perflevel0 on an Intel Mac)
    return value.value


def _macos_sysctl_int(name: str) -> int | None:
    value = _macos_sysctl_raw(name)
    return value if value is not None and value > 0 else None


def _macos_sysctl_str(name: str) -> str | None:
    import ctypes

    sysctlbyname = _macos_sysctlbyname()
    key = name.encode("ascii")
    size = ctypes.c_size_t(0)
    # The first call only asks for the size the string needs.
    if sysctlbyname(key, None, ctypes.byref(size), None, 0) or not size.value:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if sysctlbyname(key, buffer, ctypes.byref(size), None, 0):
        return None
    return buffer.value.decode("utf-8", "replace")


def _macos_topology() -> tuple[int, int] | None:
    physical = _macos_sysctl_int("hw.physicalcpu")
    if not physical:
        return None
    # Apple Silicon numbers its core clusters by speed, perflevel0 the fastest.
    performance = _macos_sysctl_int("hw.perflevel0.physicalcpu") or physical
    return physical, min(performance, physical)


@functools.lru_cache(maxsize=None)
def _topology() -> tuple[int, int] | None:
    """(physical cores, performance cores), or None when the platform probe
    could not answer. Computed once per process."""
    try:
        if sys.platform == "win32":
            result = _windows_topology()
        elif sys.platform == "darwin":
            result = _macos_topology()
        elif sys.platform.startswith("linux"):
            result = _linux_topology()
        else:
            result = None
    except Exception:
        log.debug("CPU topology probe failed — using os.cpu_count()", exc_info=True)
        result = None
    if result is not None:
        physical, performance = result
        if physical < 1 or not 1 <= performance <= physical:
            result = None
    if result is None:
        log.debug("CPU topology unknown — counting %d logical CPUs", logical_cpus())
    else:
        log.info("CPU topology: %d physical core(s), %d performance core(s)", *result)
    return result


def physical_cores() -> int:
    """Physical cores (hyper-threads not counted), at least 1. Falls back to
    the logical processor count when the platform cannot be asked."""
    topology = _topology()
    return topology[0] if topology else logical_cpus()


def performance_cores() -> int:
    """Performance cores, at least 1 — the physical cores on a CPU that is not
    hybrid, the logical processor count when the platform cannot be asked."""
    topology = _topology()
    return topology[1] if topology else logical_cpus()


def resolve_cpu_threads(value) -> int:
    """The thread count to run a CPU decode with, for ``cfg["cpu_threads"]``.

    0 — and anything that is not a positive whole number (a negative value, a
    string that is not one, a bool) — means automatic: the performance cores,
    held to 1–8, but never fewer than the 4 CTranslate2 used before (or the
    physical cores, when there are fewer). The floor is for the common
    business laptop with 2 P-cores next to 8 E-cores (the U-series): P-cores
    alone would halve the threads it ran with, unmeasured. A positive number
    is used as configured, held to the logical processors there are and to
    MAX_CPU_THREADS. Never raises.
    """
    count = 0
    if not isinstance(value, bool):
        try:
            count = int(value)
        except (TypeError, ValueError, OverflowError):
            count = 0
    if count <= 0:
        floor = min(_AUTO_MIN_THREADS, physical_cores())
        count = min(max(performance_cores(), floor), _AUTO_MAX_THREADS)
    return max(1, min(count, logical_cpus(), MAX_CPU_THREADS))


# ------------------------------------------------- instruction set and name


def _machine() -> str:
    """The process's CPU architecture, lowercased ("amd64", "x86_64", "arm64").

    Not platform.machine(): on Windows before Python 3.12 that goes through
    platform.uname(), which may start ``cmd /c ver`` — the subprocess this
    module never starts. The environment says the same thing for free.
    """
    if sys.platform == "win32":
        value = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get(
            "PROCESSOR_ARCHITECTURE", ""
        )
    else:
        try:
            value = os.uname().machine
        except (AttributeError, OSError):
            value = ""
    return value.strip().lower()


def is_x86() -> bool | None:
    """Whether this is an x86 / x86-64 CPU — the family AVX2 belongs to. None
    when the architecture cannot be told."""
    machine = _machine()
    if not machine:
        return None
    return machine in _X86_MACHINES


def _parse_proc_cpuinfo(text: str) -> dict[str, str]:
    """The first processor's ``key: value`` lines out of /proc/cpuinfo text —
    every processor repeats the same flags and model name. Split out of the
    file read so the parsing is testable on any platform."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if fields:
                break  # the blank line that ends the first processor's block
            continue
        key, sep, value = line.partition(":")
        if sep:
            fields.setdefault(key.strip().lower(), value.strip())
    return fields


@functools.lru_cache(maxsize=None)
def _proc_cpuinfo() -> dict[str, str]:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            return _parse_proc_cpuinfo(fh.read())
    except OSError:
        return {}


def _windows_avx2() -> bool | None:
    import ctypes
    from ctypes import wintypes

    present = ctypes.WinDLL("kernel32").IsProcessorFeaturePresent
    present.argtypes = [wintypes.DWORD]
    present.restype = wintypes.BOOL
    if not present(_PF_SSSE3_INSTRUCTIONS_AVAILABLE):
        # Every x86-64 CPU of the last 15 years has SSSE3: a False here is a
        # Windows build that does not know feature numbers this new, whose
        # AVX2 answer would be False for a CPU that has it.
        return None
    return bool(present(_PF_AVX2_INSTRUCTIONS_AVAILABLE))


def _linux_avx2() -> bool | None:
    flags = _proc_cpuinfo().get("flags")
    return None if flags is None else "avx2" in flags.split()


def _macos_avx2() -> bool | None:
    value = _macos_sysctl_raw("hw.optional.avx2_0")
    return None if value is None else value > 0


@functools.lru_cache(maxsize=None)
def has_avx2() -> bool | None:
    """Whether the CPU executes AVX2 — CTranslate2's fast int8 kernels on x86
    need it, and without it a large Whisper model decodes several times
    slower. False on a CPU that is not x86 (no AVX2 exists there; its own
    vector units are what the engines use), None when it cannot be told.
    Computed once per process; never raises."""
    try:
        if is_x86() is False:
            result = False
        elif sys.platform == "win32":
            result = _windows_avx2()
        elif sys.platform == "darwin":
            result = _macos_avx2()
        elif sys.platform.startswith("linux"):
            result = _linux_avx2()
        else:
            result = None
    except Exception:
        log.debug("AVX2 probe failed", exc_info=True)
        result = None
    log.debug("CPU AVX2: %s", {True: "yes", False: "no", None: "unknown"}[result])
    return result


def _windows_cpu_name() -> str | None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CPU_NAME_KEY) as key:
        value, _kind = winreg.QueryValueEx(key, "ProcessorNameString")
    return value if isinstance(value, str) else None


@functools.lru_cache(maxsize=None)
def cpu_name() -> str | None:
    """The processor's marketing name ("12th Gen Intel(R) Core(TM) i7-1265U"),
    whitespace-collapsed, or None when the platform does not say — for the
    text that explains a recommendation, never for a decision. Computed once
    per process; never raises."""
    try:
        if sys.platform == "win32":
            name = _windows_cpu_name()
        elif sys.platform == "darwin":
            name = _macos_sysctl_str("machdep.cpu.brand_string")
        elif sys.platform.startswith("linux"):
            name = _proc_cpuinfo().get("model name")
        else:
            name = None
    except Exception:
        log.debug("CPU name probe failed", exc_info=True)
        name = None
    name = " ".join(name.split()) if name else ""
    return name or None
