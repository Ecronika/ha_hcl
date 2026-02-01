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
    this._updatesPending = false;
    this._debouncer = null;
    this._isDragging = false;
    // Cache für JSON String um unnötige Cycles zu sparen
    this._lastPointsJSON = "";

    // Validator State
    this._validationResult = { errors: [], warnings: [] };

    // Settings for Validation
    this._valSettings = {
        nightStart: 1320, // 22:00
        nightEnd: 360,    // 06:00
        minDailyPeakDuration: 240, // 4 hours
        maxSlopeB: 2.0,   // % per min
        maxSlopeK: 100,   // K per min
        windDownDuration: 180 // 3 hours
    };

    // Presets: Scientifically inspired 12-point profiles
    // T: Minutes, B: Brightness (%), K: Kelvin
    this._presets = {
        // 1. DEFAULT: The "True" DIN-inspired Curve (v0.2.1 Replica)
        // Balance between Activation, Regeneration (Dip), and Sleep.
        "default": [
            { t: 420, b: 30, k: 2700 }, // 07:00 Wake
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
            { t: 1320, b: 10, k: 2200 }  // 22:00 Bedtime
        ],

        // 2. FOCUS (Work from Home): High Performance
        // Sustained high Kelvin for alertness, minimal dip to maintain concentration.
        "focus": [
            { t: 420, b: 30, k: 3500 }, // 07:00 Wake (Cold Shower)
            { t: 480, b: 80, k: 5500 }, // 08:00 Fast Ramp Up
            { t: 540, b: 100, k: 6500 }, // 09:00 Deep Work Start
            { t: 720, b: 100, k: 6500 }, // 12:00
            { t: 780, b: 80, k: 5500 }, // 13:00 Lunch (Brief relax, stay alert)
            { t: 840, b: 100, k: 6000 }, // 14:00 Afternoon Push
            { t: 1020, b: 80, k: 5500 }, // 17:00 End Work
            { t: 1080, b: 50, k: 3500 }, // 18:00 Transition
            { t: 1200, b: 30, k: 2700 }, // 20:00
            { t: 1320, b: 10, k: 2200 }, // 22:00
            { t: 1439, b: 5, k: 2000 }, // Midnight
            { t: 0, b: 5, k: 2000 }  // Loop
        ],

        // 3. RELAX (Wellness / Weekend): Hygge
        // Never exceeds 4500K. Softer brightness. Early warm evening.
        "relax": [
            { t: 480, b: 20, k: 2200 }, // 08:00 Slow Start
            { t: 600, b: 50, k: 3000 }, // 10:00
            { t: 720, b: 71, k: 5001 }, // 12:00 Max "Daylight" (Neutral)
            { t: 840, b: 71, k: 5001 }, // 14:00
            { t: 960, b: 70, k: 5001 }, // 16:00 Tea Time
            { t: 1080, b: 40, k: 2700 }, // 18:00
            { t: 1200, b: 30, k: 2200 }, // 20:00
            { t: 1260, b: 20, k: 2000 }, // 21:00 Fireplace
            { t: 1320, b: 10, k: 2000 }, // 22:00
            { t: 1439, b: 5, k: 2000 },
            { t: 0, b: 5, k: 2000 },
            { t: 315, b: 10, k: 2000 }
        ],

        // 4. EARLY BIRD: Default shifted -90 Minutes
        // Wake 05:30, Sleep 20:30
        "early_bird": [
            { t: 330, b: 30, k: 2700 }, // 05:30
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
            { t: 1230, b: 10, k: 2200 }  // 20:30 Sleep
        ],

        // 5. NIGHT OWL: Default shifted +120 Minutes
        // Wake 09:00, Sleep 00:00
        "night_owl": [
            { t: 540, b: 30, k: 2700 }, // 09:00
            { t: 660, b: 50, k: 4500 },
            { t: 690, b: 75, k: 5500 },
            { t: 720, b: 100, k: 6500 },
            { t: 840, b: 100, k: 6500 },
            { t: 870, b: 50, k: 4000 }, // 14:30 Lunch
            { t: 900, b: 50, k: 4000 },
            { t: 930, b: 75, k: 6000 },
            { t: 960, b: 75, k: 6000 },
            { t: 1080, b: 50, k: 4000 },
            { t: 1200, b: 30, k: 2700 }, // 20:00 Wind Down
            { t: 1440, b: 10, k: 2200 }  // 00:00 Sleep
        ]
    };
}

    set hass(hass) {
    this._hass = hass;
    if (!this.config || !this.config.entity) return;

    const stateObj = hass.states[this.config.entity];
    // Defensive check: stateObj existiert
    if (stateObj && stateObj.attributes.control_points) {
        if (!this._isDragging) {
            // Optimization: Referenz-Check zuerst, falls HA das Objekt cached
            const rawPoints = stateObj.attributes.control_points;

            // PERFORMANCE FIX: Check reference equality first
            if (this._rawPointsRef === rawPoints) return;

            const newPointsJSON = JSON.stringify(rawPoints);

            if (this._lastPointsJSON !== newPointsJSON) {
                this._points = JSON.parse(newPointsJSON);
                this._lastPointsJSON = newPointsJSON;
                this._rawPointsRef = rawPoints; // Cache Ref
                this._refreshCharts();
            }
        }
    }
}

setConfig(config) {
    if (!config.entity) {
        throw new Error('You need to define an entity (sensor.hcl_lighting_curve)');
    }
    this.config = config;
    this.attachShadow({ mode: 'open' });
}

getCardSize() {
    return 6;
}

    async connectedCallback() {
    // Robustness: Try/Catch for CDN load failure
    // Robustness: Try/Catch for CDN load failure
    if (!window.Chart) {
        try {
            // Local Import (Robustness)
            await import('/hcl_lighting_static/chart.js');
        } catch (e) {
            this.shadowRoot.innerHTML = `<ha-card style="padding:16px; color:red;">Error loading Chart.js: ${e.message}. Check integration installation.</ha-card>`;
            return;
        }
    }

    this.render();
    this._initialized = true;

    this._resizeObserver = new ResizeObserver(() => {
        // Perf: rAF um Resize-Loop Errors zu vermeiden
        requestAnimationFrame(() => {
            if (this._initialized && !this._isDragging) {
                if (this._chartB) this._chartB.resize();
                if (this._chartK) this._chartK.resize();
                this._updateVisuals();
            }
        });
    });

    const container = this.shadowRoot.querySelector('.charts-container');
    if (container) {
        this._resizeObserver.observe(container);
    }

    // Fallback Initialisierung
    setTimeout(() => this._refreshCharts(), 300);
}

// Neu: Cleanup beim Entfernen der Karte
// Neu: Cleanup beim Entfernen der Karte
disconnectedCallback() {
    if (this._resizeObserver) {
        this._resizeObserver.disconnect();
    }

    // Remove Event Listeners
    this.shadowRoot.getElementById('btn-sanitize')?.removeEventListener('click', this._boundSanitize);
    this.shadowRoot.getElementById('btn-save')?.removeEventListener('click', this._boundSave);
    this.shadowRoot.getElementById('btn-test')?.removeEventListener('click', this._boundTest);
    this.shadowRoot.getElementById('btn-revert')?.removeEventListener('click', this._boundRevert);
    this.shadowRoot.getElementById('preset-select')?.removeEventListener('change', this._boundPreset);

    // STABILITY FIX: Destroy charts to prevent memory leaks
    if (this._chartB) { this._chartB.destroy(); this._chartB = null; }
    if (this._chartK) { this._chartK.destroy(); this._chartK = null; }
    this._initialized = false;
}

render() {
    if (this.shadowRoot.innerHTML) return;

    this.shadowRoot.innerHTML = `
      <style>
          :host {
              display: block;
              --glass-bg: rgba(20, 20, 25, 0.6); /* Dunkler für Kontrast */
              --glass-border: rgba(255, 255, 255, 0.1);
              --chart-bg: rgba(0, 0, 0, 0.3);
              --accent-gold: #FFD700;
              --accent-blue: #00E5FF;
              --text-main: #ffffff;
              --text-muted: rgba(255, 255, 255, 0.4);
          }
          ha-card {
              background: var(--ha-card-background, var(--glass-bg));
              backdrop-filter: blur(20px);
              -webkit-backdrop-filter: blur(20px);
              border: 1px solid var(--glass-border);
              border-radius: 24px; /* Design Study Match */
              overflow: hidden;
              color: var(--text-main);
              padding-bottom: 16px;
              padding-bottom: 16px;
              position: relative; /* Anchor for absolute overlay */
          }
          /* Overlay Validation Messages */
          #validation-area {
              position: absolute;
              top: 76px; /* Below header */
              left: 24px; right: 24px;
              z-index: 20;
              pointer-events: none; /* Let clicks pass through to charts */
              display: flex;
              flex-direction: column;
              gap: 4px;
          }
          #validation-area > div {
              pointer-events: auto; /* Re-enable clicks on messages */
              box-shadow: 0 4px 12px rgba(0,0,0,0.5);
              backdrop-filter: blur(4px);
          }
              padding: 20px 24px;
              display: flex;
              justify-content: space-between;
              align-items: center;
              border-bottom: 1px solid rgba(255,255,255,0.05);
              margin-bottom: 16px;
          }
          .controls-row {
              display: flex;
              gap: 12px;
              align-items: center;
              flex-wrap: wrap;
          }
          /* "Pill" Buttons wie im Design */
          button, select {
              background: rgba(255, 255, 255, 0.05);
              border: 1px solid rgba(255, 255, 255, 0.1);
              color: rgba(255, 255, 255, 0.8);
              padding: 6px 16px;
              border-radius: 20px; /* Pill shape */
              font-size: 12px;
              font-weight: 500;
              cursor: pointer;
              text-transform: uppercase;
              letter-spacing: 0.5px;
              transition: all 0.2s ease;
          }
          button:hover, select:hover {
              background: rgba(255, 255, 255, 0.15);
              border-color: rgba(255, 255, 255, 0.3);
              color: #fff;
          }
          /* FIX: Dropdown Option Styling (Robust) */
          select {
             background: rgba(20, 20, 25, 0.95); /* Contrast against Glass */
             border: 1px solid rgba(255, 255, 255, 0.1);
             color: var(--text-main); 
          }
          option {
             background-color: #1a1a1a; /* Safety for Safari/Mobile */
             color: white;
          }

          /* Tooltip for Handles */
          .handle-info {
             position: absolute;
             bottom: 18px; 
             left: 50%;
             transform: translateX(-50%);
             background: rgba(10, 10, 15, 0.9);
             border: 1px solid rgba(255, 255, 255, 0.2);
             padding: 4px 8px;
             border-radius: 6px;
             font-size: 10px;
             font-family: monospace;
             color: white;
             white-space: nowrap;
             opacity: 0; 
             pointer-events: none;
             transition: opacity 0.2s;
             z-index: 100;
             box-shadow: 0 4px 8px rgba(0,0,0,0.5);
          }
          .handle:hover .handle-info,
          .handle:active .handle-info,
          .handle:focus .handle-info {
              opacity: 1;
          }
          
          /* Responsive Grid: Nebeneinander wenn Platz, sonst untereinander */
          .charts-container {
              padding: 0 20px;
              display: grid;
              grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
              gap: 20px;
              /* touch-action: none; Removed to allow scrolling on background */
          }
          .chart-wrapper {
              position: relative;
              height: 240px;
              background: var(--chart-bg);
              border-radius: 20px;
              border: 1px solid rgba(255, 255, 255, 0.05);
              padding: 16px; /* Wichtig für Alignment */
          }
          /* Overlay Labels (Brightness/Temp) */
          .chart-label {
              position: absolute;
              top: 16px; left: 24px;
              font-size: 11px;
              color: var(--text-muted);
              text-transform: uppercase;
              letter-spacing: 1px;
              font-weight: 600;
              pointer-events: none;
              z-index: 5;
          }
          canvas { width: 100%; height: 100%; display: block; }
          
          /* Handles: Glow Effects */
          .handle-layer {
              position: absolute;
              top: 16px; left: 16px; right: 16px; bottom: 16px; /* Muss Padding matchen */
              pointer-events: none;
              overflow: visible;
          }
          .handle {
              position: absolute;
              width: 12px; height: 12px;
              border-radius: 50%;
              /* transform: translate(-50%, -50%); REMOVED for GPU Drag Performance */
              margin-left: -6px; margin-top: -6px; /* Centering replacement */
              cursor: grab;
              pointer-events: auto;
              z-index: 10;
              transition: width 0.1s, height 0.1s;
              touch-action: none; /* Only disable scroll on handles */
          }
          /* Increase Hit Area for Touch */
          .handle::after {
              content: '';
              position: absolute;
              top: -10px; right: -10px; bottom: -10px; left: -10px;
          }
          .handle:hover { transform: translate(-50%, -50%) scale(1.3); }
          .handle:active { cursor: grabbing; }
          /* Spezifische Glows aus Design */
          .handle.type-b { 
              background: var(--accent-gold); 
              box-shadow: 0 0 0 2px rgba(0,0,0,0.5), 0 0 10px rgba(255, 215, 0, 0.6); 
          }
          .handle.type-k { 
              background: var(--accent-blue); 
              box-shadow: 0 0 0 2px rgba(0,0,0,0.5), 0 0 10px rgba(0, 229, 255, 0.6); 
          }

          /* Footer / Color Bar */
          .footer-section {
              margin-top: 20px;
              padding: 0 24px;
          }
          .color-bar {
              height: 8px;
              border-radius: 4px;
              width: 100%;
              box-shadow: 0 0 10px rgba(0,0,0,0.3);
              border: 1px solid rgba(255,255,255,0.1);
          }
          .axis-labels {
              display: flex;
              justify-content: space-between;
              margin-top: 6px;
              font-size: 10px;
              color: var(--text-muted);
              font-family: monospace;
          }
      </style>
      <ha-card>
          <div class="card-header">
             <div class="controls-row">
                 <span style="font-weight:600; font-size:16px;">HCL Configurator</span>
                 <select id="preset-select" aria-label="Presets">
                   <option value="" disabled selected>PRESETS</option>
                   <option value="default">Default (Balanced)</option>
                   <option value="focus">Focus (Home Office)</option>
                   <option value="relax">Relax (Wellness)</option>
                   <option value="early_bird">Early Bird</option>
                   <option value="night_owl">Night Owl</option>
                 </select>
             </div>
             <div class="controls-row">
                <button id="btn-sanitize" title="Fix sorting/duplicates" style="display:none;">FIX</button>
                 <button id="btn-revert" title="Discard unsaved changes">REVERT</button>
                <button id="btn-test" title="Apply without saving">TEST</button>
                <button id="btn-save" title="Save to disk" style="border-color:var(--accent-blue); color:var(--accent-blue);">SAVE</button>
             </div>
          </div>

          <!-- Validation Messages -->
                      <!-- Validation Messages (Overlay) -->
           <div id="validation-area" style="display: none;"></div>

           <div class="charts-container">
             <div class="chart-wrapper">
                 <span class="chart-label">Brightness</span>
                 <canvas id="chartB"></canvas>
                 <div class="handle-layer" id="handles-b"></div>
             </div>
             
             <div class="chart-wrapper">
                 <span class="chart-label">Color Temp</span>
                 <canvas id="chartK"></canvas>
                 <div class="handle-layer" id="handles-k"></div>
             </div>
          </div>

          <div class="footer-section">
              <div class="color-bar" id="color-bar-gradient"></div>
              <div class="axis-labels">
                  <span>00:00</span>
                  <span>06:00</span>
                  <span>12:00</span>
                  <span>18:00</span>
                  <span>24:00</span>
              </div>
          </div>
      </ha-card>
    `;

    // Bind Controls (Store references for cleanup)
    this._boundSanitize = () => this._sanitizeCurve();
    this._boundSave = () => this._saveCurve();
    this._boundTest = () => this._testCurve();
    this._boundRevert = () => this._revertCurve();
    this._boundPreset = (e) => {
        this._applyPreset(e.target.value);
        e.target.value = ""; // Reset dropdown
    };

    this.shadowRoot.getElementById('btn-sanitize').addEventListener('click', this._boundSanitize);
    this.shadowRoot.getElementById('btn-save').addEventListener('click', this._boundSave);
    this.shadowRoot.getElementById('btn-test').addEventListener('click', this._boundTest);
    this.shadowRoot.getElementById('btn-revert').addEventListener('click', this._boundRevert);
    this.shadowRoot.getElementById('preset-select').addEventListener('change', this._boundPreset);

    // Initialize Charts
    this._initCharts();
}

_initCharts() {
    const commonOpts = {
        responsive: true, maintainAspectRatio: false, animation: false,
        layout: { padding: 0 },
        scales: {
            x: { type: 'linear', min: 0, max: 1440, display: false },
            y: { display: true, position: 'right', grid: { color: 'rgba(255,255,255,0.05)' } }
        },
        plugins: {
            legend: false, tooltip: false,
            annotation: {
                annotations: {}, // Will be populated dynamically
                common: {
                    drawTime: 'beforeDatasetsDraw',
                }
            }
        }
    };

    // Register inline plugin for Shading + Validation Backgrounds
    const customBackgroundPlugin = {
        id: 'customBackground',
        beforeDraw: (chart) => {
            const ctx = chart.ctx;
            const yAxis = chart.scales.y;
            const xAxis = chart.scales.x;

            // 1. Min/Max Shading (Legacy Logic)
            if (chart.canvas.id === 'chartB') {
                // Get Limits
                let minB = 0; let maxB = 100;
                if (this._hass && this.config && this.config.entity) {
                    const attr = this._hass.states[this.config.entity].attributes;
                    if (attr.min_brightness !== undefined) minB = attr.min_brightness;
                    if (attr.max_brightness !== undefined) maxB = attr.max_brightness;
                }
                ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
                if (maxB < 100) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(100), xAxis.width, yAxis.getPixelForValue(maxB) - yAxis.getPixelForValue(100));
                if (minB > 0) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(minB), xAxis.width, yAxis.getPixelForValue(0) - yAxis.getPixelForValue(minB));
            }

            // 2. Validation Highlights (Visual Feedback)
            // We draw these on both charts if relevant
            const annotations = this._getValidationAnnotations(chart.canvas.id === 'chartB' ? 'b' : 'k');
            annotations.forEach(anno => {
                ctx.fillStyle = anno.color;
                const xStart = xAxis.getPixelForValue(anno.xMin);
                const xEnd = xAxis.getPixelForValue(anno.xMax);

                // Allow wrapping (drawing 2 boxes if needed)
                // Simplified: just drawing simple range for now.
                // If xMin > xMax (wrap), draw two boxes?
                if (anno.xMin > anno.xMax) {
                    // Wrap Case: xMin->1440 AND 0->xMax
                    ctx.fillRect(xStart, yAxis.top, xAxis.right - xStart, yAxis.bottom - yAxis.top);
                    ctx.fillRect(xAxis.left, yAxis.top, xAxis.getPixelForValue(anno.xMax) - xAxis.left, yAxis.bottom - yAxis.top);
                } else {
                    ctx.fillRect(xStart, yAxis.top, xEnd - xStart, yAxis.bottom - yAxis.top);
                }
            });
        }
    };

    // Register inline plugin

    const ctxB = this.shadowRoot.getElementById('chartB').getContext('2d');
    this._chartB = new Chart(ctxB, {
        type: 'line',
        data: { datasets: [{ data: [], borderColor: '#FFD700', fill: true, backgroundColor: 'rgba(255,215,0,0.1)', tension: 0.4 }] },
        options: {
            ...commonOpts,
            elements: { point: { radius: 0, hoverRadius: 0 }, line: { borderWidth: 2, tension: 0.4 } },
            scales: { ...commonOpts.scales, y: { min: 0, max: 100, ...commonOpts.scales.y } }
        },
        plugins: [customBackgroundPlugin]
    });

    const ctxK = this.shadowRoot.getElementById('chartK').getContext('2d');
    this._chartK = new Chart(ctxK, {
        type: 'line',
        data: { datasets: [{ data: [], borderColor: '#00E5FF', fill: true, backgroundColor: 'rgba(0,229,255,0.1)', tension: 0.4 }] },
        options: {
            ...commonOpts,
            elements: { point: { radius: 0, hoverRadius: 0 }, line: { borderWidth: 2, tension: 0.4 } },
            scales: { ...commonOpts.scales, y: { min: 2000, max: 7000, ...commonOpts.scales.y } }
        }
    });
}

_refreshCharts() {
    if (!this._chartB || !this._points.length) return;

    this._rebuildHandles(); // Only if points changed
    this._updateVisuals();
}

_rebuildHandles() {
    ['b', 'k'].forEach(type => {
        const container = this.shadowRoot.getElementById(`handles-${type}`);
        container.innerHTML = ''; // Reset for now to ensure clean state with correct indices

        this._points.forEach((pt, idx) => {
            const el = document.createElement('div');
            el.className = `handle type-${type}`;
            el.dataset.idx = idx;

            // Tooltip Element
            const tooltip = document.createElement('div');
            tooltip.className = 'handle-info';

            // Initial Text
            const valText = type === 'b' ? `${Math.round(pt.b)}%` : `${Math.round(pt.k)}K`;
            tooltip.innerText = `${minToTime(pt.t)} | ${valText}`;

            el.appendChild(tooltip);

            // Accessibility Attributes
            el.setAttribute('role', 'slider');
            el.setAttribute('tabindex', '0');
            el.setAttribute('aria-label', `${type === 'b' ? 'Brightness' : 'Kelvin'} Point ${idx + 1}`);
            el.setAttribute('aria-valuemin', type === 'b' ? '0' : '2000');
            el.setAttribute('aria-valuemax', type === 'b' ? '100' : '7000');
            el.setAttribute('aria-valuenow', type === 'b' ? pt.b : pt.k);
            el.setAttribute('aria-valuetext', `${minToTime(pt.t)}, ${type === 'b' ? pt.b + '%' : pt.k + 'K'}`);

            // Mouse/Touch Interaction
            el.addEventListener('pointerdown', (e) => this._onDragStart(e, idx, type, el));

            // Keyboard Interaction
            el.addEventListener('keydown', (e) => this._onKeyDown(e, idx, type));

            container.appendChild(el);
        });
    });
}

_onKeyDown(e, idx, type) {
    const pt = this._points[idx];
    let changed = false;
    const shift = e.shiftKey ? 10 : 1; // Modifier for faster movement

    switch (e.key) {
        case 'ArrowLeft': pt.t = Math.max(0, pt.t - 15); changed = true; break;
        case 'ArrowRight': pt.t = Math.min(1440, pt.t + 15); changed = true; break;
        case 'ArrowUp':
            if (type === 'b') pt.b = Math.min(100, pt.b + shift);
            else pt.k = Math.min(7000, pt.k + (shift * 50));
            changed = true;
            break;
        case 'ArrowDown':
            if (type === 'b') pt.b = Math.max(0, pt.b - shift);
            else pt.k = Math.max(2000, pt.k - (shift * 50));
            changed = true;
            break;
    }

    if (changed) {
        e.preventDefault();
        this._updateVisuals();
        this._schedulePreview();
        // Focus behalten
        e.target.focus();
    }
}

_onDragStart(e, idx, type, el) {
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    this._isDragging = true;

    // Fix: Variable pt definieren!
    const pt = this._points[idx];

    // Visual feedback for grabbing not strictly needed via class if cursor: grabbing works, 
    // but beneficial for state tracking.

    const chart = (type === 'b') ? this._chartB : this._chartK;
    const layer = this.shadowRoot.getElementById(`handles-${type}`);
    const rect = layer.getBoundingClientRect();

    const onMove = (ev) => {
        // throttle via rAF not strictly needed for mouse move, but good practice
        const mx = ev.clientX - rect.left;
        const my = ev.clientY - rect.top;

        const tVal = chart.scales.x.getValueForPixel(mx);
        const yVal = chart.scales.y.getValueForPixel(my);

        // Drag Constraint: Min Distance to Neighbors
        const prevPoint = idx > 0 ? this._points[idx - 1] : null;
        const nextPoint = idx < this._points.length - 1 ? this._points[idx + 1] : null;

        const minT = prevPoint ? prevPoint.t + 15 : 0;
        const maxT = nextPoint ? nextPoint.t - 15 : 1440; // Hard max, can be 1440

        const rawT = chart.scales.x.getValueForPixel(mx);
        // Snap & Clamp
        let newT = Math.round(rawT / 15) * 15;
        newT = Math.max(minT, Math.min(maxT, newT));

        this._points[idx].t = newT;

        if (type === 'b') {
            pt.b = Math.round(Math.max(0, Math.min(100, yVal)));
        } else {
            pt.k = Math.round(Math.max(2000, Math.min(7000, yVal)));
        }

        // Performance: Throttle visual updates to screen refresh rate
        if (!this._rafInFlight) {
            this._rafInFlight = true;
            requestAnimationFrame(() => {
                this._updateVisuals();
                this._rafInFlight = false;
            });
        }
        this._schedulePreview();
    };

    const onUp = () => {
        this._isDragging = false;
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        // Save final state logic if needed, or just leave at preview
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
}

_schedulePreview() {
    if (this._debouncer) clearTimeout(this._debouncer);
    this._debouncer = setTimeout(() => {
        this._hass.callService('hcl_lighting', 'update_curve', {
            entity_id: this.config.entity,
            points: this._points,
            mode: 'preview'
        });
    }, 100); // 100ms debounce
}

_saveCurve() {
    this._hass.callService('hcl_lighting', 'update_curve', {
        entity_id: this.config.entity,
        points: this._points,
        mode: 'save'
    });
}

_revertCurve() {
    if (!confirm('Discard all unsaved changes and reload from disk?')) return;
    this._hass.callService('hcl_lighting', 'update_curve', {
        entity_id: this.config.entity,
        mode: 'revert'
    });
}

_testCurve() {
    this._hass.callService('hcl_lighting', 'update_curve', {
        entity_id: this.config.entity,
        points: this._points,
        mode: 'apply', // Apply runtime state
        // driving lights is implicit in apply mode usually, or we can explicit it if backed supports
    });
}

_applyPreset(name) {
    if (this._presets[name]) {
        // Deep copy to break references
        this._points = JSON.parse(JSON.stringify(this._presets[name]));
        this._refreshCharts();
        this._schedulePreview();
    }
}

_updateVisuals(retryCount = 0) {
    if (!this._chartB || !this._chartK) return; // Guard

    // STABILITY FIX: Guard against disconnected state
    if (!this.isConnected) return;

    const data = this._calculateCurve();

    this._chartB.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.b[i] }));
    this._chartK.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.k[i] }));

    // Update Validation UI
    this._runValidation(data);
    this._updateValidationUI();

    // Diagramme aktualisieren
    this._chartB.update('none');
    this._chartK.update('none');

    // NEU: Sicherstellen, dass die Scales fertig berechnet sind
    // Wenn getPixelForValue(0) immer noch 0 liefert, ist das Chart noch nicht bereit
    const xAxis = this._chartB.scales.x;
    // Robust check: width must be > 0 and scale initialized
    if (!xAxis || xAxis.width <= 0 || xAxis.getPixelForValue(0) === undefined) {
        // STABILITY FIX: Prevent infinite loop if card is hidden or layout fails
        if (retryCount < 50) {
            requestAnimationFrame(() => this._updateVisuals(retryCount + 1));
        } else {
            console.warn("HCL Card: Chart scaling timed out or card hidden.");
        }
        return;
    }

    // Jetzt erst Handles synchronisieren
    this._points.forEach((pt, idx) => {
        this._syncHandle(idx, pt, 'b', this._chartB);
        this._syncHandle(idx, pt, 'k', this._chartK);
    });

    // Update Color Bar Gradient
    this._updateColorBar(data);
}

_updateColorBar(data) {
    const bar = this.shadowRoot.getElementById('color-bar-gradient');
    if (!bar) return;

    // Create CSS Gradient from PCHIP data (approximate)
    // We pick ~10 stops to keep style string short but accurate
    const stops = [];
    for (let i = 0; i <= 96; i += 8) { // Every 2 hours (8 * 15m)
        const k = data.k[i];
        const percent = (i / 96) * 100;
        stops.push(`${this._kelvinToRgb(k)} ${percent.toFixed(1)}%`);
    }
    bar.style.background = `linear-gradient(90deg, ${stops.join(', ')})`;
}

_kelvinToRgb(k) {
    // Simple approx algorithm or just map to predefined colors
    // Using a cheap approximation for UI feedback
    let temp = k / 100;
    let r, g, b;

    if (temp <= 66) {
        r = 255;
        g = temp;
        g = 99.4708025861 * Math.log(g) - 161.1195681661;
        if (temp <= 19) b = 0;
        else {
            b = temp - 10;
            b = 138.5177312231 * Math.log(b) - 305.0447927307;
        }
    } else {
        r = temp - 60;
        r = 329.698727446 * Math.pow(r, -0.1332047592);
        g = temp - 60;
        g = 288.1221695283 * Math.pow(g, -0.0755148492);
        b = 255;
    }
    return `rgb(${Math.min(255, Math.max(0, r))}, ${Math.min(255, Math.max(0, g))}, ${Math.min(255, Math.max(0, b))})`;
}

_syncHandle(idx, pt, type, chart) {
    const el = this.shadowRoot.querySelector(`#handles-${type} .handle[data-idx="${idx}"]`);
    if (!el) return;

    const x = chart.scales.x.getPixelForValue(pt.t);
    const yVal = type === 'b' ? pt.b : pt.k;
    const y = chart.scales.y.getPixelForValue(yVal);

    // PERFORMANCE FIX: Use transform for GPU composition instead of layout reflow
    el.style.transform = `translate(${x}px, ${y}px)`;
    // el.style.left = ... (removed)
    // el.style.top = ... (removed)

    // A11y Update
    el.setAttribute('aria-valuenow', yVal);
    el.setAttribute('aria-valuetext', `${minToTime(pt.t)}, ${type === 'b' ? pt.b + '%' : pt.k + 'K'}`);

    // Update Tooltip
    const tooltip = el.querySelector('.handle-info');
    if (tooltip) {
        const valText = type === 'b' ? `${Math.round(pt.b)}%` : `${Math.round(pt.k)}K`;
        tooltip.innerText = `${minToTime(pt.t)} | ${valText}`;
    }
}

// --- PCHIP Logic (Ported from Dashboard) ---
_calculateCurve() {
    let sorted = [...this._points].sort((a, b) => a.t - b.t);
    let X = [], B = [], K = [];

    [-1440, 0, 1440].forEach(offset => {
        sorted.forEach(pt => {
            X.push(pt.t + offset); B.push(pt.b); K.push(pt.k);
        });
    });

    let res = { t: [], b: [], k: [] };
    for (let i = 0; i <= 96; i++) {
        let t = i * 15;
        res.t.push(t);
        res.b.push(this._pchip(t, X, B));
        res.k.push(this._pchip(t, X, K));
    }
    return res;
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


// --- Validator Engine (v0.4.0-rc4) ---
_runValidation(data) {
    this._validationResult = { errors: [], warnings: [] };

    // 1. Technical Errors
    if (this._points.length < 2) {
        this._validationResult.errors.push({ msg: "Curve needs at least 2 points." });
    }

    // Check for duplicates/unsorted
    let lastT = -1;
    let needsSanitize = false;

    // Copy and sort for logic check
    const sorted = [...this._points].sort((a, b) => a.t - b.t);

    for (let i = 0; i < sorted.length; i++) {
        if (sorted[i].t === lastT) {
            this._validationResult.errors.push({ msg: `Duplicate time at ${minToTime(sorted[i].t)}.` });
            needsSanitize = true;
        }
        lastT = sorted[i].t;
    }

    // Check original order
    for (let i = 0; i < this._points.length - 1; i++) {
        if (this._points[i].t > this._points[i + 1].t) {
            this._validationResult.errors.push({ msg: "Points are not sorted by time." });
            needsSanitize = true;
            break;
        }
    }

    const btnSanitize = this.shadowRoot.getElementById('btn-sanitize');
    if (btnSanitize) btnSanitize.style.display = needsSanitize ? 'block' : 'none';

    if (this._validationResult.errors.length > 0) return; // Stop if hard errors

    // 2. HCL Heuristics

    // A) Steilheit Check (Slopes)
    for (let i = 0; i < data.t.length - 1; i++) {
        const dt = data.t[i + 1] - data.t[i];
        if (dt <= 0) continue;

        const slopeB = Math.abs(data.b[i + 1] - data.b[i]) / dt;
        const slopeK = Math.abs(data.k[i + 1] - data.k[i]) / dt;

        if (slopeB > this._valSettings.maxSlopeB) {
            this._validationResult.warnings.push({
                type: 'slope',
                msg: `Brightness jump too steep (>2%/min) at ${minToTime(data.t[i])}`,
                xMin: data.t[i], xMax: data.t[i + 1]
            });
        }
        if (slopeK > this._valSettings.maxSlopeK) {
            this._validationResult.warnings.push({
                type: 'slope',
                msg: `Color Temp jump too steep (>100K/min) at ${minToTime(data.t[i])}`,
                xMin: data.t[i], xMax: data.t[i + 1]
            });
        }
    }

    // B) Daily Peak Check
    let peakMinutes = 0;
    data.t.forEach((t, i) => {
        if (data.b[i] > 70 && data.k[i] > 5000) {
            peakMinutes += 15; // Resolution is 15m
        }
    });

    if (peakMinutes < this._valSettings.minDailyPeakDuration) {
        // Smart Strategy: Find "Mismatches" to guide user
        // 1. High Brightness (>70%), Low Kelvin (<=5000) -> Needs more K
        // 2. High Kelvin (>5000), Low Brightness (<=70) -> Needs more B

        let rangesNeedK = [];
        let rangesNeedB = [];

        // Helper to add ranges
        const addRange = (list, t) => {
            if (list.length > 0 && t === list[list.length - 1].end) {
                list[list.length - 1].end += 15; // Extend
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
            if (r.end - r.start >= 30) { // Only warn for significant blocks (>30m)
                this._validationResult.warnings.push({
                    type: 'peak', targetChart: 'k',
                    msg: `Active Phase: Temp too low here. Increase to >5000K.`,
                    xMin: r.start, xMax: r.end
                });
                hasAdvice = true;
            }
        });

        rangesNeedB.forEach(r => {
            if (r.end - r.start >= 30) {
                this._validationResult.warnings.push({
                    type: 'peak', targetChart: 'b',
                    msg: `Active Phase: Brightness too low here. Increase to >70%.`,
                    xMin: r.start, xMax: r.end
                });
                hasAdvice = true;
            }
        });

        if (!hasAdvice) {
            // Fallback: Just mark the middle of the day (10:00 - 14:00) as a suggestion
            this._validationResult.warnings.push({
                type: 'peak', targetChart: 'b',
                msg: `Active Phase too short (<4h). Try high B/K around noon.`,
                xMin: 600, xMax: 840
            });
            this._validationResult.warnings.push({
                type: 'peak', targetChart: 'k',
                msg: `Active Phase too short (<4h). Try high B/K around noon.`,
                xMin: 600, xMax: 840
            });
        }
    }

    // C) Night Checks (Sleep Window)
    const isNight = (t) => t >= this._valSettings.nightStart || t < this._valSettings.nightEnd;
    let nightViolationsB = [];
    let nightViolationsK = [];

    data.t.forEach((t, i) => {
        if (isNight(t)) {
            if (data.b[i] > 10) nightViolationsB.push(t); // > 10%
            if (data.k[i] > 3000) nightViolationsK.push(t); // > 3000K
        }
    });

    if (nightViolationsB.length > 2) {
        // Group into ranges
        this._addNightWarnings(nightViolationsB, 'b', 'bright', '>10%');
    }
    if (nightViolationsK.length > 2) {
        this._addNightWarnings(nightViolationsK, 'k', 'cold', '>3000K');
    }
}

_addNightWarnings(times, chartType, typeLabel, valLabel) {
    if (times.length === 0) return;
    // Simple clustering: if diff > 15, start new block
    let start = times[0];
    let prev = times[0];

    for (let i = 1; i < times.length; i++) {
        if (times[i] - prev > 15) {
            // End of block
            this._validationResult.warnings.push({
                type: 'night',
                targetChart: chartType,
                msg: `Night too ${typeLabel} (${valLabel}) at ${minToTime(start)}-${minToTime(prev + 15)}.`,
                xMin: start, xMax: prev + 15
            });
            start = times[i];
        }
        prev = times[i];
    }
    // Last block
    this._validationResult.warnings.push({
        type: 'night',
        targetChart: chartType,
        msg: `Night too ${typeLabel} (${valLabel}) at ${minToTime(start)}-${minToTime(prev + 15)}.`,
        xMin: start, xMax: prev + 15
    });
}

_getValidationAnnotations(chartType) {
    // chartType: 'b' (Brightness) or 'k' (Kelvin)
    const list = [];
    this._validationResult.warnings.forEach(w => {
        // 1. Filter by Chart Specifics
        if (w.targetChart && w.targetChart !== chartType) return;

        // 2. Add Annotation
        if (w.xMin !== undefined && w.xMax !== undefined) {
            let color = 'rgba(255, 165, 0, 0.15)'; // Default orange
            if (w.type === 'slope') color = 'rgba(255, 69, 0, 0.3)'; // Red-Orange

            list.push({ xMin: w.xMin, xMax: w.xMax, color });
        }
    });
    return list;
}

_updateValidationUI() {
    const area = this.shadowRoot.getElementById('validation-area');
    const btnSave = this.shadowRoot.getElementById('btn-save');

    if (!area || !btnSave) return;

    // Security: Escape HTML to prevent XSS
    const escapeHtml = (unsafe) => {
        return String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    };

    if (this._validationResult.errors.length > 0) {
        area.style.display = 'block';
        area.innerHTML = this._validationResult.errors.map(e =>
            `<div style="background:rgba(255,0,0,0.2); border-left:4px solid red; padding:8px; margin-bottom:4px; font-size:12px;">🚫 ${escapeHtml(e.msg)}</div>`
        ).join('');
        btnSave.disabled = true;
        btnSave.style.opacity = 0.5;
        return;
    }

    btnSave.disabled = false;
    btnSave.style.opacity = 1;

    if (this._validationResult.warnings.length > 0) {
        area.style.display = 'block';
        area.innerHTML = this._validationResult.warnings.map(w =>
            `<div style="background:rgba(255,165,0,0.2); border-left:4px solid orange; padding:8px; margin-bottom:4px; font-size:12px;">⚠️ ${escapeHtml(w.msg)}</div>`
        ).join('');
    } else {
        area.style.display = 'none';
    }
}

_sanitizeCurve() {
    // Fix Sorting & Duplicates
    let newPoints = [...this._points];

    // 1. Sort
    newPoints.sort((a, b) => a.t - b.t);

    // 2. Dedupe
    const unique = [];
    if (newPoints.length > 0) unique.push(newPoints[0]);
    for (let i = 1; i < newPoints.length; i++) {
        if (newPoints[i].t !== unique[unique.length - 1].t) {
            unique.push(newPoints[i]);
        }
    }

    this._points = unique;
    this._refreshCharts();
    this._schedulePreview();
}
}

// Helper Funktion muss im Scope oder in der Klasse sein
function minToTime(m) {
    let h = Math.floor(m / 60);
    let min = m % 60;
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
