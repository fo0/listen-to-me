# Deployment

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps trigger + pipeline path + agent scope + the merge/dispatch rule; this file carries the full wording and the mechanics.

## Trigger & pipeline

- **Trigger:** manual `workflow_dispatch` on `.github/workflows/release.yml`. It builds the Windows one-file exe and publishes a GitHub Release tagged `vYYYY.MM.DD.<run>`. A guard job fails any dispatch from a ref other than `main`.
- **Verification reuse:** `release.yml` calls the `ci.yml` `check` job via `workflow_call`, so a release can never be built from a red tree.
- **PRs** only run the `ci.yml` `check` job — never a build, never a release.
- **Distribution:** portable single-file `ListenToMe-<date>-<hhmm>-win64.exe` (UTC timestamp) attached to the Release. The in-app updater (`updater.py`) offers newer releases from the GitHub Releases API.
- **Environments:** none. There is no server; the "environment" is the user's desktop.

## Agent scope

The agent may push to feature branches and open/update PRs. Merging a PR and dispatching the release build each require an explicit user command.

**Routine exception.** A session running an **owner-authorized routine** counts as an explicit user command. Its merges are pre-approved — _including_ any pipeline a merge triggers — provided **both** conditions hold:

- the change set is **non-destructive**: additive; no history rewrite, no force-push, no repo-settings change, no migration forced on existing users; **and**
- **verification passed**: the `ci.yml` `check` job, or its local equivalent (`python -m compileall -q src scripts` plus the offscreen `gui_smoke`), is green.

**Destructive change sets stay gated** behind an explicit interactive user command — no routine substitutes for one there.

**Accepted risk.** The routine claim arrives as prompt text, which reaches a session from outside the repository, and the agent cannot verify it: a scheduled trigger someone else edited, or an instruction injected through an issue or PR body, can assert routine status and inherit merge rights on a repo whose release workflow runs with `contents: write`. The owner accepted that trade knowingly, for fleet-wide consistency with the fifteen sibling repos and for automation throughput. The mitigations that remain are the two conditions above, the SHA-pinned actions (#22), and the fact that a merge alone publishes nothing — `release.yml` is `workflow_dispatch`-only and guarded to `main`. Full reasoning and alternatives: ADR-0005, superseding ADR-0004 (issue #21).

Merge gate: `.claude/skills/pr/SKILL.md → /pr merge`.

## GitHub Actions are pinned by commit SHA

Never by tag (#22). A tag can be moved to point at different code, and `release.yml` runs with `contents: write` and publishes the exe the in-app updater hands to users.

- Format: `uses: owner/repo@<40-hex-sha> # vX.Y.Z`
- To bump one, resolve the new SHA first: `git ls-remote --tags https://github.com/<owner>/<repo>`. For an annotated tag take the `^{}` line — that is the commit.
- Update the trailing comment with the new version.
- Dependabot proposes these bumps weekly and groups them into one PR (`.github/dependabot.yml`); it rewrites the SHA **and** the trailing version comment together, which is this same procedure. Review the pair before merging — a bump made by hand still follows the steps above.

## PortAudio is pinned by commit SHA too

The `build-windows` job builds `portaudio.dll` from source and ships it in the one-file exe, so system audio (#191, ADR-0009) can capture any output device through WASAPI loopback instead of needing `Stereo Mix` or a virtual cable (#194). `sounddevice` resolves `find_library('portaudio')` — `portaudio.dll` on `PATH` — before its own bundled copy, so the file name is the whole integration. The pin lives in that job's `env` block:

```yaml
PORTAUDIO_COMMIT: a4dbf68c51fd32734f32657db64849aac24739e7 # PortAudio master, fetched 2026-09-10
```

The last PortAudio release, 19.7.0 (2021), predates loopback support, so this is necessarily a **master commit** and the SHA is the only version identity there is. Same rule as the actions above (#22), for a stronger reason: this is native code inside a binary end users run, and a branch or tag would let a rebuild pull in something else.

### Bumping the pin

1. Resolve the new SHA: `git ls-remote https://github.com/PortAudio/portaudio.git refs/heads/master`. Full 40 hex characters, never abbreviated.
2. Read the range (`https://github.com/PortAudio/portaudio/compare/<old>...<new>`) and confirm all five things the build leans on still hold:
   - `include/pa_win_wasapi.h` still declares `PaWasapi_IsLoopback`.
   - `src/hostapi/wasapi/pa_win_wasapi.c` still appends the `[Loopback]` name marker (`PA_WASAPI_LOOPBACK_NAME_IDENTIFICATOR`, used by `FillLooopbackDeviceInfo`). This is a **name-based contract**: the app finds these devices through `system_audio.LOOPBACK_HINTS`, so a renamed marker breaks the feature while the DLL still builds and still exports the function. Upstream's "do not change!" comment is a convention, not a guarantee.
   - `CMakeLists.txt` still knows `PA_BUILD_SHARED_LIBS`, `PA_USE_WASAPI`, `PA_DLL_LINK_WITH_STATIC_RUNTIME`, `PA_BUILD_TESTS` and `PA_BUILD_EXAMPLES` — CMake ignores an unknown `-D` with a warning, so a renamed option changes the build silently.
   - What `cmake_minimum_required` asks for, because it decides which of the two static-runtime mechanisms is live. Below 3.15 (upstream asks for 3.10) policy CMP0091 stays OLD and `PA_DLL_LINK_WITH_STATIC_RUNTIME` works, by string-replacing `/MD` with `/MT` in `CMAKE_C_FLAGS_*`. At 3.15 or above the policy is NEW, the runtime flag is not in those variables at all and that replace becomes a **silent no-op** — which is why the workflow also passes `-DCMAKE_POLICY_DEFAULT_CMP0091=NEW -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded`, the abstraction that replaced the flags. Exactly one of the two is ever in force and the import-table assertion below is what catches it if a bump breaks both.
   - `set_target_properties(portaudio PROPERTIES OUTPUT_NAME portaudio)` still stands, i.e. the artifact is still named `portaudio.dll`.
3. Update the SHA and its trailing `# PortAudio master, fetched <date>` comment together — the same procedure as an action pin.

### Verifying a bump

- The build's own gate is the **Verify the PortAudio DLL exports WASAPI loopback** step, and its assertions each prove one thing and not the next one:
  - The `ctypes` load proves the file is a PE that a 64-bit Python can load, so it catches a 32-bit build. It proves **nothing** about the MSVC redistributable: `windows-latest` has Visual Studio and therefore that runtime, so a `/MD`-linked DLL loads on the runner exactly as happily as a `/MT` one.
  - The `PaWasapi_IsLoopback` export proves `PA_USE_WASAPI` was on, because `cmake/portaudio.def.in` drops every `PaWasapi_*` export without it.
  - Parsing the DLL's own PE import table — the import directory and the delay-load one — proves the static runtime took effect, by finding no import from a redistributable family (`vcruntime140.dll`, `msvcp140.dll`, `msvcr120.dll`, `concrt140.dll`; Windows' own `msvcrt.dll` is not one of them and does not fail the gate). Only the file can answer this, which is why the step reads it.
- End to end the check is the exe's `--selftest` in the **Smoke test executable** step. That is the only place WASAPI exists at all — the Linux `check` job cannot see any of it.
- Both live in `release.yml`, which is `workflow_dispatch`-only and guarded to `main`, so **a bump is not verifiable in a PR**: it is verified the first time a release is dispatched after the merge. To check earlier, run the job's `cmake` commands by hand on a Windows machine with Visual Studio 2022 plus CMake and inspect the result with `dumpbin /exports portaudio.dll` and `dumpbin /dependents portaudio.dll` from a Developer Command Prompt.
- A DLL that is found but refuses to load costs only the feature, not the app: `sounddevice` wraps the whole `find_library` path in `try: … except OSError` (0.5.6, lines 63-91) and falls back to its own `libportaudio64bit.dll`. That is why the CI gate above loads the DLL itself — the fallback would otherwise hide a broken build until someone looked for a `[Loopback]` device.
- The version string cannot tell you which DLL got loaded: this master commit still reports `PortAudio V19.7.0-devel` (`paVersionMinor` is still 7 in `src/common/pa_front.c`), exactly what the `sounddevice` wheel's DLL reports. The `PaWasapi_IsLoopback` export and the presence of `[Loopback]` input devices are the discriminators.

### Costs, stated plainly

- The DLL comes from a **non-release commit**, so there are no upstream release notes to read: every bump is a judgment call over a raw commit range.
- It is **unsigned**, like the exe — this changes nothing about the SmartScreen warning.
- The release job carries a native toolchain step (fetch, CMake configure, MSVC build) and the wall clock it costs, on every dispatch.
- **A source install ships no DLL.** `pip install -e .` leaves `sounddevice` on its own bundled copy, so Windows users running from source still need `Stereo Mix` or a virtual cable.

## Rollback

See `.claude/skills/rollback/SKILL.md`. For a bad release, prefer a revert-PR plus a fresh dispatched build over hand-editing a published asset — the updater serves whatever the Release carries.

<!-- Generated by claude-code-optimizer v1.42.0 -->
