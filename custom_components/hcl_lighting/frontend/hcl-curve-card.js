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
        this._boundPreset = (e) => {
            this._applyPreset(e.target.value);
            e.target.value = "";
        };
    }

    set hass(hass) {
        this._hass = hass;
        if (!this.config || !this.config.entity) return;

        const stateObj = hass.states[this.config.entity];
        if (stateObj && stateObj.attributes.control_points) {
            // Existing check: if (!this._isDragging)
            if (!this._isDragging) {
                const rawPoints = stateObj.attributes.control_points;

                // PERF-FIX: Reference check first to avoid expensive JSON.stringify
                if (this._rawPointsRef === rawPoints) return;

                // OPTIMIZATION: Strict deep equality check before parsing/rendering
                // This prevents re-renders when other attributes of the sensor change (e.g. timestamp)
                const newPointsJSON = JSON.stringify(rawPoints);
                if (this._lastPointsJSON !== newPointsJSON) {
                    // Logic to update local state
                    this._points = JSON.parse(newPointsJSON);
                    this._lastPointsJSON = newPointsJSON;
                    this._rawPointsRef = rawPoints;
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

        this._resizeObserver = new ResizeObserver((entries) => {
            // Check visibility explicitly
            if (!entries.length || entries[0].contentRect.width === 0) return;

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

        // Initialize Charts Forcefully
        this._initCharts();

        // FIX: Always build handles immediately, even if layout is pending.
        // ResizeObserver will handle the positioning (updateVisuals) once dimensions are ready.
        this._refreshCharts();

        // STABILITY-FIX: If hass data arrived while we were importing Chart.js
        if (this._points.length > 0) {
            this._refreshCharts();
        }

        // FIX: Ensure events are bound even if render() skipped due to existing innerHTML
        this._bindEvents();
    }



    disconnectedCallback() {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
        }

        if (this._dragCleanup) {
            this._dragCleanup();
        }

        if (this._dragCleanup) {
            this._dragCleanup();
        }

        // Use helper to unbind
        this._unbindEvents();

        if (this._chartB) { this._chartB.destroy(); this._chartB = null; }
        if (this._chartK) { this._chartK.destroy(); this._chartK = null; }
        this._initialized = false;

        // FIX: Clear DOM to ensure render() re-runs and re-binds events on reconnect
        // CRITICAL FIX: Do NOT clear innerHTML. Let the DOM nodes stay for performance.
        // this.shadowRoot.innerHTML = ''; 
    }

    render() {
        if (this.shadowRoot.innerHTML) return;

        this.shadowRoot.innerHTML = `
      <style>
              display: block;
              /* Use HA defaults with fallbacks */
              /* UX-FIX: Force dark text color context if we force dark background, OR use system background */
              --ha-card-background: var(--card-background-color, #1c1c1c); 
              --chart-text-color: #e0e0e0; /* Fixed color for inside dark charts */
              
              --glass-border: var(--divider-color, rgba(255, 255, 255, 0.1));
              --chart-bg: rgba(0, 0, 0, 0.2);
              
              --accent-gold: #FFD700;
              --accent-blue: #00E5FF;
          }
          ha-card {
              background: var(--ha-card-background, var(--glass-bg));
              backdrop-filter: blur(20px);
              -webkit-backdrop-filter: blur(20px);
              border: 1px solid var(--glass-border);
              border-radius: 24px; 
              overflow: hidden;
              color: var(--primary-text-color);
              padding-bottom: 16px;
              position: relative; 
          }
          #validation-area {
              position: absolute;
              top: 76px; 
              left: 24px; right: 24px;
              z-index: 5; 
              pointer-events: none;
              display: flex;
              flex-direction: column;
              gap: 4px;
          }
          #validation-area > div {
              pointer-events: auto;
              box-shadow: 0 4px 12px rgba(0,0,0,0.5);
              backdrop-filter: blur(4px);
          }
          .card-header {
              position: relative;
              z-index: 25; 
              padding: 20px 24px;
              display: flex;
              justify-content: space-between;
              align-items: center;
              align-items: center;
              border-bottom: 1px solid var(--glass-border);
              margin-bottom: 16px;
              margin-bottom: 16px;
          }
          .controls-row {
              display: flex;
              gap: 12px;
              align-items: center;
              flex-wrap: wrap;
          }
          button, select {
              background: var(--card-background-color, rgba(255, 255, 255, 0.05));
              border: 1px solid var(--glass-border);
              color: var(--primary-text-color);
              padding: 6px 16px;
              border-radius: 20px;
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
          select {
             background: var(--card-background-color, rgba(20, 20, 25, 0.95));
             border: 1px solid var(--glass-border);
             color: var(--primary-text-color); 
          }
          option {
             background-color: var(--card-background-color, #1a1a1a);
             color: var(--primary-text-color);
          }
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
          .charts-container {
              padding: 0 20px;
              display: grid;
              grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
              gap: 20px;
          }
          .chart-wrapper {
              position: relative;
              height: 240px;
              background: var(--chart-bg);
              border-radius: 20px;
              border: 1px solid rgba(255, 255, 255, 0.05);
              padding: 16px;
          }
          .chart-label {
              position: absolute;
              top: 16px; left: 24px;
              font-size: 11px;
              color: var(--chart-text-color); /* UX-FIX: Readable on dark bg */
              text-transform: uppercase;
              letter-spacing: 1px;
              font-weight: 600;
              pointer-events: none;
              z-index: 5;
          }
          canvas { width: 100%; height: 100%; display: block; }
          .handle-layer {
              position: absolute;
              top: 16px; left: 16px; right: 16px; bottom: 16px;
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
              transition: width 0.1s, height 0.1s;
              touch-action: none;
          }
          .handle::after {
              content: '';
              position: absolute;
              top: -10px; right: -10px; bottom: -10px; left: -10px;
          }
          .handle:hover { transform: translate(-50%, -50%) scale(1.3); }
          .handle:active { cursor: grabbing; }
          .handle.type-b { 
              background: var(--accent-gold, #FFD700); 
              box-shadow: 0 0 0 2px rgba(0,0,0,0.5), 0 0 10px rgba(255, 215, 0, 0.6); 
          }
          .handle.type-k { 
              background: var(--accent-blue, #00E5FF); 
              box-shadow: 0 0 0 2px rgba(0,0,0,0.5), 0 0 10px rgba(0, 229, 255, 0.6); 
          }
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
      </ha-card>
    `;

        this._initCharts();
    }

    _bindEvents() {
        const btnSanitize = this.shadowRoot.getElementById('btn-sanitize');
        const btnSave = this.shadowRoot.getElementById('btn-save');
        const btnTest = this.shadowRoot.getElementById('btn-test');
        const btnRevert = this.shadowRoot.getElementById('btn-revert');
        const presetSelect = this.shadowRoot.getElementById('preset-select');

        // Remove first to be safe (idempotent)
        this._unbindEvents();

        if (btnSanitize) btnSanitize.addEventListener('click', this._boundSanitize);
        if (btnSave) btnSave.addEventListener('click', this._boundSave);
        if (btnTest) btnTest.addEventListener('click', this._boundTest);
        if (btnRevert) btnRevert.addEventListener('click', this._boundRevert);
        if (presetSelect) presetSelect.addEventListener('change', this._boundPreset);
    }

    _unbindEvents() {
        const btnSanitize = this.shadowRoot.getElementById('btn-sanitize');
        const btnSave = this.shadowRoot.getElementById('btn-save');
        const btnTest = this.shadowRoot.getElementById('btn-test');
        const btnRevert = this.shadowRoot.getElementById('btn-revert');
        const presetSelect = this.shadowRoot.getElementById('preset-select');

        if (btnSanitize) btnSanitize.removeEventListener('click', this._boundSanitize);
        if (btnSave) btnSave.removeEventListener('click', this._boundSave);
        if (btnTest) btnTest.removeEventListener('click', this._boundTest);
        if (btnRevert) btnRevert.removeEventListener('click', this._boundRevert);
        if (presetSelect) presetSelect.removeEventListener('change', this._boundPreset);
    }

    _initCharts() {
        if (this._chartB) { this._chartB.destroy(); this._chartB = null; }
        if (this._chartK) { this._chartK.destroy(); this._chartK = null; }

        const commonOpts = {
            responsive: true, maintainAspectRatio: false, animation: false,
            layout: { padding: 0 },
            scales: {
                x: { type: 'linear', min: 0, max: 1440, display: false },
                y: {
                    display: true,
                    position: 'right',
                    grid: { color: 'rgba(255,255,255,0.1)' }, /* A11Y-FIX: Better contrast */
                    ticks: { color: 'rgba(255,255,255,0.7)' }  /* A11Y-FIX: Readable ticks */
                }
            },
            plugins: {
                legend: false, tooltip: false,
                annotation: { annotations: {}, common: { drawTime: 'beforeDatasetsDraw' } }
            }
        };

        const customBackgroundPlugin = {
            id: 'customBackground',
            beforeDraw: (chart) => {
                const ctx = chart.ctx;
                const yAxis = chart.scales.y;
                const xAxis = chart.scales.x;

                if (!xAxis || !yAxis) return;

                if (chart.canvas.id === 'chartB') {
                    let minB = 0; let maxB = 100;
                    if (this._hass && this.config && this.config.entity) {
                        const attr = this._hass.states[this.config.entity]?.attributes || {};
                        if (attr.min_brightness !== undefined) minB = attr.min_brightness;
                        if (attr.max_brightness !== undefined) maxB = attr.max_brightness;
                    }
                    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
                    if (maxB < 100) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(100), xAxis.width, yAxis.getPixelForValue(maxB) - yAxis.getPixelForValue(100));
                    if (minB > 0) ctx.fillRect(xAxis.left, yAxis.getPixelForValue(minB), xAxis.width, yAxis.getPixelForValue(0) - yAxis.getPixelForValue(minB));
                }

                const annotations = this._getValidationAnnotations(chart.canvas.id === 'chartB' ? 'b' : 'k');
                annotations.forEach(anno => {
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
            }
        };

        const canvasB = this.shadowRoot.getElementById('chartB');
        const canvasK = this.shadowRoot.getElementById('chartK');

        if (canvasB) canvasB.getContext('2d').clearRect(0, 0, canvasB.width, canvasB.height);
        if (canvasK) canvasK.getContext('2d').clearRect(0, 0, canvasK.width, canvasK.height);

        const ctxB = canvasB.getContext('2d');
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

        const ctxK = canvasK.getContext('2d');
        this._chartK = new Chart(ctxK, {
            type: 'line',
            data: { datasets: [{ data: [], borderColor: '#00E5FF', fill: true, backgroundColor: 'rgba(0,229,255,0.1)', tension: 0.4 }] },
            options: {
                ...commonOpts,
                elements: { point: { radius: 0, hoverRadius: 0 }, line: { borderWidth: 2, tension: 0.4 } },
                scales: { ...commonOpts.scales, y: { min: 2000, max: 7000, ...commonOpts.scales.y } }
            },
            plugins: [customBackgroundPlugin]
        });
    }

    _refreshCharts() {
        if (!this._chartB || !this._points.length) return;

        if (this._chartB.canvas.clientWidth > 0 && this._chartB.width !== this._chartB.canvas.clientWidth) {
            this._chartB.resize();
        }
        if (this._chartK.canvas.clientWidth > 0 && this._chartK.width !== this._chartK.canvas.clientWidth) {
            this._chartK.resize();
        }

        this._rebuildHandles();
        this._updateVisuals();
    }

    _rebuildHandles() {
        // A11y Fix: Store focus to restore it after rebuilding DOM
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
                el.className = `handle type-${type}`;
                el.dataset.idx = idx;

                const tooltip = document.createElement('div');
                tooltip.className = 'handle-info';
                const valText = type === 'b' ? `${Math.round(pt.b)}%` : `${Math.round(pt.k)}K`;
                tooltip.innerText = `${minToTime(pt.t)} | ${valText}`;
                el.appendChild(tooltip);

                el.setAttribute('role', 'slider');
                el.setAttribute('tabindex', '0');
                el.setAttribute('aria-label', `${type === 'b' ? 'Brightness' : 'Kelvin'} Point ${idx + 1}`);
                el.setAttribute('aria-valuemin', type === 'b' ? '0' : '2000');
                el.setAttribute('aria-valuemax', type === 'b' ? '100' : '7000');
                el.setAttribute('aria-valuenow', type === 'b' ? pt.b : pt.k);
                el.setAttribute('aria-valuetext', `${minToTime(pt.t)}, ${type === 'b' ? pt.b + '%' : pt.k + 'K'}`);

                el.addEventListener('pointerdown', (e) => this._onDragStart(e, idx, type, el));
                el.addEventListener('keydown', (e) => this._onKeyDown(e, idx, type));

                container.appendChild(el);
            });
        });

        // A11y Fix: Restore focus
        if (focusedType !== null && focusedIdx !== -1) {
            // Wait for DOM update
            requestAnimationFrame(() => {
                const el = this.shadowRoot.querySelector(`#handles-${focusedType} .handle[data-idx="${focusedIdx}"]`);
                if (el) el.focus();
            });
        }
    }

    _onKeyDown(e, idx, type) {
        const pt = this._points[idx];
        let changed = false;
        const shift = e.shiftKey ? 10 : 1;

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
            e.target.focus();
        }
    }

    _onDragStart(e, idx, type, el) {
        e.preventDefault();
        el.setPointerCapture(e.pointerId);
        this._isDragging = true;
        const pt = this._points[idx];
        const chart = (type === 'b') ? this._chartB : this._chartK;
        const layer = this.shadowRoot.getElementById(`handles-${type}`);
        const rect = layer.getBoundingClientRect();

        const onMove = (ev) => {
            const mx = ev.clientX - rect.left;
            const my = ev.clientY - rect.top;
            const yVal = chart.scales.y.getValueForPixel(my);

            const prevPoint = idx > 0 ? this._points[idx - 1] : null;
            const nextPoint = idx < this._points.length - 1 ? this._points[idx + 1] : null;
            const minT = prevPoint ? prevPoint.t + 15 : 0;
            const maxT = nextPoint ? nextPoint.t - 15 : 1440;

            const rawT = chart.scales.x.getValueForPixel(mx);
            let newT = Math.round(rawT / 15) * 15;
            newT = Math.max(minT, Math.min(maxT, newT));

            this._points[idx].t = newT;

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
            this._schedulePreview();
        };

        // Stability Fix: Store cleanup function reference
        this._dragCleanup = () => {
            this._isDragging = false;
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            this._dragCleanup = null;
        };

        const onUp = () => {
            if (this._dragCleanup) this._dragCleanup();
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
        }, 500);
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
            mode: 'apply'
        });
    }

    _applyPreset(name) {
        if (this._presets[name]) {
            this._points = JSON.parse(JSON.stringify(this._presets[name]));
            this._refreshCharts();
            this._schedulePreview();
        }
    }

    _updateVisuals(retryCount = 0) {
        if (!this._chartB || !this._chartK) return;
        if (!this.isConnected) return;

        // NEW: Check if card is actually visible to prevent layout calculation errors
        // offsetParent is null if element or any parent has display: none
        // RELAXED CHECK: If width > 0, we are fine. offsetParent can be flaky in some custom cards.
        if (this.offsetParent === null && (!this._chartB.canvas || this._chartB.canvas.clientWidth === 0)) return;

        const data = this._calculateCurve();

        this._chartB.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.b[i] }));
        this._chartK.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.k[i] }));

        this._runValidation(data);
        this._updateValidationUI();

        this._chartB.update('none');
        this._chartK.update('none');

        const xAxis = this._chartB.scales.x;
        if (!xAxis || xAxis.width <= 0 || xAxis.getPixelForValue(0) === undefined) {
            if (retryCount < 50) {
                requestAnimationFrame(() => this._updateVisuals(retryCount + 1));
            } else {
                console.warn("HCL Card: Chart scaling timed out or card hidden.");
            }
            return;
        }

        this._points.forEach((pt, idx) => {
            this._syncHandle(idx, pt, 'b', this._chartB);
            this._syncHandle(idx, pt, 'k', this._chartK);
        });

        this._updateColorBar(data);
    }

    _updateColorBar(data) {
        const bar = this.shadowRoot.getElementById('color-bar-gradient');
        if (!bar) return;
        const stops = [];
        for (let i = 0; i <= 96; i += 8) {
            const k = data.k[i];
            const percent = (i / 96) * 100;
            stops.push(`${this._kelvinToRgb(k)} ${percent.toFixed(1)}%`);
        }
        bar.style.background = `linear-gradient(90deg, ${stops.join(', ')})`;
    }

    _kelvinToRgb(k) {
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
        el.style.transform = `translate(${x}px, ${y}px)`;
        el.setAttribute('aria-valuenow', yVal);
        el.setAttribute('aria-valuetext', `${minToTime(pt.t)}, ${type === 'b' ? pt.b + '%' : pt.k + 'K'}`);
        const tooltip = el.querySelector('.handle-info');
        if (tooltip) {
            const valText = type === 'b' ? `${Math.round(pt.b)}%` : `${Math.round(pt.k)}K`;
            tooltip.innerText = `${minToTime(pt.t)} | ${valText}`;
        }
    }

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

    _runValidation(data) {
        this._validationResult = { errors: [], warnings: [] };
        if (this._points.length < 2) {
            this._validationResult.errors.push({ msg: "Curve needs at least 2 points." });
        }
        let lastT = -1;
        let needsSanitize = false;
        const sorted = [...this._points].sort((a, b) => a.t - b.t);
        for (let i = 0; i < sorted.length; i++) {
            if (sorted[i].t === lastT) {
                this._validationResult.errors.push({ msg: `Duplicate time at ${minToTime(sorted[i].t)}.` });
                needsSanitize = true;
            }
            lastT = sorted[i].t;
        }
        for (let i = 0; i < this._points.length - 1; i++) {
            if (this._points[i].t > this._points[i + 1].t) {
                this._validationResult.errors.push({ msg: "Points are not sorted by time." });
                needsSanitize = true;
                break;
            }
        }
        const btnSanitize = this.shadowRoot.getElementById('btn-sanitize');
        if (btnSanitize) btnSanitize.style.display = needsSanitize ? 'block' : 'none';
        if (this._validationResult.errors.length > 0) return;

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

        let peakMinutes = 0;
        data.t.forEach((t, i) => {
            if (data.b[i] > 70 && data.k[i] > 5000) {
                peakMinutes += 15;
            }
        });

        if (peakMinutes < this._valSettings.minDailyPeakDuration) {
            let rangesNeedK = [];
            let rangesNeedB = [];
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

        const isNight = (t) => t >= this._valSettings.nightStart || t < this._valSettings.nightEnd;
        let nightViolationsB = [];
        let nightViolationsK = [];
        data.t.forEach((t, i) => {
            if (isNight(t)) {
                if (data.b[i] > 10) nightViolationsB.push(t);
                if (data.k[i] > 3000) nightViolationsK.push(t);
            }
        });
        if (nightViolationsB.length > 2) {
            this._addNightWarnings(nightViolationsB, 'b', 'bright', '>10%');
        }
        if (nightViolationsK.length > 2) {
            this._addNightWarnings(nightViolationsK, 'k', 'cold', '>3000K');
        }
    }

    _addNightWarnings(times, chartType, typeLabel, valLabel) {
        if (times.length === 0) return;
        let start = times[0];
        let prev = times[0];
        for (let i = 1; i < times.length; i++) {
            if (times[i] - prev > 15) {
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
        this._validationResult.warnings.push({
            type: 'night',
            targetChart: chartType,
            msg: `Night too ${typeLabel} (${valLabel}) at ${minToTime(start)}-${minToTime(prev + 15)}.`,
            xMin: start, xMax: prev + 15
        });
    }

    _getValidationAnnotations(chartType) {
        const list = [];
        this._validationResult.warnings.forEach(w => {
            if (w.targetChart && w.targetChart !== chartType) return;
            if (w.xMin !== undefined && w.xMax !== undefined) {
                let color = 'rgba(255, 165, 0, 0.15)';
                if (w.type === 'slope') color = 'rgba(255, 69, 0, 0.3)';
                list.push({ xMin: w.xMin, xMax: w.xMax, color });
            }
        });
        return list;
    }

    _updateValidationUI() {
        const area = this.shadowRoot.getElementById('validation-area');
        const btnSave = this.shadowRoot.getElementById('btn-save');
        if (!area || !btnSave) return;

        // NEW: Generate a signature/hash of the current state to avoid DOM trashing
        const currentSig = JSON.stringify(this._validationResult);
        if (this._lastValidationSig === currentSig) return;
        this._lastValidationSig = currentSig;

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
        let newPoints = [...this._points];
        newPoints.sort((a, b) => a.t - b.t);
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
