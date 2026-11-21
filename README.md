# Nib

*Pen plotter control – Every line, by the pen.*

Eigene Steuer-Software für den UUNATeK-3.0-Stiftplotter (GRBL/FluidNC über USB/CH340).
Die Oberfläche ist englisch, hell oder dunkel (folgt Windows oder per Knopf rechts oben).

**Alle Bedienelemente und Einstellungen erklärt: [BEDIENUNG.md](BEDIENUNG.md)**

## Starten
Doppelklick auf **`Nib.exe`**. Nib öffnet sich als eigenes Programmfenster, ohne Browser.
**Beenden:** Fenster schließen. Läuft gerade ein Plot (auch pausiert oder beim Stiftwechsel), fragt
Nib vorher nach. Bei „Ja“ wird der Plot abgebrochen und die Stelle zum Fortsetzen gemerkt.
Einstellungen (`settings.json`) und Fortsetzen-Stand (`job_state.json`) liegen neben der exe.

**exe neu bauen** (nach Änderungen am Code): Doppelklick auf **`build_exe.bat`**. Das dauert etwa
eine halbe Minute und legt eine neue `Nib.exe` in diesen Ordner. Benötigt Python und Windows 11
bzw. die Edge-WebView2-Runtime (in Windows 11 eingebaut).

**Alternativ im Browser:** `Nib starten.bat` öffnet die Oberfläche auf http://127.0.0.1:8765.
Beim Schließen des Browserfensters beendet sich Nib selbst, außer während eines Plots.
Zum Entwickeln lässt sich das mit `server.py --keep-running` abschalten.

**Wichtig:** Vorher die UUNA-Software schließen. Es kann immer nur ein Programm COM3 benutzen.

## Erster Test mit dem echten Plotter
1. Oben **COM3** wählen, dann **Connect**. In der Konsole sollte „Controller started: Grbl …“ stehen.
2. **Pen up** und **Pen down** testen. Bei Bedarf „Pen up (Z)“ / „Pen down (Z)“ unter *Speed & pen* anpassen.
   Die Standardwerte stammen aus deiner UUNA-Konfiguration (0,5 mm / 5 mm).
3. Mit den Pfeilen verfahren und prüfen: → fährt nach rechts, ↓ fährt zu dir (Blatt nach unten).
   Falls nicht, unter *Machine* **Invert X**, **Invert Y** oder **Swap X/Y** anhaken.
4. Stift an die **obere linke Blattecke** fahren, dann **Set origin** drücken.
5. SVG laden (**Open SVG**), dann **Trace frame**. Der Stift fährt angehoben die Kontur der Vorschau ab.
6. **Plot**.

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
| `app.py` | Programmfenster (Nib.exe) |
| `web/` | Oberfläche (Schriften: IBM Plex, SIL Open Font License, siehe `web/fonts/`) |
| `settings.json`, `job_state.json` | Gespeicherte Einstellungen und Fortsetzungspunkt (werden automatisch angelegt) |
