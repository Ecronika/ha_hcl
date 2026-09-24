# HCL Lighting für Home Assistant – Kurzanleitung

Die Integration führt Helligkeit und Farbtemperatur deiner Lichter über den Tag einer Kurve nach, angelehnt an die Empfehlungen der DIN SPEC 67600 / DIN/TS 67600. Ausführliche Beschreibung: [README (englisch)](README.md).

## Installation
1. HACS → Integrationen → Menü → Benutzerdefinierte Repositories → `https://github.com/Ecronika/ha_hcl` als **Integration** hinzufügen und installieren, Home Assistant neu starten.
2. Einstellungen → Geräte & Dienste → Integration hinzufügen → **HCL Lighting**.
3. Name vergeben (z. B. „Wohnzimmer“), Lichter wählen (Entitäten, Geräte, Bereiche, Etagen oder Labels) und Aufwach-, Mittags- und Schlafenszeit festlegen. Zwischen Aufwach- und Schlafenszeit müssen mehr als 6 Stunden liegen.
4. Dashboard-Karte hinzufügen: Die Reparaturmeldung unter Einstellungen → Reparaturen enthält das YAML, z. B.
   ```yaml
   type: custom:hcl-curve-card
   entity: sensor.wohnzimmer_curve_data
   ```

Voraussetzung: Home Assistant **2024.7** oder neuer.

## Entitäten je Instanz
| Entität | Zweck |
|---|---|
| **HCL aktiv** (Schalter) | HCL ein/aus. Attribut `manual_control`: manuell gesteuerte Lichter |
| **Helligkeit anpassen** (Schalter) | Aus: HCL lässt die Helligkeit unverändert |
| **Farbtemperatur anpassen** (Schalter) | Aus: HCL lässt die Farbtemperatur unverändert |
| **Szenario** (Auswahl) | Auto, Fokus, Entspannen, Putzen, Gast, Schlafen. Attribut `until`: Ende eines zeitlich begrenzten Szenarios |
| **Curve Data** (Sensor) | Daten für die Karte |

Bestehende Installationen behalten ihre Entity-IDs; nur die Anzeigenamen ändern sich.

## Szenarien
- **Auto**: Lichter folgen der Kurve.
- **Fokus / Entspannen / Putzen**: feste Werte (in den Optionen einstellbar, optional mit Dauer in Minuten, danach zurück zu Auto).
- **Gast**: HCL sendet keine Befehle.
- **Schlafen**: Eingeschaltete Lichter werden ausgeblendet. Wer nachts ein Licht einschaltet, steuert es manuell; es bleibt an, bis es ausgeschaltet wird.

## Manuelle Steuerung
HCL pausiert ein einzelnes Licht, wenn
- Home Assistant Helligkeit oder Farbe mit einem Befehl ändert, der nicht von HCL stammt (App, Dashboard, Szene, Automation, Sprachassistent), oder
- das Licht Werte meldet, die von HCL abweichen (z. B. Wandtaster, Hersteller-App).

Das Licht kehrt zu HCL zurück, wenn es aus- und wieder eingeschaltet wird oder nach der eingestellten Zeit (Standard 4 Stunden). HCL schaltet nie ein Licht ein. Einstellbar sind außerdem: ob Ausschalten die manuelle Steuerung beendet, ob sie Neustarts überdauert und ob Einschaltbefehle mit eigenen Werten (z. B. Szenen) respektiert werden.

## Optionen (Integration → Konfigurieren)
1. **Kurve und Lichter**: Lichter, Ankerzeiten, minimale/maximale Helligkeit, Kompatibilitätsmodus. Eine in der Karte gespeicherte Kurve hat Vorrang; wer eine Ankerzeit ändert, verwirft sie.
2. **Aktualisierung und manuelle Steuerung**: Intervall (Standard 27 s), Übergangszeit (20 s), Übergang beim Einschalten (0 s), Rückkehr zu HCL (240 min, 0 = nie), Ausschalten beendet manuelle Steuerung, über Neustarts behalten, Werte von Einschaltbefehlen behalten.
3. **Szenarien**: Werte von Fokus, Entspannen und Putzen sowie deren Dauer.

## Dashboard-Karte
Punkte ziehen, mit ➕ oder Doppelklick hinzufügen, mit ➖ oder Entf löschen, Uhrzeit/Helligkeit/Farbtemperatur direkt eingeben, mit ↶ oder Strg+Z rückgängig machen. **Vorschau** sendet die ungespeicherte Kurve bis zum nächsten Neuladen an die Lichter, **Speichern** übernimmt sie dauerhaft, **Verwerfen** lädt die gespeicherte Kurve. Die gestrichelte senkrechte Linie zeigt die aktuelle Uhrzeit, darunter stehen die aktuellen Werte.
