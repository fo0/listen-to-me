# Mute other apps while dictating (Discord, …)

If you dictate while a voice call is open, your speech would normally be picked
up by that call too. The **Integrations** page can mute other apps for exactly
the time you are recording and restore them when you stop.

It uses the target app's own **global mute keybind** — no API, account or
vendor approval is required, so it works with anything that exposes such a
keybind. The **Add app** menu comes with the common ones ready-made, each with
that app's documented mute keybind already filled in:

| Preset              | Keybind                      | Works from another window?                                                                                     |
| ------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Discord**         | `Ctrl+Shift+M` (Toggle Mute) | ✅ Yes, nothing to set up                                                                                      |
| **Zoom**            | `Alt+A`                      | Only after ticking _Settings → Keyboard Shortcuts → Enable Global Shortcut_                                    |
| **Slack**           | `Ctrl+Shift+Space` (huddle)  | Only after enabling _Preferences → Audio & video → allow keyboard shortcut to mute_                            |
| **Microsoft Teams** | `Ctrl+Shift+M`               | ❌ Teams reacts only while focused — no global keybind exists. On Windows 11 try `Win+Alt+K` (`<cmd>+<alt>+k`) |
| **OBS Studio**      | —                            | OBS ships no default; set one under _Settings → Hotkeys_ at your Mic/Aux source, then copy it here             |

Every preset ships **disabled** and repeats its caveat in the app, right under
the row — because a keybind an app only honours while it has focus would do
nothing at all here, silently. Discord is the one that just works.

To set an app up manually, the same combination has to exist in both places:

1. In the app, bind a key to mute. In Discord: **User Settings → Keybinds → Add
   a Keybind** and choose either **Push to Mute** or **Toggle Mute**, then press
   your combination (e.g. `F9`).
2. In Listen To Me, open **Settings → Integrations**, enable the app, set the
   **same** combination (use the _Change…_ picker) and pick the matching **mode**:
   - **Push-to-mute (hold)** — the key is held down for the whole recording.
     Stateless and self-correcting, so it can never leave you stuck muted.
     Recommended, and the natural match for Discord's _Push to Mute_.
   - **Toggle mute** — the key is tapped once when recording starts and once
     when it stops. Match this to a _Toggle Mute_ keybind.

Prefer a modifier chord or a function key so the combination stays inert in the
document you're dictating into. A mute keybind identical to your recording
hotkey is refused; one that merely shares keys with it (Discord's default
`Ctrl+Shift+M` next to the default `Ctrl+Alt+Space`) is fine in **toggle**
mode — the keybind is sent a moment after you let the hotkey go, because the
target app reads the same keyboard you are still holding. In **hold** mode the
start tap has to go out _while_ you hold the hotkey, so a toggle target whose
keybind shares a key with the hotkey or uses a modifier is skipped for that
take and you are told so (pick a plain function key as the hotkey, or switch the
target to hold mode). Add as many apps as you like; the master
switch turns the whole feature off without losing your entries. Two apps that
share a keybind (Discord and Teams both default to `Ctrl+Shift+M`) are sent it
**once** — one press reaches both, and sending it twice would toggle each of
them right back.

Both the `mute_while_recording` master switch and every preset **ship
disabled** — turn the switch on, check the keybind, then enable the entries you
want:

```jsonc
"integrations": {
  "mute_while_recording": true,
  "targets": [
    { "name": "Discord", "enabled": true, "mode": "toggle", "hotkey": "<ctrl>+<shift>+m" }
  ]
}
```

> An existing `config.json` keeps its own target list on upgrade — your entries
> are never overwritten. The presets are then one click away under **Add app**.
