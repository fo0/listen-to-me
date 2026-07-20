# Listen To Me 🎙️ — Kurzanleitung (Deutsch)

Push-to-Talk-Spracheingabe für den Desktop — vollständig lokal, Open Source.
Hotkey drücken, sprechen, nochmal drücken: Der Text wird von einem lokalen
**Whisper-Modell** transkribiert und an der **Cursorposition** des gerade
fokussierten Feldes eingefügt.

> Dies ist eine deutschsprachige Kurzanleitung. Die vollständige Dokumentation
> (Funktionen, Einstellungen, Fehlerbehebung, Build) steht im englischen
> [README.md](README.md).

## Schnellstart

1. `ListenToMe-<datum>-win64.exe` aus den [Releases](https://github.com/fo0/listen-to-me/releases)
   herunterladen und starten — die App liegt danach im System-Tray.
2. Cursor in ein beliebiges Textfeld setzen, `Strg+Alt+Leertaste` drücken,
   sprechen, nochmal drücken → der Text wird lokal transkribiert und an der
   Cursorposition eingefügt.
3. Rechtsklick auf das Tray-Icon → **Settings…**: dort Sprache (z. B. *German*),
   Whisper-Modell, Hotkey, Mikrofon und **Autostart mit Windows** einstellen.
4. Optional: unter **Assistant** die LLM-Nachbearbeitung aktivieren (z. B. mit
   lokalem Ollama) und den System-Prompt frei anpassen — *Reset to default*
   stellt den Standard wieder her.
5. Optional: unter **Integrations** andere Programme wie **Discord** während der
   Aufnahme automatisch stummschalten. Dafür in Discord unter *Einstellungen →
   Tastenkombinationen* eine Taste für **„Stummschaltung gedrückt halten"**
   (Push-to-Mute) oder **„Stummschaltung umschalten"** vergeben und in Listen To
   Me dieselbe Kombination samt passendem Modus eintragen — so wird dein Diktat
   nicht in den Voice-Call übertragen und danach automatisch wieder aktiviert.

## Lizenz

[MIT](LICENSE)
