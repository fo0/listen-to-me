# Listen To Me 🎙️ — Kurzanleitung (Deutsch)

Push-to-Talk-Spracheingabe für den Desktop — vollständig lokal, Open Source.
Hotkey drücken, sprechen, nochmal drücken: Der Text wird von einem lokalen
**Whisper-Modell** transkribiert und an der **Cursorposition** des gerade
fokussierten Feldes eingefügt.

> Dies ist eine deutschsprachige Kurzanleitung. Die vollständige Dokumentation
> (Funktionen, Einstellungen, Fehlerbehebung, Build) steht auf Englisch unter
> [docs/guide/](docs/guide/features.md), der Einstieg im [README.md](README.md).

## Schnellstart

1. `ListenToMe-<datum>-<hhmm>-win64.exe` aus den [Releases](https://github.com/fo0/listen-to-me/releases/latest)
   herunterladen und starten — die App liegt danach im System-Tray. Beim ersten
   Start fragt ein kurzer Einrichtungsassistent Hotkey, Sprache, Engine und
   Mikrofon ab.
2. Cursor in ein beliebiges Textfeld setzen, `Strg+Alt+Leertaste` drücken,
   sprechen, nochmal drücken → der Text wird lokal transkribiert und an der
   Cursorposition eingefügt.
3. Rechtsklick auf das Tray-Icon → **Settings…**: dort Sprache (z. B. _German_),
   Whisper-Modell, Hotkey, Mikrofon und **Autostart mit Windows** einstellen.
4. Optional: unter **Assistant** die LLM-Nachbearbeitung aktivieren (z. B. mit
   lokalem Ollama) und den System-Prompt frei anpassen — _Reset to default_
   stellt den Standard wieder her.
5. Optional: unter **Integrations** andere Programme wie **Discord** während der
   Aufnahme automatisch stummschalten. Dafür in Discord unter _Einstellungen →
   Tastenkombinationen_ eine Taste für **„Stummschaltung gedrückt halten"**
   (Push-to-Mute) oder **„Stummschaltung umschalten"** vergeben und in Listen To
   Me dieselbe Kombination samt passendem Modus eintragen — so wird dein Diktat
   nicht in den Voice-Call übertragen und danach automatisch wieder aktiviert.
6. Schon aktiv: Ein Filter verwirft bei **stillen Aufnahmen** Sätze, die
   Whisper erfindet („Vielen Dank.", „Untertitelung des ZDF, 2020"). Echt
   Gesprochenes bleibt erhalten; die Liste ist unter **Engine → Silent takes**
   editierbar. [Details →](docs/guide/settings.md#silent-takes-and-invented-phrases)
7. Optional: unter **Audio → System audio** einen zweiten Hotkey setzen, der
   aufnimmt, was der Rechner **abspielt** (Telefonat, Meeting, Video). Die
   heruntergeladene `.exe` braucht dafür keine Einrichtung, aus dem Quellcode
   gestartet ist „Stereomix" oder ein virtuelles Audiokabel nötig.
   [Details →](docs/guide/system-audio.md)
8. Optional: unter **Overlay → Show the transcript at** den Text am
   **Mauszeiger** statt am floating icon anzeigen, praktisch beim Diktieren auf
   einem zweiten Monitor. Funktioniert auch mit ausgeschaltetem floating icon.

## Lizenz

[MIT](LICENSE)
