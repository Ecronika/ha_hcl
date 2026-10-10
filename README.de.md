# HCL Lighting für Home Assistant

Die Integration führt Helligkeit und Farbtemperatur deiner Lichter über den Tag einer Kurve nach, angelehnt an die Empfehlungen der DIN SPEC 67600 / DIN/TS 67600. English version: [README.md](README.md).

## Funktionen
- **Dashboard-Karte** zum Bearbeiten der Tageskurve (Helligkeit und Farbtemperatur), mit Vorschau, Standardkurve, Plausibilitäts-Hinweisen und Szenario-Chips.
- **Kurve** mit monotoner PCHIP-Interpolation (keine Überschwinger) aus Aufwach- und Schlafenszeit oder aus eigenen Punkten.
- **Szenarien** Auto, Fokus, Entspannen, Putzen, Nachtlicht, Schlafen und Gast (abgekündigt).
- **Manuelle Steuerung**: Wer ein Licht selbst ändert, pausiert HCL für dieses Licht; HCL übernimmt es später wieder.
- **Helligkeit und Farbtemperatur getrennt**: zwei Schalter je Instanz.
- **Sofort beim Einschalten**: Lichter bekommen die HCL-Werte direkt nach dem Einschalten, ohne Übergang (nicht im Gastmodus; wer während „Schlafen“ einschaltet, steuert manuell).
- **Sparsame Befehle**: Aktualisiert wird nur bei spürbarer Änderung (Helligkeit > 1 %, Farbtemperatur > 50 K).
- **Tageslichtkompensation** (optional): Ein Luxsensor im Raum senkt in Auto die Helligkeit, wenn genug Tageslicht da ist.
- **Sollwert-Sensoren**, **Aktionen**, **Logbuch und Event** bei manueller Steuerung, **Diagnose** und **Reparatur-Hinweis** bei Doppelsteuerung.
- **Farbfähigkeiten** werden erkannt: Lichter mit Farbtemperatur bekommen sie immer direkt, begrenzt auf ihren Bereich (auch RGBCCT-Leuchten: kein Farbsprung an der Bereichsgrenze, kein RGB-Weiß; eine Leuchte im Farbmodus, z. B. aus der XY-Simulation bis 0.7, wird in den Farbtemperatur-Modus zurückgeholt); Farbleuchten ohne Farbtemperatur (XY, HS, RGB, RGBW, RGBWW) bekommen sie über XY (Kurvenbereich 2000–7000 K).

## Installation
1. HACS → Integrationen → Menü → Benutzerdefinierte Repositories → `https://github.com/Ecronika/ha_hcl` als **Integration** hinzufügen und installieren, Home Assistant neu starten.
2. Einstellungen → Geräte & Dienste → Integration hinzufügen → **HCL Lighting**.
3. Name vergeben (z. B. „Wohnzimmer“), Lichter wählen (mindestens ein Ziel: Entitäten, Geräte, Bereiche, Etagen oder Labels; Lichtgruppen werden in ihre Mitglieder aufgelöst) und Aufwach- und Schlafenszeit festlegen. Bereiche, Geräte, Etagen und Labels löst Home Assistant selbst auf, mit den Regeln der installierten Version (wie bei Licht-Aktionen). In der Regel zählen ausgeblendete Lichter und Konfigurations-/Diagnose-Lichter, die über ein Gerät oder einen Bereich erreicht werden (z. B. Status-LEDs von Tastern), nicht mit; ein Licht mit eigenem Bereich gehört zu diesem und nicht zum Bereich seines Geräts; bei Versionen mit Unter-Geräten schließt ein Gerät diese ein. Details richten sich nach der installierten Version, z. B. ob ein Konfigurations-Licht mit dem gewählten Label selbst mitzählt. Direkt gewählte Lichter zählen immer. Lichter, die später in einen gewählten Bereich, ein Gerät, eine Etage oder ein Label kommen, werden automatisch übernommen.
4. Dashboard-Karte hinzufügen: Dashboard bearbeiten → **Karte hinzufügen** → **HCL Curve Card** (visueller Editor mit Instanz und Ansicht). Nach dem Anlegen einer Instanz zeigt eine einmalige Benachrichtigung das YAML mit der genauen Entity-ID, z. B.
   ```yaml
   type: custom:hcl-curve-card
   entity: sensor.wohnzimmer_curve_data
   ```
   Optional: `view: compact`, `title: Küche` (Standard: Name der Instanz).

Voraussetzung: Home Assistant **2024.7** oder neuer.

Die Karten-Ressource wird im UI-Modus der Dashboards automatisch als `/hcl_lighting_static/hcl-curve-card.js?v=<Version>` eingetragen; ein Update ersetzt den Eintrag. Im YAML-Modus selbst ergänzen:
```yaml
lovelace:
  resources:
    - url: /hcl_lighting_static/hcl-curve-card.js
      type: module
```
Ohne HACS: `custom_components/hcl_lighting` in den Ordner `custom_components` der Konfiguration kopieren und neu starten. Nach dem Entfernen der Integration bleibt die Ressource stehen (Einstellungen → Dashboards → ⋮ → Ressourcen); dort löschen, wenn die Karte nicht mehr gebraucht wird.

**Nach einem Update** die Dashboard-Seite im Browser ohne Cache neu laden (Strg+F5, am Mac Cmd+Shift+R; in der Companion-App den Frontend-Cache in den App-Einstellungen zurücksetzen), damit die neue Karte geladen wird.

## Standardkurve
Aus Aufwach- und Schlafenszeit erzeugt (Werte für 07:00 / 22:00):
- **Morgen**: 30 % / 3000 K zur Aufwachzeit, 90 % / 4500 K 20 Minuten später, 100 % / 5000 K nach einer Stunde – morgens wird es schnell hell.
- **Tag**: 100 %; die Farbtemperatur steigt bis fünf Stunden nach der Aufwachzeit auf 6000 K und sinkt bis vier Stunden vor der Schlafenszeit auf 5000 K. Kein Mittagstief.
- **Abend**: ab drei Stunden vor der Schlafenszeit abfallend auf 10 % / 2200 K zur Schlafenszeit.
- **Nacht**: 5 % / 2200 K ab 15 Minuten nach der Schlafenszeit bis zur Aufwachzeit (Orientierungslicht; HCL schaltet nie ein Licht ein).
- Die Werte sind ingenieurmäßige Annahmen zwischen Blendung und Wirkung; keine Norm legt sie fest. Ist der Tag kürzer als etwa 9 Stunden, wird die Kurve auf die Spanne gestaucht.

Eine in der Karte gespeicherte Kurve hat Vorrang vor den Ankerzeiten; Speichern der Optionen behält sie. **Wer Aufwach- oder Schlafenszeit ändert, verwirft die gespeicherte Kurve** und bekommt eine neue Standardkurve.

## Optionen (Integration → Konfigurieren)
**1. Kurve und Lichter**
- **Zu steuernde Lichter** (mindestens ein Ziel).
- **Aufwachzeit** (07:00), **Schlafenszeit** (22:00); dazwischen müssen mehr als 6 Stunden liegen.
- **Minimale/Maximale Helligkeit** (1–100 %, Minimum kleiner als Maximum; Standard 3–100 %; Instanzen von vor 0.8.0 behalten ihr Minimum, 10 %, wenn es nie geändert wurde): Kurvenwerte außerhalb werden abgeschnitten; die Karte schattiert diese Bereiche und zeigt die wirksame Helligkeit gestrichelt. Fokus, Entspannen und Putzen bleiben ebenfalls in den Grenzen, Schlafen und Nachtlicht nicht.
- **Kompatibilitätsmodus (langsame/komplexe Lichter)**: für Lichter, die bei Aktualisierungen flackern oder stocken, z. B. IKEA TRÅDFRI (sie blenden je Befehl nur einen Wert über und ignorieren während eines Farbübergangs weitere Befehle). Helligkeit und Farbe gehen in zwei getrennten Befehlen, die Farbtemperatur ohne Übergang (Übergang 0, damit kein Standardübergang eines Lichtprofils oder der Integration der Leuchte greift); der zweite Befehl geht nur raus, wenn das Licht noch an ist und nicht zwischendurch von Hand geändert wurde. Scheitert das, werden die Werte einmal ohne Übergang gesendet (einmal als Warnung im Log, bis der zweiteilige Befehl wieder klappt). Gilt für Aktualisierungen mit Übergang; die Werte direkt nach dem Einschalten und Aktualisierungen ohne Übergang sind immer ein Befehl.

**2. Aktualisierung und manuelle Steuerung**
| Option | Standard | Bedeutung |
|---|---|---|
| Rückkehr zu HCL nach manueller Steuerung | 240 min | 0–1440 min; 0 = nie automatisch |
| Ausschalten beendet die manuelle Steuerung | an | Aus: ein pausiertes Licht bleibt pausiert, auch nach Aus- und Einschalten |
| Manuelle Steuerung über Neustarts behalten | aus | An: pausierte Lichter bleiben nach einem Neustart pausiert |
| Werte von Einschaltbefehlen behalten | aus | An: Ein Licht, das über Home Assistant mit eigener Helligkeit oder Farbe eingeschaltet wird (Szene, Automation, Sprache, App), behält diese Werte |


Im eingeklappten Abschnitt **Erweitert: Zeiten** (meist unverändert lassen):

| Option | Standard | Bedeutung |
|---|---|---|
| Aktualisierungsintervall | 27 s | Abstand der Aktualisierungen (15–300 s) |
| Übergangszeit der Aktualisierungen | 20 s | 0–300 s, kürzer als das Intervall; Lichter ohne Übergänge ignorieren sie |
| Übergang bei Szenario-Wechsel | wie Übergangszeit | 0–300 s; gilt auch, wenn ein zeitlich begrenztes Szenario endet; darf länger als das Intervall sein (die Lichter bleiben bis zum Ende in Ruhe) |

Ein eingeschaltetes Licht bekommt die Werte sofort, ohne Übergang (die Option „Übergangszeit beim Einschalten“ aus 0.6/0.7 entfällt mit 0.8.0).

**3. Szenarien**: Helligkeit (1–100 %) und Farbtemperatur (2000–7000 K) von **Fokus** (100 % / 5500 K), **Entspannen** (40 % / 2700 K), **Putzen** (100 % / 4000 K) und **Nachtlicht** (3 % / 2200 K) sowie die **Dauer** von Fokus/Entspannen/Putzen (0–1440 min, danach zurück zu Auto; 0 = bis zur Änderung).

**4. Tageslichtkompensation (optional)**: Ein **Luxsensor** im Raum senkt in **Auto** die Helligkeit, wenn genug Tageslicht da ist (gemessener Regelkreis). Nach einem Update oder einer Neuinstallation aus.
- **Luxsensor** (Geräteklasse Beleuchtungsstärke) und **Ziel-Beleuchtungsstärke am Sensor** (50–2000 lx) sind bei eingeschalteter Funktion Pflicht. Der Zielwert ist ein Regelwert an der Sensorposition, kein Normwert (Arbeitsplätze weiterhin eigens planen und messen).
- Die Helligkeit liegt **nie über der Kurve** und **nie unter der Mindesthelligkeit**; die **Farbtemperatur bleibt unverändert**. HCL schaltet weiterhin nie ein oder aus.
- **Nur in Auto**: In einem Szenario (Fokus, Entspannen, Putzen, Nachtlicht, Schlafen, Gast) gelten die Szenario-Werte; die Absenkung bleibt erhalten und wird bei der Rückkehr zu Auto innerhalb von 2 Stunden weiterverwendet.
- Die Absenkung ändert sich **höchstens um 11 Prozentpunkte pro Minute** (unabhängig vom Intervall), bei kleinen Abweichungen langsamer; ein **Totband** (5 % des Zielwerts, mindestens 20 lx) und eine **Glättung** des Messwerts (60 s) verhindern Kleinständerungen.
- **Keine Änderung ohne Wirkung**: Solange alle eingeschalteten Lichter manuell gesteuert werden (oder zu HCL zurückkehren), „Helligkeit anpassen“ aus ist oder „HCL aktiv“ aus ist, wird die Absenkung gehalten. Ausgeschaltete Lichter folgen weiter dem Tageslicht – ein eingeschaltetes Licht startet gedimmt.
- **Sensor ohne Wert** (nicht verfügbar, unbekannt, keine Zahl oder 60 min ohne Meldung): Die Absenkung wird 5 Minuten gehalten, danach geht die Helligkeit langsam zur Kurve zurück. Ein einzelner ungültiger Wert ändert nichts. Für Sensoren, die nur bei Änderung melden, „Sensorwert veraltet nach“ auf 0 stellen.
- **Neustart und Neuladen**: Die Absenkung wird gespeichert (höchstens alle 5 Minuten und beim Beenden von Home Assistant) und weiterverwendet, wenn sie höchstens 2 Stunden alt ist; sonst startet HCL bei der Helligkeit, die die Lichter in Auto hatten, oder bei der Kurve. Kein Sprung auf die Kurve nach dem Speichern der Optionen.
- **Sensorposition**: Der Sensor soll den Raum sehen, nicht direkt die Leuchten. Ein Sensor, den die Leuchten stark anstrahlen (z. B. 100 lx mehr je Prozent Helligkeit), kann die Helligkeit um einige Prozent pendeln lassen; ein träger Sensor verstärkt das. Je Lichtzone eine Instanz mit eigenem Sensor; nutzen mehrere aktive Instanzen denselben Sensor, erscheint eine Reparaturmeldung.
- Die Sollwert-Sensoren zeigen den wirksamen Wert; ihre Attribute `base_value` (Kurve oder Szenario), `environment_status`, `environment_reason`, `measured_lux`, `filtered_lux`, `target_lux`, `cap_pct` und `sensor_age` erklären ihn (nicht im Verlauf). Die Karte zeigt z. B. „80 % → 35 % · Tageslicht“.

Im eingeklappten Abschnitt **Erweitert: Tageslichtregelung**: Totband, Glättung, Regelband (300 lx: Abweichung mit voller Geschwindigkeit), maximale Geschwindigkeit, „Sensorwert veraltet nach“ (3600 s) und Haltezeit bei fehlendem Sensorwert (300 s).

**Hinweise zu Leuchtmitteln**: Manche Leuchtmittel haben Firmware-Grenzen, die HCL nicht beheben kann; die Optionen helfen dabei:
- **IKEA TRÅDFRI** (und ähnliche): **Kompatibilitätsmodus** einschalten (siehe oben).
- **Lichter glimmen nach „Schlafen“ weiter**: „Schlafen“ schaltet mit dem *Übergang bei Szenario-Wechsel* aus. Manche Leuchtmittel bleiben beim Ausschalten mit Übergang auf ihrer kleinsten Stufe stehen (berichtet für IKEA und AwoX/EGLO), während Home Assistant sie als aus zeigt. Diesen Übergang auf 0 s stellen.
- **Lichter schalten sich selbst wieder ein** (berichtet für Sengled): Während eines langen Übergangs ausgeschaltet, setzen sie ihn fort. Eine kurze *Übergangszeit der Aktualisierungen* wählen.
- **Alte Farbe beim Einschalten sichtbar**: HCL sendet seine Werte, sobald das Licht „an“ meldet; bis dahin zeigt es kurz seine vorherigen Werte. Abhilfe: das Licht mit den HCL-Werten einschalten (siehe *Rezepte*). Mit ZHA verhindert die Option „Enhanced light transition“, dass ein solcher Befehl mit Übergang von der alten Farbe aus überblendet.

## Entitäten je Instanz
Jede Instanz ist ein Gerät mit diesen Entitäten (Entity-IDs neuer Installationen; bestehende Installationen behalten ihre IDs, nur die Anzeigenamen ändern sich; der Namensteil der ID folgt der Sprache beim Anlegen, z. B. `_hcl_aktiv`):

| Entität | Beispiel-ID | Zweck |
|---|---|---|
| **HCL aktiv** (Schalter) | `switch.wohnzimmer_hcl_aktiv` | HCL ein/aus. Wird diese Entität deaktiviert, steht die Instanz still (die Aktionen `apply`, `set_manual_control` und `set_scenario` melden das). Attribut `manual_control`: manuell gesteuerte Lichter. Die Attribute (`manual_control`, `target_entities`, `calculated_*`) sind Live-Werte und stehen nicht im Verlauf; den Verlauf zeigen die Sollwert-Sensoren, die manuelle Steuerung das Logbuch |
| **Helligkeit anpassen** (Schalter) | `switch.wohnzimmer_helligkeit_anpassen` | Aus: HCL lässt die Helligkeit unverändert (Schlafen schaltet trotzdem aus) |
| **Farbtemperatur anpassen** (Schalter) | `switch.wohnzimmer_farbtemperatur_anpassen` | Aus: HCL lässt die Farbtemperatur unverändert |
| **Szenario** (Auswahl) | `select.wohnzimmer_szenario` | Auto, Schlafen, Nachtlicht, Fokus, Entspannen, Putzen, Gast (abgekündigt; auch die Chips der Karte). Attribut `until`: Ende eines zeitlich begrenzten Szenarios |
| **Sollhelligkeit** / **Sollfarbtemperatur** (Sensoren) | `sensor.wohnzimmer_sollhelligkeit` | Werte, die HCL jetzt sendet (Szenario, Min/Max und Tageslichtkompensation berücksichtigt; Schlafen 0 %, Gast `unknown`), unabhängig von den Anpassungs-Schaltern und der manuellen Steuerung |
| **Curve Data** (Sensor) | `sensor.wohnzimmer_curve_data` | Daten für die Karte (Zustand: Zeit der letzten Kurven-/Szenarioänderung). Attribute u. a. `instance` (Name der Instanz, Kartentitel), `preview_active` (Lichter folgen einer ungespeicherten Vorschau), `wake_time`, `sleep_time`, `default_points` (Standardkurve zu diesen Zeiten, für die Schaltfläche **Standardkurve** der Karte) |

## Szenarien
- **Auto**: Lichter folgen der Kurve.
- **Fokus / Entspannen / Putzen**: feste Werte (in den Optionen einstellbar, optional mit Dauer), innerhalb der minimalen/maximalen Helligkeit.
- **Gast** (abgekündigt, entfällt in 0.9.0): HCL sendet keine Befehle – wie „HCL aktiv“ aus. Die Auswahl schreibt eine Warnung ins Log und zeigt eine Reparaturmeldung; stattdessen „HCL aktiv“ ausschalten.
- **Schlafen**: Eingeschaltete Lichter werden ausgeblendet. Wer währenddessen ein Licht einschaltet, steuert es manuell; es bleibt an, bis es ausgeschaltet wird (oder die Rückkehrzeit abläuft).
- **Nachtlicht**: gedimmtes, warmes Licht (Standard 3 % / 2200 K). Eingeschaltete und nachts eingeschaltete Lichter bekommen diese Werte; HCL schaltet nichts ein oder aus.

Schlafen und Nachtlicht enden zur nächsten Aufwachzeit (zurück zu Auto); mit `hcl_lighting.set_scenario` und `duration: 0` bleiben sie bis zur Änderung. Ein Szenario-Wechsel wird mit dem „Übergang bei Szenario-Wechsel“ gesendet.

## Manuelle Steuerung
HCL pausiert ein einzelnes Licht (der Schalter „HCL aktiv“ bleibt an), wenn
- Home Assistant Helligkeit oder Farbe mit einem Befehl ändert, der nicht von HCL stammt (App, Dashboard, Szene, Automation, Sprachassistent), oder
- das Licht Werte meldet, die von den HCL-Werten abweichen (z. B. Wandtaster, Hersteller-App): Helligkeit > 2 %, Farbtemperatur > 100 K, XY-Farbe > 0,05. Eine Meldung „an“ mit Helligkeit 0 (z. B. KNX, wenn der Helligkeitsstatus kurz vor oder nach dem Schaltstatus kommt) enthält keine Helligkeit und zählt dafür nicht.

Änderungen an einem Attribut, das HCL nicht anpasst (Anpassungs-Schalter), pausieren nicht. Home Assistant ordnet Meldungen eines Lichts bis 5 Sekunden nach einem Befehl diesem Befehl zu, auch eine Bedienung am Gerät (z. B. Dimmen am Tastdimmer direkt nach dem Einschalten). Solche Meldungen bewertet HCL nach ihren Werten: Weicht das Licht über seinen vorigen Wert hinaus ab, ist es sofort manuell gesteuert; bewegt es sich zurück Richtung vorigen Wert, entscheidet HCL am Ende des Übergangs (hat das Licht den HCL-Wert bis dahin nicht erreicht, ist es manuell gesteuert).

Das Licht kehrt zu HCL zurück, wenn es aus- und wieder eingeschaltet wird (mit „Ausschalten beendet die manuelle Steuerung“, Standard), oder nach der eingestellten Zeit (Standard 4 Stunden), wenn es noch an ist – mit einem sanften Übergang über 3 Minuten, den die normalen Aktualisierungen nicht unterbrechen (ein Szenario-Wechsel, eine Kurvenänderung oder Ausschalten beenden ihn). HCL schaltet nie ein Licht ein. Ein Licht, das bis zu 5 Minuten nicht erreichbar ist (`unavailable`/`unknown`, z. B. Neustart oder Funkaussetzer), bleibt manuell gesteuert; eine längere Lücke zählt wie Ausschalten. Pausierte Lichter bleiben pausiert, wenn Kurve oder Optionen gespeichert werden, auf Wunsch auch über Neustarts.

Standardmäßig bekommt ein eingeschaltetes Licht sofort die HCL-Werte, auch wenn der Einschaltbefehl eigene Werte enthielt; mit **Werte von Einschaltbefehlen behalten** bleiben sie erhalten.

## Aktionen (Services)
| Aktion | Felder | Wirkung |
|---|---|---|
| `hcl_lighting.apply` | `entity_id` (beliebige Entität der Instanz), `lights` (optional), `transition` (s, optional), `release_manual_control` | Sendet die aktuellen Werte sofort an eingeschaltete Lichter. Die Lichter der Instanz werden beim Aufruf aufgelöst (Bereiche, Geräte, Labels, Gruppen), auch bei ausgeschaltetem *HCL aktiv*. Schaltet nie ein; manuell gesteuerte nur mit `release_manual_control: true`; nicht im Gastmodus. Ein Übergang länger als der der Aktualisierungen wird nicht unterbrochen. Scheitert ein Lichtbefehl oder antwortet ein Licht nicht innerhalb von 10 s, endet die Aktion mit einem Fehler; die übrigen Lichter sind aktualisiert |
| `hcl_lighting.set_manual_control` | `entity_id`, `lights` (optional, Standard alle), `manual_control` (Standard `true`) | Lichter pausieren oder an HCL zurückgeben |
| `hcl_lighting.set_scenario` | `entity_id`, `scenario`, `duration` (min, optional; 0 = bis zur Änderung) | Setzt das Szenario; eine Dauer ersetzt das eingestellte Ende |
| `hcl_lighting.get_curve` | `entity_id` | Antwortdaten: `points`, `saved_points`, `preview_active`, `wake_time`, `sleep_time` |
| `hcl_lighting.update_curve` | `entity_id`, `mode`, `points` | Von der Karte genutzt: `mode` `preview`/`apply` (Punkte bis zum nächsten Neuladen, Standard `preview`), `save` (dauerhaft, ohne die Integration neu zu laden), `revert` (gespeicherte Kurve laden); `points`: mindestens 2 × `{t: 0–1440 min, b: 0–100 %, k: 2000–7000 K}` mit verschiedenen Zeiten (1440 = 00:00, andere Schlüssel werden ignoriert, für `revert` nicht nötig) |

**Berechtigungen**: Benutzer mit eingeschränkten Rechten brauchen für die schreibenden Aktionen (`apply`, `set_manual_control`, `set_scenario`, `update_curve`) die Steuerberechtigung für die angegebene HCL-Entität, den Schalter „HCL aktiv“ (bei `set_scenario` auch die Szenario-Auswahl) und die unter `lights` genannten Lichter; `get_curve` braucht Leserechte. Sendet eine Aktion die HCL-Werte sofort an die Lichter, braucht sie zusätzlich die Steuerberechtigung für alle Lichter der Instanz – wie beim direkten Schalten: `apply` ohne `lights`, `set_manual_control` mit `manual_control: false` (aktualisiert sofort die ganze Instanz), `set_scenario`, `update_curve` sowie im Dashboard Szenario wählen, „HCL aktiv“ einschalten und die Anpassungs-Schalter. Lichter pausieren (`manual_control: true`) und HCL ausschalten senden keinen Befehl. Automationen und Skripte sind nicht eingeschränkt. Die Lichtbefehle einer Aktion laufen als der Benutzer, der sie ausgelöst hat (Logbuch, Traces); die regelmäßigen Aktualisierungen und das automatische Ende eines Szenarios laufen ohne Benutzer.

Beginnt oder endet die manuelle Steuerung eines Lichts, erscheinen ein Logbuch-Eintrag und das Event `hcl_lighting_manual_control` (`entity_id`, `manual_control`, `instance`, `config_entry_id`). Steuern zwei Instanzen dasselbe Licht für dasselbe Attribut, meldet eine Reparatur das. Diagnosedaten lassen sich auf der Integrationsseite herunterladen – ohne Namen der Instanz, Entitäts-, Geräte-, Bereichs-, Etagen- und Label-IDs als Pseudonyme (z. B. `light.redacted_1`), manuelle Steuerung als Alter in Minuten. Kurve und Aufwach- und Schlafenszeit bleiben für die Fehlersuche enthalten; vor dem Veröffentlichen (z. B. in einem Issue) bitte prüfen.

## Rezepte
**Licht mit den HCL-Werten einschalten** (z. B. für Leuchten, die im ausgeschalteten Zustand keine Werte annehmen, oder für ein KNX-/DALI-Gateway):
```yaml
action: light.turn_on
target:
  entity_id: light.nachttisch
data:
  brightness_pct: "{{ states('sensor.wohnzimmer_sollhelligkeit') | int(50) }}"
  color_temp_kelvin: "{{ states('sensor.wohnzimmer_sollfarbtemperatur') | int(3000) }}"
```
Bei „Schlafen“ ist die Sollhelligkeit 0 % (das Licht wird ausgeschaltet); im Gastmodus sind die Sensoren `unknown`, dann gelten die Werte in `int(...)`.

**Alle Lichter zur Aufwachzeit an HCL zurückgeben**:
```yaml
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: hcl_lighting.set_manual_control
    data:
      entity_id: switch.wohnzimmer_hcl_aktiv
      manual_control: false
```

**Kurve in eine andere Instanz kopieren**:
```yaml
- action: hcl_lighting.get_curve
  data:
    entity_id: sensor.wohnzimmer_curve_data
  response_variable: curve
- action: hcl_lighting.update_curve
  data:
    entity_id: sensor.schlafzimmer_curve_data
    mode: save
    points: "{{ curve.points }}"
```

**Tageslicht (Lux)**: Die Tageslichtkompensation (Optionen, Abschnitt 4) senkt die Helligkeit mit einem Luxsensor. Lichter bei genug Tageslicht ausschalten bleibt eine Automation: mit `set_manual_control` pausieren, ausschalten und danach an HCL zurückgeben.

## Dashboard-Karte
Punkte ziehen, mit ➕ oder Doppelklick hinzufügen, mit ➖, Entf oder Rücktaste löschen, Uhrzeit/Helligkeit/Farbtemperatur direkt eingeben, mit ↶ oder Strg+Z rückgängig machen; die Punkte bleiben zeitlich sortiert. **Vorschau** sendet die ungespeicherte Kurve bis zum nächsten Neuladen an die Lichter (die Karte zeigt dann „Vorschau aktiv – nicht gespeichert“), **Speichern** übernimmt sie dauerhaft (ohne die Integration neu zu laden), **Verwerfen** lädt die gespeicherte Kurve. Schlägt Speichern fehl, zeigt die Karte den Fehler und die Änderungen bleiben als ungespeichert markiert. Die gestrichelte senkrechte Linie zeigt die aktuelle Uhrzeit (Zeitzone von Home Assistant), darunter stehen das aktive Szenario mit seinem Ende (z. B. „bis 07:00“) und die Werte, die HCL jetzt sendet (aus den Sollwert-Sensoren; „Sollwerte nicht verfügbar“, solange sie keinen Wert haben). Mit Tageslichtkompensation zeigt die Zeile Kurven- bzw. Szenario-Wert und wirksamen Wert, z. B. „80 % → 35 % · Tageslicht“ (auch „Tageslicht gehalten“ und „Tageslichtsensor ohne Wert“). Hinweise warnen vor unplausiblen Kurven, z. B. hellem oder kaltem Licht nachts (von der Schlafens- bis zur Aufwachzeit).

Die Szenario-Chips wechseln das Szenario; die Kurve lässt sich in jedem Szenario bearbeiten, wirkt aber nur in Auto. Wird die Kurve woanders geändert, während du bearbeitest, bleibt dein Entwurf erhalten und die Karte bietet „Diese Kurve laden“ an. **Standardkurve** lädt die Standardkurve zu Aufwach- und Schlafenszeit der Instanz in den Editor (mit Speichern übernehmen); bis 0.7 gab es stattdessen feste Vorlagen. Tastatur am gewählten Punkt: ↑/↓ Wert (Bild↑/Bild↓ in größeren Schritten), ←/→ Uhrzeit, Pos1/Ende Minimum/Maximum, Umschalt = größere Schritte, Entf/Rücktaste löschen. Sprache, Uhrzeit- und Zahlenformat folgen dem Home-Assistant-Profil, die Farben dem aktiven (hellen oder dunklen) Theme. Mit `view: compact` zeigt die Karte nur Status und Szenario-Chips, der Editor klappt bei Bedarf auf. Titel der Karte ist der Name der Instanz (Eintrag unter Einstellungen → Geräte & Dienste umbenennen, z. B. „Küche“) oder `title:` in der Kartenkonfiguration. Die Karte passt sich schmalen Spalten (ab 240 px) an. In Sections-Dashboards die Höhe auf „automatisch“ lassen: Die Höhe der Karte ändert sich mit ihrem Inhalt (Editor auf/zu, Hinweise); bei fester Höhe scrollt die Karte innen. Mit Screenreader ist jeder Punkt ein Schieberegler („Helligkeitspunkt 1, 07:00, 30 %“): Wert mit der Schieberegler-Geste des Screenreaders anpassen oder Punkt wählen und Uhrzeit und Werte in den Feldern unter den Diagrammen eingeben.

## Technische Details
- **Aktualisierung**: standardmäßig alle 27 s. Es läuft immer nur eine Aktualisierung: Ein Takt entfällt, solange noch gesendet wird; angeforderte Aktualisierungen (Szenario-Wechsel, Kurvenvorschau/-verwerfen, Rückgabe der manuellen Steuerung, `apply`) warten und werden danach gesendet (mehrere werden zusammengefasst).
- **Umgebungsregler**: einzige Stelle, an der aus dem Kurven- bzw. Szenario-Wert (Basis) der wirksame Sollwert wird. Jede reguläre Aktualisierung schreitet ihn einmal fort; Sollwert-Sensoren, `apply`, Karte und ein eingeschaltetes Licht lesen ihn, ohne ihn zu verändern. Geschwindigkeiten gelten je Zeit (echte Zeit seit der letzten Aktualisierung, höchstens 60 s). Ein Fehler in einer Funktion fällt auf den Wert ohne sie zurück und steht einmal im Log. Ohne konfigurierte Funktion sind die Werte genau die Basiswerte.
- **Ein Befehl je Licht**, damit ein fehlschlagendes Licht den Erfolg der anderen nicht verdeckt. Eine Aktualisierung wartet höchstens 10 s auf ihre Lichtbefehle; der Befehl wird nicht abgebrochen. Ein Licht bekommt keinen weiteren Befehl, solange einer läuft (auch über ein Neuladen der Integration und beim Einschalten).
- **Fehlgeschlagene Befehle** zählen nicht als gesendet (kein Übergangsschutz, keine falsche manuelle Steuerung bei der nächsten Meldung); die nächste Aktualisierung versucht es erneut. Ein dauerhaft fehlschlagendes Licht steht einmal als Warnung im Log und einmal, wenn es wieder Befehle annimmt (Wiederholungen auf Debug-Ebene).
- **Farbtemperatur**: Lichter mit eigener Farbtemperatur bekommen den Wert, den sie erreichen (begrenzt auf ihr Minimum/Maximum), auch wenn sie Farbe können (seit 0.8.0); Farblichter ohne Farbtemperatur erhalten sie über die XY-Simulation. Verglichen wird mit dem erreichbaren Wert (Lichter im XY-Modus nach Farbe). RGBW- und RGBWW-Leuchten werden wie Farbleuchten über XY gesteuert: Die Umrechnung von Home Assistant auf die Weißkanäle braucht deren Bereich, den diese Leuchten nicht melden.

Entwicklung und Tests: siehe [README (englisch), Development](README.md#-development).
