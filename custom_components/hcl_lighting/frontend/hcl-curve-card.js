/*
 * HCL Curve Card – interactive editor for the HCL Lighting curve.
 * Texts follow the Home Assistant language (German/English), colours follow the active theme.
 */
const HCL_STRINGS = {
    en: {
        title: "HCL Configurator",
        presets: "Presets",
        preset_default: "Default (balanced)",
        preset_focus: "Focus (home office)",
        preset_relax: "Relax (wellness)",
        preset_early_bird: "Early bird",
        preset_night_owl: "Night owl",
        fix: "Fix",
        fix_title: "Fix sorting/duplicates",
        revert: "Revert",
        revert_title: "Discard unsaved changes",
        preview: "Preview",
        preview_title: "Apply unsaved changes to the lights until the next reload",
        save: "Save",
        save_title: "Save the curve",
        undo_title: "Undo last change (Ctrl+Z)",
        add_title: "Add point (or double-click the chart)",
        delete_title: "Delete selected point (Del)",
        brightness: "Brightness",
        color_temp: "Colour temperature",
        time: "Time",
        now: "Now",
        no_selection: "Select a point to edit it",
        mode_auto: "Auto",
        mode_focus: "Focus",
        mode_relax: "Relax",
        mode_cleaning: "Cleaning",
        mode_guest: "Guest",
        mode_sleep: "Sleep",
        confirm_revert: "Discard all unsaved changes and reload the saved curve?",
        point_b: "Brightness point {n}",
        point_k: "Colour temperature point {n}",
        val_min_points: "The curve needs at least 2 points.",
        val_duplicate: "Duplicate time at {time}.",
        val_unsorted: "Points are not sorted by time.",
        val_slope_b: "Brightness changes too steeply (>2 %/min) at {time}.",
        val_slope_k: "Colour temperature changes too steeply (>100 K/min) at {time}.",
        val_peak_k: "Active phase: colour temperature too low here, raise it above 5000 K.",
        val_peak_b: "Active phase: brightness too low here, raise it above 70 %.",
        val_peak_short: "Active phase too short (<4 h). Try high brightness and colour temperature around noon.",
        val_night_b: "Night too bright (>10 %) {from}–{to}.",
        val_night_k: "Night too cold (>3000 K) {from}–{to}.",
        chart_error: "Error loading Chart.js: {msg}. Check the integration installation.",
    },
    de: {
        title: "HCL-Konfigurator",
        presets: "Vorlagen",
        preset_default: "Standard (ausgewogen)",
        preset_focus: "Fokus (Homeoffice)",
        preset_relax: "Entspannung (Wellness)",
        preset_early_bird: "Frühaufsteher",
        preset_night_owl: "Nachteule",
        fix: "Korrigieren",
        fix_title: "Reihenfolge/Duplikate korrigieren",
        revert: "Verwerfen",
        revert_title: "Ungespeicherte Änderungen verwerfen",
        preview: "Vorschau",
        preview_title: "Ungespeicherte Änderungen bis zum nächsten Neuladen an die Lichter senden",
        save: "Speichern",
        save_title: "Kurve speichern",
        undo_title: "Letzte Änderung rückgängig (Strg+Z)",
        add_title: "Punkt hinzufügen (oder Doppelklick ins Diagramm)",
        delete_title: "Ausgewählten Punkt löschen (Entf)",
        brightness: "Helligkeit",
        color_temp: "Farbtemperatur",
        time: "Uhrzeit",
        now: "Jetzt",
        no_selection: "Punkt auswählen, um ihn zu bearbeiten",
        mode_auto: "Auto",
        mode_focus: "Fokus",
        mode_relax: "Entspannen",
        mode_cleaning: "Putzen",
        mode_guest: "Gast",
        mode_sleep: "Schlafen",
        confirm_revert: "Alle ungespeicherten Änderungen verwerfen und die gespeicherte Kurve laden?",
        point_b: "Helligkeitspunkt {n}",
        point_k: "Farbtemperaturpunkt {n}",
        val_min_points: "Die Kurve braucht mindestens 2 Punkte.",
        val_duplicate: "Doppelte Uhrzeit {time}.",
        val_unsorted: "Punkte sind nicht nach Uhrzeit sortiert.",
        val_slope_b: "Helligkeit ändert sich zu steil (>2 %/min) um {time}.",
        val_slope_k: "Farbtemperatur ändert sich zu steil (>100 K/min) um {time}.",
        val_peak_k: "Aktivphase: Farbtemperatur hier zu niedrig, über 5000 K anheben.",
        val_peak_b: "Aktivphase: Helligkeit hier zu niedrig, über 70 % anheben.",
        val_peak_short: "Aktivphase zu kurz (<4 h). Um die Mittagszeit hohe Helligkeit und Farbtemperatur wählen.",
        val_night_b: "Nacht zu hell (>10 %) {from}–{to}.",
        val_night_k: "Nacht zu kalt (>3000 K) {from}–{to}.",
        chart_error: "Chart.js konnte nicht geladen werden: {msg}. Installation der Integration prüfen.",
    },
};

// Fallback values of the fixed scenarios (the curve sensor provides the configured ones)
const HCL_SCENARIO_DEFAULTS = {
    focus: { b: 100, k: 5500 },
    relax: { b: 40, k: 2700 },
    cleaning: { b: 100, k: 4000 },
    sleep: { b: 0, k: 2000 },
};

const HCL_MODES = [
    ["auto", "mdi:chart-bell-curve"],
    ["focus", "mdi:brain"],
    ["relax", "mdi:coffee"],
    ["cleaning", "mdi:broom"],
    ["guest", "mdi:account-group"],
    ["sleep", "mdi:bed"],
];

const HCL_UNDO_LIMIT = 50;
const HCL_STEP = 15; // minutes

class HCLCurveCard extends HTMLElement {
    static getStubConfig() {
        return {
            type: "custom:hcl-curve-card",
            entity: "sensor.hcl_lighting_curve_data"
        };
    }

    constructor() {
        super();
        this._initialized = false;
        this._points = [];
        this._chartB = null;
        this._chartK = null;
        this._isDragging = false;
        this._lastPointsJSON = "";
        this._lang = "en";
        this._themeKey = null;
        this._selected = -1;
        this._undo = [];

        // Validator State
        this._validationResult = { errors: [], warnings: [] };
        this._isDirty = false;

        // Settings for Validation
        this._valSettings = {
            nightStart: 1320, // 22:00
            nightEnd: 360,    // 06:00
            minDailyPeakDuration: 240, // 4 hours
            maxSlopeB: 2.0,   // % per min
            maxSlopeK: 100,   // K per min
        };

        // Scenario values drawn as horizontal lines (updated from the curve sensor)
        this._scenarios = JSON.parse(JSON.stringify(HCL_SCENARIO_DEFAULTS));

        // Presets: Scientifically inspired 12-point profiles
        // T: Minutes, B: Brightness (%), K: Kelvin
        this._presets = {
            // 1. DEFAULT: The "True" DIN-inspired Curve (v0.2.1 Replica)
            "default": [
                { t: 435, b: 14, k: 2700 }, // 07:15 Wake
                { t: 540, b: 50, k: 4500 }, // 09:00 Rise
                { t: 570, b: 75, k: 5500 }, // 09:30
                { t: 600, b: 100, k: 6500 }, // 10:00 Peak Focus
                { t: 720, b: 100, k: 6500 }, // 12:00
                { t: 750, b: 50, k: 4000 }, // 12:30 Regeneration Dip (Lunch)
                { t: 780, b: 50, k: 4000 }, // 13:00
                { t: 810, b: 75, k: 6000 }, // 13:30 Re-Activation
                { t: 840, b: 75, k: 6000 }, // 14:00
                { t: 960, b: 50, k: 4000 }, // 16:00
                { t: 1080, b: 30, k: 2700 }, // 18:00 Wind Down
                { t: 1380, b: 5, k: 2200 }  // 23:00 Bedtime
            ],
            // 2. FOCUS (Work from Home): High Performance
            "focus": [
                { t: 420, b: 15, k: 3500 }, // 07:00 Wake
                { t: 480, b: 80, k: 5500 }, // 08:00
                { t: 540, b: 100, k: 6500 }, // 09:00 Deep Work
                { t: 720, b: 100, k: 6500 }, // 12:00
                { t: 780, b: 80, k: 5500 }, // 13:00 Lunch
                { t: 840, b: 100, k: 6000 }, // 14:00
                { t: 1020, b: 80, k: 5500 }, // 17:00 End Work
                { t: 1080, b: 50, k: 3500 }, // 18:00
                { t: 1200, b: 30, k: 2700 }, // 20:00
                { t: 1320, b: 10, k: 2200 }, // 22:00
                { t: 1439, b: 5, k: 2000 }, // Midnight
                { t: 0, b: 5, k: 2000 }  // Loop
            ],
            // 3. RELAX (Wellness / Weekend)
            "relax": [
                { t: 480, b: 20, k: 2200 }, // 08:00
                { t: 600, b: 50, k: 3000 }, // 10:00
                { t: 720, b: 71, k: 5001 }, // 12:00
                { t: 840, b: 71, k: 5001 }, // 14:00
                { t: 960, b: 70, k: 5001 }, // 16:00
                { t: 1080, b: 40, k: 2700 }, // 18:00
                { t: 1200, b: 30, k: 2200 }, // 20:00
                { t: 1260, b: 20, k: 2000 }, // 21:00
                { t: 1320, b: 10, k: 2000 }, // 22:00
                { t: 1439, b: 5, k: 2000 },
                { t: 0, b: 5, k: 2000 },
                { t: 315, b: 10, k: 2000 }
            ],
            // 4. EARLY BIRD
            "early_bird": [
                { t: 360, b: 11, k: 2700 }, // 06:00
                { t: 450, b: 50, k: 4500 },
                { t: 480, b: 75, k: 5500 },
                { t: 510, b: 100, k: 6500 },
                { t: 630, b: 100, k: 6500 },
                { t: 660, b: 50, k: 4000 }, // 11:00 Lunch
                { t: 690, b: 50, k: 4000 },
                { t: 720, b: 75, k: 6000 },
                { t: 750, b: 75, k: 6000 },
                { t: 870, b: 50, k: 4000 },
                { t: 990, b: 30, k: 2700 }, // 16:30 Wind Down
                { t: 1290, b: 5, k: 2200 }  // 21:30 Sleep
            ],
            // 5. NIGHT OWL
            "night_owl": [
                { t: 540, b: 20, k: 2700 }, // 09:00
                { t: 660, b: 50, k: 4500 },
                { t: 690, b: 75, k: 5500 },
                { t: 720, b: 100, k: 6500 },
                { t: 840, b: 100, k: 6500 },
                { t: 870, b: 50, k: 4000 }, // 14:30 Lunch
                { t: 900, b: 50, k: 4000 },
                { t: 930, b: 75, k: 6000 },
                { t: 960, b: 75, k: 6000 },
                { t: 1080, b: 50, k: 4000 },
                { t: 1200, b: 21, k: 2700 }, // 20:00 Wind Down
                { t: 1440, b: 5, k: 2200 }  // 00:00 Sleep
            ]
        };

        // Bound Event Handlers (defined in constructor to persist across reconnects)
        this._boundSanitize = () => this._sanitizeCurve();
        this._boundSave = () => this._saveCurve();
        this._boundTest = () => this._testCurve();
        this._boundRevert = () => this._revertCurve();
        this._boundUndo = () => this._undoLast();
        this._boundAdd = () => this._addPoint();
        this._boundDelete = () => this._deletePoint(this._selected);
        this._boundNumeric = () => this._applyNumeric();
        this._boundPreset = (e) => {
            this._applyPreset(e.target.value);
            e.target.value = "";
        };
        this._boundCardKey = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
                e.preventDefault();
                this._undoLast();
            }
        };
        this._boundDblClick = (e) => this._onChartDblClick(e);
    }

    // ------------------------------------------------------------ i18n
    _t(key, params = {}) {
        const table = HCL_STRINGS[this._lang] || HCL_STRINGS.en;
        let text = table[key] ?? HCL_STRINGS.en[key] ?? key;
        Object.entries(params).forEach(([name, value]) => {
            text = text.replace(`{${name}}`, value);
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
        this._updateUIState();
        this._lastValidationSig = null;
        [this._chartB, this._chartK].forEach(chart => { if (chart) chart.options.locale = this._lang; });
        if (this._chartB) this._updateVisuals();
    }

    set hass(hass) {
        this._hass = hass;
        const lang = ((hass.locale && hass.locale.language) || hass.language || "en").split("-")[0];
        const newLang = HCL_STRINGS[lang] ? lang : "en";
        if (newLang !== this._lang) {
            this._lang = newLang;
            this._applyTexts();
        }
        const themeKey = JSON.stringify([hass.themes && hass.themes.darkMode, hass.themes && hass.themes.theme, hass.selectedTheme]);
        if (themeKey !== this._themeKey) {
            this._themeKey = themeKey;
            // Theme variables are applied to the DOM after this setter; read them afterwards
            requestAnimationFrame(() => this._applyTheme());
        }
        if (!this.config || !this.config.entity) return;

        const stateObj = hass.states[this.config.entity];
        if (stateObj) {
            if (stateObj.attributes.scenarios) {
                this._scenarios = { ...HCL_SCENARIO_DEFAULTS, ...stateObj.attributes.scenarios };
            }
            this._syncMode(hass, stateObj);
        }
        if (stateObj && stateObj.attributes.control_points && !this._isDragging) {
            const rawPoints = stateObj.attributes.control_points;
            // Reference check first to avoid an expensive JSON.stringify
            if (this._rawPointsRef === rawPoints) return;
            const newPointsJSON = JSON.stringify(rawPoints);
            if (this._lastPointsJSON !== newPointsJSON) {
                this._points = JSON.parse(newPointsJSON);
                this._lastPointsJSON = newPointsJSON;
                this._rawPointsRef = rawPoints;
                this._undo = [];
                this._selected = -1;
                this._isDirty = false;
                this._refreshCharts();
                this._updateEditor();
                this._updateUIState();
            }
        }
    }

    // Mirrors the state of the mode select entity into the chips and the
    // scenario line (the mode can also change via automations or restarts).
    _syncMode(hass, stateObj) {
        const modeId = stateObj.attributes.mode_entity_id;
        const modeState = modeId ? hass.states[modeId] : null;
        if (!modeState || modeState.state === this._currentMode) return;
        this._currentMode = modeState.state;
        this._updateModeVisuals(this._currentMode);
        if (this._chartB) this._chartB.update('none');
        if (this._chartK) this._chartK.update('none');
    }

    setConfig(config) {
        if (!config.entity) {
            throw new Error('You need to define an entity (sensor.<name>_curve_data)');
        }
        this.config = config;
        if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    }

    getCardSize() {
        return 7;
    }

    async connectedCallback() {
        if (!window.Chart) {
            try {
                await import('/hcl_lighting_static/chart.js');
            } catch (e) {
                this.shadowRoot.innerHTML = `<ha-card style="padding:16px; color:var(--error-color, red);"></ha-card>`;
                this.shadowRoot.querySelector("ha-card").textContent = this._t("chart_error", { msg: e.message });
                return;
            }
        }

        this.render();
        this._initialized = true;

        this._resizeObserver = new ResizeObserver((entries) => {
            if (!entries.length || entries[0].contentRect.width === 0) return;
            // rAF avoids ResizeObserver loop errors
            requestAnimationFrame(() => {
                if (this._initialized && !this._isDragging) {
                    if (this._chartB) this._chartB.resize();
                    if (this._chartK) this._chartK.resize();
                    this._updateVisuals();
                }
            });
        });
        const container = this.shadowRoot.querySelector('.charts');
        if (container) this._resizeObserver.observe(container);

        this._initCharts();
        this._applyTheme();
        this._refreshCharts();
        this._bindEvents();
        this._bindChipEvents();
        this._applyTexts();
        if (this._currentMode) this._updateModeVisuals(this._currentMode);

        // The "now" marker moves once per minute
        this._nowTimer = setInterval(() => this._updateVisuals(), 60000);
    }

    _bindChipEvents() {
        this.shadowRoot.querySelectorAll('.chip').forEach(chip => {
            chip.onclick = () => this._setMode(chip.dataset.mode);
        });
    }

    _setMode(mode) {
        if (!this.config.entity || !this._hass) return;
        const stateObj = this._hass.states[this.config.entity];
        if (stateObj && stateObj.attributes.mode_entity_id) {
            this._hass.callService("select", "select_option", {
                entity_id: stateObj.attributes.mode_entity_id,
                option: mode
            });
            // Optimistic update; the select state confirms it
            this._updateModeVisuals(mode);
        } else {
            console.warn("HCL Curve Card: 'mode_entity_id' not found in attributes of " + this.config.entity);
        }
    }

    _updateModeVisuals(mode) {
        const chips = this.shadowRoot.querySelectorAll('.chip');
        if (!chips.length) return;
        chips.forEach(chip => chip.classList.toggle('active', chip.dataset.mode === mode));
        // The curve is only edited while it is in use (Auto)
        this.shadowRoot.querySelectorAll('.charts, .point-editor').forEach(el => {
            el.classList.toggle('disabled', mode !== 'auto');
        });
    }

    disconnectedCallback() {
        if (this._resizeObserver) this._resizeObserver.disconnect();
        if (this._dragCleanup) this._dragCleanup();
        if (this._nowTimer) clearInterval(this._nowTimer);
        this._unbindEvents();
        if (this._chartB) { this._chartB.destroy(); this._chartB = null; }
        if (this._chartK) { this._chartK.destroy(); this._chartK = null; }
        this._initialized = false;
        // DOM nodes stay; render() is skipped on reconnect and events are re-bound
    }

    render() {
        if (this.shadowRoot.innerHTML) return;
        const chips = HCL_MODES.map(([mode, icon]) =>
            `<button class="chip" data-mode="${mode}"><ha-icon icon="${icon}"></ha-icon><span data-i18n="mode_${mode}"></span></button>`
        ).join("");

        this.shadowRoot.innerHTML = `
      <style>
          :host {
              display: block;
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
          ha-card {
              overflow: hidden;
              color: var(--hcl-text);
              padding-bottom: 12px;
              position: relative;
          }
          .card-header {
              padding: 16px 16px 8px 16px;
              display: flex;
              justify-content: space-between;
              align-items: center;
              flex-wrap: wrap;
              gap: 8px;
          }
          .title { font-weight: 500; font-size: 16px; }
          .controls-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
          button, select, input {
              font: inherit;
              font-size: 12px;
              color: var(--hcl-text);
              background: var(--hcl-surface);
              border: 1px solid var(--hcl-divider);
              border-radius: 16px;
              padding: 5px 12px;
          }
          button { cursor: pointer; }
          button:hover:not(:disabled) { border-color: var(--hcl-accent); }
          button:disabled, input:disabled { opacity: 0.45; cursor: default; }
          button.primary { border-color: var(--hcl-accent); color: var(--hcl-accent); }
          button.dirty { border-color: var(--hcl-warning); }
          button.icon { padding: 5px 10px; min-width: 32px; }
          select option { background: var(--card-background-color, #fff); color: var(--hcl-text); }
          #validation-area {
              margin: 0 16px 8px 16px;
              display: flex;
              flex-direction: column;
              gap: 4px;
          }
          .msg {
              border-left: 4px solid var(--hcl-warning);
              background: var(--hcl-surface);
              padding: 6px 8px;
              font-size: 12px;
              border-radius: 4px;
          }
          .msg.error { border-left-color: var(--hcl-error); }
          .mode-selector { padding: 0 16px 12px 16px; display: flex; gap: 6px; flex-wrap: wrap; }
          .chip { display: flex; align-items: center; gap: 4px; }
          .chip ha-icon { --mdc-icon-size: 16px; }
          .chip.active { background: var(--hcl-accent); border-color: var(--hcl-accent); color: var(--text-primary-color, #fff); }
          .charts {
              padding: 0 16px;
              display: grid;
              grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
              gap: 12px;
          }
          .charts.disabled, .point-editor.disabled { opacity: 0.5; pointer-events: none; }
          .chart-wrapper {
              position: relative;
              height: 220px;
              background: var(--hcl-surface);
              border-radius: 12px;
              padding: 12px;
          }
          .chart-label {
              position: absolute;
              top: 10px; left: 16px;
              font-size: 11px;
              color: var(--hcl-text-2);
              text-transform: uppercase;
              letter-spacing: 0.5px;
              pointer-events: none;
              z-index: 5;
          }
          canvas { width: 100%; height: 100%; display: block; }
          .handle-layer {
              position: absolute;
              top: 12px; left: 12px; right: 12px; bottom: 12px;
              pointer-events: none;
              overflow: visible;
          }
          .handle {
              position: absolute;
              width: 12px; height: 12px;
              border-radius: 50%;
              margin-left: -6px; margin-top: -6px;
              cursor: grab;
              pointer-events: auto;
              z-index: 10;
              touch-action: none;
              border: 2px solid var(--card-background-color, #fff);
              box-sizing: border-box;
          }
          .handle::after { content: ''; position: absolute; inset: -10px; }
          .handle:active { cursor: grabbing; }
          .handle.type-b { background: var(--hcl-b-color); }
          .handle.type-k { background: var(--hcl-k-color); }
          .handle.selected { outline: 2px solid var(--hcl-text); outline-offset: 2px; }
          .handle-info {
              position: absolute;
              bottom: 18px; left: 50%;
              transform: translateX(-50%);
              background: var(--card-background-color, #fff);
              color: var(--hcl-text);
              border: 1px solid var(--hcl-divider);
              padding: 3px 6px;
              border-radius: 6px;
              font-size: 10px;
              font-family: monospace;
              white-space: nowrap;
              opacity: 0;
              pointer-events: none;
              transition: opacity 0.2s;
              z-index: 100;
          }
          .handle:hover .handle-info, .handle:active .handle-info, .handle:focus .handle-info { opacity: 1; }
          .point-editor {
              display: flex;
              gap: 8px;
              align-items: center;
              flex-wrap: wrap;
              padding: 12px 16px 0 16px;
              font-size: 12px;
              color: var(--hcl-text-2);
          }
          .point-editor label { display: flex; gap: 4px; align-items: center; }
          .point-editor input { width: 80px; border-radius: 8px; }
          .point-editor input[type=time] { width: 100px; }
          .point-editor .hint { flex: 1 1 auto; }
          .footer-section { margin-top: 12px; padding: 0 16px; }
          .color-bar { height: 8px; border-radius: 4px; width: 100%; border: 1px solid var(--hcl-divider); }
          .axis-labels {
              display: flex;
              justify-content: space-between;
              margin-top: 4px;
              font-size: 10px;
              color: var(--hcl-text-2);
              font-family: monospace;
          }
          #now-info { margin-top: 6px; font-size: 12px; color: var(--hcl-text-2); }
      </style>
      <ha-card>
          <div class="card-header">
             <div class="controls-row">
                 <span class="title" data-i18n="title"></span>
                 <select id="preset-select" data-i18n-title="presets">
                   <option value="" disabled selected data-i18n="presets"></option>
                   <option value="default" data-i18n="preset_default"></option>
                   <option value="focus" data-i18n="preset_focus"></option>
                   <option value="relax" data-i18n="preset_relax"></option>
                   <option value="early_bird" data-i18n="preset_early_bird"></option>
                   <option value="night_owl" data-i18n="preset_night_owl"></option>
                 </select>
             </div>
             <div class="controls-row">
                <button id="btn-sanitize" data-i18n="fix" data-i18n-title="fix_title" style="display:none;"></button>
                <button id="btn-revert" data-i18n="revert" data-i18n-title="revert_title"></button>
                <button id="btn-test" data-i18n="preview" data-i18n-title="preview_title"></button>
                <button id="btn-save" class="primary" data-i18n="save" data-i18n-title="save_title"></button>
             </div>
          </div>

          <div id="validation-area" style="display: none;"></div>

          <div class="mode-selector" id="mode-chips">${chips}</div>

          <div class="charts">
             <div class="chart-wrapper">
                 <span class="chart-label" data-i18n="brightness"></span>
                 <canvas id="chartB"></canvas>
                 <div class="handle-layer" id="handles-b"></div>
             </div>
             <div class="chart-wrapper">
                 <span class="chart-label" data-i18n="color_temp"></span>
                 <canvas id="chartK"></canvas>
                 <div class="handle-layer" id="handles-k"></div>
             </div>
          </div>

          <div class="point-editor">
              <button id="btn-add" class="icon" data-i18n-title="add_title">+</button>
              <button id="btn-delete" class="icon" data-i18n-title="delete_title">−</button>
              <button id="btn-undo" class="icon" data-i18n-title="undo_title">↶</button>
              <label><span data-i18n="time"></span><input id="in-t" type="time" step="900"></label>
              <label><span data-i18n="brightness"></span><input id="in-b" type="number" min="0" max="100" step="1">%</label>
              <label><span data-i18n="color_temp"></span><input id="in-k" type="number" min="2000" max="7000" step="50">K</label>
              <span class="hint" id="editor-hint" data-i18n="no_selection"></span>
          </div>

          <div class="footer-section">
              <div class="color-bar" id="color-bar-gradient"></div>
              <div class="axis-labels">
                  <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span>
              </div>
              <div id="now-info"></div>
          </div>
      </ha-card>
    `;
    }

    _drawOverrideLine(chart, value, color) {
        if (!chart) return;
        const ctx = chart.ctx;
        const yAxis = chart.scales.y;
        const xAxis = chart.scales.x;
        const yPixel = yAxis.getPixelForValue(value);

        ctx.save();
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        ctx.moveTo(xAxis.left, yPixel);
        ctx.lineTo(xAxis.right, yPixel);
        ctx.stroke();

        ctx.fillStyle = color;
        ctx.font = 'bold 10px sans-serif';
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
        ctx.strokeStyle = this._theme ? this._theme.accent : '#03a9f4';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.moveTo(x, yAxis.top);
        ctx.lineTo(x, yAxis.bottom);
        ctx.stroke();
        ctx.restore();
    }

    _nowMinutes() {
        const now = new Date();
        return now.getHours() * 60 + now.getMinutes();
    }

    _bindEvents() {
        this._unbindEvents();
        const $ = (id) => this.shadowRoot.getElementById(id);
        const bind = (id, type, fn) => { const el = $(id); if (el) el.addEventListener(type, fn); };
        bind('btn-sanitize', 'click', this._boundSanitize);
        bind('btn-save', 'click', this._boundSave);
        bind('btn-test', 'click', this._boundTest);
        bind('btn-revert', 'click', this._boundRevert);
        bind('btn-undo', 'click', this._boundUndo);
        bind('btn-add', 'click', this._boundAdd);
        bind('btn-delete', 'click', this._boundDelete);
        bind('preset-select', 'change', this._boundPreset);
        ['in-t', 'in-b', 'in-k'].forEach(id => bind(id, 'change', this._boundNumeric));
        bind('chartB', 'dblclick', this._boundDblClick);
        bind('chartK', 'dblclick', this._boundDblClick);
        this.addEventListener('keydown', this._boundCardKey);
    }

    _unbindEvents() {
        if (!this.shadowRoot) return;
        const $ = (id) => this.shadowRoot.getElementById(id);
        const unbind = (id, type, fn) => { const el = $(id); if (el) el.removeEventListener(type, fn); };
        unbind('btn-sanitize', 'click', this._boundSanitize);
        unbind('btn-save', 'click', this._boundSave);
        unbind('btn-test', 'click', this._boundTest);
        unbind('btn-revert', 'click', this._boundRevert);
        unbind('btn-undo', 'click', this._boundUndo);
        unbind('btn-add', 'click', this._boundAdd);
        unbind('btn-delete', 'click', this._boundDelete);
        unbind('preset-select', 'change', this._boundPreset);
        ['in-t', 'in-b', 'in-k'].forEach(id => unbind(id, 'change', this._boundNumeric));
        unbind('chartB', 'dblclick', this._boundDblClick);
        unbind('chartK', 'dblclick', this._boundDblClick);
        this.removeEventListener('keydown', this._boundCardKey);
    }

    // ------------------------------------------------------------ theme
    _readTheme() {
        const style = getComputedStyle(this);
        const v = (name, fallback) => (style.getPropertyValue(name) || '').trim() || fallback;
        return {
            b: v('--hcl-b-color', '#ffb300'),
            k: v('--hcl-k-color', '#00acc1'),
            text: v('--hcl-text-2', '#727272'),
            grid: v('--hcl-divider', 'rgba(127,127,127,0.25)'),
            accent: v('--hcl-accent', '#03a9f4'),
            warning: v('--hcl-warning', '#ffa600'),
        };
    }

    _withAlpha(color, alpha) {
        const probe = document.createElement('canvas').getContext('2d');
        probe.fillStyle = '#000';
        probe.fillStyle = color;
        const c = probe.fillStyle;
        if (c.startsWith('#') && c.length === 7) {
            const n = parseInt(c.slice(1), 16);
            return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
        }
        return c.replace(/rgba?\(([^)]+)\)/, (m, inner) => {
            const parts = inner.split(',').slice(0, 3).map(s => s.trim());
            return `rgba(${parts.join(', ')}, ${alpha})`;
        });
    }

    _applyTheme() {
        if (!this._chartB || !this._chartK || !this.isConnected) return;
        const th = this._readTheme();
        this._theme = th;
        [[this._chartB, th.b], [this._chartK, th.k]].forEach(([chart, color]) => {
            chart.options.scales.y.grid.color = th.grid;
            chart.options.scales.y.ticks.color = th.text;
            chart.data.datasets[0].borderColor = color;
            chart.data.datasets[0].backgroundColor = this._withAlpha(color, 0.12);
        });
        this._chartB.data.datasets[1].borderColor = th.b;
        this._chartB.update('none');
        this._chartK.update('none');
    }

    _initCharts() {
        if (this._chartB) { this._chartB.destroy(); this._chartB = null; }
        if (this._chartK) { this._chartK.destroy(); this._chartK = null; }
        const th = this._readTheme();
        this._theme = th;

        const axisY = (min, max) => ({
            min, max,
            display: true,
            position: 'right',
            grid: { color: th.grid },
            ticks: { color: th.text },
        });
        const commonOpts = {
            responsive: true, maintainAspectRatio: false, animation: false,
            layout: { padding: 0 },
            plugins: { legend: false, tooltip: false },
            elements: { point: { radius: 0, hoverRadius: 0 }, line: { borderWidth: 2 } },
        };

        const bandPlugin = {
            id: 'hclBands',
            beforeDraw: (chart) => {
                const ctx = chart.ctx;
                const yAxis = chart.scales.y;
                const xAxis = chart.scales.x;
                if (!xAxis || !yAxis) return;

                if (chart.canvas.id === 'chartB') {
                    const { minB, maxB } = this._limits();
                    ctx.fillStyle = 'rgba(127, 127, 127, 0.18)';
                    if (maxB < 100) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(100), xAxis.width, yAxis.getPixelForValue(maxB) - yAxis.getPixelForValue(100));
                    if (minB > 0) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(minB), xAxis.width, yAxis.getPixelForValue(0) - yAxis.getPixelForValue(minB));
                }

                this._getValidationAnnotations(chart.canvas.id === 'chartB' ? 'b' : 'k').forEach(anno => {
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
                const isB = chart.canvas.id === 'chartB';
                const value = isB ? scenario.b : scenario.k;
                if (value === null || value === undefined) return;
                this._drawOverrideLine(chart, value, isB ? this._theme.b : this._theme.k);
            },
        };

        const canvasB = this.shadowRoot.getElementById('chartB');
        const canvasK = this.shadowRoot.getElementById('chartK');
        const xAxis = { type: 'linear', min: 0, max: 1440, display: false };

        this._chartB = new Chart(canvasB.getContext('2d'), {
            type: 'line',
            data: { datasets: [
                { data: [], borderColor: th.b, fill: true, backgroundColor: this._withAlpha(th.b, 0.12) },
                // Effective brightness (limited by min/max), shown only when it differs
                { data: [], borderColor: th.b, borderDash: [4, 4], borderWidth: 1.5, fill: false },
            ] },
            options: { ...commonOpts, scales: { x: xAxis, y: axisY(0, 100) } },
            plugins: [bandPlugin]
        });
        this._chartK = new Chart(canvasK.getContext('2d'), {
            type: 'line',
            data: { datasets: [{ data: [], borderColor: th.k, fill: true, backgroundColor: this._withAlpha(th.k, 0.12) }] },
            options: { ...commonOpts, scales: { x: xAxis, y: axisY(2000, 7000) } },
            plugins: [bandPlugin]
        });
    }

    _limits() {
        let minB = 0, maxB = 100;
        if (this._hass && this.config && this.config.entity) {
            const attr = (this._hass.states[this.config.entity] || {}).attributes || {};
            if (attr.min_brightness !== undefined) minB = Number(attr.min_brightness);
            if (attr.max_brightness !== undefined) maxB = Number(attr.max_brightness);
        }
        return { minB, maxB };
    }

    _refreshCharts() {
        if (!this._chartB || !this._points.length) return;
        if (this._chartB.canvas.clientWidth > 0 && this._chartB.width !== this._chartB.canvas.clientWidth) this._chartB.resize();
        if (this._chartK.canvas.clientWidth > 0 && this._chartK.width !== this._chartK.canvas.clientWidth) this._chartK.resize();
        this._rebuildHandles();
        this._updateVisuals();
    }

    _rebuildHandles() {
        // Keep keyboard focus across the rebuild
        let focusedType = null;
        let focusedIdx = -1;
        const activeEl = this.shadowRoot.activeElement;
        if (activeEl && activeEl.classList.contains('handle')) {
            focusedType = activeEl.classList.contains('type-b') ? 'b' : 'k';
            focusedIdx = parseInt(activeEl.dataset.idx, 10);
        }

        ['b', 'k'].forEach(type => {
            const container = this.shadowRoot.getElementById(`handles-${type}`);
            container.innerHTML = '';
            this._points.forEach((pt, idx) => {
                const el = document.createElement('div');
                el.className = `handle type-${type}` + (idx === this._selected ? ' selected' : '');
                el.dataset.idx = idx;

                const tooltip = document.createElement('div');
                tooltip.className = 'handle-info';
                el.appendChild(tooltip);

                el.setAttribute('role', 'slider');
                el.setAttribute('tabindex', '0');
                el.setAttribute('aria-label', this._t(type === 'b' ? 'point_b' : 'point_k', { n: idx + 1 }));
                el.setAttribute('aria-valuemin', type === 'b' ? '0' : '2000');
                el.setAttribute('aria-valuemax', type === 'b' ? '100' : '7000');

                el.addEventListener('pointerdown', (e) => this._onDragStart(e, idx, type, el));
                el.addEventListener('keydown', (e) => this._onKeyDown(e, idx, type));
                el.addEventListener('focus', () => this._select(idx, false));
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

    // ------------------------------------------------------------ editing
    _pushUndo() {
        this._undo.push(JSON.stringify(this._points));
        if (this._undo.length > HCL_UNDO_LIMIT) this._undo.shift();
    }

    _undoLast() {
        if (!this._undo.length) return;
        this._points = JSON.parse(this._undo.pop());
        if (this._selected >= this._points.length) this._selected = -1;
        this._isDirty = JSON.stringify(this._points) !== this._lastPointsJSON;
        this._afterEdit(true);
    }

    _afterEdit(rebuild) {
        if (rebuild) this._rebuildHandles();
        this._updateVisuals();
        this._updateEditor();
        this._updateUIState();
    }

    _markChanged(rebuild = false) {
        this._isDirty = true;
        this._afterEdit(rebuild);
    }

    // Neighbour limits keep the points in chronological order (15-min grid)
    _timeBounds(idx) {
        const prev = idx > 0 ? this._points[idx - 1] : null;
        const next = idx < this._points.length - 1 ? this._points[idx + 1] : null;
        return {
            minT: prev ? prev.t + HCL_STEP : 0,
            maxT: next ? next.t - HCL_STEP : 1440,
        };
    }

    _select(idx, rebuild = true) {
        this._selected = idx;
        this.shadowRoot.querySelectorAll('.handle').forEach(el => {
            el.classList.toggle('selected', parseInt(el.dataset.idx, 10) === idx);
        });
        this._updateEditor();
        if (rebuild) this._updateVisuals();
    }

    _updateEditor() {
        if (!this.shadowRoot) return;
        const $ = (id) => this.shadowRoot.getElementById(id);
        const pt = this._points[this._selected];
        const has = !!pt;
        ['in-t', 'in-b', 'in-k'].forEach(id => { if ($(id)) $(id).disabled = !has; });
        if ($('btn-delete')) $('btn-delete').disabled = !has || this._points.length <= 2;
        if ($('btn-undo')) $('btn-undo').disabled = this._undo.length === 0;
        if ($('editor-hint')) $('editor-hint').style.display = has ? 'none' : '';
        if (has) {
            $('in-t').value = minToTime(Math.min(pt.t, 1439));
            $('in-b').value = Math.round(pt.b);
            $('in-k').value = Math.round(pt.k);
        } else if ($('in-t')) {
            $('in-t').value = ''; $('in-b').value = ''; $('in-k').value = '';
        }
    }

    _applyNumeric() {
        const idx = this._selected;
        const pt = this._points[idx];
        if (!pt) return;
        const $ = (id) => this.shadowRoot.getElementById(id);
        const [h, m] = ($('in-t').value || '').split(':').map(Number);
        const b = Number($('in-b').value);
        const k = Number($('in-k').value);
        if ([h, m, b, k].some(v => Number.isNaN(v))) { this._updateEditor(); return; }
        const { minT, maxT } = this._timeBounds(idx);
        this._pushUndo();
        pt.t = Math.max(minT, Math.min(maxT, Math.round((h * 60 + m) / HCL_STEP) * HCL_STEP));
        pt.b = Math.max(0, Math.min(100, Math.round(b)));
        pt.k = Math.max(2000, Math.min(7000, Math.round(k)));
        this._markChanged();
    }

    _insertPoint(t) {
        t = Math.max(0, Math.min(1440, Math.round(t / HCL_STEP) * HCL_STEP));
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
            const gap = ((next.t - p.t) + 1440) % 1440 || 1440;
            if (gap > best.gap) best = { gap, t: (p.t + gap / 2) % 1440 };
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
        const chart = e.target.id === 'chartB' ? this._chartB : this._chartK;
        if (!chart) return;
        const rect = e.target.getBoundingClientRect();
        this._insertPoint(chart.scales.x.getValueForPixel(e.clientX - rect.left));
    }

    _onKeyDown(e, idx, type) {
        const pt = this._points[idx];
        if (!pt) return;
        const shift = e.shiftKey ? 10 : 1;
        const { minT, maxT } = this._timeBounds(idx);
        let changed = false;

        switch (e.key) {
            case 'ArrowLeft':
                if (pt.t - HCL_STEP >= minT) { this._pushUndo(); pt.t -= HCL_STEP; changed = true; }
                break;
            case 'ArrowRight':
                if (pt.t + HCL_STEP <= maxT) { this._pushUndo(); pt.t += HCL_STEP; changed = true; }
                break;
            case 'ArrowUp':
                this._pushUndo();
                if (type === 'b') pt.b = Math.min(100, pt.b + shift);
                else pt.k = Math.min(7000, pt.k + (shift * 50));
                changed = true;
                break;
            case 'ArrowDown':
                this._pushUndo();
                if (type === 'b') pt.b = Math.max(0, pt.b - shift);
                else pt.k = Math.max(2000, pt.k - (shift * 50));
                changed = true;
                break;
            case 'Delete':
            case 'Backspace':
                e.preventDefault();
                this._deletePoint(idx);
                return;
        }

        if (changed) {
            e.preventDefault();
            this._selected = idx;
            this._markChanged();
            e.target.focus();
        }
    }

    _onDragStart(e, idx, type, el) {
        e.preventDefault();
        el.setPointerCapture(e.pointerId);
        this._isDragging = true;
        this._select(idx, false);
        this._pushUndo();
        let moved = false;
        const pt = this._points[idx];
        const chart = (type === 'b') ? this._chartB : this._chartK;
        const layer = this.shadowRoot.getElementById(`handles-${type}`);
        const rect = layer.getBoundingClientRect();

        const onMove = (ev) => {
            moved = true;
            const mx = ev.clientX - rect.left;
            const my = ev.clientY - rect.top;
            const yVal = chart.scales.y.getValueForPixel(my);
            const { minT, maxT } = this._timeBounds(idx);
            const rawT = chart.scales.x.getValueForPixel(mx);
            pt.t = Math.max(minT, Math.min(maxT, Math.round(rawT / HCL_STEP) * HCL_STEP));
            if (type === 'b') {
                pt.b = Math.round(Math.max(0, Math.min(100, yVal)));
            } else {
                pt.k = Math.round(Math.max(2000, Math.min(7000, yVal)));
            }
            if (!this._rafInFlight) {
                this._rafInFlight = true;
                requestAnimationFrame(() => {
                    this._updateVisuals();
                    this._rafInFlight = false;
                });
            }
            this._isDirty = true;
            this._updateUIState();
        };

        this._dragCleanup = () => {
            this._isDragging = false;
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            this._dragCleanup = null;
        };

        const onUp = () => {
            if (!moved) this._undo.pop(); // a click only selects the point
            if (this._dragCleanup) this._dragCleanup();
            this._updateEditor();
        };

        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
    }

    _saveCurve() {
        this._hass.callService('hcl_lighting', 'update_curve', {
            entity_id: this.config.entity,
            points: this._points,
            mode: 'save'
        });
        this._isDirty = false;
        this._updateUIState();
    }

    _revertCurve() {
        if (!confirm(this._t('confirm_revert'))) return;

        this._hass.callService('hcl_lighting', 'update_curve', {
            entity_id: this.config.entity,
            mode: 'revert'
        });

        // Show the last known state immediately; the backend update follows
        if (this._hass && this.config.entity) {
            const stateObj = this._hass.states[this.config.entity];
            if (stateObj && stateObj.attributes.control_points) {
                this._points = JSON.parse(JSON.stringify(stateObj.attributes.control_points));
                this._lastPointsJSON = "";
                this._undo = [];
                this._selected = -1;
                this._refreshCharts();
            }
        }
        this._isDirty = false;
        this._updateEditor();
        this._updateUIState();
    }

    _testCurve() {
        this._hass.callService('hcl_lighting', 'update_curve', {
            entity_id: this.config.entity,
            points: this._points,
            mode: 'preview'
        });
    }

    _applyPreset(name) {
        if (this._presets[name]) {
            this._pushUndo();
            this._points = JSON.parse(JSON.stringify(this._presets[name]));
            this._selected = -1;
            this._markChanged(true);
        }
    }

    // ------------------------------------------------------------ drawing
    _updateVisuals(retryCount = 0) {
        if (!this._chartB || !this._chartK) return;
        if (!this.isConnected) return;
        // Skip while the card is hidden (no layout)
        if (this.offsetParent === null && (!this._chartB.canvas || this._chartB.canvas.clientWidth === 0)) return;
        if (!this._points.length) return;

        const data = this._calculateCurve();
        const { minB, maxB } = this._limits();
        const clamped = data.b.map(b => Math.max(minB, Math.min(maxB, b)));
        const limited = clamped.some((b, i) => Math.abs(b - data.b[i]) > 0.5);

        this._chartB.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.b[i] }));
        this._chartB.data.datasets[1].data = limited ? data.t.map((t, i) => ({ x: t, y: clamped[i] })) : [];
        this._chartK.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.k[i] }));

        this._runValidation(data);
        this._updateValidationUI();

        this._chartB.update('none');
        this._chartK.update('none');

        const xAxis = this._chartB.scales.x;
        if (!xAxis || xAxis.width <= 0 || xAxis.getPixelForValue(0) === undefined) {
            if (retryCount < 50) {
                requestAnimationFrame(() => this._updateVisuals(retryCount + 1));
            }
            return;
        }

        this._points.forEach((pt, idx) => {
            this._syncHandle(idx, pt, 'b', this._chartB);
            this._syncHandle(idx, pt, 'k', this._chartK);
        });

        this._updateColorBar(data);
        this._updateNowInfo(minB, maxB);
    }

    _updateNowInfo(minB, maxB) {
        const el = this.shadowRoot.getElementById('now-info');
        if (!el || !this._points.length) return;
        const now = this._nowMinutes();
        const v = this._calculateCurveAt(now);
        const b = Math.round(Math.max(minB, Math.min(maxB, v.b)));
        el.textContent = `${this._t('now')} ${minToTime(now)} · ${b} % · ${Math.round(v.k)} K`;
    }

    _updateColorBar(data) {
        const bar = this.shadowRoot.getElementById('color-bar-gradient');
        if (!bar) return;
        const stops = [];
        for (let i = 0; i <= 96; i += 8) {
            stops.push(`${this._kelvinToRgb(data.k[i])} ${((i / 96) * 100).toFixed(1)}%`);
        }
        bar.style.background = `linear-gradient(90deg, ${stops.join(', ')})`;
    }

    _kelvinToRgb(k) {
        let temp = k / 100;
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

    _syncHandle(idx, pt, type, chart) {
        const el = this.shadowRoot.querySelector(`#handles-${type} .handle[data-idx="${idx}"]`);
        if (!el) return;
        const x = chart.scales.x.getPixelForValue(pt.t);
        const yVal = type === 'b' ? pt.b : pt.k;
        const y = chart.scales.y.getPixelForValue(yVal);
        el.style.transform = `translate(${x}px, ${y}px)`;
        const valText = type === 'b' ? `${Math.round(pt.b)} %` : `${Math.round(pt.k)} K`;
        el.setAttribute('aria-valuenow', yVal);
        el.setAttribute('aria-valuetext', `${minToTime(pt.t)}, ${valText}`);
        const tooltip = el.querySelector('.handle-info');
        if (tooltip) tooltip.textContent = `${minToTime(pt.t)} | ${valText}`;
    }

    _curveArrays() {
        const sorted = [...this._points].sort((a, b) => a.t - b.t);
        const X = [], B = [], K = [];
        [-1440, 0, 1440].forEach(offset => {
            sorted.forEach(pt => {
                X.push(pt.t + offset); B.push(pt.b); K.push(pt.k);
            });
        });
        return { X, B, K };
    }

    _calculateCurve() {
        const { X, B, K } = this._curveArrays();
        const res = { t: [], b: [], k: [] };
        for (let i = 0; i <= 96; i++) {
            const t = i * 15;
            res.t.push(t);
            res.b.push(this._pchip(t, X, B));
            res.k.push(this._pchip(t, X, K));
        }
        return res;
    }

    _calculateCurveAt(t) {
        const { X, B, K } = this._curveArrays();
        return { b: this._pchip(t, X, B), k: this._pchip(t, X, K) };
    }

    _pchip(tTarget, X, Y) {
        let i = 0;
        while (i < X.length - 2 && tTarget > X[i + 1]) i++;
        const t0 = X[i], t1 = X[i + 1];
        if (Math.abs(tTarget - t0) < 0.001) return Y[i];
        if (Math.abs(tTarget - t1) < 0.001) return Y[i + 1];
        const getPt = (idx) => ({ x: X[idx], y: Y[idx] });
        const curr = getPt(i);
        const next = getPt(i + 1);
        const prev = (i > 0) ? getPt(i - 1) : { x: curr.x - (next.x - curr.x), y: curr.y };
        const next_next = (i < X.length - 2) ? getPt(i + 2) : { x: next.x + (next.x - curr.x), y: next.y };
        const m0 = this._pchipSlope(prev, curr, next);
        const m1 = this._pchipSlope(curr, next, next_next);
        const h = t1 - t0;
        const t = (tTarget - t0) / h;
        return this._hermite(t, h, curr.y, next.y, m0, m1);
    }

    _pchipSlope(pPrev, pCurr, pNext) {
        const dt_left = pCurr.x - pPrev.x;
        const dt_right = pNext.x - pCurr.x;
        if (dt_left === 0 || dt_right === 0) return 0;
        const d_left = (pCurr.y - pPrev.y) / dt_left;
        const d_right = (pNext.y - pCurr.y) / dt_right;
        if (d_left * d_right <= 0) return 0;
        const w1 = 2 * dt_right + dt_left;
        const w2 = dt_right + 2 * dt_left;
        return (w1 + w2) / (w1 / d_left + w2 / d_right);
    }

    _hermite(t, h, y0, y1, m0, m1) {
        const t2 = t * t;
        const t3 = t2 * t;
        return (2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m0 + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * m1;
    }

    // ------------------------------------------------------------ validation
    _runValidation(data) {
        this._validationResult = { errors: [], warnings: [] };
        const V = this._validationResult;
        if (this._points.length < 2) {
            V.errors.push({ msg: this._t('val_min_points') });
        }
        let lastT = -1;
        let needsSanitize = false;
        const sorted = [...this._points].sort((a, b) => a.t - b.t);
        for (let i = 0; i < sorted.length; i++) {
            if (sorted[i].t === lastT) {
                V.errors.push({ msg: this._t('val_duplicate', { time: minToTime(sorted[i].t) }) });
                needsSanitize = true;
            }
            lastT = sorted[i].t;
        }
        for (let i = 0; i < this._points.length - 1; i++) {
            if (this._points[i].t > this._points[i + 1].t) {
                V.errors.push({ msg: this._t('val_unsorted') });
                needsSanitize = true;
                break;
            }
        }
        const btnSanitize = this.shadowRoot.getElementById('btn-sanitize');
        if (btnSanitize) btnSanitize.style.display = needsSanitize ? '' : 'none';
        if (V.errors.length > 0) return;

        for (let i = 0; i < data.t.length - 1; i++) {
            const dt = data.t[i + 1] - data.t[i];
            if (dt <= 0) continue;
            const slopeB = Math.abs(data.b[i + 1] - data.b[i]) / dt;
            const slopeK = Math.abs(data.k[i + 1] - data.k[i]) / dt;
            if (slopeB > this._valSettings.maxSlopeB) {
                V.warnings.push({ type: 'slope', msg: this._t('val_slope_b', { time: minToTime(data.t[i]) }), xMin: data.t[i], xMax: data.t[i + 1] });
            }
            if (slopeK > this._valSettings.maxSlopeK) {
                V.warnings.push({ type: 'slope', msg: this._t('val_slope_k', { time: minToTime(data.t[i]) }), xMin: data.t[i], xMax: data.t[i + 1] });
            }
        }

        let peakMinutes = 0;
        data.t.forEach((t, i) => {
            if (data.b[i] > 70 && data.k[i] > 5000) peakMinutes += 15;
        });

        if (peakMinutes < this._valSettings.minDailyPeakDuration) {
            const rangesNeedK = [];
            const rangesNeedB = [];
            const addRange = (list, t) => {
                if (list.length > 0 && t === list[list.length - 1].end) {
                    list[list.length - 1].end += 15;
                } else {
                    list.push({ start: t, end: t + 15 });
                }
            };
            data.t.forEach((t, i) => {
                const bHigh = data.b[i] > 70;
                const kHigh = data.k[i] > 5000;
                if (bHigh && !kHigh) addRange(rangesNeedK, t);
                if (kHigh && !bHigh) addRange(rangesNeedB, t);
            });
            let hasAdvice = false;
            rangesNeedK.forEach(r => {
                if (r.end - r.start >= 30) {
                    V.warnings.push({ type: 'peak', targetChart: 'k', msg: this._t('val_peak_k'), xMin: r.start, xMax: r.end });
                    hasAdvice = true;
                }
            });
            rangesNeedB.forEach(r => {
                if (r.end - r.start >= 30) {
                    V.warnings.push({ type: 'peak', targetChart: 'b', msg: this._t('val_peak_b'), xMin: r.start, xMax: r.end });
                    hasAdvice = true;
                }
            });
            if (!hasAdvice) {
                V.warnings.push({ type: 'peak', targetChart: 'b', msg: this._t('val_peak_short'), xMin: 600, xMax: 840 });
                V.warnings.push({ type: 'peak', targetChart: 'k', msg: this._t('val_peak_short'), xMin: 600, xMax: 840 });
            }
        }

        const isNight = (t) => t >= this._valSettings.nightStart || t < this._valSettings.nightEnd;
        const nightViolationsB = [];
        const nightViolationsK = [];
        data.t.forEach((t, i) => {
            if (isNight(t)) {
                if (data.b[i] > 10) nightViolationsB.push(t);
                if (data.k[i] > 3000) nightViolationsK.push(t);
            }
        });
        if (nightViolationsB.length > 2) this._addNightWarnings(nightViolationsB, 'b', 'val_night_b');
        if (nightViolationsK.length > 2) this._addNightWarnings(nightViolationsK, 'k', 'val_night_k');
    }

    _addNightWarnings(times, chartType, key) {
        if (times.length === 0) return;
        const push = (start, end) => this._validationResult.warnings.push({
            type: 'night', targetChart: chartType,
            msg: this._t(key, { from: minToTime(start), to: minToTime(end) }),
            xMin: start, xMax: end
        });
        let start = times[0];
        let prev = times[0];
        for (let i = 1; i < times.length; i++) {
            if (times[i] - prev > 15) {
                push(start, prev + 15);
                start = times[i];
            }
            prev = times[i];
        }
        push(start, prev + 15);
    }

    _getValidationAnnotations(chartType) {
        const list = [];
        const warn = this._theme ? this._theme.warning : '#ffa600';
        this._validationResult.warnings.forEach(w => {
            if (w.targetChart && w.targetChart !== chartType) return;
            if (w.xMin !== undefined && w.xMax !== undefined) {
                list.push({ xMin: w.xMin, xMax: w.xMax, color: this._withAlpha(warn, w.type === 'slope' ? 0.3 : 0.15) });
            }
        });
        return list;
    }

    _updateValidationUI() {
        const area = this.shadowRoot.getElementById('validation-area');
        const btnSave = this.shadowRoot.getElementById('btn-save');
        if (!area || !btnSave) return;

        // Only touch the DOM when the result changed
        const currentSig = JSON.stringify(this._validationResult);
        if (this._lastValidationSig === currentSig) return;
        this._lastValidationSig = currentSig;

        area.innerHTML = '';
        const add = (msg, cls) => {
            const div = document.createElement('div');
            div.className = `msg ${cls}`;
            div.textContent = msg;
            area.appendChild(div);
        };
        if (this._validationResult.errors.length > 0) {
            area.style.display = '';
            this._validationResult.errors.forEach(e => add(e.msg, 'error'));
            btnSave.disabled = true;
            return;
        }
        btnSave.disabled = false;
        if (this._validationResult.warnings.length > 0) {
            area.style.display = '';
            this._validationResult.warnings.forEach(w => add(w.msg, 'warning'));
        } else {
            area.style.display = 'none';
        }
    }

    _sanitizeCurve() {
        this._pushUndo();
        const newPoints = [...this._points].sort((a, b) => a.t - b.t);
        const unique = [];
        if (newPoints.length > 0) unique.push(newPoints[0]);
        for (let i = 1; i < newPoints.length; i++) {
            if (newPoints[i].t !== unique[unique.length - 1].t) unique.push(newPoints[i]);
        }
        this._points = unique;
        this._selected = -1;
        this._markChanged(true);
    }

    _updateUIState() {
        if (!this.shadowRoot) return;
        const btnTest = this.shadowRoot.getElementById('btn-test');
        const btnSave = this.shadowRoot.getElementById('btn-save');
        if (btnTest) {
            btnTest.classList.toggle('dirty', this._isDirty);
            btnTest.textContent = this._t('preview') + (this._isDirty ? ' *' : '');
        }
        if (btnSave) btnSave.classList.toggle('dirty', this._isDirty);
        const btnUndo = this.shadowRoot.getElementById('btn-undo');
        if (btnUndo) btnUndo.disabled = this._undo.length === 0;
    }
}

function minToTime(m) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

customElements.define('hcl-curve-card', HCLCurveCard);
window.customCards = window.customCards || [];
window.customCards.push({
    type: "hcl-curve-card",
    name: "HCL Curve Card",
    preview: true,
    description: "Interactive HCL Curve Editor"
});
