# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Released Windows builds are published on the
[GitHub Releases](https://github.com/fo0/listen-to-me/releases) page — each
release lists the commits it contains (auto-generated) and attaches the portable
`.exe`. Release tags follow the `vYYYY.MM.DD.<build>` scheme, so the Releases
page is the authoritative, always-current history; this file highlights notable
changes at a glance.

## [Unreleased]

### Added

- **Heads-up before the maximum recording length** — a notification 30 seconds
  before the cap ends a running take, instead of only "Maximum recording length
  reached." once everything said after it was already lost.
- **Export transcripts** in Settings → History: an **Export…** button writes the
  listed transcripts — the search field filters them — to a plain text file,
  each with its timestamp.
- **Delete a single transcript** in Settings → History: every entry now has its
  own **Delete** button next to **Copy**, so one dictation that should not stay
  on disk no longer costs the whole history.
- **Copy last transcript** in the tray menu and the floating icon's right-click
  menu — puts the text of the most recent recording back on the clipboard
  without opening Settings → History.
- The tray status line and the floating icon's tooltip now name the configured
  hotkey ("Idle — press Ctrl+Alt+Space to record") instead of saying "the
  hotkey", and follow it when it is changed in the settings.

### Fixed

- A `config.json` with a wrong-typed value (a quoted number, a string where a
  number belongs, `null` where a value belongs) no longer reaches the code that
  uses it: plausible hand-edits are repaired, anything else falls back to that
  one option's default instead of failing during startup.

### Changed

- **"Ignore SSL certificate errors" now covers updates too.** The option
  previously applied to the model downloads and the assistant only, so behind
  the very corporate proxy it exists for, the update check kept failing. It now
  covers every connection the app makes. Updates are the risky part of that —
  they replace the program file — so the download still has to come over HTTPS
  from a GitHub host and match the release's size and SHA256, every unverified
  request is logged, and the install dialog says the download is not
  authenticated before it starts. The option remains off by default.
- Documentation and repository housekeeping in preparation for the public
  release (English-only main README with a separate German quick-start,
  contributor guide, hardened `.gitignore`).
