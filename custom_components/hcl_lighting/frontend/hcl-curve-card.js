class HCLCurveCard extends HTMLElement {
    constructor() {
        super();
        this._initialized = false;
        this._points = [];
        this._chartB = null;
        this._chartK = null;
        this._updatesPending = false;
        this._debouncer = null;
    }

    set hass(hass) {
        this._hass = hass;
        if (!this.config || !this.config.entity) return;

        const stateObj = hass.states[this.config.entity];
        if (stateObj && stateObj.attributes.control_points) {
            // Only update if points differ and we aren't dragging
            if (!this._isDragging) {
                // JSON stringify compare for deep check
                const newPointsJSON = JSON.stringify(stateObj.attributes.control_points);
                if (this._lastPointsJSON !== newPointsJSON) {
                    this._points = JSON.parse(newPointsJSON); // Deep copy
                    this._lastPointsJSON = newPointsJSON;
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
        if (!window.Chart) {
            await import('https://cdn.jsdelivr.net/npm/chart.js');
        }
        this.render();
        this._initialized = true;

        // Neu: ResizeObserver überwacht die tatsächliche Größe der Karte
        this._resizeObserver = new ResizeObserver(() => {
            if (this._initialized && !this._isDragging) {
                // WICHTIG: Erst Chart-Layout erzwingen, dann zeichnen
                if (this._chartB) this._chartB.resize();
                if (this._chartK) this._chartK.resize();
                this._updateVisuals();
            }
        });

        const container = this.shadowRoot.querySelector('.charts-container');
        if (container) {
            this._resizeObserver.observe(container);
        }

        // Einmaliger verzögerter Start als Sicherheitsnetz für langsame Dashboards
        setTimeout(() => this._refreshCharts(), 300);
    }

    // Neu: Cleanup beim Entfernen der Karte
    disconnectedCallback() {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
        }
    }

    render() {
        if (this.shadowRoot.innerHTML) return;

        this.shadowRoot.innerHTML = `
      <style>
        :host {
           display: block;
           --glass-bg: rgba(255, 255, 255, 0.03);
           --glass-border: rgba(255, 255, 255, 0.08);
           --accent-gold: #FFD700;
           --accent-blue: #00E5FF;
           --text-main: #ffffff;
        }
        ha-card {
           background: var(--ha-card-background, var(--glass-bg));
           backdrop-filter: blur(20px);
           -webkit-backdrop-filter: blur(20px);
           border: 1px solid var(--glass-border);
           border-radius: 12px;
           overflow: hidden;
           color: var(--text-main);
        }
        .card-header {
           padding: 16px;
           font-size: 18px;
           font-weight: 500;
           display: flex;
           justify-content: space-between;
           align-items: center;
        }
        .toolbar {
           display: flex;
           gap: 8px;
        }
        button {
           background: rgba(255,255,255,0.1);
           border: 1px solid rgba(255,255,255,0.2);
           color: white;
           padding: 6px 12px;
           border-radius: 6px;
           cursor: pointer;
        }
        button:hover { background: rgba(255,255,255,0.2); }
        .charts-container {
           padding: 0 16px 16px 16px;
           display: grid;
           grid-template-rows: 1fr 1fr;
           gap: 16px;
        }
        .chart-wrapper {
           position: relative;
           height: 200px;
           background: rgba(0,0,0,0.2);
           border-radius: 12px;
           border: 1px solid rgba(255,255,255,0.05);
           padding: 10px;
        }
        canvas {
            width: 100%;
            height: 100%;
        }
        .handle-layer {
           position: absolute;
           top: 10px; left: 10px; right: 10px; bottom: 10px;
           pointer-events: none;
           overflow: visible;
        }
        .handle {
           position: absolute;
           width: 12px; height: 12px;
           border-radius: 50%;
           transform: translate(-50%, -50%);
           cursor: grab;
           pointer-events: auto;
           z-index: 10;
        }
        .handle.type-b { background: var(--accent-gold); box-shadow: 0 0 5px rgba(255,215,0,0.5); }
        .handle.type-k { background: var(--accent-blue); box-shadow: 0 0 5px rgba(0,229,255,0.5); }
      </style>
      <ha-card>
        <div class="card-header">
           <span>HCL Curve</span>
           <div class="toolbar">
              <button id="btn-save">SAVE</button>
           </div>
        </div>
        <div class="charts-container">
           <div class="chart-wrapper">
               <canvas id="chartB"></canvas>
               <div class="handle-layer" id="handles-b"></div>
           </div>
           <div class="chart-wrapper">
               <canvas id="chartK"></canvas>
               <div class="handle-layer" id="handles-k"></div>
           </div>
        </div>
      </ha-card>
    `;

        // Bind Save
        this.shadowRoot.getElementById('btn-save').addEventListener('click', () => this._saveCurve());

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
            plugins: { legend: false, tooltip: false }
        };

        const ctxB = this.shadowRoot.getElementById('chartB').getContext('2d');
        this._chartB = new Chart(ctxB, {
            type: 'line',
            data: { datasets: [{ data: [], borderColor: '#FFD700', fill: true, backgroundColor: 'rgba(255,215,0,0.1)', tension: 0.4 }] },
            options: { ...commonOpts, scales: { ...commonOpts.scales, y: { min: 0, max: 100, ...commonOpts.scales.y } } }
        });

        const ctxK = this.shadowRoot.getElementById('chartK').getContext('2d');
        this._chartK = new Chart(ctxK, {
            type: 'line',
            data: { datasets: [{ data: [], borderColor: '#00E5FF', fill: true, backgroundColor: 'rgba(0,229,255,0.1)', tension: 0.4 }] },
            options: { ...commonOpts, scales: { ...commonOpts.scales, y: { min: 2000, max: 7000, ...commonOpts.scales.y } } }
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
            container.innerHTML = '';

            this._points.forEach((pt, idx) => {
                const el = document.createElement('div');
                el.className = `handle type-${type}`;
                el.dataset.idx = idx;

                // Interaction
                el.addEventListener('pointerdown', (e) => this._onDragStart(e, idx, type, el));
                container.appendChild(el);
            });
        });
    }

    _onDragStart(e, idx, type, el) {
        e.preventDefault();
        el.setPointerCapture(e.pointerId);
        this._isDragging = true;

        const chart = (type === 'b') ? this._chartB : this._chartK;
        const layer = this.shadowRoot.getElementById(`handles-${type}`);
        const rect = layer.getBoundingClientRect();

        const onMove = (ev) => {
            const mx = ev.clientX - rect.left;
            const my = ev.clientY - rect.top;

            const tVal = chart.scales.x.getValueForPixel(mx);
            const yVal = chart.scales.y.getValueForPixel(my);

            // Update Point
            const pt = this._points[idx];
            pt.t = Math.round(Math.max(0, Math.min(1440, tVal)));

            if (type === 'b') {
                pt.b = Math.round(Math.max(0, Math.min(100, yVal)));
            } else {
                pt.k = Math.round(Math.max(2000, Math.min(7000, yVal)));
            }

            this._updateVisuals();
            this._schedulePreview();
        };

        const onUp = () => {
            this._isDragging = false;
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
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

    _updateVisuals() {
        if (!this._chartB || !this._chartK) return; // Guard

        const data = this._calculateCurve();

        this._chartB.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.b[i] }));
        this._chartK.data.datasets[0].data = data.t.map((t, i) => ({ x: t, y: data.k[i] }));

        // Diagramme aktualisieren
        this._chartB.update('none');
        this._chartK.update('none');

        // NEU: Sicherstellen, dass die Scales fertig berechnet sind
        // Wenn getPixelForValue(0) immer noch 0 liefert, ist das Chart noch nicht bereit
        if (this._chartB.scales.x.getPixelForValue(0) <= 0) {
            return;
        }

        // Jetzt erst Handles synchronisieren
        this._points.forEach((pt, idx) => {
            this._syncHandle(idx, pt, 'b', this._chartB);
            this._syncHandle(idx, pt, 'k', this._chartK);
        });
    }

    _syncHandle(idx, pt, type, chart) {
        const el = this.shadowRoot.querySelector(`#handles-${type} .handle[data-idx="${idx}"]`);
        if (!el) return;
        const x = chart.scales.x.getPixelForValue(pt.t);
        const y = chart.scales.y.getPixelForValue(type === 'b' ? pt.b : pt.k);
        el.style.left = `${x}px`;
        el.style.top = `${y}px`;
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
}

customElements.define('hcl-curve-card', HCLCurveCard);
window.customCards = window.customCards || [];
window.customCards.push({
    type: "hcl-curve-card",
    name: "HCL Curve Card",
    preview: true,
    description: "Interactive HCL Curve Editor"
});
