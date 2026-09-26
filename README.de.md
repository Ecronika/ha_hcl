# HCL Lighting für Home Assistant – Kurzanleitung

Die Integration führt Helligkeit und Farbtemperatur deiner Lichter über den Tag einer Kurve nach, angelehnt an die Empfehlungen der DIN SPEC 67600 / DIN/TS 67600. Ausführliche Beschreibung: [README (englisch)](README.md).

## Installation
1. HACS → Integrationen → Menü → Benutzerdefinierte Repositories → `https://github.com/Ecronika/ha_hcl` als **Integration** hinzufügen und installieren, Home Assistant neu starten.
2. Einstellungen → Geräte & Dienste → Integration hinzufügen → **HCL Lighting**.
3. Name vergeben (z. B. „Wohnzimmer“), Lichter wählen (Entitäten, Geräte, Bereiche, Etagen oder Labels) und Aufwach-, Mittags- und Schlafenszeit festlegen. Zwischen Aufwach- und Schlafenszeit müssen mehr als 6 Stunden liegen.
4. Dashboard-Karte hinzufügen: Dashboard bearbeiten → **Karte hinzufügen** → **HCL Curve Card** (visueller Editor mit Instanz und Ansicht). Nach dem Anlegen einer Instanz zeigt eine einmalige Benachrichtigung das YAML, z. B.
   ```yaml
   type: custom:hcl-curve-card
   entity: sensor.wohnzimmer_curve_data
   ```

Voraussetzung: Home Assistant **2024.7** oder neuer.

Die Karten-Ressource wird im UI-Modus automatisch als `/hcl_lighting_static/hcl-curve-card.js?v=<Version>` eingetragen. Im YAML-Modus selbst ergänzen (`url: /hcl_lighting_static/hcl-curve-card.js`, `type: module`). Ohne HACS: `custom_components/hcl_lighting` in den Ordner `custom_components` der Konfiguration kopieren und neu starten. Nach dem Entfernen der Integration bleibt die Ressource stehen (Einstellungen → Dashboards → ⋮ → Ressourcen).

**Nach einem Update** die Dashboard-Seite im Browser ohne Cache neu laden (Strg+F5, am Mac Cmd+Shift+R; in der Companion-App den Frontend-Cache in den App-Einstellungen zurücksetzen), damit die neue Karte geladen wird.

## Entitäten je Instanz
| Entität | Zweck |
|---|---|
| **HCL aktiv** (Schalter) | HCL ein/aus. Attribut `manual_control`: manuell gesteuerte Lichter |
| **Helligkeit anpassen** (Schalter) | Aus: HCL lässt die Helligkeit unverändert |
| **Farbtemperatur anpassen** (Schalter) | Aus: HCL lässt die Farbtemperatur unverändert |
| **Szenario** (Auswahl) | Auto, Schlafen, Nachtlicht, Fokus, Entspannen, Putzen, Gast. Attribut `until`: Ende eines zeitlich begrenzten Szenarios |
| **Sollhelligkeit** / **Sollfarbtemperatur** (Sensoren) | Werte, die HCL jetzt sendet (Szenario, Min/Max, Skalierung berücksichtigt; Schlafen 0 %, Gast `unknown`), z. B. um ein Licht mit HCL-Werten einzuschalten |
| **Curve Data** (Sensor) | Daten für die Karte. Attribute u. a. `preview_active` (Lichter folgen einer ungespeicherten Vorschau), `wake_time`, `sleep_time` |

Bestehende Installationen behalten ihre Entity-IDs; nur die Anzeigenamen ändern sich.

## Szenarien
- **Auto**: Lichter folgen der Kurve.
- **Fokus / Entspannen / Putzen**: feste Werte (in den Optionen einstellbar, optional mit Dauer in Minuten, danach zurück zu Auto).
- **Gast**: HCL sendet keine Befehle.
- **Schlafen**: Eingeschaltete Lichter werden ausgeblendet. Wer nachts ein Licht einschaltet, steuert es manuell; es bleibt an, bis es ausgeschaltet wird.
- **Nachtlicht**: gedimmtes, warmes Licht (Standard 3 % / 2200 K). Eingeschaltete und nachts eingeschaltete Lichter bekommen diese Werte; HCL schaltet nichts ein oder aus.

Schlafen und Nachtlicht können optional zur Aufwachzeit enden. Ein Szenario-Wechsel wird mit dem „Übergang bei Szenario-Wechsel“ gesendet.

## Manuelle Steuerung
HCL pausiert ein einzelnes Licht, wenn
- Home Assistant Helligkeit oder Farbe mit einem Befehl ändert, der nicht von HCL stammt (App, Dashboard, Szene, Automation, Sprachassistent), oder
- das Licht Werte meldet, die von HCL abweichen (z. B. Wandtaster, Hersteller-App).

Das Licht kehrt zu HCL zurück, wenn es aus- und wieder eingeschaltet wird oder nach der eingestellten Zeit (Standard 4 Stunden) mit einem sanften Übergang über 3 Minuten, den die normalen Aktualisierungen nicht unterbrechen. HCL schaltet nie ein Licht ein. Einstellbar sind außerdem: ob Ausschalten die manuelle Steuerung beendet, ob sie Neustarts überdauert und ob Einschaltbefehle mit eigenen Werten (z. B. Szenen) respektiert werden.

## Aktionen (Services)
- `hcl_lighting.apply`: aktuelle Werte sofort an eingeschaltete Lichter senden (optional Übergang, den die Aktualisierungen nicht abbrechen; manuell gesteuerte nur mit `release_manual_control: true`; nicht im Gastmodus).
- `hcl_lighting.set_manual_control`: Lichter pausieren (`manual_control: true`) oder an HCL zurückgeben (`false`).
- `hcl_lighting.set_scenario`: Szenario setzen, optional mit Dauer in Minuten.
- `hcl_lighting.get_curve`: Kurve als Antwortdaten, z. B. um sie mit `update_curve` in eine andere Instanz zu kopieren.

Beginnt oder endet die manuelle Steuerung eines Lichts, erscheint ein Logbuch-Eintrag und das Event `hcl_lighting_manual_control`. Steuern zwei Instanzen dasselbe Licht für dasselbe Attribut, meldet eine Reparatur das. Diagnosedaten lassen sich auf der Integrationsseite herunterladen. Beispiele: [README (englisch), Recipes](README.md#recipes).

## Optionen (Integration → Konfigurieren)
1. **Kurve und Lichter**: Lichter, Ankerzeiten, minimale/maximale Helligkeit, „Auf Min/Max skalieren statt abschneiden“ (Standard aus), Kompatibilitätsmodus. Eine in der Karte gespeicherte Kurve hat Vorrang; wer eine Ankerzeit ändert, verwirft sie.
2. **Aktualisierung und manuelle Steuerung**: Intervall (Standard 27 s), Übergangszeit (20 s), Übergang beim Einschalten (0 s), Rückkehr zu HCL (240 min, 0 = nie), Ausschalten beendet manuelle Steuerung, über Neustarts behalten, Werte von Einschaltbefehlen behalten, Übergang bei Szenario-Wechsel (Standard wie Übergangszeit).
3. **Szenarien**: Werte von Fokus, Entspannen, Putzen und Nachtlicht, Dauer von Fokus/Entspannen/Putzen, Fokus/Entspannen/Putzen auf Min/Max begrenzen (aus), Schlafen und Nachtlicht enden zur Aufwachzeit (aus).

## Dashboard-Karte
Punkte ziehen, mit ➕ oder Doppelklick hinzufügen, mit ➖ oder Entf löschen, Uhrzeit/Helligkeit/Farbtemperatur direkt eingeben, mit ↶ oder Strg+Z rückgängig machen. **Vorschau** sendet die ungespeicherte Kurve bis zum nächsten Neuladen an die Lichter (die Karte zeigt dann „Vorschau aktiv – nicht gespeichert“), **Speichern** übernimmt sie dauerhaft, **Verwerfen** lädt die gespeicherte Kurve. Schlägt Speichern fehl, zeigt die Karte den Fehler und die Änderungen bleiben als ungespeichert markiert. Die gestrichelte senkrechte Linie zeigt die aktuelle Uhrzeit (Zeitzone von Home Assistant), darunter stehen die Werte, die HCL jetzt sendet. Die Nacht-Hinweise gelten von der Schlafens- bis zur Aufwachzeit.

Die Szenario-Chips wechseln das Szenario; die Kurve lässt sich in jedem Szenario bearbeiten, wirkt aber nur in Auto. Wird die Kurve woanders geändert, während du bearbeitest, bleibt dein Entwurf erhalten und die Karte bietet „Diese Kurve laden“ an. Presets: Standard, Standard mit Nachtruhe, Standard ohne Mittagstief, Fokus, Entspannung, Frühaufsteher, Nachteule. Tastatur am gewählten Punkt: ↑/↓ Wert (Bild↑/Bild↓ in größeren Schritten), ←/→ Uhrzeit, Pos1/Ende Minimum/Maximum, Umschalt = größere Schritte, Entf löschen. Uhrzeit und Zahlen folgen dem Format im Home-Assistant-Profil. Mit `view: compact` zeigt die Karte nur Status und Szenario-Chips, der Editor klappt bei Bedarf auf.

RGBW- und RGBWW-Leuchten werden wie Farbleuchten über XY gesteuert.
