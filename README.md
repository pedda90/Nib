# Nib

Eigene Steuer-Software für den UUNATeK-3.0-Stiftplotter (GRBL über USB/CH340).

**Alle Bedienelemente und Einstellungen erklärt: [BEDIENUNG.md](BEDIENUNG.md)**

## Starten
Doppelklick auf **`Nib starten.bat`**. Der Browser öffnet sich auf http://127.0.0.1:8765.
**Beenden:** Einfach das Browserfenster bzw. den Tab schließen. Nib beendet sich nach wenigen
Sekunden selbst, das schwarze Fenster schließt sich mit. Läuft gerade ein Plot (auch pausiert oder beim
Stiftwechsel), wird er zu Ende geführt und Nib beendet sich erst danach. Zurück zur Oberfläche
geht es dann über http://127.0.0.1:8765. Zum Entwickeln lässt sich das mit `server.py --keep-running` abschalten.

**Wichtig:** Vorher die UUNA-Software schließen. Es kann immer nur ein Programm COM3 benutzen.

## Erster Test mit dem echten Plotter
1. Oben **COM3** wählen, dann **Verbinden**. Im Konsolenfeld sollte „Controller gestartet: Grbl …“ stehen.
2. **Stift hoch** und **Stift runter** testen. Bei Bedarf „Stift oben/unten (Z)“ anpassen.
   Die Standardwerte stammen aus deiner UUNA-Konfiguration (0,5 mm / 5 mm).
3. Mit den Pfeilen verfahren und prüfen: → fährt nach rechts, ↓ fährt zu dir (Blatt nach unten).
   Falls nicht, unter „Achsen“ *X umkehren*, *Y umkehren* oder *X/Y tauschen* anhaken.
4. Stift an die **obere linke Blattecke** fahren, dann **Nullpunkt hier** drücken.
5. SVG laden, dann **Rahmen abfahren**. Der Stift fährt angehoben die Kontur der Vorschau ab.
6. **Start**.

## Funktionen
- SVG aus Illustrator, DrawingBotV3 usw. mit korrekter Größe in mm.
  Die Position auf der Zeichenfläche bleibt erhalten.
- Ebenen nach Farbe oder nach Illustrator-Ebene, ein- und ausschaltbar, Reihenfolge änderbar,
  automatische Pause zum Stiftwechsel.
- Pfadoptimierung: Reihenfolge sortieren, Linien verbinden, Doppelte entfernen, vereinfachen (Standardwerte werden angezeigt).
- Illustrator-Ebenen innerhalb einer Stiftfarbe einzeln ein- und ausblenden.
- Vorschau mit Leerfahrten, Zeitschätzung pro Ebene, Live-Fortschritt und Stiftposition.
- Pause/Weiter (auch mit der Leertaste), Stopp ohne Verlust des Nullpunkts,
  **Fortsetzen nach Abbruch** (auch nach einem Neustart des Programms) oder ab einem beliebigen Pfad.
- **Rückwärts plotten** (vom Ende zum Anfang) und Startpunkt per Klick in die Vorschau wählen.
- Arbeitsbereichs-Grenzen ab der Einschaltecke. Geschwindigkeiten auf das Firmware-Maximum begrenzt.
- Manuelle Steuerung, einstellbare Geschwindigkeiten, Konsole für G-Code und `$`-Befehle.
- „SIMULATOR“ als Schnittstelle zum Ausprobieren ohne Plotter.

## Dateien
| Datei | Inhalt |
|---|---|
| `server.py` | Webserver und Ablaufsteuerung |
| `grbl.py` | Verbindung, Streaming, Plot-Auftrag |
| `svgload.py` | SVG-Import |
| `optimize.py` | Pfadoptimierung |
| `gcode.py` | Platzierung und G-Code |
| `mockgrbl.py` | Simulierter Plotter |
| `web/` | Oberfläche |
| `settings.json`, `job_state.json` | Gespeicherte Einstellungen und Fortsetzungspunkt (werden automatisch angelegt) |
