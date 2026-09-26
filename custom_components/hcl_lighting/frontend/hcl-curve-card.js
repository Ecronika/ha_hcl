/*
 * HCL Curve Card – status and daily-curve editor for HCL Lighting.
 *
 * Structure of this file:
 *   1. texts and constants
 *   2. curve maths (same algorithm as the integration, logic/hcl_math.py)
 *   3. formatting (Home Assistant language, time and number format)
 *   4. loading Chart.js (own, versioned copy; a foreign global Chart is not used)
 *   5. the card: state model (saved curve, preview, draft), rendering, editing
 *   6. the card configuration editor
 *
 * The card is loaded as a JavaScript module (Lovelace resource type "module").
 */

// ---------------------------------------------------------------- 1. texts
const HCL_STRINGS = {
    en: {
        title: "HCL Configurator",
        presets: "Presets",
        preset_default: "Default (balanced)",
        preset_default_night: "Default with quiet night",
        preset_no_dip: "Default without midday dip",
        preset_focus: "Focus (home office)",
        preset_relax: "Relax (wellness)",
        preset_early_bird: "Early bird",
        preset_night_owl: "Night owl",
        revert: "Revert",
        revert_title: "Discard unsaved changes and load the saved curve",
        preview: "Preview",
        preview_title: "Apply unsaved changes to the lights until the next reload",
        save: "Save",
        save_title: "Save the curve",
        undo_title: "Undo last change (Ctrl+Z)",
        add_title: "Add point (or double-click the chart)",
        delete_title: "Delete selected point (Del)",
        edit_curve: "Edit curve",
        close_editor: "Close editor",
        brightness: "Brightness",
        color_temp: "Colour temperature",
        time: "Time",
        now: "Now",
        draft: "Draft",
        no_selection: "Select a point to edit it",
        mode_auto: "Auto",
        mode_focus: "Focus",
        mode_relax: "Relax",
        mode_cleaning: "Cleaning",
        mode_guest: "Guest",
        mode_sleep: "Sleep",
        mode_night_light: "Night light",
        guest_now: "HCL sends no values",
        setpoint_unavailable: "target values not available",
        sleep_now: "lights off",
        confirm_revert: "Discard all unsaved changes and load the saved curve?",
        preview_active: "Preview active – not saved. Save keeps it, Revert discards it.",
        curve_applies_auto: "The curve applies in Auto; active now: {mode}. Changes take effect in Auto.",
        server_changed: "The curve was changed elsewhere. Your changes are kept.",
        adopt_server: "Load that curve",
        save_failed: "Saving failed: {msg}",
        preview_failed: "Preview failed: {msg}",
        revert_failed: "Revert failed: {msg}",
        mode_failed: "Changing the scenario failed: {msg}",
        data_loading: "Waiting for data from {entity} …",
        data_missing: "Entity {entity} not found. Choose the HCL curve sensor in the card settings.",
        data_unavailable: "{entity} is unavailable (is the integration loaded?).",
        data_invalid: "{entity} is not an HCL curve sensor.",
        invalid_time: "Enter a complete time (hh:mm).",
        invalid_number: "Enter a number.",
        point_b: "Brightness point {n}",
        point_k: "Colour temperature point {n}",
        handle_help: "Up/Down: value, Page Up/Down: large steps, Home/End: minimum/maximum, Left/Right: time, Delete: remove point.",
        chart_b_desc: "Brightness over the day: lowest {min} at {tmin}, highest {max} at {tmax}.",
        chart_k_desc: "Colour temperature over the day: lowest {min} at {tmin}, highest {max} at {tmax}.",
        color_bar: "Colour over the day",
        val_min_points: "The curve needs at least 2 points.",
        val_slope_b: "Brightness changes too steeply (>2 %/min) at {time}.",
        val_slope_k: "Colour temperature changes too steeply (>100 K/min) at {time}.",
        val_peak_k: "Active phase: colour temperature too low here, raise it above 5000 K.",
        val_peak_b: "Active phase: brightness too low here, raise it above 70 %.",
        val_peak_short: "Active phase too short (<4 h). Try high brightness and colour temperature around noon.",
        val_night_b: "At night (sleep to wake time) brighter than 10 %: {from}–{to}. For darker nights use the preset “Default with quiet night”.",
        val_night_k: "At night (sleep to wake time) colder than 3000 K: {from}–{to}.",
        chart_error: "Error loading Chart.js: {msg}. Check the integration installation.",
        editor_entity: "HCL curve sensor",
        editor_view: "View",
        view_full: "Full (editor always visible)",
        view_compact: "Compact (status; editor on demand)",
        editor_none: "No HCL instance found",
    },
    de: {
        title: "HCL-Konfigurator",
        presets: "Vorlagen",
        preset_default: "Standard (ausgewogen)",
        preset_default_night: "Standard mit Nachtruhe",
        preset_no_dip: "Standard ohne Mittagstief",
        preset_focus: "Fokus (Homeoffice)",
        preset_relax: "Entspannung (Wellness)",
        preset_early_bird: "Frühaufsteher",
        preset_night_owl: "Nachteule",
        revert: "Verwerfen",
        revert_title: "Ungespeicherte Änderungen verwerfen und gespeicherte Kurve laden",
        preview: "Vorschau",
        preview_title: "Ungespeicherte Änderungen bis zum nächsten Neuladen an die Lichter senden",
        save: "Speichern",
        save_title: "Kurve speichern",
        undo_title: "Letzte Änderung rückgängig (Strg+Z)",
        add_title: "Punkt hinzufügen (oder Doppelklick ins Diagramm)",
        delete_title: "Ausgewählten Punkt löschen (Entf)",
        edit_curve: "Kurve bearbeiten",
        close_editor: "Bearbeitung schließen",
        brightness: "Helligkeit",
        color_temp: "Farbtemperatur",
        time: "Uhrzeit",
        now: "Jetzt",
        draft: "Entwurf",
        no_selection: "Punkt auswählen, um ihn zu bearbeiten",
        mode_auto: "Auto",
        mode_focus: "Fokus",
        mode_relax: "Entspannen",
        mode_cleaning: "Putzen",
        mode_guest: "Gast",
        mode_sleep: "Schlafen",
        mode_night_light: "Nachtlicht",
        guest_now: "HCL sendet keine Werte",
        setpoint_unavailable: "Sollwerte nicht verfügbar",
        sleep_now: "Lichter aus",
        confirm_revert: "Alle ungespeicherten Änderungen verwerfen und die gespeicherte Kurve laden?",
        preview_active: "Vorschau aktiv – nicht gespeichert. Speichern übernimmt sie, Verwerfen verwirft sie.",
        curve_applies_auto: "Die Kurve gilt im Modus Auto; aktiv ist gerade {mode}. Änderungen wirken in Auto.",
        server_changed: "Die Kurve wurde an anderer Stelle geändert. Deine Änderungen bleiben erhalten.",
        adopt_server: "Diese Kurve laden",
        save_failed: "Speichern fehlgeschlagen: {msg}",
        preview_failed: "Vorschau fehlgeschlagen: {msg}",
        revert_failed: "Verwerfen fehlgeschlagen: {msg}",
        mode_failed: "Szenario-Wechsel fehlgeschlagen: {msg}",
        data_loading: "Warte auf Daten von {entity} …",
        data_missing: "Entität {entity} nicht gefunden. In den Karteneinstellungen den HCL-Kurvensensor wählen.",
        data_unavailable: "{entity} ist nicht verfügbar (Integration geladen?).",
        data_invalid: "{entity} ist kein HCL-Kurvensensor.",
        invalid_time: "Vollständige Uhrzeit eingeben (hh:mm).",
        invalid_number: "Zahl eingeben.",
        point_b: "Helligkeitspunkt {n}",
        point_k: "Farbtemperaturpunkt {n}",
        handle_help: "Hoch/Runter: Wert, Bild auf/ab: große Schritte, Pos1/Ende: Minimum/Maximum, Links/Rechts: Uhrzeit, Entf: Punkt löschen.",
        chart_b_desc: "Helligkeit über den Tag: niedrigster Wert {min} um {tmin}, höchster {max} um {tmax}.",
        chart_k_desc: "Farbtemperatur über den Tag: niedrigster Wert {min} um {tmin}, höchster {max} um {tmax}.",
        color_bar: "Farbverlauf des Tages",
        val_min_points: "Die Kurve braucht mindestens 2 Punkte.",
        val_slope_b: "Helligkeit ändert sich zu steil (>2 %/min) um {time}.",
        val_slope_k: "Farbtemperatur ändert sich zu steil (>100 K/min) um {time}.",
        val_peak_k: "Aktivphase: Farbtemperatur hier zu niedrig, über 5000 K anheben.",
        val_peak_b: "Aktivphase: Helligkeit hier zu niedrig, über 70 % anheben.",
        val_peak_short: "Aktivphase zu kurz (<4 h). Um die Mittagszeit hohe Helligkeit und Farbtemperatur wählen.",
        val_night_b: "Nachts (Schlafens- bis Aufwachzeit) heller als 10 %: {from}–{to}. Für dunklere Nächte die Vorlage „Standard mit Nachtruhe“ nutzen.",
        val_night_k: "Nachts (Schlafens- bis Aufwachzeit) kälter als 3000 K: {from}–{to}.",
        chart_error: "Chart.js konnte nicht geladen werden: {msg}. Installation der Integration prüfen.",
        editor_entity: "HCL-Kurvensensor",
        editor_view: "Ansicht",
        view_full: "Voll (Editor immer sichtbar)",
        view_compact: "Kompakt (Status; Editor bei Bedarf)",
        editor_none: "Keine HCL-Instanz gefunden",
    },
};

// Fallback values of the scenarios (the curve sensor provides the configured ones)
// Time a removed card waits before it releases its charts (ms)
const HCL_RELEASE_DELAY = 1000;

const HCL_SCENARIO_DEFAULTS = {
    focus: { b: 100, k: 5500 },
    relax: { b: 40, k: 2700 },
    cleaning: { b: 100, k: 4000 },
    sleep: { b: 0, k: 2000 },
    night_light: { b: 3, k: 2200 },
};

const HCL_MODES = [
    ["auto", "mdi:chart-bell-curve"],
    ["focus", "mdi:brain"],
    ["relax", "mdi:coffee"],
    ["cleaning", "mdi:broom"],
    ["guest", "mdi:account-group"],
    ["night_light", "mdi:weather-night"],
    ["sleep", "mdi:bed"],
];

// Presets (t: minutes, b: %, k: K). 00:00 is t=0 (24:00 is the same moment).
const HCL_DEFAULT_CURVE = [
    { t: 420, b: 30, k: 2700 }, { t: 540, b: 50, k: 4500 }, { t: 570, b: 75, k: 5500 },
    { t: 600, b: 100, k: 6500 }, { t: 720, b: 100, k: 6500 }, { t: 750, b: 50, k: 4000 },
    { t: 780, b: 50, k: 4000 }, { t: 810, b: 75, k: 6000 }, { t: 840, b: 75, k: 6000 },
    { t: 960, b: 50, k: 4000 }, { t: 1080, b: 30, k: 2700 }, { t: 1320, b: 10, k: 2200 },
];
const HCL_PRESETS = {
    // identical to the integration's default curve (anchors 07:00 / 12:30 / 22:00)
    default: HCL_DEFAULT_CURVE,
    // default curve with a dark, warm night between sleep and wake time
    default_night: [
        { t: 390, b: 5, k: 2200 }, ...HCL_DEFAULT_CURVE, { t: 1380, b: 5, k: 2200 },
    ],
    // default curve without the midday dip
    no_dip: [
        { t: 420, b: 30, k: 2700 }, { t: 540, b: 50, k: 4500 }, { t: 570, b: 75, k: 5500 },
        { t: 600, b: 100, k: 6500 }, { t: 840, b: 100, k: 6500 }, { t: 900, b: 75, k: 6000 },
        { t: 960, b: 50, k: 4000 }, { t: 1080, b: 30, k: 2700 }, { t: 1320, b: 10, k: 2200 },
    ],
    focus: [
        { t: 0, b: 5, k: 2000 }, { t: 420, b: 15, k: 3500 }, { t: 480, b: 80, k: 5500 },
        { t: 540, b: 100, k: 6500 }, { t: 720, b: 100, k: 6500 }, { t: 780, b: 80, k: 5500 },
        { t: 840, b: 100, k: 6000 }, { t: 1020, b: 80, k: 5500 }, { t: 1080, b: 50, k: 3500 },
        { t: 1200, b: 30, k: 2700 }, { t: 1320, b: 10, k: 2200 },
    ],
    relax: [
        { t: 0, b: 5, k: 2000 }, { t: 315, b: 10, k: 2000 }, { t: 480, b: 20, k: 2200 },
        { t: 600, b: 50, k: 3000 }, { t: 720, b: 71, k: 5000 }, { t: 840, b: 71, k: 5000 },
        { t: 960, b: 70, k: 5000 }, { t: 1080, b: 40, k: 2700 }, { t: 1200, b: 30, k: 2200 },
        { t: 1260, b: 20, k: 2000 }, { t: 1320, b: 10, k: 2000 },
    ],
    early_bird: [
        { t: 360, b: 11, k: 2700 }, { t: 450, b: 50, k: 4500 }, { t: 480, b: 75, k: 5500 },
        { t: 510, b: 100, k: 6500 }, { t: 630, b: 100, k: 6500 }, { t: 660, b: 50, k: 4000 },
        { t: 690, b: 50, k: 4000 }, { t: 720, b: 75, k: 6000 }, { t: 750, b: 75, k: 6000 },
        { t: 870, b: 50, k: 4000 }, { t: 990, b: 30, k: 2700 }, { t: 1290, b: 5, k: 2200 },
    ],
    night_owl: [
        { t: 0, b: 5, k: 2200 }, { t: 540, b: 20, k: 2700 }, { t: 660, b: 50, k: 4500 },
        { t: 690, b: 75, k: 5500 }, { t: 720, b: 100, k: 6500 }, { t: 840, b: 100, k: 6500 },
        { t: 870, b: 50, k: 4000 }, { t: 900, b: 50, k: 4000 }, { t: 930, b: 75, k: 6000 },
        { t: 960, b: 75, k: 6000 }, { t: 1080, b: 50, k: 4000 }, { t: 1200, b: 21, k: 2700 },
    ],
};
const HCL_PRESET_ORDER = ["default", "default_night", "no_dip", "focus", "relax", "early_bird", "night_owl"];

const HCL_UNDO_LIMIT = 50;
const HCL_CHART_VERSION = "4.5.1";

// ---------------------------------------------------------------- 2. curve maths
const HCL_STEP = 15; // minutes
const HCL_DAY = 1440;

// Control points: 24:00 (t=1440) is the same moment as 00:00 and becomes t=0
// (if both exist, 00:00 wins), sorted, each time once (as the integration does).
function hclNormalize(points) {
    if (!Array.isArray(points)) return null;
    const valid = points.filter(p => p && [p.t, p.b, p.k].every(v => Number.isFinite(Number(v))));
    const hasMidnight = valid.some(p => Number(p.t) === 0);
    const out = [];
    const seen = new Set();
    valid
        .map(p => ({ t: Math.round(Number(p.t)), b: Number(p.b), k: Number(p.k) }))
        .filter(p => !(p.t === HCL_DAY && hasMidnight))
        .map(p => ({ ...p, t: p.t === HCL_DAY ? 0 : p.t }))
        .filter(p => p.t >= 0 && p.t < HCL_DAY)
        .sort((a, c) => a.t - c.t)
        .forEach(p => { if (!seen.has(p.t)) { seen.add(p.t); out.push(p); } });
    return out;
}

function hclKey(points) {
    return JSON.stringify((points || []).map(p => [p.t, p.b, p.k]));
}

const hclMod = (x) => ((x % HCL_DAY) + HCL_DAY) % HCL_DAY;

function hclSlope(tPrev, yPrev, tCurr, yCurr, tNext, yNext) {
    const dtL = hclMod(tCurr - tPrev);
    const dtR = hclMod(tNext - tCurr);
    if (dtL === 0 || dtR === 0) return 0;
    const dL = (yCurr - yPrev) / dtL;
    const dR = (yNext - yCurr) / dtR;
    if (dL * dR <= 0) return 0;
    if (Math.abs(dL) < 1e-9 || Math.abs(dR) < 1e-9) return 0;
    const w1 = 2 * dtR + dtL;
    const w2 = dtR + 2 * dtL;
    return (w1 + w2) / (w1 / dL + w2 / dR);
}

function hclHermite(t, h, y0, y1, m0, m1) {
    const t2 = t * t, t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m0
        + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * m1;
}

// Unrounded curve value at a minute of the day (PCHIP on the 24-h circle)
function hclValueAt(points, minute) {
    const n = points.length;
    if (!n) return { b: 0, k: 2700 };
    if (n < 2) return { b: points[0].b, k: points[0].k };
    const now = hclMod(minute);
    let idx = n - 1;
    for (let i = 0; i < n - 1; i++) {
        if (points[i].t <= now && now < points[i + 1].t) { idx = i; break; }
    }
    const prev = points[(idx - 1 + n) % n], curr = points[idx];
    const next = points[(idx + 1) % n], next2 = points[(idx + 2) % n];
    const dt = hclMod(next.t - curr.t) || HCL_DAY;
    const t = hclMod(now - curr.t) / dt;
    const value = (key) => hclHermite(
        t, dt, curr[key], next[key],
        hclSlope(prev.t, prev[key], curr.t, curr[key], next.t, next[key]),
        hclSlope(curr.t, curr[key], next.t, next[key], next2.t, next2[key]),
    );
    return { b: value('b'), k: value('k') };
}

// Brightness the lights get: clipped to min/max, or the curve range 10–100 %
// mapped onto min–max (option "scale")
function hclEffectiveB(b, limits) {
    let v = b;
    if (limits.scale) v = limits.minB + (b - 10) * (limits.maxB - limits.minB) / 90;
    return Math.max(limits.minB, Math.min(limits.maxB, v));
}

function hclSamples(points) {
    const res = { t: [], b: [], k: [] };
    for (let i = 0; i <= HCL_DAY / HCL_STEP; i++) {
        const t = i * HCL_STEP;
        const v = hclValueAt(points, t);
        res.t.push(t); res.b.push(v.b); res.k.push(v.k);
    }
    return res;
}

// ---------------------------------------------------------------- 3. formatting
class HclFormat {
    constructor(hass) {
        const locale = (hass && hass.locale) || {};
        this.language = (locale.language || (hass && hass.language) || "en");
        const timeFormat = locale.time_format || "language";
        let hour12;
        if (timeFormat === "12") hour12 = true;
        else if (timeFormat === "24") hour12 = false;
        else {
            try {
                const loc = timeFormat === "system" ? undefined : this.language;
                hour12 = !!new Intl.DateTimeFormat(loc, { hour: "numeric" }).resolvedOptions().hour12;
            } catch (e) { hour12 = false; }
        }
        this.hour12 = hour12;
        const numberFormat = locale.number_format || "language";
        const numLocale = {
            comma_decimal: "en-US", decimal_comma: "de", space_comma: "fr", system: undefined, none: "en-US",
        }[numberFormat];
        try {
            this._num = new Intl.NumberFormat(numberFormat === "language" ? this.language : numLocale, {
                maximumFractionDigits: 0, useGrouping: numberFormat !== "none",
            });
        } catch (e) {
            this._num = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
        }
    }

    key() { return `${this.language}|${this.hour12}|${this._num.format(5500)}`; }

    // minute of the day (0..1440) as text; 1440 is only used as the axis end
    time(minute) {
        const m = Math.round(minute);
        const h = Math.floor(m / 60), min = m % 60;
        if (!this.hour12) return `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
        const h12 = h % 12 === 0 ? 12 : h % 12;
        const suffix = h % 24 < 12 ? "AM" : "PM";
        return `${h12}:${String(min).padStart(2, "0")} ${suffix}`;
    }

    clock(minute) { return this.time(hclMod(minute)); }
    percent(v) { return `${this._num.format(Math.round(v))} %`; }
    kelvin(v) { return `${this._num.format(Math.round(v))} K`; }
}

function minToTime(m) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    return `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- 4. Chart.js
// The card uses its own Chart.js (same folder, versioned like the card). A
// Chart.js set globally by another card is only reused if it is the same
// version; otherwise it is restored after loading ours.
let hclChartPromise = null;

function hclChartUrl() {
    try {
        const own = new URL(import.meta.url);
        const url = new URL("chart.js", own);
        const version = own.searchParams.get("v");
        if (version) url.searchParams.set("v", version);
        return url.href;
    } catch (e) {
        return "/hcl_lighting_static/chart.js";
    }
}

function hclLoadChart() {
    if (window.Chart && window.Chart.version === HCL_CHART_VERSION) return Promise.resolve(window.Chart);
    if (!hclChartPromise) {
        hclChartPromise = (async () => {
            const foreign = window.Chart;
            await import(hclChartUrl());
            const ours = window.Chart;
            if (foreign && foreign !== ours) window.Chart = foreign;
            if (!ours || ours === foreign) throw new Error("Chart.js did not load");
            return ours;
        })().catch((err) => { hclChartPromise = null; throw err; });
    }
    return hclChartPromise;
}

// ---------------------------------------------------------------- 5. the card
class HCLCurveCard extends HTMLElement {
    static getStubConfig(hass) {
        return { entity: hclCurveSensors(hass)[0] || "sensor.hcl_lighting_curve_data" };
    }

    static getConfigElement() {
        return document.createElement("hcl-curve-card-editor");
    }

    getGridOptions() {
        // Height follows the content (no fixed rows); at least half width
        return { columns: 12, min_columns: this.config && this.config.view === "compact" ? 4 : 6 };
    }

    getCardSize() {
        const height = this.getBoundingClientRect ? this.getBoundingClientRect().height : 0;
        if (height > 0) return Math.max(2, Math.ceil(height / 50));
        return this.config && this.config.view === "compact" && !this._editorOpen ? 4 : 12;
    }

    constructor() {
        super();
        this._initialized = false;
        this._Chart = null;
        this._chartB = null;
        this._chartK = null;
        this._drag = null;
        this._lang = "en";
        this._fmt = new HclFormat(null);
        this._themeKey = null;
        this._timeZone = null;

        // State model: saved curve from the sensor ("server"), local draft
        // (_points, shown and edited) and whether the lights follow a preview.
        this._server = { points: null, key: null, ref: null };
        this._points = [];
        this._undo = [];
        this._selected = -1;
        this._revision = 0;
        this._isDirty = false;
        this._previewActive = false;
        this._pending = null;             // running curve action: {type, key}
        this._savedKey = null;            // confirmed save of the current draft
        this._adoptRevision = null;       // after a revert: adopt the next server curve
        this._serverChanged = false;      // the sensor curve changed while the draft is unsaved
        this._serviceError = null;
        this._inputError = null;
        this._dataState = "loading";      // loading | missing | unavailable | invalid | ready

        this._currentMode = null;         // confirmed mode (select entity)
        this._pendingMode = null;
        this._scenarios = JSON.parse(JSON.stringify(HCL_SCENARIO_DEFAULTS));
        this._limits = { minB: 0, maxB: 100, scale: false };
        this._targetIds = { b: null, k: null };
        this._editorOpen = false;

        this._validationResult = { errors: [], warnings: [] };
        this._valSettings = {
            // Night = sleep time → wake time (sensor attributes, defaults 22:00–07:00)
            nightStart: 1320,
            nightEnd: 420,
            minDailyPeakDuration: 240, // 4 hours
            maxSlopeB: 2.0,            // % per min
            maxSlopeK: 100,            // K per min
        };
        this._presets = HCL_PRESETS;

        this._boundCardKey = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
                e.preventDefault();
                this._undoLast();
            }
        };
    }

    // ------------------------------------------------------------ i18n
    _t(key, params = {}) {
        const table = HCL_STRINGS[this._lang] || HCL_STRINGS.en;
        let text = table[key] ?? HCL_STRINGS.en[key] ?? key;
        Object.entries(params).forEach(([name, value]) => {
            text = text.split(`{${name}}`).join(value);
        });
        return text;
    }

    _applyTexts() {
        if (!this.shadowRoot) return;
        this.shadowRoot.querySelectorAll("[data-i18n]").forEach(el => {
            el.textContent = this._t(el.dataset.i18n);
        });
        this.shadowRoot.querySelectorAll("[data-i18n-title]").forEach(el => {
            el.title = this._t(el.dataset.i18nTitle);
            el.setAttribute("aria-label", el.title);
        });
        this._lastValidationSig = null;
        [this._chartB, this._chartK].forEach(chart => { if (chart) chart.options.locale = this._fmt.language; });
        this._renderAll();
    }

    // ------------------------------------------------------------ configuration
    setConfig(config) {
        if (!config || !config.entity) {
            throw new Error("You need to define an entity (sensor.<name>_curve_data)");
        }
        const entityChanged = this.config && this.config.entity !== config.entity;
        this.config = { view: "full", ...config };
        if (!this.shadowRoot) this.attachShadow({ mode: "open" });
        if (entityChanged) this._resetData();
        if (this._initialized) this._renderAll();
        if (this._hass) this.hass = this._hass;
    }

    _resetData() {
        this._server = { points: null, key: null, ref: null };
        this._points = [];
        this._undo = [];
        this._selected = -1;
        this._isDirty = false;
        this._savedKey = null;
        this._adoptRevision = null;
        this._serverChanged = false;
        this._previewActive = false;
        this._serviceError = null;
        this._inputError = null;
        this._currentMode = null;
        this._dataState = "loading";
        this._targetIds = { b: null, k: null };
    }

    // ------------------------------------------------------------ Home Assistant state
    set hass(hass) {
        this._hass = hass;
        const lang = ((hass.locale && hass.locale.language) || hass.language || "en").split("-")[0];
        const newLang = HCL_STRINGS[lang] ? lang : "en";
        const fmt = new HclFormat(hass);
        const langChanged = newLang !== this._lang || fmt.key() !== this._fmt.key();
        this._lang = newLang;
        this._fmt = fmt;
        const themeKey = JSON.stringify([hass.themes && hass.themes.darkMode, hass.themes && hass.themes.theme, hass.selectedTheme]);
        if (themeKey !== this._themeKey) {
            this._themeKey = themeKey;
            // Theme variables are applied to the DOM after this setter; read them afterwards
            requestAnimationFrame(() => this._applyTheme());
        }
        const timeZone = (hass.config && hass.config.time_zone) || null;
        let visualsChanged = langChanged || timeZone !== this._timeZone;
        this._timeZone = timeZone;
        if (langChanged) this._applyTexts();
        if (!this.config || !this.config.entity) return;

        const stateObj = hass.states[this.config.entity];
        const dataState = this._dataStateOf(stateObj);
        if (dataState !== this._dataState) {
            // The last server curve stays the comparison base while the sensor
            // is missing or unavailable (e.g. during a reload): an unsaved draft
            // is kept and a different curve on return is offered, not adopted.
            this._dataState = dataState;
            visualsChanged = true;
        }

        if (dataState === "ready") {
            const attrs = stateObj.attributes;
            if (this._syncAnchors(attrs)) visualsChanged = true;
            const previewActive = attrs.preview_active === true;
            if (previewActive !== this._previewActive) { this._previewActive = previewActive; visualsChanged = true; }
            if (attrs.scenarios) this._scenarios = { ...HCL_SCENARIO_DEFAULTS, ...attrs.scenarios };
            const limits = {
                minB: attrs.min_brightness !== undefined ? Number(attrs.min_brightness) : 0,
                maxB: attrs.max_brightness !== undefined ? Number(attrs.max_brightness) : 100,
                scale: attrs.brightness_scaling === true,
            };
            if (JSON.stringify(limits) !== JSON.stringify(this._limits)) { this._limits = limits; visualsChanged = true; }
            this._targetIds = { b: attrs.target_brightness_entity_id || null, k: attrs.target_color_temp_entity_id || null };
            if (this._syncMode(hass, attrs)) visualsChanged = true;
            if (this._onServerPoints(attrs.control_points)) visualsChanged = true;
        }
        if (visualsChanged) this._renderAll();
        else this._renderStatus();
    }

    _dataStateOf(stateObj) {
        if (!stateObj) return this._hass && Object.keys(this._hass.states || {}).length ? "missing" : "loading";
        // Old attributes of an unavailable sensor are not current data
        if (["unavailable", "unknown"].includes(stateObj.state)) return "unavailable";
        const attrs = stateObj.attributes || {};
        if (!Array.isArray(attrs.control_points)) return "invalid";
        const points = hclNormalize(attrs.control_points);
        return points && points.length >= 2 ? "ready" : "invalid";
    }

    // Mirrors the mode select (the mode can also change via automations or restarts)
    _syncMode(hass, attrs) {
        const modeId = attrs.mode_entity_id;
        const modeState = modeId ? hass.states[modeId] : null;
        const mode = modeState ? modeState.state : null;
        if (mode === this._currentMode) return false;
        this._currentMode = mode;
        return true;
    }

    // Night window of the validation from the anchor times (sleep → wake)
    _syncAnchors(attrs) {
        const toMin = (v) => {
            const m = /^(\d{1,2}):(\d{2})/.exec(String(v || ""));
            return m ? (Number(m[1]) % 24) * 60 + Number(m[2]) : null;
        };
        const start = toMin(attrs.sleep_time);
        const end = toMin(attrs.wake_time);
        if (start === null || end === null || start === end) return false;
        if (start === this._valSettings.nightStart && end === this._valSettings.nightEnd) return false;
        this._valSettings.nightStart = start;
        this._valSettings.nightEnd = end;
        this._lastValidationSig = null;
        return true;
    }

    // A new curve from the sensor. Returns true if the draft was replaced.
    _onServerPoints(raw) {
        // Never replace points under the finger; the next update is processed
        if (this._drag || raw === this._server.ref) return false;
        const points = hclNormalize(raw);
        const key = hclKey(points);
        this._server.ref = raw;
        if (key === this._server.key) return false;
        const previousKey = this._server.key;
        this._server.points = points;
        this._server.key = key;
        const draftKey = hclKey(this._points);
        if (this._savedKey === key) this._savedKey = null;

        const adoptAfterRevert = this._adoptRevision !== null && this._adoptRevision === this._revision;
        const clean = !this._points.length || (previousKey === null ? !this._undo.length : draftKey === previousKey);
        if (adoptAfterRevert || clean) {
            this._adoptRevision = null;
            this._adopt(points, adoptAfterRevert);
            return true;
        }
        const ownAction = this._pending && this._pending.key === key;
        if (draftKey !== key && !ownAction) this._serverChanged = true;
        this._recomputeDirty();
        return false;
    }

    _adopt(points, keepUndo = false) {
        if (!keepUndo) this._undo = [];
        this._points = points.map(p => ({ ...p }));
        this._selected = -1;
        this._serverChanged = false;
        this._recomputeDirty();
        this._afterEdit(true);
    }

    _recomputeDirty() {
        const key = hclKey(this._points);
        this._isDirty = this._server.key !== null && key !== this._server.key && key !== this._savedKey;
    }

    // ------------------------------------------------------------ lifecycle
    // Dashboards may detach and re-attach a card while it is loading (masonry
    // moves cards into columns). What counts is whether the card is attached
    // when Chart.js has loaded; a detached card initialises on its next attach.
    async connectedCallback() {
        if (!this.shadowRoot) this.attachShadow({ mode: "open" });
        if (this._releaseTimer) { clearTimeout(this._releaseTimer); this._releaseTimer = null; }
        this.addEventListener("keydown", this._boundCardKey);
        if (this._initialized) {
            this._startTimers();
            this._renderAll();
            return;
        }
        if (this._initPromise) return;
        this._initPromise = (async () => {
            let ChartCtor;
            try {
                ChartCtor = await hclLoadChart();
            } catch (e) {
                if (!this.isConnected) return;
                this.shadowRoot.innerHTML = `<ha-card style="padding:16px; color:var(--error-color, #db4437);"></ha-card>`;
                this.shadowRoot.querySelector("ha-card").textContent = this._t("chart_error", { msg: e.message });
                return;
            }
            // The card may have been removed while Chart.js was loading
            if (!this.isConnected) return;
            this._Chart = ChartCtor;
            this.render();
            this._initCharts();
            this._bindEvents();
            this._initialized = true;
            this._applyTexts();
            this._applyTheme();
            this._startTimers();
            this._renderAll();
        })().finally(() => { this._initPromise = null; });
    }

    disconnectedCallback() {
        this._endDrag(false);
        this.removeEventListener("keydown", this._boundCardKey);
        if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
        if (this._nowTimer) { clearInterval(this._nowTimer); this._nowTimer = null; }
        if (this._rafHandle) { cancelAnimationFrame(this._rafHandle); this._rafHandle = null; }
        // A card that stays removed releases its charts (Chart.js keeps every
        // instance registered until destroy()). Dashboards also detach cards
        // for a moment when they move them; those keep their charts.
        if (this._releaseTimer) clearTimeout(this._releaseTimer);
        this._releaseTimer = setTimeout(() => {
            this._releaseTimer = null;
            if (!this.isConnected) this._releaseCharts();
        }, HCL_RELEASE_DELAY);
    }

    // The draft, undo and server state stay; the next attach rebuilds the view
    _releaseCharts() {
        if (this._chartB) { this._chartB.destroy(); this._chartB = null; }
        if (this._chartK) { this._chartK.destroy(); this._chartK = null; }
        this._initialized = false;
        this._lastValidationSig = null;
    }

    _startTimers() {
        if (!this._resizeObserver) {
            this._resizeObserver = new ResizeObserver((entries) => {
                if (!entries.length || entries[0].contentRect.width === 0) return;
                if (this._rafHandle) cancelAnimationFrame(this._rafHandle);
                this._rafHandle = requestAnimationFrame(() => {
                    this._rafHandle = null;
                    if (this._initialized && !this._drag) {
                        if (this._chartB) this._chartB.resize();
                        if (this._chartK) this._chartK.resize();
                        this._updateVisuals();
                    }
                });
            });
            const container = this.shadowRoot.querySelector(".charts");
            if (container) this._resizeObserver.observe(container);
        }
        // The "now" marker moves once per minute
        if (!this._nowTimer) this._nowTimer = setInterval(() => this._updateVisuals(), 60000);
    }

    // ------------------------------------------------------------ static DOM
    render() {
        const chips = HCL_MODES.map(([mode, icon]) =>
            `<button class="chip" data-mode="${mode}" aria-pressed="false"><ha-icon icon="${icon}" aria-hidden="true"></ha-icon><span data-i18n="mode_${mode}"></span></button>`
        ).join("");
        const presets = HCL_PRESET_ORDER.map(name =>
            `<option value="${name}" data-i18n="preset_${name}"></option>`).join("");

        this.shadowRoot.innerHTML = `
      <style>
          :host {
              display: block;
              container-type: inline-size;
              /* Colours come from the Home Assistant theme */
              --hcl-b-color: var(--amber-color, #ffb300);
              --hcl-k-color: var(--cyan-color, #00acc1);
              --hcl-text: var(--primary-text-color, #212121);
              --hcl-text-2: var(--secondary-text-color, #727272);
              --hcl-divider: var(--divider-color, rgba(127, 127, 127, 0.25));
              --hcl-surface: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
              --hcl-accent: var(--primary-color, #03a9f4);
              --hcl-warning: var(--warning-color, #ffa600);
              --hcl-error: var(--error-color, #db4437);
          }
          ha-card { overflow: hidden; color: var(--hcl-text); padding-bottom: 12px; position: relative; }
          .card-header {
              padding: 16px 16px 8px 16px;
              display: flex; justify-content: space-between; align-items: center;
              flex-wrap: wrap; gap: 8px;
          }
          .title { font-weight: 500; font-size: 1rem; }
          .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
          button, select, input {
              font: inherit; font-size: 0.8125rem; color: var(--hcl-text);
              background: var(--hcl-surface);
              border: 1px solid var(--hcl-divider); border-radius: 16px;
              padding: 6px 12px; min-height: 32px; box-sizing: border-box;
          }
          button { cursor: pointer; }
          button:hover:not(:disabled) { border-color: var(--hcl-accent); }
          button:disabled, input:disabled { opacity: 0.45; cursor: default; }
          :focus-visible { outline: 2px solid var(--hcl-accent); outline-offset: 2px; }
          /* Accent only as border: text keeps the theme text colour (contrast) */
          button.primary { border: 2px solid var(--hcl-accent); font-weight: 600; }
          button.dirty { border-color: var(--hcl-warning); border-width: 2px; }
          button.icon { padding: 4px 10px; min-width: 36px; }
          select option { background: var(--card-background-color, #fff); color: var(--hcl-text); }
          .messages { margin: 0 16px 8px 16px; display: flex; flex-direction: column; gap: 4px; }
          .messages:empty { display: none; }
          .msg {
              border-left: 4px solid var(--hcl-warning);
              background: var(--hcl-surface);
              padding: 6px 8px; font-size: 0.8125rem; border-radius: 4px;
              display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
          }
          .msg.error { border-left-color: var(--hcl-error); }
          .msg.info { border-left-color: var(--hcl-accent); }
          .mode-selector { padding: 0 16px 12px 16px; display: flex; gap: 6px; flex-wrap: wrap; }
          .chip { display: flex; align-items: center; gap: 4px; }
          .chip ha-icon { --mdc-icon-size: 16px; }
          .chip.active {
              border: 2px solid var(--hcl-accent);
              background: var(--hcl-surface);
              background: color-mix(in srgb, var(--hcl-accent) 18%, transparent);
              font-weight: 600;
          }
          .chip.pending { border-style: dashed; border-color: var(--hcl-accent); }
          #now-info { padding: 0 16px 8px 16px; font-size: 0.875rem; }
          #draft-info { padding: 0 16px 8px 16px; font-size: 0.75rem; color: var(--hcl-text-2); }
          #draft-info:empty, #now-info:empty { display: none; }
          .toggle-row { padding: 0 16px 8px 16px; }
          .editor-section[hidden] { display: none; }
          .charts {
              padding: 0 16px; display: grid; gap: 12px;
              grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
          }
          .chart-wrapper {
              position: relative; height: 230px; min-width: 0;
              background: var(--hcl-surface); border-radius: 12px; padding: 12px;
          }
          .chart-label {
              position: absolute; top: 10px; left: 16px;
              font-size: 0.6875rem; color: var(--hcl-text);
              text-transform: uppercase; letter-spacing: 0.5px;
              pointer-events: none; z-index: 5;
          }
          canvas { width: 100%; height: 100%; display: block; }
          .handle-layer {
              position: absolute; top: 12px; left: 12px; right: 12px; bottom: 12px;
              pointer-events: none; overflow: visible;
          }
          .handle {
              position: absolute; width: 12px; height: 12px; border-radius: 50%;
              margin-left: -6px; margin-top: -6px; cursor: grab;
              pointer-events: auto; z-index: 10; touch-action: none;
              border: 2px solid var(--card-background-color, #fff); box-sizing: border-box;
          }
          .handle::after { content: ''; position: absolute; inset: -10px; }
          .handle:active { cursor: grabbing; }
          .handle.type-b { background: var(--hcl-b-color); }
          .handle.type-k { background: var(--hcl-k-color); }
          .handle.selected, .handle:focus-visible { outline: 2px solid var(--hcl-text); outline-offset: 2px; }
          .handle-info {
              position: absolute; bottom: 18px; left: 50%; transform: translateX(-50%);
              background: var(--card-background-color, #fff); color: var(--hcl-text);
              border: 1px solid var(--hcl-divider); padding: 3px 6px; border-radius: 6px;
              font-size: 0.6875rem; font-family: monospace; white-space: nowrap;
              opacity: 0; pointer-events: none; transition: opacity 0.2s; z-index: 100;
          }
          .handle:hover .handle-info, .handle:active .handle-info, .handle:focus .handle-info { opacity: 1; }
          @media (prefers-reduced-motion: reduce) { .handle-info { transition: none; } }
          .point-editor {
              display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
              padding: 12px 16px 0 16px; font-size: 0.8125rem; color: var(--hcl-text-2);
          }
          .point-editor label { display: flex; gap: 4px; align-items: center; }
          .point-editor input { width: 5.5em; border-radius: 8px; }
          .point-editor input[type=time] { width: 7.5em; }
          .point-editor input[aria-invalid=true] { border-color: var(--hcl-error); border-width: 2px; }
          .point-editor .hint { flex: 1 1 auto; }
          .actions { padding: 12px 16px 0 16px; justify-content: flex-end; }
          .footer-section { margin-top: 12px; padding: 0 16px; }
          .color-caption { font-size: 0.6875rem; color: var(--hcl-text-2); margin-bottom: 2px; }
          .color-bar { height: 8px; border-radius: 4px; width: 100%; border: 1px solid var(--hcl-divider); }
          .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
          @container (max-width: 360px) {
              .card-header, .messages, .mode-selector, .charts, .point-editor, .actions, .footer-section, #now-info, #draft-info, .toggle-row {
                  padding-left: 8px; padding-right: 8px; margin-left: 0; margin-right: 0;
              }
              .chart-wrapper { padding: 8px; height: 200px; }
              .handle-layer { top: 8px; left: 8px; right: 8px; bottom: 8px; }
          }
      </style>
      <ha-card>
          <div class="card-header">
              <span class="title" data-i18n="title"></span>
          </div>
          <div id="status" class="messages" role="status" aria-live="polite"></div>
          <div class="mode-selector" id="mode-chips" role="group">${chips}</div>
          <div id="now-info"></div>
          <div class="toggle-row"><button id="btn-toggle-editor" aria-expanded="false"></button></div>
          <div class="editor-section" id="editor-section">
              <div class="row actions">
                  <select id="preset-select" data-i18n-title="presets">
                      <option value="" disabled selected data-i18n="presets"></option>
                      ${presets}
                  </select>
                  <button id="btn-revert" data-i18n="revert" data-i18n-title="revert_title"></button>
                  <button id="btn-test" data-i18n-title="preview_title"></button>
                  <button id="btn-save" class="primary" data-i18n="save" data-i18n-title="save_title"></button>
              </div>
              <div id="validation-area" class="messages"></div>
              <div id="draft-info"></div>
              <div class="charts">
                  <div class="chart-wrapper">
                      <span class="chart-label" data-i18n="brightness" aria-hidden="true"></span>
                      <canvas id="chartB" role="img"></canvas>
                      <div class="handle-layer" id="handles-b"></div>
                  </div>
                  <div class="chart-wrapper">
                      <span class="chart-label" data-i18n="color_temp" aria-hidden="true"></span>
                      <canvas id="chartK" role="img"></canvas>
                      <div class="handle-layer" id="handles-k"></div>
                  </div>
              </div>
              <span id="handle-help" class="sr-only" data-i18n="handle_help"></span>
              <div class="point-editor">
                  <button id="btn-add" class="icon" data-i18n-title="add_title">+</button>
                  <button id="btn-delete" class="icon" data-i18n-title="delete_title">−</button>
                  <button id="btn-undo" class="icon" data-i18n-title="undo_title">↶</button>
                  <label><span data-i18n="time"></span><input id="in-t" type="time" step="900"></label>
                  <label><span data-i18n="brightness"></span><input id="in-b" type="number" min="0" max="100" step="1" inputmode="numeric">%</label>
                  <label><span data-i18n="color_temp"></span><input id="in-k" type="number" min="2000" max="7000" step="50" inputmode="numeric">K</label>
                  <span class="hint" id="editor-hint" data-i18n="no_selection"></span>
              </div>
              <div class="footer-section" aria-hidden="true">
                  <div class="color-caption" data-i18n="color_bar"></div>
                  <div class="color-bar" id="color-bar-gradient"></div>
              </div>
          </div>
      </ha-card>
    `;
    }

    _bindEvents() {
        const $ = (id) => this.shadowRoot.getElementById(id);
        $("btn-save").addEventListener("click", () => this._saveCurve());
        $("btn-test").addEventListener("click", () => this._testCurve());
        $("btn-revert").addEventListener("click", () => this._revertCurve());
        $("btn-undo").addEventListener("click", () => this._undoLast());
        $("btn-add").addEventListener("click", () => this._addPoint());
        $("btn-delete").addEventListener("click", () => this._deletePoint(this._selected));
        $("btn-toggle-editor").addEventListener("click", () => this._toggleEditor());
        $("preset-select").addEventListener("change", (e) => {
            this._applyPreset(e.target.value);
            e.target.value = "";
        });
        ["in-t", "in-b", "in-k"].forEach(id => $(id).addEventListener("change", () => this._applyNumeric()));
        $("chartB").addEventListener("dblclick", (e) => this._onChartDblClick(e));
        $("chartK").addEventListener("dblclick", (e) => this._onChartDblClick(e));
        this.shadowRoot.querySelectorAll(".chip").forEach(chip => {
            chip.addEventListener("click", () => this._setMode(chip.dataset.mode));
        });
    }

    _toggleEditor() {
        this._editorOpen = !this._editorOpen;
        this._renderLayout();
        if (this._editorOpen) requestAnimationFrame(() => this._refreshCharts());
    }

    // ------------------------------------------------------------ theme
    _readTheme() {
        const style = getComputedStyle(this);
        const v = (name, fallback) => (style.getPropertyValue(name) || "").trim() || fallback;
        return {
            b: v("--hcl-b-color", "#ffb300"),
            k: v("--hcl-k-color", "#00acc1"),
            // axis labels on the chart surface: primary text colour (contrast)
            text: v("--hcl-text", "#212121"),
            grid: v("--hcl-divider", "rgba(127,127,127,0.25)"),
            accent: v("--hcl-accent", "#03a9f4"),
            warning: v("--hcl-warning", "#ffa600"),
        };
    }

    _withAlpha(color, alpha) {
        const probe = document.createElement("canvas").getContext("2d");
        probe.fillStyle = "#000";
        probe.fillStyle = color;
        const c = probe.fillStyle;
        if (c.startsWith("#") && c.length === 7) {
            const n = parseInt(c.slice(1), 16);
            return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
        }
        return c.replace(/rgba?\(([^)]+)\)/, (m, inner) => {
            const parts = inner.split(",").slice(0, 3).map(s => s.trim());
            return `rgba(${parts.join(", ")}, ${alpha})`;
        });
    }

    _applyTheme() {
        if (!this._chartB || !this._chartK || !this.isConnected) return;
        const th = this._readTheme();
        this._theme = th;
        [[this._chartB, th.b], [this._chartK, th.k]].forEach(([chart, color]) => {
            chart.options.scales.y.grid.color = th.grid;
            chart.options.scales.y.ticks.color = th.text;
            chart.options.scales.x.ticks.color = th.text;
            chart.data.datasets[0].borderColor = color;
            chart.data.datasets[0].backgroundColor = this._withAlpha(color, 0.12);
        });
        this._chartB.data.datasets[1].borderColor = th.b;
        this._chartB.update("none");
        this._chartK.update("none");
    }

    // ------------------------------------------------------------ charts
    _initCharts() {
        const th = this._readTheme();
        this._theme = th;
        const axisY = (min, max) => ({
            min, max, display: true, position: "right",
            grid: { color: th.grid },
            ticks: { color: th.text, font: { size: 10 } },
        });
        // Each chart has its own time axis (00:00 … 24:00)
        const axisX = () => ({
            type: "linear", min: 0, max: HCL_DAY, display: true,
            grid: { display: false },
            ticks: {
                stepSize: 360, autoSkip: false, maxRotation: 0, color: th.text, font: { size: 10 },
                callback: (value) => (value % 360 === 0 ? this._fmt.time(value) : ""),
            },
        });
        const commonOpts = {
            responsive: true, maintainAspectRatio: false, animation: false,
            layout: { padding: 0 },
            plugins: { legend: false, tooltip: false },
            elements: { point: { radius: 0, hoverRadius: 0 }, line: { borderWidth: 2 } },
        };
        const bandPlugin = {
            id: "hclBands",
            beforeDraw: (chart) => {
                const ctx = chart.ctx;
                const yAxis = chart.scales.y;
                const xAxis = chart.scales.x;
                if (!xAxis || !yAxis) return;
                if (chart.canvas.id === "chartB") {
                    const { minB, maxB } = this._limits;
                    ctx.fillStyle = "rgba(127, 127, 127, 0.18)";
                    if (maxB < 100) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(100), xAxis.width, yAxis.getPixelForValue(maxB) - yAxis.getPixelForValue(100));
                    if (minB > 0) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(minB), xAxis.width, yAxis.getPixelForValue(0) - yAxis.getPixelForValue(minB));
                }
                this._getValidationAnnotations(chart.canvas.id === "chartB" ? "b" : "k").forEach(anno => {
                    ctx.fillStyle = anno.color;
                    const xStart = xAxis.getPixelForValue(anno.xMin);
                    const xEnd = xAxis.getPixelForValue(anno.xMax);
                    if (anno.xMin > anno.xMax) {
                        ctx.fillRect(xStart, yAxis.top, xAxis.right - xStart, yAxis.bottom - yAxis.top);
                        ctx.fillRect(xAxis.left, yAxis.top, xAxis.getPixelForValue(anno.xMax) - xAxis.left, yAxis.bottom - yAxis.top);
                    } else {
                        ctx.fillRect(xStart, yAxis.top, xEnd - xStart, yAxis.bottom - yAxis.top);
                    }
                });
            },
            // Current time and the fixed value of the active scenario
            afterDatasetsDraw: (chart) => {
                this._drawNowLine(chart);
                const scenario = this._scenarios[this._currentMode];
                if (!scenario) return;
                const isB = chart.canvas.id === "chartB";
                const value = isB ? scenario.b : scenario.k;
                if (value === null || value === undefined) return;
                this._drawOverrideLine(chart, value, isB ? this._theme.b : this._theme.k);
            },
        };
        const Chart = this._Chart;
        this._chartB = new Chart(this.shadowRoot.getElementById("chartB").getContext("2d"), {
            type: "line",
            data: { datasets: [
                { data: [], borderColor: th.b, fill: true, backgroundColor: this._withAlpha(th.b, 0.12) },
                // Brightness the lights get (min/max, scaling), shown only when it differs
                { data: [], borderColor: th.b, borderDash: [4, 4], borderWidth: 1.5, fill: false },
            ] },
            options: { ...commonOpts, scales: { x: axisX(), y: axisY(0, 100) } },
            plugins: [bandPlugin],
        });
        this._chartK = new Chart(this.shadowRoot.getElementById("chartK").getContext("2d"), {
            type: "line",
            data: { datasets: [{ data: [], borderColor: th.k, fill: true, backgroundColor: this._withAlpha(th.k, 0.12) }] },
            options: { ...commonOpts, scales: { x: axisX(), y: axisY(2000, 7000) } },
            plugins: [bandPlugin],
        });
    }

    _drawOverrideLine(chart, value, color) {
        if (!chart) return;
        const ctx = chart.ctx;
        const yPixel = chart.scales.y.getPixelForValue(value);
        const xAxis = chart.scales.x;
        ctx.save();
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        ctx.moveTo(xAxis.left, yPixel);
        ctx.lineTo(xAxis.right, yPixel);
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.font = "bold 10px sans-serif";
        ctx.fillText(this._t(`mode_${this._currentMode}`).toUpperCase(), xAxis.left + 5, yPixel - 5);
        ctx.restore();
    }

    _drawNowLine(chart) {
        const xAxis = chart.scales.x;
        const yAxis = chart.scales.y;
        if (!xAxis || !yAxis) return;
        const x = xAxis.getPixelForValue(this._nowMinutes());
        const ctx = chart.ctx;
        ctx.save();
        ctx.beginPath();
        ctx.strokeStyle = this._theme ? this._theme.accent : "#03a9f4";
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.moveTo(x, yAxis.top);
        ctx.lineTo(x, yAxis.bottom);
        ctx.stroke();
        ctx.restore();
    }

    // Current time of day in the Home Assistant time zone (the integration steers
    // the lights in this zone); falls back to the browser time zone
    _nowMinutes(date = new Date()) {
        if (this._timeZone) {
            try {
                const parts = new Intl.DateTimeFormat("en-US", {
                    timeZone: this._timeZone, hour: "numeric", minute: "numeric", hourCycle: "h23",
                }).formatToParts(date);
                const get = (type) => Number(parts.find(p => p.type === type).value);
                return (get("hour") % 24) * 60 + get("minute");
            } catch (err) {
                // unknown time zone: use the browser time
            }
        }
        return date.getHours() * 60 + date.getMinutes();
    }

    // ------------------------------------------------------------ rendering
    _renderAll() {
        if (!this._initialized) return;
        this._renderLayout();
        this._renderChips();
        this._refreshCharts();
        this._renderStatus();
    }

    _renderLayout() {
        const $ = (id) => this.shadowRoot.getElementById(id);
        const ready = this._dataState === "ready";
        const compact = this.config && this.config.view === "compact";
        const showEditor = ready && (!compact || this._editorOpen);
        $("editor-section").hidden = !showEditor;
        const toggle = $("btn-toggle-editor");
        toggle.parentElement.hidden = !(ready && compact);
        toggle.textContent = this._t(this._editorOpen ? "close_editor" : "edit_curve");
        toggle.setAttribute("aria-expanded", String(showEditor));
        $("mode-chips").hidden = !ready;
    }

    _renderChips() {
        if (!this.shadowRoot) return;
        this.shadowRoot.querySelectorAll(".chip").forEach(chip => {
            const active = chip.dataset.mode === this._currentMode;
            const pending = chip.dataset.mode === this._pendingMode;
            chip.classList.toggle("active", active);
            chip.classList.toggle("pending", pending);
            chip.setAttribute("aria-pressed", String(active));
            chip.setAttribute("aria-busy", String(pending));
        });
    }

    _refreshCharts() {
        if (!this._chartB) return;
        if (this._chartB.canvas.clientWidth > 0 && this._chartB.width !== this._chartB.canvas.clientWidth) this._chartB.resize();
        if (this._chartK.canvas.clientWidth > 0 && this._chartK.width !== this._chartK.canvas.clientWidth) this._chartK.resize();
        this._rebuildHandles();
        this._updateVisuals();
    }

    _updateVisuals(retryCount = 0) {
        if (!this._chartB || !this._chartK || !this.isConnected) return;
        this._renderNowInfo();
        if (this._dataState !== "ready" || !this._points.length) {
            this._chartB.data.datasets.forEach(d => { d.data = []; });
            this._chartK.data.datasets[0].data = [];
            this._chartB.update("none");
            this._chartK.update("none");
            return;
        }
        // Skip while the editor is hidden (no layout)
        if (this._chartB.canvas.clientWidth === 0) return;

        const data = this._calculateCurve();
        const effective = data.b.map(b => hclEffectiveB(b, this._limits));
        const limited = effective.some((b, i) => Math.abs(b - data.b[i]) > 0.5);
        this._chartB.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.b[i] }));
        this._chartB.data.datasets[1].data = limited ? data.t.map((t, i) => ({ x: t, y: effective[i] })) : [];
        this._chartK.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.k[i] }));

        this._runValidation(data);
        this._updateValidationUI();
        this._describeCharts(data);
        this._chartB.update("none");
        this._chartK.update("none");

        const xAxis = this._chartB.scales.x;
        if (!xAxis || xAxis.width <= 0 || xAxis.getPixelForValue(0) === undefined) {
            if (retryCount < 50) requestAnimationFrame(() => this._updateVisuals(retryCount + 1));
            return;
        }
        this._points.forEach((pt, idx) => {
            this._syncHandle(idx, pt, "b", this._chartB);
            this._syncHandle(idx, pt, "k", this._chartK);
        });
        this._updateColorBar(data);
    }

    // "Now": the value HCL is aiming for (setpoint sensors), not the draft
    _renderNowInfo() {
        const $ = (id) => this.shadowRoot && this.shadowRoot.getElementById(id);
        const el = $("now-info");
        const draftEl = $("draft-info");
        if (!el) return;
        if (this._dataState !== "ready" || !this._points.length) {
            el.textContent = "";
            if (draftEl) draftEl.textContent = "";
            return;
        }
        const now = this._nowMinutes();
        const f = this._fmt;
        const mode = this._currentMode;
        const modeText = mode ? this._t(`mode_${mode}`) : null;
        const parts = [`${this._t("now")} ${f.clock(now)}`];
        if (modeText) parts.push(modeText);
        const states = (this._hass && this._hass.states) || {};
        const bState = this._targetIds.b ? states[this._targetIds.b] : undefined;
        const kState = this._targetIds.k ? states[this._targetIds.k] : undefined;
        const valid = (st) => !!st && st.state !== "" && Number.isFinite(Number(st.state));
        if (mode === "guest") {
            parts.push(this._t("guest_now"));
        } else if (mode === "sleep") {
            parts.push(this._t("sleep_now"));
        } else if (valid(bState) && valid(kState)) {
            parts.push(f.percent(Number(bState.state)), f.kelvin(Number(kState.state)));
        } else if (bState || kState) {
            // The setpoint sensors exist but have no current value: no substitute
            parts.push(this._t("setpoint_unavailable"));
        } else {
            // No setpoint sensors (disabled, or an older integration): computed
            // from the active scenario or the saved curve, like the integration
            const fixed = mode && mode !== "auto" ? this._scenarios[mode] : null;
            if (fixed && Number.isFinite(Number(fixed.b)) && Number.isFinite(Number(fixed.k))) {
                parts.push(f.percent(Number(fixed.b)), f.kelvin(Number(fixed.k)));
            } else if (!mode || mode === "auto") {
                const v = hclValueAt(this._server.points || this._points, now);
                parts.push(f.percent(hclEffectiveB(v.b, this._limits)), f.kelvin(v.k));
            } else {
                parts.push(this._t("setpoint_unavailable"));
            }
        }
        el.textContent = parts.join(" · ");
        if (draftEl) {
            if (this._isDirty) {
                const v = hclValueAt(this._points, now);
                draftEl.textContent = `${this._t("draft")} ${f.clock(now)}: ${f.percent(hclEffectiveB(v.b, this._limits))} · ${f.kelvin(v.k)}`;
            } else {
                draftEl.textContent = "";
            }
        }
    }

    _describeCharts(data) {
        const f = this._fmt;
        const describe = (values, key, fmtValue) => {
            let min = 0, max = 0;
            values.forEach((v, i) => { if (v < values[min]) min = i; if (v > values[max]) max = i; });
            return this._t(key, {
                min: fmtValue(values[min]), tmin: f.clock(data.t[min]),
                max: fmtValue(values[max]), tmax: f.clock(data.t[max]),
            });
        };
        const cb = this.shadowRoot.getElementById("chartB");
        const ck = this.shadowRoot.getElementById("chartK");
        if (cb) cb.setAttribute("aria-label", describe(data.b.map(b => hclEffectiveB(b, this._limits)), "chart_b_desc", v => f.percent(v)));
        if (ck) ck.setAttribute("aria-label", describe(data.k, "chart_k_desc", v => f.kelvin(v)));
    }

    _updateColorBar(data) {
        const bar = this.shadowRoot.getElementById("color-bar-gradient");
        if (!bar) return;
        const stops = [];
        for (let i = 0; i <= 96; i += 8) {
            stops.push(`${this._kelvinToRgb(data.k[i])} ${((i / 96) * 100).toFixed(1)}%`);
        }
        bar.style.background = `linear-gradient(90deg, ${stops.join(", ")})`;
    }

    _kelvinToRgb(k) {
        const temp = k / 100;
        let r, g, b;
        if (temp <= 66) {
            r = 255;
            g = 99.4708025861 * Math.log(temp) - 161.1195681661;
            b = temp <= 19 ? 0 : 138.5177312231 * Math.log(temp - 10) - 305.0447927307;
        } else {
            r = 329.698727446 * Math.pow(temp - 60, -0.1332047592);
            g = 288.1221695283 * Math.pow(temp - 60, -0.0755148492);
            b = 255;
        }
        const c = (x) => Math.min(255, Math.max(0, x));
        return `rgb(${c(r)}, ${c(g)}, ${c(b)})`;
    }

    _calculateCurve() {
        return hclSamples(this._points);
    }

    _calculateCurveAt(t) {
        return hclValueAt(this._points, t);
    }

    // ------------------------------------------------------------ status messages
    _renderStatus() {
        if (!this.shadowRoot) return;
        const status = this.shadowRoot.getElementById("status");
        if (!status) return;
        const entity = this.config ? this.config.entity : "";
        const messages = [];
        if (this._dataState !== "ready") {
            messages.push({ cls: this._dataState === "loading" ? "info" : "error", text: this._t(`data_${this._dataState}`, { entity }) });
        } else {
            if (this._serviceError) messages.push({ cls: "error", text: this._serviceError });
            if (this._inputError) messages.push({ cls: "error", text: this._inputError });
            if (this._serverChanged) messages.push({ cls: "warning", text: this._t("server_changed"), action: "adopt" });
            if (this._previewActive) messages.push({ cls: "info", text: this._t("preview_active") });
            if (this._currentMode && this._currentMode !== "auto") {
                messages.push({ cls: "info", text: this._t("curve_applies_auto", { mode: this._t(`mode_${this._currentMode}`) }) });
            }
        }
        const sig = JSON.stringify(messages) + this._lang;
        if (sig !== this._statusSig) {
            this._statusSig = sig;
            status.innerHTML = "";
            messages.forEach(m => {
                const div = document.createElement("div");
                div.className = `msg ${m.cls}`;
                const span = document.createElement("span");
                span.textContent = m.text;
                div.appendChild(span);
                if (m.action === "adopt") {
                    const btn = document.createElement("button");
                    btn.id = "btn-adopt";
                    btn.textContent = this._t("adopt_server");
                    btn.addEventListener("click", () => this._adoptServer());
                    div.appendChild(btn);
                }
                status.appendChild(div);
            });
            status.classList.toggle("error", messages.some(m => m.cls === "error"));
        }
        this._updateUIState();
    }

    _updateUIState() {
        if (!this.shadowRoot) return;
        const $ = (id) => this.shadowRoot.getElementById(id);
        const busy = !!this._pending;
        const btnTest = $("btn-test");
        if (btnTest) {
            btnTest.classList.toggle("dirty", this._isDirty);
            btnTest.textContent = this._t("preview") + (this._isDirty ? " *" : "");
            btnTest.disabled = busy;
        }
        const btnSave = $("btn-save");
        if (btnSave) {
            // Save stays highlighted while the lights follow an unsaved preview
            btnSave.classList.toggle("dirty", this._isDirty || this._previewActive);
            btnSave.disabled = busy || this._validationResult.errors.length > 0;
        }
        const btnRevert = $("btn-revert");
        if (btnRevert) btnRevert.disabled = busy;
        const btnUndo = $("btn-undo");
        if (btnUndo) btnUndo.disabled = this._undo.length === 0;
        this._renderNowInfo();
    }

    // ------------------------------------------------------------ handles
    _rebuildHandles() {
        // Keep keyboard focus across the rebuild
        let focusedType = null;
        let focusedIdx = -1;
        const activeEl = this.shadowRoot.activeElement;
        if (activeEl && activeEl.classList && activeEl.classList.contains("handle")) {
            focusedType = activeEl.classList.contains("type-b") ? "b" : "k";
            focusedIdx = parseInt(activeEl.dataset.idx, 10);
        }
        ["b", "k"].forEach(type => {
            const container = this.shadowRoot.getElementById(`handles-${type}`);
            if (!container) return;
            container.innerHTML = "";
            if (this._dataState !== "ready") return;
            this._points.forEach((pt, idx) => {
                const el = document.createElement("div");
                el.className = `handle type-${type}` + (idx === this._selected ? " selected" : "");
                el.dataset.idx = idx;
                const tooltip = document.createElement("div");
                tooltip.className = "handle-info";
                tooltip.setAttribute("aria-hidden", "true");
                el.appendChild(tooltip);
                el.setAttribute("role", "slider");
                el.setAttribute("tabindex", "0");
                el.setAttribute("aria-label", this._t(type === "b" ? "point_b" : "point_k", { n: idx + 1 }));
                el.setAttribute("aria-valuemin", type === "b" ? "0" : "2000");
                el.setAttribute("aria-valuemax", type === "b" ? "100" : "7000");
                el.setAttribute("aria-describedby", "handle-help");
                el.addEventListener("pointerdown", (e) => this._onDragStart(e, idx, type, el));
                el.addEventListener("keydown", (e) => this._onKeyDown(e, idx, type));
                el.addEventListener("focus", () => this._select(idx, false));
                container.appendChild(el);
            });
        });
        if (focusedType !== null && focusedIdx !== -1) {
            requestAnimationFrame(() => {
                const el = this.shadowRoot.querySelector(`#handles-${focusedType} .handle[data-idx="${focusedIdx}"]`);
                if (el) el.focus();
            });
        }
    }

    _syncHandle(idx, pt, type, chart) {
        const el = this.shadowRoot.querySelector(`#handles-${type} .handle[data-idx="${idx}"]`);
        if (!el) return;
        const x = chart.scales.x.getPixelForValue(pt.t);
        const yVal = type === "b" ? pt.b : pt.k;
        const y = chart.scales.y.getPixelForValue(yVal);
        el.style.transform = `translate(${x}px, ${y}px)`;
        const f = this._fmt;
        const valText = type === "b" ? f.percent(pt.b) : f.kelvin(pt.k);
        el.setAttribute("aria-valuenow", String(Math.round(yVal)));
        el.setAttribute("aria-valuetext", `${f.clock(pt.t)}, ${valText}`);
        const tooltip = el.querySelector(".handle-info");
        if (tooltip) tooltip.textContent = `${f.clock(pt.t)} | ${valText}`;
    }

    // ------------------------------------------------------------ editing
    _pushUndo() {
        this._undo.push(JSON.stringify(this._points));
        if (this._undo.length > HCL_UNDO_LIMIT) this._undo.shift();
    }

    _undoLast() {
        if (!this._undo.length) return;
        this._points = JSON.parse(this._undo.pop());
        if (this._selected >= this._points.length) this._selected = -1;
        this._revision += 1;
        this._recomputeDirty();
        this._afterEdit(true);
    }

    _afterEdit(rebuild) {
        if (!this._initialized) return;
        if (rebuild) this._rebuildHandles();
        this._updateVisuals();
        this._updateEditor();
        this._renderStatus();
    }

    _markChanged(rebuild = false) {
        this._revision += 1;
        this._inputError = null;
        this._recomputeDirty();
        this._afterEdit(rebuild);
    }

    // Neighbour limits keep the points in chronological order (15-min grid)
    _timeBounds(idx) {
        const prev = idx > 0 ? this._points[idx - 1] : null;
        const next = idx < this._points.length - 1 ? this._points[idx + 1] : null;
        return {
            minT: prev ? prev.t + HCL_STEP : 0,
            maxT: next ? next.t - HCL_STEP : HCL_DAY - HCL_STEP,
        };
    }

    _select(idx, rebuild = true) {
        this._selected = idx;
        this.shadowRoot.querySelectorAll(".handle").forEach(el => {
            el.classList.toggle("selected", parseInt(el.dataset.idx, 10) === idx);
        });
        this._updateEditor();
        if (rebuild) this._updateVisuals();
    }

    _updateEditor() {
        if (!this.shadowRoot) return;
        const $ = (id) => this.shadowRoot.getElementById(id);
        const pt = this._points[this._selected];
        const has = !!pt;
        ["in-t", "in-b", "in-k"].forEach(id => {
            if (!$(id)) return;
            $(id).disabled = !has;
            $(id).removeAttribute("aria-invalid");
        });
        if ($("btn-delete")) $("btn-delete").disabled = !has || this._points.length <= 2;
        if ($("btn-undo")) $("btn-undo").disabled = this._undo.length === 0;
        if ($("editor-hint")) $("editor-hint").style.display = has ? "none" : "";
        if (has) {
            $("in-t").value = minToTime(pt.t);
            $("in-b").value = Math.round(pt.b);
            $("in-k").value = Math.round(pt.k);
        } else if ($("in-t")) {
            $("in-t").value = ""; $("in-b").value = ""; $("in-k").value = "";
        }
    }

    // Numeric input: invalid or incomplete values change nothing
    _applyNumeric() {
        const idx = this._selected;
        const pt = this._points[idx];
        if (!pt) return;
        const $ = (id) => this.shadowRoot.getElementById(id);
        const timeMatch = /^(\d{1,2}):(\d{2})(:\d{2})?$/.exec(($("in-t").value || "").trim());
        const number = (id) => {
            const raw = ($(id).value || "").trim();
            const value = raw === "" ? NaN : Number(raw);
            return Number.isFinite(value) ? value : null;
        };
        const b = number("in-b");
        const k = number("in-k");
        const invalid = [];
        if (!timeMatch || Number(timeMatch[1]) > 23 || Number(timeMatch[2]) > 59) invalid.push("in-t");
        if (b === null) invalid.push("in-b");
        if (k === null) invalid.push("in-k");
        if (invalid.length) {
            this._updateEditor();
            invalid.forEach(id => $(id).setAttribute("aria-invalid", "true"));
            this._inputError = this._t(invalid.includes("in-t") ? "invalid_time" : "invalid_number");
            this._renderStatus();
            return;
        }
        const minutes = Number(timeMatch[1]) * 60 + Number(timeMatch[2]);
        const { minT, maxT } = this._timeBounds(idx);
        const t = Math.max(minT, Math.min(maxT, Math.round(minutes / HCL_STEP) * HCL_STEP));
        const nb = Math.max(0, Math.min(100, Math.round(b)));
        const nk = Math.max(2000, Math.min(7000, Math.round(k)));
        if (t === pt.t && nb === pt.b && nk === pt.k) { this._inputError = null; this._updateEditor(); this._renderStatus(); return; }
        this._pushUndo();
        pt.t = t; pt.b = nb; pt.k = nk;
        this._markChanged();
    }

    _insertPoint(t) {
        t = Math.max(0, Math.min(HCL_DAY - HCL_STEP, Math.round(t / HCL_STEP) * HCL_STEP));
        const existing = this._points.findIndex(p => p.t === t);
        if (existing !== -1) { this._select(existing); return; }
        const data = this._calculateCurveAt(t);
        this._pushUndo();
        const pt = { t, b: Math.round(data.b), k: Math.round(data.k) };
        this._points.push(pt);
        this._points.sort((a, c) => a.t - c.t);
        this._selected = this._points.indexOf(pt);
        this._markChanged(true);
    }

    // Adds a point in the middle of the largest gap between two points
    _addPoint() {
        if (!this._points.length) return;
        const pts = [...this._points].sort((a, c) => a.t - c.t);
        let best = { gap: -1, t: 0 };
        pts.forEach((p, i) => {
            const next = pts[(i + 1) % pts.length];
            const gap = hclMod(next.t - p.t) || HCL_DAY;
            if (gap > best.gap) best = { gap, t: hclMod(p.t + Math.round(gap / 2 / HCL_STEP) * HCL_STEP) };
        });
        if (best.gap < 2 * HCL_STEP) return;
        this._insertPoint(best.t);
    }

    _deletePoint(idx) {
        if (idx < 0 || idx >= this._points.length || this._points.length <= 2) return;
        this._pushUndo();
        this._points.splice(idx, 1);
        this._selected = -1;
        this._markChanged(true);
    }

    _onChartDblClick(e) {
        const chart = e.currentTarget.id === "chartB" ? this._chartB : this._chartK;
        if (!chart) return;
        const rect = chart.canvas.getBoundingClientRect();
        this._insertPoint(chart.scales.x.getValueForPixel(e.clientX - rect.left));
    }

    _applyPreset(name) {
        if (!this._presets[name]) return;
        this._pushUndo();
        this._points = hclNormalize(this._presets[name]);
        this._selected = -1;
        this._markChanged(true);
    }

    // Handles: Up/Down value, PageUp/PageDown large steps, Home/End min/max,
    // Left/Right time, Delete remove
    _onKeyDown(e, idx, type) {
        const pt = this._points[idx];
        if (!pt) return;
        const key = type === "b" ? "b" : "k";
        const [min, max, step, big] = type === "b" ? [0, 100, 1, 10] : [2000, 7000, 50, 500];
        const shift = e.shiftKey;
        const { minT, maxT } = this._timeBounds(idx);
        let next = null;
        let nextT = null;
        switch (e.key) {
            case "ArrowUp": next = pt[key] + (shift ? big : step); break;
            case "ArrowDown": next = pt[key] - (shift ? big : step); break;
            case "PageUp": next = pt[key] + big; break;
            case "PageDown": next = pt[key] - big; break;
            case "Home": next = min; break;
            case "End": next = max; break;
            case "ArrowLeft": nextT = pt.t - (shift ? 60 : HCL_STEP); break;
            case "ArrowRight": nextT = pt.t + (shift ? 60 : HCL_STEP); break;
            case "Delete":
            case "Backspace":
                e.preventDefault();
                this._deletePoint(idx);
                return;
            default:
                return;
        }
        e.preventDefault();
        if (next !== null) {
            next = Math.max(min, Math.min(max, next));
            if (next === pt[key]) return;
            this._pushUndo();
            pt[key] = next;
        } else {
            nextT = Math.max(minT, Math.min(maxT, nextT));
            if (nextT === pt.t) return;
            this._pushUndo();
            pt.t = nextT;
        }
        this._selected = idx;
        this._markChanged();
        e.target.focus();
    }

    // Dragging a handle. Every end of the gesture (up, cancel, lost capture,
    // removal of the card) goes through _endDrag.
    _onDragStart(e, idx, type, el) {
        if (this._drag) this._endDrag(false);
        e.preventDefault();
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events */ }
        const chart = (type === "b") ? this._chartB : this._chartK;
        const layer = this.shadowRoot.getElementById(`handles-${type}`);
        const drag = {
            pointerId: e.pointerId, idx, type, el, chart,
            rect: layer.getBoundingClientRect(), moved: false,
        };
        this._drag = drag;
        this._select(idx, false);
        this._pushUndo();

        drag.onMove = (ev) => {
            if (ev.pointerId !== drag.pointerId || this._drag !== drag) return;
            drag.moved = true;
            const pt = this._points[drag.idx];
            if (!pt) return;
            const { minT, maxT } = this._timeBounds(drag.idx);
            const rawT = chart.scales.x.getValueForPixel(ev.clientX - drag.rect.left);
            const yVal = chart.scales.y.getValueForPixel(ev.clientY - drag.rect.top);
            pt.t = Math.max(minT, Math.min(maxT, Math.round(rawT / HCL_STEP) * HCL_STEP));
            if (type === "b") pt.b = Math.round(Math.max(0, Math.min(100, yVal)));
            else pt.k = Math.round(Math.max(2000, Math.min(7000, yVal)));
            if (!this._dragFrame) {
                this._dragFrame = requestAnimationFrame(() => {
                    this._dragFrame = null;
                    if (this._drag === drag) this._updateVisuals();
                });
            }
            this._revision += 1;
            this._recomputeDirty();
            this._updateUIState();
        };
        drag.onEnd = (ev) => {
            if (ev && ev.pointerId !== undefined && ev.pointerId !== drag.pointerId) return;
            this._endDrag(true);
        };
        el.addEventListener("pointermove", drag.onMove);
        el.addEventListener("pointerup", drag.onEnd);
        el.addEventListener("pointercancel", drag.onEnd);
        el.addEventListener("lostpointercapture", drag.onEnd);
        window.addEventListener("pointermove", drag.onMove);
        window.addEventListener("pointerup", drag.onEnd);
        window.addEventListener("pointercancel", drag.onEnd);
    }

    _endDrag(commit) {
        const drag = this._drag;
        if (!drag) return;
        this._drag = null;
        const { el } = drag;
        el.removeEventListener("pointermove", drag.onMove);
        el.removeEventListener("pointerup", drag.onEnd);
        el.removeEventListener("pointercancel", drag.onEnd);
        el.removeEventListener("lostpointercapture", drag.onEnd);
        window.removeEventListener("pointermove", drag.onMove);
        window.removeEventListener("pointerup", drag.onEnd);
        window.removeEventListener("pointercancel", drag.onEnd);
        try { if (el.hasPointerCapture && el.hasPointerCapture(drag.pointerId)) el.releasePointerCapture(drag.pointerId); } catch (err) { /* ignore */ }
        if (this._dragFrame) { cancelAnimationFrame(this._dragFrame); this._dragFrame = null; }
        if (!drag.moved) this._undo.pop(); // a click only selects the point
        if (commit && drag.moved) this._markChanged();
        else if (this._initialized) { this._updateEditor(); this._updateUIState(); }
    }

    // ------------------------------------------------------------ service calls
    async _callService(domain, service, data, errorKey) {
        try {
            await this._hass.callService(domain, service, data);
            this._serviceError = null;
            return true;
        } catch (err) {
            const msg = (err && (err.message || err.code)) || String(err);
            this._serviceError = this._t(errorKey, { msg });
            return false;
        }
    }

    // Curve actions run one at a time; the result belongs to the draft revision
    // that was sent.
    async _curveAction(type, mode, points, errorKey) {
        if (this._pending) return false;
        const key = points ? hclKey(points) : null;
        this._pending = { type, key };
        this._renderStatus();
        const data = { entity_id: this.config.entity, mode };
        if (points) data.points = points;
        try {
            return await this._callService("hcl_lighting", "update_curve", data, errorKey);
        } finally {
            this._pending = null;
            this._renderStatus();
        }
    }

    async _saveCurve() {
        const points = hclNormalize(this._points);
        const key = hclKey(points);
        if (await this._curveAction("save", "save", points, "save_failed")) {
            // Confirmed: the draft of this revision is saved, even before the
            // sensor reports it (later edits stay unsaved)
            this._savedKey = key;
            this._serverChanged = false;
            this._recomputeDirty();
            this._renderStatus();
        }
    }

    _testCurve() {
        return this._curveAction("preview", "preview", hclNormalize(this._points), "preview_failed");
    }

    async _revertCurve() {
        if (!confirm(this._t("confirm_revert"))) return;
        const revision = this._revision;
        if (await this._curveAction("revert", "revert", null, "revert_failed")) {
            // Edited while the call was running: keep the newer draft
            if (this._revision !== revision) return;
            // Load the saved curve (the sensor sends it now or with the next update)
            this._pushUndo();
            this._revision += 1;
            this._adoptRevision = this._revision;
            this._savedKey = null;
            if (this._server.points) this._adopt(this._server.points, true);
        }
    }

    _adoptServer() {
        if (!this._server.points) return;
        this._pushUndo();
        this._revision += 1;
        this._adopt(this._server.points, true);
    }

    async _setMode(mode) {
        if (!this.config || !this._hass || this._pendingMode) return;
        const stateObj = this._hass.states[this.config.entity];
        const modeId = stateObj && stateObj.attributes.mode_entity_id;
        if (!modeId || mode === this._currentMode) return;
        this._pendingMode = mode;
        this._renderChips();
        await this._callService("select", "select_option", { entity_id: modeId, option: mode }, "mode_failed");
        // The chips follow the confirmed state of the mode select
        this._pendingMode = null;
        this._renderChips();
        this._renderStatus();
    }

    // ------------------------------------------------------------ validation
    _runValidation(data) {
        this._validationResult = { errors: [], warnings: [] };
        const V = this._validationResult;
        const f = this._fmt;
        if (this._points.length < 2) {
            V.errors.push({ msg: this._t("val_min_points") });
            return;
        }
        for (let i = 0; i < data.t.length - 1; i++) {
            const dt = data.t[i + 1] - data.t[i];
            if (dt <= 0) continue;
            const slopeB = Math.abs(data.b[i + 1] - data.b[i]) / dt;
            const slopeK = Math.abs(data.k[i + 1] - data.k[i]) / dt;
            if (slopeB > this._valSettings.maxSlopeB) {
                V.warnings.push({ type: "slope", msg: this._t("val_slope_b", { time: f.clock(data.t[i]) }), xMin: data.t[i], xMax: data.t[i + 1] });
            }
            if (slopeK > this._valSettings.maxSlopeK) {
                V.warnings.push({ type: "slope", msg: this._t("val_slope_k", { time: f.clock(data.t[i]) }), xMin: data.t[i], xMax: data.t[i + 1] });
            }
        }
        // one day of samples (00:00 … 23:45; 24:00 is the same as 00:00)
        const day = data.t.slice(0, -1);
        let peakMinutes = 0;
        day.forEach((t, i) => { if (data.b[i] > 70 && data.k[i] > 5000) peakMinutes += HCL_STEP; });
        if (peakMinutes < this._valSettings.minDailyPeakDuration) {
            const rangesNeedK = [];
            const rangesNeedB = [];
            const addRange = (list, t) => {
                if (list.length > 0 && t === list[list.length - 1].end) list[list.length - 1].end += HCL_STEP;
                else list.push({ start: t, end: t + HCL_STEP });
            };
            day.forEach((t, i) => {
                const bHigh = data.b[i] > 70;
                const kHigh = data.k[i] > 5000;
                if (bHigh && !kHigh) addRange(rangesNeedK, t);
                if (kHigh && !bHigh) addRange(rangesNeedB, t);
            });
            let hasAdvice = false;
            rangesNeedK.forEach(r => {
                if (r.end - r.start >= 30) {
                    V.warnings.push({ type: "peak", targetChart: "k", msg: this._t("val_peak_k"), xMin: r.start, xMax: r.end });
                    hasAdvice = true;
                }
            });
            rangesNeedB.forEach(r => {
                if (r.end - r.start >= 30) {
                    V.warnings.push({ type: "peak", targetChart: "b", msg: this._t("val_peak_b"), xMin: r.start, xMax: r.end });
                    hasAdvice = true;
                }
            });
            if (!hasAdvice) {
                V.warnings.push({ type: "peak", targetChart: "b", msg: this._t("val_peak_short"), xMin: 600, xMax: 840 });
                V.warnings.push({ type: "peak", targetChart: "k", msg: this._t("val_peak_short"), xMin: 600, xMax: 840 });
            }
        }
        const { nightStart, nightEnd } = this._valSettings;
        const isNight = (t) => {
            const m = hclMod(t);
            return nightStart < nightEnd ? (m >= nightStart && m < nightEnd) : (m >= nightStart || m < nightEnd);
        };
        const nightB = [];
        const nightK = [];
        day.forEach((t, i) => {
            if (!isNight(t)) return;
            if (hclEffectiveB(data.b[i], this._limits) > 10) nightB.push(t);
            if (data.k[i] > 3000) nightK.push(t);
        });
        if (nightB.length > 2) this._addNightWarnings(nightB, "b", "val_night_b");
        if (nightK.length > 2) this._addNightWarnings(nightK, "k", "val_night_k");
    }

    // Consecutive night samples as intervals; an interval over midnight is one
    // interval (e.g. 22:15–07:00), times are always valid clock times
    _addNightWarnings(times, chartType, key) {
        const intervals = [];
        times.forEach(t => {
            const last = intervals[intervals.length - 1];
            if (last && t === last.end) last.end += HCL_STEP;
            else intervals.push({ start: t, end: t + HCL_STEP });
        });
        if (intervals.length > 1 && intervals[0].start === 0 && intervals[intervals.length - 1].end === HCL_DAY) {
            const first = intervals.shift();
            intervals[intervals.length - 1].end = HCL_DAY + first.end;
        }
        const f = this._fmt;
        intervals.forEach(({ start, end }) => {
            this._validationResult.warnings.push({
                type: "night", targetChart: chartType,
                msg: this._t(key, { from: f.clock(start), to: f.clock(end) }),
                xMin: hclMod(start), xMax: end === HCL_DAY ? HCL_DAY : hclMod(end),
            });
        });
    }

    _getValidationAnnotations(chartType) {
        const list = [];
        const warn = this._theme ? this._theme.warning : "#ffa600";
        this._validationResult.warnings.forEach(w => {
            if (w.targetChart && w.targetChart !== chartType) return;
            if (w.xMin !== undefined && w.xMax !== undefined) {
                list.push({ xMin: w.xMin, xMax: w.xMax, color: this._withAlpha(warn, w.type === "slope" ? 0.3 : 0.15) });
            }
        });
        return list;
    }

    _updateValidationUI() {
        const area = this.shadowRoot.getElementById("validation-area");
        if (!area) return;
        // Only touch the DOM when the result changed
        const currentSig = JSON.stringify(this._validationResult);
        if (this._lastValidationSig === currentSig) return;
        this._lastValidationSig = currentSig;
        area.innerHTML = "";
        const add = (msg, cls) => {
            const div = document.createElement("div");
            div.className = `msg ${cls}`;
            div.textContent = msg;
            area.appendChild(div);
        };
        this._validationResult.errors.forEach(e => add(e.msg, "error"));
        if (!this._validationResult.errors.length) {
            this._validationResult.warnings.forEach(w => add(w.msg, "warning"));
        }
        this._updateUIState();
    }
}

// ---------------------------------------------------------------- helpers
function hclCurveSensors(hass) {
    if (!hass || !hass.states) return [];
    return Object.keys(hass.states)
        .filter(id => id.startsWith("sensor."))
        .filter(id => {
            const attrs = hass.states[id].attributes || {};
            return Array.isArray(attrs.control_points) && "mode_entity_id" in attrs;
        })
        .sort();
}

// ---------------------------------------------------------------- 6. editor
class HCLCurveCardEditor extends HTMLElement {
    setConfig(config) {
        this._config = { view: "full", ...config };
        this._render();
    }

    set hass(hass) {
        this._hass = hass;
        this._render();
    }

    _t(key) {
        const lang = ((this._hass && ((this._hass.locale && this._hass.locale.language) || this._hass.language)) || "en").split("-")[0];
        return (HCL_STRINGS[lang] || HCL_STRINGS.en)[key] || HCL_STRINGS.en[key];
    }

    _render() {
        if (!this._config) return;
        if (!this.shadowRoot) this.attachShadow({ mode: "open" });
        const sensors = hclCurveSensors(this._hass);
        const sig = JSON.stringify([sensors, this._config, this._t("editor_entity")]);
        if (sig === this._sig) return;
        this._sig = sig;
        const current = this._config.entity || "";
        const options = sensors.map(id => ({ id, name: this._hass.states[id].attributes.friendly_name || id }));
        this.shadowRoot.innerHTML = `
          <style>
              .form { display: flex; flex-direction: column; gap: 12px; }
              label { display: flex; flex-direction: column; gap: 4px; font-size: 0.875rem; }
              select { font: inherit; padding: 8px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc);
                       background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121); }
          </style>
          <div class="form">
              <label><span id="l-entity"></span><select id="entity"></select></label>
              <label><span id="l-view"></span><select id="view"></select></label>
          </div>`;
        const $ = (id) => this.shadowRoot.getElementById(id);
        $("l-entity").textContent = this._t("editor_entity");
        $("l-view").textContent = this._t("editor_view");
        const entitySelect = $("entity");
        if (!options.length) {
            const opt = document.createElement("option");
            opt.value = current;
            opt.textContent = current || this._t("editor_none");
            entitySelect.appendChild(opt);
        }
        if (current && !sensors.includes(current) && options.length) {
            const opt = document.createElement("option");
            opt.value = current;
            opt.textContent = current;
            entitySelect.appendChild(opt);
        }
        options.forEach(({ id, name }) => {
            const opt = document.createElement("option");
            opt.value = id;
            opt.textContent = `${name} (${id})`;
            entitySelect.appendChild(opt);
        });
        entitySelect.value = current;
        const viewSelect = $("view");
        [["full", "view_full"], ["compact", "view_compact"]].forEach(([value, key]) => {
            const opt = document.createElement("option");
            opt.value = value;
            opt.textContent = this._t(key);
            viewSelect.appendChild(opt);
        });
        viewSelect.value = this._config.view || "full";
        entitySelect.addEventListener("change", () => this._changed({ entity: entitySelect.value }));
        viewSelect.addEventListener("change", () => this._changed({ view: viewSelect.value }));
    }

    _changed(update) {
        this._config = { ...this._config, ...update };
        this.dispatchEvent(new CustomEvent("config-changed", {
            detail: { config: this._config }, bubbles: true, composed: true,
        }));
    }
}

// Curve maths for tests and tools (same results as the integration)
HCLCurveCard.curve = { normalize: hclNormalize, valueAt: hclValueAt, effectiveB: hclEffectiveB, samples: hclSamples };

if (!customElements.get("hcl-curve-card")) customElements.define("hcl-curve-card", HCLCurveCard);
if (!customElements.get("hcl-curve-card-editor")) customElements.define("hcl-curve-card-editor", HCLCurveCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "hcl-curve-card")) {
    window.customCards.push({
        type: "hcl-curve-card",
        name: "HCL Curve Card",
        preview: true,
        description: "Status and daily curve editor for HCL Lighting",
        documentationURL: "https://github.com/Ecronika/ha_hcl",
    });
}
