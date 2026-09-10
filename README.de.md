# Listen To Me 🎙️ — Kurzanleitung (Deutsch)

Push-to-Talk-Spracheingabe für den Desktop — vollständig lokal, Open Source.
Hotkey drücken, sprechen, nochmal drücken: Der Text wird von einem lokalen
**Whisper-Modell** transkribiert und an der **Cursorposition** des gerade
fokussierten Feldes eingefügt.

> Dies ist eine deutschsprachige Kurzanleitung. Die vollständige Dokumentation
> (Funktionen, Einstellungen, Fehlerbehebung, Build) steht im englischen
> [README.md](README.md).

## Schnellstart

1. `ListenToMe-<datum>-<hhmm>-win64.exe` aus den [Releases](https://github.com/fo0/listen-to-me/releases)
   herunterladen und starten — die App liegt danach im System-Tray.
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
6. Schon aktiv: der Filter für stille Aufnahmen, unter **Engine →
   Silent takes (invented phrases)**. Wer den Hotkey drückt, nichts sagt und
   wieder drückt, bekommt sonst einen Satz eingefügt, den niemand gesprochen
   hat: „Vielen Dank.", „Thank you.", „Untertitelung des ZDF, 2020". Das kommt
   aus dem Whisper-Modell, nicht aus der App — Whisper ist auf untertitelten
   Videos trainiert, und eine Passage ohne Sprache trägt dort meist den
   Schlusssatz des Clips. Besteht ein Transkript **ausschließlich** aus einer
   Phrase der Liste, wird es verworfen und wie eine Aufnahme ohne Sprache
   gemeldet; „Vielen Dank für die Datei" bleibt dagegen unverändert. 18 Phrasen
   (deutsch und englisch) sind voreingestellt, die Liste ist frei editierbar und
   der Filter ganz abschaltbar.
7. Optional: unter **Audio → System Audio** einen zweiten Hotkey setzen — der
   nimmt auf, was der Rechner **abspielt** (Telefonat, Meeting, Video), mit der
   gleichen Bedienung wie das Diktat und mit eigenem Gerät, eigener Maximallänge
   (900 s) und eigenem Assistant-Profil. Dafür braucht die App ein
   **Loopback**-Aufnahmegerät: Unter Windows heißt es meist „Stereomix" und ist
   zwar vorhanden, aber **standardmäßig ausgeblendet und deaktiviert** — im
   Windows-Sound-Dialog im Tab _Aufnahme_ → Rechtsklick →
   _Deaktivierte Geräte anzeigen_ einblenden und danach aktivieren; alternativ
   ein virtuelles Audiokabel wie VB-CABLE installieren. Unter Linux genügt die
   Quelle „Monitor of …", unter macOS ein virtuelles Ausgabegerät wie BlackHole.
   Fehlt so ein Gerät, verweigert die App die Aufnahme und zeigt genau diesen
   Hinweis — sie greift absichtlich **nicht** auf das Standard-Mikrofon zurück,
   das den Raum statt den Ton des Rechners aufnehmen würde.

## Lizenz

[MIT](LICENSE)
