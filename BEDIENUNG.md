# Nib – Bedienung

Erklärung aller Bedienelemente und Einstellungen, plus Tipps für den sicheren Betrieb.
Installation und erster Start stehen in der [README](README.md).

---

## Das schwarze Fenster

Darin läuft Nib selbst: Der Python-Server steuert den Plotter, die Browser-Seite ist nur
die Oberfläche. Das Fenster offen lassen (minimieren geht). **Schließen beendet Nib.**

Nach Änderungen an Nib: Fenster schließen, `Nib starten.bat` neu starten und die Browser-Seite neu laden.

---

## Steuerung (links oben)

| Element | Funktion |
|---|---|
| **0,1 / 1 / 10 / 50 / eigene Zahl** | Schrittweite in mm. Jeder Pfeil-Klick fährt so weit. Die Pfeiltasten der Tastatur gehen auch. |
| **Pfeile** | Stift in X/Y verfahren. An der Grenze des Arbeitsbereichs wird automatisch gestoppt. |
| **Stift hoch / Stift runter** | Fährt Z auf die Höhe „Stift oben“ bzw. „Stift unten“, z. B. um zu prüfen, ob der Stift richtig aufsetzt. |
| **Nullpunkt hier** | Die aktuelle Position wird die Ecke deines Blatts. Ab hier zählt die Platzierung (X/Y) in der Vorschau. |
| **⌂** (Mitte der Pfeile) | Fährt zurück zu dem Punkt, der mit „Nullpunkt hier“ gesetzt wurde. |
| **Zum Maschinen-Nullpunkt** | Fährt zur Einschaltposition (Ecke). Der gesetzte Nullpunkt bleibt dabei erhalten. |
| **Entsperren** | Nach einem Alarm (z. B. Grenze angefahren) ist der Plotter gesperrt. Das hebt die Sperre auf, ohne dass der Nullpunkt verloren geht. |
| **Z −0,5 / Z +0,5** | Stift in kleinen Schritten hoch bzw. runter, zum Einrichten der Stifthöhe (siehe unten). |

Während ein Plot läuft, ist die Steuerung gesperrt.

### Stifthöhe einrichten (neuer Stift / anderes Papier)

1. **Stift hoch** klicken.
2. Mit **Z +0,5** so lange runter, bis die Spitze das Papier gerade berührt.
3. Den angezeigten Z-Wert ablesen, **0,5–1 mm** für etwas Andruck dazurechnen und bei **Stift unten** eintragen.

---

## Geschwindigkeit & Stift

| Einstellung | Bedeutung | Hinweise |
|---|---|---|
| **Zeichnen** | Tempo mit abgesenktem Stift | Langsamer gibt sauberere, sattere Linien. Zu schnell kann bei Finelinern blasse oder unterbrochene Linien geben. |
| **Leerfahrt** | Tempo mit angehobenem Stift zwischen zwei Linien | Nicht ganz am Maximum betreiben, z. B. **8000 mm/min**, sonst kann der Plotter Schritte verlieren (siehe unten). |
| **Verfahren (Jog)** | Tempo beim manuellen Verfahren mit den Pfeilen | – |
| **Stift oben** | Z-Höhe, wenn der Stift angehoben ist | Nur so hoch wie nötig (z. B. 0,5–2 mm). Höher kostet bei tausenden Anhebungen unnötig Zeit. |
| **Stift unten** | Z-Höhe, auf der der Stift zeichnet | Papierberührung plus etwas Andruck (aktuell 5 mm). |
| **Z-Geschwindigkeit** | Wie schnell der Stift hoch- und runterfährt | Zu schnell kann den Stift aufs Papier „knallen“ lassen und Punkte oder Kleckse am Linienanfang geben. |
| **Pause nach Absetzen** | Wartezeit (s), nachdem der Stift unten ist, bevor er losfährt | Hilft, wenn Linienanfänge fehlen oder blass sind (z. B. 0,05–0,2 s). |
| **Pause nach Anheben** | Wartezeit (s), bevor nach dem Anheben weggefahren wird | Hilft bei kleinen Haken oder Schleifspuren am Linienende. |

**Z-Werte:** Sie zählen in mm ab der Einschaltposition. **0 = ganz oben**, größere Werte bedeuten tiefer.
Laut Firmware ist **0 bis 12 mm** erlaubt.

**Pausen:** Normal stehen beide auf 0. Jede Pause kommt pro Linie dazu: Bei 14 000 Linien
machen 0,1 s schon rund **23 Minuten** mehr aus.

**Maximalwerte:** Die Geschwindigkeiten werden beim Verbinden automatisch auf das Maximum der
Firmware begrenzt (X/Y 11 000 mm/min, Z 5000 mm/min).

**Während eines Plots:** Die Werte werden beim Start fest übernommen. Änderungen gelten erst beim nächsten Start.

---

## Arbeitsbereich (Grenzen)

Der Plotter hat keine Endschalter. Er weiß nur, wie weit er sich **seit dem Einschalten** bewegt hat.
Deshalb gilt die Position beim Einschalten als **Maschinen-Nullpunkt**, und alle Grenzen zählen ab dort.

- **Max. X / Max. Y:** Größe des nutzbaren Bereichs ab der Einschaltecke (rot gestrichelt in der Vorschau).
  Verfahren stoppt an der Grenze, Plots und Rahmen außerhalb werden gar nicht erst gestartet.
- Die Firmware erlaubt **420 × 297 mm**. Ein selbst eingetragener kleinerer Wert bleibt erhalten und wird beim Verbinden nie automatisch vergrößert.
- **Ausmessen:** „Zum Ausmessen öffnen“, dann mit 1-mm-Schritten bis kurz vor den Anschlag joggen, dann **Pos. → Max. X** bzw. **Pos. → Max. Y**. Dabei wird 1 mm Reserve abgezogen.
- **Grenzen einhalten** sollte immer an sein.

---

## Plotten

1. SVG laden. Die Ebenen (Farben) erscheinen rechts und lassen sich ein- und ausschalten sowie umsortieren.
2. Platzierung (X/Y, Maßstab, Drehung) einstellen.
3. **Rahmen abfahren:** Der Stift fährt angehoben die Kontur des Designs ab. Damit prüfst du die Lage auf dem Blatt.
4. **Start.** Zwischen den Ebenen hält der Plotter für den Stiftwechsel an, wenn „Zwischen Ebenen pausieren“ aktiv ist.

| Funktion | Beschreibung |
|---|---|
| **Pause / Weiter** | Hält an und fährt an derselben Stelle weiter. Geht auch mit der Leertaste. |
| **Stopp** | Bricht ab. Der Nullpunkt bleibt erhalten, die Stelle wird für „Fortsetzen“ gemerkt. |
| **Rückwärts plotten** | Ebenen und Linien vom Ende zum Anfang, jede Linie in Gegenrichtung. Praktisch, wenn z. B. die Tinte ausgegangen ist und man den Rest von hinten fertig zeichnen will. |
| **Startpunkt wählen** | **In Vorschau wählen**, dann auf eine Linie klicken. Ein roter Marker zeigt die Stelle. Bereits erledigte Linien werden blass, die noch zu plottenden kräftig dargestellt. Ebene und Pfad lassen sich auch als Zahl eingeben, **Zurücksetzen** startet wieder ganz vorne. |
| **Fortsetzen nach Abbruch** | **Stelle anzeigen & übernehmen** setzt die unterbrochene Stelle (samt Richtung) als Startpunkt. Gestartet wird danach mit **Start**. Funktioniert auch nach einem Neustart von Nib. |

---

## Sicherer Betrieb

- **Immer in der Ecke einschalten** (Schlitten an beiden Anschlägen). Sonst stimmen die Grenzen nicht.
- **Schlitten nicht von Hand bewegen**, während der Plotter eingeschaltet ist oder zwischen Aus- und Einschalten, ohne ihn danach wieder in die Ecke zu schieben.
- **Nach einem Stopp mitten in der Fahrt oder nach einem Anschlag:** ausschalten, Schlitten in die Ecke, wieder einschalten.
- **Schrittverlust:** Bei sehr hohem Tempo (v. a. Leerfahrt am Maximum) kann der schwere Y-Schlitten Schritte verlieren. Dann stimmt die Position nicht mehr, und er kann trotz Grenzen anschlagen. Leerfahrt etwas reduzieren.
- **Vorher die UUNA-Software schließen.** COM3 kann immer nur ein Programm benutzen.
- **SIMULATOR** als Schnittstelle wählen, um ohne Plotter etwas auszuprobieren.
