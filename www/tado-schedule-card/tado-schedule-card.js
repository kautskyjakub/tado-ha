/**
 * tado-schedule-card
 *
 * A tado-style thermostat card: circular dial (same drag-to-set interaction
 * as a normal HA thermostat card), eco/away mode icons, and a paintable
 * weekly schedule grid - all talking to the `tado_schedule` local
 * integration's entities and services. No external dependencies (no
 * LitElement, no CDN) so it works purely as a local www/ resource.
 *
 * Card YAML config:
 *   type: custom:tado-schedule-card
 *   config_entry_id: <entry id, shown in Settings > Devices & Services>
 *   climate_entity: climate.living_room
 *   eco_switch: switch.living_room_eco_mode
 *   away_switch: switch.living_room_away_mode
 *   away_number: number.living_room_away_temperature
 *   weekplan_sensor: sensor.living_room_week_plan
 *   decision_sensor: sensor.living_room_current_decision           # optional
 *   next_change_sensor: sensor.living_room_next_schedule_change   # optional
 *   next_garmin_sensor: sensor.living_room_next_garmin_wake       # optional
 *   min_temp: 10   # optional, defaults 5
 *   max_temp: 28   # optional, defaults 25
 */

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const WEEKDAY_LABELS = { mon: "Po", tue: "Ú", wed: "St", thu: "Čt", fri: "Pá", sat: "So", sun: "Ne" };
const SLOTS_PER_DAY = 48; // 30-minute resolution
const MODE_COLOR = {
  comfort: "var(--tado-comfort-color, #ff8c3b)",
  eco: "var(--tado-eco-color, #4caf7d)",
  off: "var(--tado-off-color, #3a3f4b)",
};
const MODE_CYCLE = ["comfort", "eco", "off"];

function slotToTime(slot) {
  const h = Math.floor(slot / 2);
  const m = slot % 2 === 0 ? "00" : "30";
  return `${String(h).padStart(2, "0")}:${m}`;
}

function blocksToSlots(blocks) {
  const slots = new Array(SLOTS_PER_DAY).fill(null);
  for (let i = 0; i < blocks.length; i++) {
    const [h, m] = blocks[i].start.split(":").map(Number);
    const startSlot = h * 2 + (m >= 30 ? 1 : 0);
    const endSlot = i + 1 < blocks.length ? timeToSlot(blocks[i + 1].start) : SLOTS_PER_DAY;
    for (let s = startSlot; s < endSlot; s++) slots[s] = { mode: blocks[i].mode, temp: blocks[i].temp };
  }
  // fill any gap at the very start defensively
  for (let s = 0; s < SLOTS_PER_DAY; s++) if (!slots[s]) slots[s] = slots[s - 1] || { mode: "comfort", temp: 20 };
  return slots;
}

function timeToSlot(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 2 + (m >= 30 ? 1 : 0);
}

function slotsToBlocks(slots, comfortTemp, ecoTemp) {
  const tempFor = (mode) => (mode === "comfort" ? comfortTemp : mode === "eco" ? ecoTemp : comfortTemp - 10);
  const blocks = [];
  let currentMode = null;
  for (let s = 0; s < SLOTS_PER_DAY; s++) {
    const mode = slots[s];
    if (mode !== currentMode) {
      blocks.push({ start: slotToTime(s), mode, temp: tempFor(mode) });
      currentMode = mode;
    }
  }
  if (blocks.length === 0 || blocks[0].start !== "00:00") {
    blocks.unshift({ start: "00:00", mode: currentMode || "comfort", temp: tempFor(currentMode || "comfort") });
  }
  return blocks;
}

class TadoScheduleCard extends HTMLElement {
  setConfig(config) {
    if (!config.climate_entity) throw new Error("tado-schedule-card: 'climate_entity' is required");
    if (!config.config_entry_id) throw new Error("tado-schedule-card: 'config_entry_id' is required");
    this._config = {
      min_temp: 5,
      max_temp: 25,
      ...config,
    };
    this._paintMode = "comfort";
    this._daySlots = null; // { mon: [...48], tue: [...] } while editing, before save
    this._dragging = false;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
    }
    this._updateFromHass();
  }

  getCardSize() {
    return 8;
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  _build() {
    this._render();
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="zone-name"></div>
          <div class="modes">
            <button class="mode-btn" id="eco-btn" title="Eco mode">
              <ha-icon icon="mdi:leaf"></ha-icon>
            </button>
            <button class="mode-btn" id="away-btn" title="Away mode">
              <ha-icon icon="mdi:airplane"></ha-icon>
            </button>
          </div>
        </div>

        <div class="away-panel" id="away-panel" hidden>
          <span>Teplota v režimu pryč</span>
          <button id="away-minus">-</button>
          <span id="away-value">16</span>
          <button id="away-plus">+</button>
        </div>

        <div class="dial-wrap">
          <svg viewBox="0 0 220 220" id="dial">
            <circle cx="110" cy="110" r="95" class="dial-track"></circle>
            <path id="dial-arc" class="dial-arc"></path>
            <circle id="dial-handle" cx="110" cy="15" r="11" class="dial-handle"></circle>
          </svg>
          <div class="dial-center">
            <div class="current-temp" id="current-temp">--</div>
            <div class="target-temp" id="target-temp">--°</div>
            <div class="hvac-state" id="hvac-state"></div>
          </div>
        </div>

        <div class="status-row">
          <span id="decision-reason"></span>
          <span id="next-change"></span>
        </div>
        <div class="status-row" id="garmin-row" hidden>
          <ha-icon icon="mdi:watch"></ha-icon>
          <span id="garmin-next"></span>
        </div>

        <div class="schedule">
          <div class="schedule-toolbar">
            <button class="paint-btn" data-mode="comfort">
              <ha-icon icon="mdi:sofa"></ha-icon> Comfort
              <input type="number" id="comfort-temp" step="0.5" />
            </button>
            <button class="paint-btn" data-mode="eco">
              <ha-icon icon="mdi:leaf"></ha-icon> Eco
              <input type="number" id="eco-temp" step="0.5" />
            </button>
            <button class="paint-btn" data-mode="off">
              <ha-icon icon="mdi:power"></ha-icon> Off
            </button>
          </div>
          <div class="grid" id="grid"></div>
          <div class="grid-footer">
            <span>00</span><span>06</span><span>12</span><span>18</span><span>24</span>
          </div>
          <button class="save-btn" id="save-btn" hidden>Uložit rozvrh</button>
        </div>
      </ha-card>
    `;
    this._wireStaticHandlers();
    this._buildGrid();
  }

  _wireStaticHandlers() {
    const $ = (sel) => this.shadowRoot.querySelector(sel);

    $("#eco-btn").addEventListener("click", () => this._toggleSwitch(this._config.eco_switch));
    $("#away-btn").addEventListener("click", () => {
      this._toggleSwitch(this._config.away_switch);
      const panel = $("#away-panel");
      panel.hidden = !this._isOn(this._config.away_switch);
    });
    $("#away-minus").addEventListener("click", () => this._stepAwayTemp(-0.5));
    $("#away-plus").addEventListener("click", () => this._stepAwayTemp(0.5));

    this.shadowRoot.querySelectorAll(".paint-btn").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        if (ev.target.tagName === "INPUT") return;
        this._paintMode = btn.dataset.mode;
        this._highlightPaintMode();
      });
    });
    $("#comfort-temp").addEventListener("change", () => this._repaintTemps());
    $("#eco-temp").addEventListener("change", () => this._repaintTemps());
    $("#save-btn").addEventListener("click", () => this._saveSchedule());

    this._wireDial();
  }

  _highlightPaintMode() {
    this.shadowRoot.querySelectorAll(".paint-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.mode === this._paintMode);
    });
  }

  // ---------- dial ----------

  _wireDial() {
    const svg = this.shadowRoot.querySelector("#dial");
    const onMove = (ev) => {
      if (!this._draggingDial) return;
      const temp = this._angleToTemp(this._pointerAngle(svg, ev));
      this._setDialTemp(temp);
    };
    svg.addEventListener("pointerdown", (ev) => {
      this._draggingDial = true;
      svg.setPointerCapture(ev.pointerId);
      onMove(ev);
    });
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerup", (ev) => {
      this._draggingDial = false;
      this._commitTargetTemp();
    });
  }

  _pointerAngle(svg, ev) {
    const rect = svg.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = ev.clientX - cx;
    const dy = ev.clientY - cy;
    let deg = (Math.atan2(dy, dx) * 180) / Math.PI + 90; // 0deg = top
    if (deg < 0) deg += 360;
    return deg;
  }

  // Dial sweeps 300 degrees, from -150deg (min_temp) to +150deg (max_temp),
  // leaving a 60 degree gap at the bottom like most round thermostat UIs.
  _angleToTemp(deg) {
    let a = deg;
    if (a > 180) a -= 360; // range now -180..180, gap is around 180/-180
    const clamped = Math.max(-150, Math.min(150, a));
    const fraction = (clamped + 150) / 300;
    const { min_temp, max_temp } = this._config;
    const raw = min_temp + fraction * (max_temp - min_temp);
    return Math.round(raw * 2) / 2;
  }

  _tempToAngle(temp) {
    const { min_temp, max_temp } = this._config;
    const fraction = (temp - min_temp) / (max_temp - min_temp);
    return fraction * 300 - 150;
  }

  _setDialTemp(temp) {
    this._pendingTarget = temp;
    this._renderDial(temp);
    this.shadowRoot.querySelector("#target-temp").textContent = `${temp}°`;
  }

  _renderDial(temp) {
    const angle = this._tempToAngle(temp);
    const rad = ((angle - 90) * Math.PI) / 180;
    const r = 95;
    const cx = 110 + r * Math.cos(rad);
    const cy = 110 + r * Math.sin(rad);
    const handle = this.shadowRoot.querySelector("#dial-handle");
    handle.setAttribute("cx", cx.toFixed(1));
    handle.setAttribute("cy", cy.toFixed(1));

    const startRad = ((-150 - 90) * Math.PI) / 180;
    const sx = 110 + r * Math.cos(startRad);
    const sy = 110 + r * Math.sin(startRad);
    const largeArc = angle - -150 > 180 ? 1 : 0;
    const arc = this.shadowRoot.querySelector("#dial-arc");
    arc.setAttribute("d", `M ${sx.toFixed(1)} ${sy.toFixed(1)} A ${r} ${r} 0 ${largeArc} 1 ${cx.toFixed(1)} ${cy.toFixed(1)}`);
  }

  async _commitTargetTemp() {
    if (this._pendingTarget == null) return;
    await this._hass.callService("climate", "set_temperature", {
      entity_id: this._config.climate_entity,
      temperature: this._pendingTarget,
    });
    this._pendingTarget = null;
  }

  // ---------- schedule grid ----------

  _buildGrid() {
    const grid = this.shadowRoot.querySelector("#grid");
    grid.innerHTML = "";
    WEEKDAYS.forEach((day) => {
      const row = document.createElement("div");
      row.className = "grid-row";
      const label = document.createElement("div");
      label.className = "grid-label";
      label.textContent = WEEKDAY_LABELS[day];
      row.appendChild(label);

      const cellsWrap = document.createElement("div");
      cellsWrap.className = "grid-cells";
      cellsWrap.dataset.day = day;
      for (let s = 0; s < SLOTS_PER_DAY; s++) {
        const cell = document.createElement("div");
        cell.className = "grid-cell";
        cell.dataset.slot = String(s);
        cellsWrap.appendChild(cell);
      }
      row.appendChild(cellsWrap);
      grid.appendChild(row);
    });

    grid.addEventListener("pointerdown", (ev) => this._startPaint(ev));
    grid.addEventListener("pointerover", (ev) => this._continuePaint(ev));
    grid.addEventListener("pointerup", () => this._endPaint());
    grid.addEventListener("pointerleave", () => {});
    window.addEventListener("pointerup", () => this._endPaint());
  }

  _startPaint(ev) {
    const cell = ev.target.closest(".grid-cell");
    if (!cell) return;
    this._dragging = true;
    this._paintCell(cell);
  }

  _continuePaint(ev) {
    if (!this._dragging) return;
    const cell = ev.target.closest(".grid-cell");
    if (!cell) return;
    this._paintCell(cell);
  }

  _endPaint() {
    this._dragging = false;
  }

  _paintCell(cell) {
    const day = cell.parentElement.dataset.day;
    const slot = Number(cell.dataset.slot);
    if (!this._daySlots) return;
    this._daySlots[day][slot] = this._paintMode;
    cell.style.background = MODE_COLOR[this._paintMode];
    this.shadowRoot.querySelector("#save-btn").hidden = false;
  }

  _repaintTemps() {
    // Just re-renders colors/labels; actual temps are read at save time from the inputs.
  }

  async _saveSchedule() {
    const comfortTemp = Number(this.shadowRoot.querySelector("#comfort-temp").value);
    const ecoTemp = Number(this.shadowRoot.querySelector("#eco-temp").value);
    const weekplan = {};
    for (const day of WEEKDAYS) {
      weekplan[day] = slotsToBlocks(this._daySlots[day], comfortTemp, ecoTemp);
    }
    await this._hass.callService("tado_schedule", "set_schedule", {
      config_entry_id: this._config.config_entry_id,
      weekplan,
    });
    this.shadowRoot.querySelector("#save-btn").hidden = true;
  }

  // ---------- misc entity helpers ----------

  _isOn(entityId) {
    if (!entityId || !this._hass.states[entityId]) return false;
    return this._hass.states[entityId].state === "on";
  }

  async _toggleSwitch(entityId) {
    if (!entityId) return;
    await this._hass.callService("switch", this._isOn(entityId) ? "turn_off" : "turn_on", { entity_id: entityId });
  }

  async _stepAwayTemp(delta) {
    const entityId = this._config.away_number;
    if (!entityId || !this._hass.states[entityId]) return;
    const current = Number(this._hass.states[entityId].state);
    await this._hass.callService("number", "set_value", { entity_id: entityId, value: current + delta });
  }

  // ---------- render from hass state ----------

  _updateFromHass() {
    const $ = (sel) => this.shadowRoot.querySelector(sel);
    const climate = this._hass.states[this._config.climate_entity];
    if (!climate) return;

    $(".zone-name").textContent = climate.attributes.friendly_name || this._config.climate_entity;
    $("#current-temp").textContent = climate.attributes.current_temperature != null ? `${climate.attributes.current_temperature}°` : "--";
    $("#hvac-state").textContent = climate.state === "off" ? "Vypnuto" : "Topení";

    if (!this._draggingDial) {
      const target = climate.attributes.temperature;
      if (target != null) {
        $("#target-temp").textContent = `${target}°`;
        this._renderDial(target);
      }
    }

    $("#eco-btn").classList.toggle("active", this._isOn(this._config.eco_switch));
    $("#away-btn").classList.toggle("active", this._isOn(this._config.away_switch));
    $("#away-panel").hidden = !this._isOn(this._config.away_switch);
    if (this._config.away_number && this._hass.states[this._config.away_number]) {
      $("#away-value").textContent = this._hass.states[this._config.away_number].state;
    }

    if (this._config.next_change_sensor && this._hass.states[this._config.next_change_sensor]) {
      const state = this._hass.states[this._config.next_change_sensor];
      $("#next-change").textContent = state.state !== "unknown" ? `další změna: ${new Date(state.state).toLocaleString()}` : "";
    }

    if (this._config.decision_sensor && this._hass.states[this._config.decision_sensor]) {
      $("#decision-reason").textContent = this._hass.states[this._config.decision_sensor].state;
    }

    if (this._config.next_garmin_sensor && this._hass.states[this._config.next_garmin_sensor]) {
      const state = this._hass.states[this._config.next_garmin_sensor];
      const row = $("#garmin-row");
      if (state.state && state.state !== "unknown") {
        row.hidden = false;
        $("#garmin-next").textContent = new Date(state.state).toLocaleString();
      } else {
        row.hidden = true;
      }
    }

    if (!this._daySlots && this._config.weekplan_sensor && this._hass.states[this._config.weekplan_sensor]) {
      const weekplan = this._hass.states[this._config.weekplan_sensor].attributes.weekplan;
      if (weekplan) this._loadWeekplan(weekplan);
    }
  }

  _loadWeekplan(weekplan) {
    this._daySlots = {};
    let comfortTemp = 21;
    let ecoTemp = 17;
    for (const day of WEEKDAYS) {
      const blocks = weekplan[day] || [];
      const slots = blocksToSlots(blocks);
      this._daySlots[day] = slots.map((s) => s.mode);
      for (const s of slots) {
        if (s.mode === "comfort") comfortTemp = s.temp;
        if (s.mode === "eco") ecoTemp = s.temp;
      }
    }
    this.shadowRoot.querySelector("#comfort-temp").value = comfortTemp;
    this.shadowRoot.querySelector("#eco-temp").value = ecoTemp;
    this._paintMode = "comfort";
    this._highlightPaintMode();
    this._paintAllCellsFromSlots();
  }

  _paintAllCellsFromSlots() {
    const grid = this.shadowRoot.querySelector("#grid");
    WEEKDAYS.forEach((day) => {
      const cellsWrap = grid.querySelector(`.grid-cells[data-day="${day}"]`);
      if (!cellsWrap) return;
      this._daySlots[day].forEach((mode, slot) => {
        const cell = cellsWrap.querySelector(`.grid-cell[data-slot="${slot}"]`);
        if (cell) cell.style.background = MODE_COLOR[mode];
      });
    });
  }
}

const STYLE = `
  ha-card { padding: 16px; display: block; }
  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .zone-name { font-size: 1.2em; font-weight: 500; }
  .modes { display: flex; gap: 8px; }
  .mode-btn { background: var(--secondary-background-color); border: none; border-radius: 50%;
    width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
  .mode-btn.active { background: var(--tado-comfort-color, #ff8c3b); color: white; }
  .away-panel { display: flex; align-items: center; gap: 10px; justify-content: center; margin-bottom: 8px; }
  .away-panel button { width: 28px; height: 28px; border-radius: 50%; border: none; background: var(--secondary-background-color); cursor: pointer; }
  .dial-wrap { position: relative; width: 220px; height: 220px; margin: 8px auto; }
  #dial { width: 100%; height: 100%; }
  .dial-track { fill: none; stroke: var(--divider-color, #444); stroke-width: 10; }
  .dial-arc { fill: none; stroke: var(--tado-comfort-color, #ff8c3b); stroke-width: 10; stroke-linecap: round; }
  .dial-handle { fill: var(--tado-comfort-color, #ff8c3b); stroke: white; stroke-width: 2; cursor: grab; touch-action: none; }
  .dial-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; }
  .current-temp { font-size: 0.9em; opacity: 0.7; }
  .target-temp { font-size: 2.4em; font-weight: 600; }
  .hvac-state { font-size: 0.8em; opacity: 0.7; }
  .status-row { display: flex; justify-content: space-between; font-size: 0.85em; opacity: 0.8; margin: 2px 0; }
  #garmin-row { justify-content: flex-start; gap: 6px; align-items: center; }
  .schedule { margin-top: 16px; }
  .schedule-toolbar { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .paint-btn { display: flex; align-items: center; gap: 4px; border: 2px solid transparent; border-radius: 8px;
    background: var(--secondary-background-color); padding: 6px 8px; cursor: pointer; color: var(--primary-text-color); }
  .paint-btn.active { border-color: var(--primary-color); }
  .paint-btn input { width: 44px; margin-left: 4px; }
  .grid-row { display: flex; align-items: center; margin-bottom: 2px; }
  .grid-label { width: 24px; font-size: 0.75em; opacity: 0.7; }
  .grid-cells { display: flex; flex: 1; height: 18px; touch-action: none; }
  .grid-cell { flex: 1; background: var(--tado-off-color, #3a3f4b); cursor: pointer; }
  .grid-cell:first-child { border-radius: 4px 0 0 4px; }
  .grid-cell:last-child { border-radius: 0 4px 4px 0; }
  .grid-footer { display: flex; justify-content: space-between; font-size: 0.7em; opacity: 0.6; padding-left: 24px; }
  .save-btn { margin-top: 10px; width: 100%; padding: 10px; border: none; border-radius: 8px;
    background: var(--primary-color); color: var(--text-primary-color, white); cursor: pointer; font-weight: 600; }
`;

customElements.define("tado-schedule-card", TadoScheduleCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "tado-schedule-card",
  name: "Tado Schedule Card",
  description: "Local tado-style thermostat card with visual weekly schedule, away temp, eco mode and Garmin wake sync.",
});
