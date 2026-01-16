const canvas = document.getElementById("schematic");
const ctx = canvas.getContext("2d");
const libraryEl = document.getElementById("library");
const propsEl = document.getElementById("props");
const toolButtons = document.getElementById("toolButtons");
const runBtn = document.getElementById("runBtn");
const simToggle = document.getElementById("simToggle");
const simStatus = document.getElementById("simStatus");
const gridToggle = document.getElementById("gridToggle");
const clearBtn = document.getElementById("clearBtn");
const rotateBtn = document.getElementById("rotateBtn");
const undoBtn = document.getElementById("undoBtn");
const meterReadout = document.getElementById("meterReadout");
const saveNameInput = document.getElementById("saveName");
const saveBtn = document.getElementById("saveBtn");
const saveList = document.getElementById("saveList");
const canvasResizer = document.getElementById("canvasResizer");
const debugLog = document.getElementById("debugLog");
const debugClear = document.getElementById("debugClear");

const GRID = 20;
const TERMINAL_RADIUS = 6;
const COMPONENT_W = 80;
const COMPONENT_H = 40;
const CONTACTOR_W = 120;
const CONTACTOR_MIN_H = 70;
const WIRE_LIVE_THRESHOLD = 0.5;

const state = {
  components: [],
  wires: [],
  activeTool: "select",
  placementType: null,
  dragging: null,
  draggingWirePoint: null,
  draggingMeter: null,
  activeMomentary: null,
  selectedId: null,
  selectedWireId: null,
  wireStart: null,
  wirePoints: [],
  showGrid: true,
  simRunning: false,
  animTime: 0,
  simDirty: true,
  simPending: false,
  canvasSize: null,
  canvasResizing: null,
  simTimerId: null,
  meter: {
    mode: "voltage",
    picks: [],
    lastResult: null,
  },
  meters: [],
  lastSolution: null,
  contactorStates: {},
  lampLit: {},
  motorRunning: {},
  motor3phDirection: {},
  timerStates: {},
  faults: {},
  solveErrors: {},
  wireDefaults: { color: "#2f2f34", area: 1.5, length: 1, material: "copper" },
  debugEntries: [],
  undoStack: [],
};

const libraryGroups = [
  {
    name: "Källor",
    items: [
      {
        id: "voltage_source",
        type: "voltage_source",
        label: "Spänningskälla",
        defaults: { value: 12, supplyType: "DC", frequency: 50, connection: "Y", neutral: true },
      },
      { id: "ground", type: "ground", label: "Jord", defaults: {} },
    ],
  },
  {
    name: "Last",
    items: [
      {
        id: "lamp",
        type: "lamp",
        label: "Lampa",
        defaults: { value: 80, threshold: 6, ratedVoltage: 12, litColor: "#f6c453" },
      },
      { id: "motor", type: "motor", label: "Motor", defaults: { value: 20, startVoltage: 6 } },
      {
        id: "motor_3ph",
        type: "motor_3ph",
        label: "Motor 3-fas",
        defaults: { value: 12, startVoltage: 200, connection: "Y" },
      },
      { id: "resistor", type: "resistor", label: "Resistor", defaults: { value: 100 } },
      { id: "capacitor", type: "capacitor", label: "Kondensator", defaults: { value: 1e-6 } },
      { id: "inductor", type: "inductor", label: "Induktor", defaults: { value: 0.1 } },
    ],
  },
  {
    name: "Styrning",
    items: [
      { id: "switch", type: "switch", label: "Brytare", defaults: { closed: true } },
      { id: "push_button", type: "push_button", label: "Tryckknapp", defaults: { closed: false } },
      { id: "switch_spdt", type: "switch_spdt", label: "Trappbrytare", defaults: { position: "up" } },
      {
        id: "timer",
        type: "timer",
        label: "Timer",
        defaults: {
          delayMs: 3000,
          pullInVoltage: 9,
          coilResistance: 120,
          loop: false,
          initialClosed: false,
          timerState: {},
        },
      },
      {
        id: "time_timer",
        type: "time_timer",
        label: "Timer (klocka)",
        defaults: { startTime: "08:00", endTime: "17:00", timerState: {} },
      },
      {
        id: "contactor_standard",
        type: "contactor",
        label: "Kontaktor",
        defaults: {
          coilResistance: 120,
          pullInVoltage: 9,
          coilRatedVoltage: 12,
          contactType: "standard",
          poles: ["NO"],
        },
      },
      {
        id: "contactor_changeover",
        type: "contactor",
        label: "Kontaktor omkastande",
        defaults: {
          coilResistance: 120,
          pullInVoltage: 9,
          coilRatedVoltage: 12,
          contactType: "changeover",
          poles: ["NO"],
        },
      },
    ],
  },
  {
    name: "Noder",
    items: [{ id: "node", type: "node", label: "Förgrening", defaults: {} }],
  },
];

const libraryItems = new Map();
libraryGroups.forEach((group) => {
  group.items.forEach((item) => {
    libraryItems.set(item.id, item);
  });
});

const componentLabels = {
  resistor: "R",
  capacitor: "C",
  inductor: "L",
  switch: "S",
  push_button: "PB",
  switch_spdt: "S",
  voltage_source: "V",
  motor: "M",
  motor_3ph: "M3",
  lamp: "L",
  contactor: "K",
  timer: "T",
  time_timer: "TT",
  node: "N",
  ground: "GND",
};

function resizeCanvas() {
  const wrap = canvas.parentElement;
  if (!state.canvasSize) {
    const baseWidth = wrap ? wrap.clientWidth : canvas.clientWidth;
    const baseHeight = wrap ? wrap.clientHeight : canvas.clientHeight;
    applyCanvasSize(baseWidth || 800, baseHeight || 600);
  } else {
    applyCanvasSize(state.canvasSize.width, state.canvasSize.height);
  }
  render();
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function setCanvasSize(width, height) {
  if (!Number.isFinite(width) || !Number.isFinite(height)) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  state.canvasWidth = width;
  state.canvasHeight = height;
}

function applyCanvasSize(width, height) {
  const nextWidth = Math.max(400, Math.round(width / GRID) * GRID);
  const nextHeight = Math.max(300, Math.round(height / GRID) * GRID);
  state.canvasSize = { width: nextWidth, height: nextHeight };
  setCanvasSize(nextWidth, nextHeight);
}

function snap(value) {
  return Math.round(value / GRID) * GRID;
}

function updateSimToggle() {
  if (!simToggle) return;
  simToggle.textContent = `Simläge: ${state.simRunning ? "På" : "Av"}`;
}

function clearSimSchedule() {
  if (state.simTimerId) {
    clearTimeout(state.simTimerId);
    state.simTimerId = null;
  }
}

function parseTimeToMinutes(value, fallbackMinutes) {
  if (!value || typeof value !== "string" || !value.includes(":")) return fallbackMinutes;
  const [hh, mm] = value.split(":").map((part) => Number(part));
  if (!Number.isFinite(hh) || !Number.isFinite(mm)) return fallbackMinutes;
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return fallbackMinutes;
  return hh * 60 + mm;
}

function getNextBoundaryDelay(startTime, endTime) {
  const now = new Date();
  const startMinutes = parseTimeToMinutes(startTime, 8 * 60);
  const endMinutes = parseTimeToMinutes(endTime, 17 * 60);
  if (startMinutes === endMinutes) return null;

  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  const active =
    endMinutes > startMinutes
      ? currentMinutes >= startMinutes && currentMinutes < endMinutes
      : currentMinutes >= startMinutes || currentMinutes < endMinutes;
  const targetMinutes = active ? endMinutes : startMinutes;

  const target = new Date(now);
  target.setHours(Math.floor(targetMinutes / 60), targetMinutes % 60, 0, 0);
  if (target.getTime() <= now.getTime()) {
    target.setDate(target.getDate() + 1);
  }
  return target.getTime() - now.getTime();
}

function scheduleNextSimulation() {
  clearSimSchedule();
  if (!state.simRunning) return;
  let nextDelay = Infinity;

  state.components.forEach((comp) => {
    if (comp.type === "timer") {
      const timerState = state.timerStates[comp.id] || {};
      if (timerState.running && Number.isFinite(timerState.startAt)) {
        const delayMs = comp.props.delayMs || 0;
        const remaining = Math.max(0, delayMs - (Date.now() - timerState.startAt));
        if (remaining > 0) nextDelay = Math.min(nextDelay, remaining);
      }
    }
    if (comp.type === "time_timer") {
      const delay = getNextBoundaryDelay(comp.props.startTime, comp.props.endTime);
      if (delay !== null) nextDelay = Math.min(nextDelay, delay);
    }
  });

  if (!Number.isFinite(nextDelay) || nextDelay <= 0) return;
  const delay = Math.max(150, Math.min(nextDelay + 50, 24 * 60 * 60 * 1000));
  state.simTimerId = setTimeout(() => {
    if (state.simRunning) {
      requestSimulation();
    }
  }, delay);
}

function serializeCircuit() {
  const meters = state.meters.map((meter) => ({
    id: meter.id,
    mode: meter.mode,
    componentId: meter.componentId || null,
    aRef: meter.aRef || null,
    bRef: meter.bRef || null,
    x: meter.x,
    y: meter.y,
    unit: meter.unit || "",
  }));
  const wires = state.wires.map((wire) => ({
    ...wire,
    material: wire.material || state.wireDefaults.material,
  }));
  return {
    components: state.components,
    wires,
    meters,
    canvasSize: state.canvasSize,
    wireDefaults: { ...state.wireDefaults },
  };
}

function cloneSnapshot(snapshot) {
  return JSON.parse(JSON.stringify(snapshot));
}

function recordHistory() {
  const snapshot = serializeCircuit();
  state.undoStack.push(cloneSnapshot(snapshot));
  if (state.undoStack.length > 50) {
    state.undoStack.shift();
  }
}

function restoreSnapshot(snapshot) {
  loadFromSnapshot(snapshot);
  if (snapshot.wireDefaults) {
    state.wireDefaults = { ...state.wireDefaults, ...snapshot.wireDefaults };
  }
  state.simDirty = true;
  if (state.simRunning) {
    requestSimulation();
  }
}

function formatDebugTime(date) {
  return date.toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function addDebugEntry(entry) {
  state.debugEntries.push(entry);
  if (state.debugEntries.length > 200) {
    state.debugEntries.shift();
  }
  renderDebugLog();
}

function renderDebugLog() {
  if (!debugLog) return;
  debugLog.innerHTML = "";
  if (!state.debugEntries.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "Inga simuleringar ännu.";
    debugLog.appendChild(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  state.debugEntries.slice().reverse().forEach((entry) => {
    const wrapper = document.createElement("div");
    wrapper.className = `debug-entry debug-entry--${entry.status}`;
    const header = document.createElement("div");
    header.className = "debug-entry__header";
    header.textContent = `${formatDebugTime(entry.time)} · ${entry.summary}`;
    wrapper.appendChild(header);
    if (entry.details && entry.details.length) {
      const list = document.createElement("ul");
      list.className = "debug-entry__details";
      entry.details.forEach((line) => {
        const item = document.createElement("li");
        item.textContent = line;
        list.appendChild(item);
      });
      wrapper.appendChild(list);
    }
    fragment.appendChild(wrapper);
  });
  debugLog.appendChild(fragment);
}

function loadFromSnapshot(snapshot) {
  state.components = snapshot.components || [];
  state.wires = snapshot.wires || [];
  state.meters = (snapshot.meters || []).map((meter) => ({
    ...meter,
    value: null,
  }));
  if (snapshot.wireDefaults) {
    state.wireDefaults = { ...state.wireDefaults, ...snapshot.wireDefaults };
  }
  if (snapshot.canvasSize && Number.isFinite(snapshot.canvasSize.width) && Number.isFinite(snapshot.canvasSize.height)) {
    applyCanvasSize(snapshot.canvasSize.width, snapshot.canvasSize.height);
  }
  state.wires.forEach((wire) => {
    if (!wire.color) wire.color = state.wireDefaults.color;
    if (wire.area === undefined) wire.area = state.wireDefaults.area;
    if (wire.length === undefined) wire.length = state.wireDefaults.length;
    if (!wire.material) wire.material = state.wireDefaults.material;
    if (!Array.isArray(wire.points)) wire.points = [];
  });
  state.components.forEach((comp) => {
    if (comp.props.name === undefined) {
      comp.props.name = "";
    }
    if (comp.type === "lamp" && comp.props.ratedVoltage === undefined) {
      comp.props.ratedVoltage = comp.props.threshold ?? 12;
    }
    if (comp.type === "lamp" && comp.props.litColor === undefined) {
      comp.props.litColor = "#f6c453";
    }
    if (comp.type === "timer") {
      if (comp.props.delayMs === undefined) comp.props.delayMs = 3000;
      if (comp.props.pullInVoltage === undefined) comp.props.pullInVoltage = 9;
      if (comp.props.coilResistance === undefined) comp.props.coilResistance = 120;
      if (comp.props.loop === undefined) comp.props.loop = false;
      if (comp.props.initialClosed === undefined) comp.props.initialClosed = false;
      if (!comp.props.timerState) comp.props.timerState = {};
      if (!Number.isFinite(comp.props.delayMs)) comp.props.delayMs = 3000;
    }
    if (comp.type === "time_timer") {
      if (!comp.props.startTime) comp.props.startTime = "08:00";
      if (!comp.props.endTime) comp.props.endTime = "17:00";
      if (!comp.props.timerState) comp.props.timerState = {};
    }
    if (comp.type === "contactor" && comp.props.coilRatedVoltage === undefined) {
      comp.props.coilRatedVoltage = comp.props.pullInVoltage ?? 12;
    }
    if (comp.type === "contactor" && comp.props.contactType === undefined) {
      comp.props.contactType = "standard";
    }
    if (comp.type === "contactor" && !Array.isArray(comp.props.poles)) {
      comp.props.poles = ["NO"];
    }
    if (comp.type === "voltage_source" && comp.props.supplyType === undefined) {
      comp.props.supplyType = "DC";
    }
    if (comp.type === "voltage_source" && comp.props.frequency === undefined) {
      comp.props.frequency = 50;
    }
    if (comp.type === "voltage_source" && comp.props.connection === undefined) {
      comp.props.connection = "Y";
    }
    if (comp.type === "motor_3ph" && comp.props.connection === undefined) {
      comp.props.connection = "Y";
    }
    if (comp.type === "motor_3ph" && comp.props.startVoltage === undefined) {
      comp.props.startVoltage = 200;
    }
  });
  state.selectedId = null;
  state.selectedWireId = null;
  state.wireStart = null;
  state.wirePoints = [];
  state.draggingWirePoint = null;
  state.wirePoints = [];
  state.contactorStates = {};
  state.lampLit = {};
  state.motorRunning = {};
  state.timerStates = {};
  state.faults = {};
  state.simDirty = true;
  updatePropsPanel();
  render();
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Serverfel");
  }
  return payload;
}

async function renderSaveList() {
  if (!saveList) return;
  saveList.innerHTML = "";
  try {
    const payload = await fetchJSON("/api/saves");
    const saves = payload.saves || [];
    if (!saves.length) {
      saveList.innerHTML = '<div class="muted">Inga sparade labbar ännu.</div>';
      return;
    }
    saves.forEach((save) => {
      const row = document.createElement("div");
      row.className = "save-item";
      const name = document.createElement("div");
      name.textContent = save.name;
      const load = document.createElement("button");
      load.textContent = "Ladda";
      load.addEventListener("click", async () => {
        const data = await fetchJSON(`/api/saves/${save.id}`);
        loadFromSnapshot(data.snapshot || {});
        if (state.simRunning) markDirty();
      });
      const remove = document.createElement("button");
      remove.textContent = "Ta bort";
      remove.addEventListener("click", async () => {
        await fetchJSON(`/api/saves/${save.id}`, { method: "DELETE" });
        renderSaveList();
      });
      row.appendChild(name);
      row.appendChild(load);
      row.appendChild(remove);
      saveList.appendChild(row);
    });
  } catch (error) {
    saveList.innerHTML = `<div class="muted">${error.message}</div>`;
  }
}

async function saveCurrent(name) {
  if (!name) return;
  const snapshot = serializeCircuit();
  await postJSON("/api/saves", { name, snapshot });
  await renderSaveList();
}

async function postJSON(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Serverfel");
  }
  return payload;
}

async function requestSimulation() {
  if (!state.simRunning || state.simPending) return;
  state.simPending = true;
  state.simDirty = false;
  simStatus.textContent = "Simulerar...";
  try {
    const payload = await postJSON("/api/simulate", { ...serializeCircuit(), simTime: Date.now() });
    state.lastSolution = payload.solution || null;
    state.contactorStates = payload.contactorStates || {};
    state.timerStates = payload.timerStates || {};
    if (payload.timerStates) {
      Object.entries(payload.timerStates).forEach(([id, timerState]) => {
        const comp = state.components.find((c) => c.id === id);
        if (comp) {
          comp.props.timerState = timerState;
        }
      });
    }
    state.lampLit = payload.lampLit || {};
    state.motorRunning = payload.motorRunning || {};
    state.motor3phDirection = payload.motor3phDirection || {};
    state.faults = payload.faults || {};
    state.solveErrors = payload.solveErrors || {};
    const faultMessages = Object.values(state.faults);
    const solveMessages = Object.entries(state.solveErrors)
      .filter(([key]) => !key.startsWith("__"))
      .map(([, value]) => value);
    const networkErrors = Object.entries(state.solveErrors)
      .filter(([key]) => key.startsWith("__"))
      .map(([, value]) => value);
    const debugInfo = payload.debugInfo || {};
    let summary = "Simulering uppdaterad.";
    let status = "ok";
    if (solveMessages.length) {
      summary = `Delvis simulering: ${solveMessages[0]}`;
      status = "partial";
    } else if (networkErrors.length) {
      summary = `Simulering: ${networkErrors[0]}`;
      status = "error";
    } else if (faultMessages.length) {
      summary = `Fel: ${faultMessages[0]}`;
      status = "fault";
    }
    simStatus.textContent = summary;
    const details = [];
    if (solveMessages.length) {
      details.push(`Delvis fel: ${solveMessages.join("; ")}`);
    }
    if (networkErrors.length) {
      details.push(`Nätfel: ${networkErrors.join("; ")}`);
    }
    if (faultMessages.length) {
      details.push(`Komponentfel: ${faultMessages.join("; ")}`);
    }
    if (debugInfo.dc && Object.keys(debugInfo.dc).length) {
      details.push(
        `DC: noder=${debugInfo.dc.nodes}, källor=${debugInfo.dc.sources}, flytande=${debugInfo.dc.floating}, inaktiva=${debugInfo.dc.inactive || 0}, virtuell jord=${debugInfo.dc.virtualGround ? "ja" : "nej"}`
      );
    }
    if (debugInfo.ac && Object.keys(debugInfo.ac).length) {
      details.push(
        `AC: noder=${debugInfo.ac.nodes}, källor=${debugInfo.ac.sources}, flytande=${debugInfo.ac.floating}, inaktiva=${debugInfo.ac.inactive || 0}, virtuell jord=${debugInfo.ac.virtualGround ? "ja" : "nej"}`
      );
    }
    if (!details.length) {
      details.push(`Komponenter: ${state.components.length}, ledningar: ${state.wires.length}`);
    }
    addDebugEntry({ time: new Date(), status, summary, details });
  } catch (error) {
    const summary = error.message || "Simulering misslyckades.";
    simStatus.textContent = summary;
    addDebugEntry({
      time: new Date(),
      status: "error",
      summary,
      details: ["Kunde inte hämta svar från servern."],
    });
  } finally {
    state.simPending = false;
    updatePropsPanel();
    render();
    await refreshMeters();
    scheduleNextSimulation();
    if (state.simDirty) {
      requestSimulation();
    }
  }
}

async function requestMeasure(payload) {
  try {
    const result = await postJSON("/api/measure", { ...serializeCircuit(), ...payload });
    return result;
  } catch (error) {
    return { error: error.message || "Mätning misslyckades." };
  }
}

function markDirty() {
  state.simDirty = true;
  if (state.simRunning) {
    requestSimulation();
  }
}

async function updateMeterValue(meter) {
  if (["current", "ac_current", "ac_power_p", "ac_power_q", "ac_power_s", "ac_pf"].includes(meter.mode)) {
    const result = await requestMeasure({ mode: meter.mode, componentId: meter.componentId });
    if (result.error) {
      meter.value = null;
      meterReadout.textContent = result.error;
      return;
    }
    meter.value = result.value;
    return;
  }
  const result = await requestMeasure({
    mode: meter.mode,
    aRef: meter.aRef,
    bRef: meter.bRef,
  });
  if (result.error) {
    meter.value = null;
    meterReadout.textContent = result.error;
    return;
  }
  meter.value = result.value;
}

async function refreshMeters() {
  if (!state.meters.length) return;
  for (const meter of state.meters) {
    await updateMeterValue(meter);
  }
  render();
}

function rotatePoint(x, y, deg) {
  const rad = (deg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return { x: x * cos - y * sin, y: x * sin + y * cos };
}

function applyRotation(component, point) {
  const rotation = component.rotation || 0;
  const rotated = rotatePoint(point.x, point.y, rotation);
  return { x: component.x + rotated.x, y: component.y + rotated.y };
}

function getContactorLayout(component) {
  const poleCount = component.props.poles ? component.props.poles.length : 1;
  const contactType = component.props.contactType || "standard";
  const poleSpacing = contactType === "changeover" ? 26 : 18;
  const contactLeft = 15;
  const contactRight = 55;
  const contactAltOffset = contactType === "changeover" ? 7 : 0;
  const coilX = -25;
  const coilRadius = 8;
  const coilTermX = -50;
  const coilTermOffsetY = 16;
  const polesStartY = -((poleCount - 1) * poleSpacing) / 2;
  const height = Math.max(CONTACTOR_MIN_H, poleCount * poleSpacing + 34);
  return {
    poleCount,
    poleSpacing,
    contactLeft,
    contactRight,
    contactAltOffset,
    contactType,
    coilX,
    coilRadius,
    coilTermX,
    coilTermOffsetY,
    polesStartY,
    width: CONTACTOR_W,
    height,
  };
}

function getComponentSize(component) {
  let w = component.type === "node" ? 20 : COMPONENT_W;
  let h = component.type === "node" ? 20 : COMPONENT_H;
  if (component.type === "contactor") {
    const layout = getContactorLayout(component);
    w = layout.width;
    h = layout.height;
  }
  const rotation = (component.rotation || 0) % 180;
  if (rotation !== 0) {
    [w, h] = [h, w];
  }
  return { w, h };
}

function addComponent(type, x, y) {
  const def = libraryItems.get(type);
  if (!def) return;
  recordHistory();
  const id = crypto.randomUUID();
  state.components.push({
    id,
    type: def.type,
    variant: def.id,
    x: snap(x),
    y: snap(y),
    rotation: 0,
    props: { ...def.defaults },
  });
  if (def.type === "contactor") state.contactorStates[id] = false;
  state.selectedId = id;
  state.placementType = null;
  markDirty();
  updatePropsPanel();
  render();
}

function getTerminals(component) {
  let base = [];
  switch (component.type) {
    case "motor_3ph":
      base = [
        { x: -COMPONENT_W / 2, y: -12 },
        { x: COMPONENT_W / 2, y: 0 },
        { x: -COMPONENT_W / 2, y: 12 },
      ];
      break;
    case "switch_spdt":
      base = [
        { x: -COMPONENT_W / 2, y: 0 },
        { x: COMPONENT_W / 2, y: -12 },
        { x: COMPONENT_W / 2, y: 12 },
      ];
      break;
    case "timer":
      base = [
        { x: -COMPONENT_W / 2, y: -12 },
        { x: -COMPONENT_W / 2, y: 12 },
        { x: COMPONENT_W / 2 - 18, y: 0 },
        { x: COMPONENT_W / 2, y: -12 },
        { x: COMPONENT_W / 2, y: 12 },
      ];
      break;
    case "time_timer":
      base = [
        { x: -COMPONENT_W / 2, y: 0 },
        { x: COMPONENT_W / 2, y: -12 },
        { x: COMPONENT_W / 2, y: 12 },
      ];
      break;
    case "contactor": {
      const layout = getContactorLayout(component);
      base = [
        { x: layout.coilTermX, y: -layout.coilTermOffsetY },
        { x: layout.coilTermX, y: layout.coilTermOffsetY },
      ];
      for (let i = 0; i < layout.poleCount; i += 1) {
        const y = layout.polesStartY + i * layout.poleSpacing;
        if (layout.contactType === "changeover") {
          base.push({ x: layout.contactLeft, y });
          base.push({ x: layout.contactRight, y: y - layout.contactAltOffset });
          base.push({ x: layout.contactRight, y: y + layout.contactAltOffset });
        } else {
          base.push({ x: layout.contactLeft, y });
          base.push({ x: layout.contactRight, y });
        }
      }
      break;
    }
    case "node":
      base = [
        { x: 0, y: -20 },
        { x: 0, y: 20 },
        { x: -20, y: 0 },
        { x: 20, y: 0 },
      ];
      break;
    case "ground":
      base = [{ x: 0, y: -16 }];
      break;
    case "voltage_source": {
      const type = component.props.supplyType || "DC";
      if (type === "AC3") {
        if ((component.props.connection || "Y") === "Delta") {
          base = [
            { x: -COMPONENT_W / 2, y: -12 },
            { x: COMPONENT_W / 2, y: 0 },
            { x: -COMPONENT_W / 2, y: 12 },
          ];
        } else {
          base = [
            { x: COMPONENT_W / 2, y: -16 },
            { x: COMPONENT_W / 2, y: 0 },
            { x: COMPONENT_W / 2, y: 16 },
            { x: -COMPONENT_W / 2, y: 0 },
          ];
        }
      } else {
        base = [
          { x: -COMPONENT_W / 2, y: 0 },
          { x: COMPONENT_W / 2, y: 0 },
        ];
      }
      break;
    }
    default:
      base = [
        { x: -COMPONENT_W / 2, y: 0 },
        { x: COMPONENT_W / 2, y: 0 },
      ];
      break;
  }
  return base.map((point) => applyRotation(component, point));
}

function drawGrid() {
  if (!state.showGrid) return;
  ctx.save();
  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--grid");
  ctx.lineWidth = 1;
  for (let x = 0; x < state.canvasWidth; x += GRID) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, state.canvasHeight);
    ctx.stroke();
  }
  for (let y = 0; y < state.canvasHeight; y += GRID) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(state.canvasWidth, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawContactorSymbol(component) {
  const layout = getContactorLayout(component);
  const energized = state.contactorStates[component.id];
  const pulse = state.simRunning ? 0.5 + 0.5 * Math.sin(state.animTime * 6) : 0;
  const accent = "#e76f51";

  if (energized) {
    ctx.save();
    ctx.fillStyle = `rgba(231, 111, 81, ${0.12 + 0.1 * pulse})`;
    ctx.beginPath();
    ctx.arc(layout.coilX, 0, layout.coilRadius + 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  ctx.beginPath();
  ctx.arc(layout.coilX, 0, layout.coilRadius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(layout.coilTermX, -layout.coilTermOffsetY);
  ctx.lineTo(layout.coilX - layout.coilRadius, -layout.coilTermOffsetY);
  ctx.moveTo(layout.coilTermX, layout.coilTermOffsetY);
  ctx.lineTo(layout.coilX - layout.coilRadius, layout.coilTermOffsetY);
  ctx.stroke();

  for (let i = 0; i < layout.poleCount; i += 1) {
    const y = layout.polesStartY + i * layout.poleSpacing;
    if (layout.contactType === "changeover") {
      const upperY = y - layout.contactAltOffset;
      const lowerY = y + layout.contactAltOffset;
      const targetY = energized ? upperY : lowerY;
      if (energized) {
        ctx.save();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2.5;
      }
      ctx.beginPath();
      ctx.moveTo(layout.contactLeft - 10, y);
      ctx.lineTo(layout.contactLeft, y);
      ctx.moveTo(layout.contactRight, upperY);
      ctx.lineTo(layout.contactRight + 10, upperY);
      ctx.moveTo(layout.contactRight, lowerY);
      ctx.lineTo(layout.contactRight + 10, lowerY);
      ctx.moveTo(layout.contactLeft, y);
      ctx.lineTo(layout.contactRight - 10, targetY);
      ctx.lineTo(layout.contactRight, targetY);
      ctx.stroke();
      if (energized) ctx.restore();
    } else {
      const poleType = component.props.poles?.[i] || "NO";
      const closed = energized ? poleType === "NO" : poleType === "NC";
      if (energized) {
        ctx.save();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2.5;
      }
      ctx.beginPath();
      ctx.moveTo(layout.contactLeft - 10, y);
      ctx.lineTo(layout.contactLeft, y);
      if (closed) {
        ctx.lineTo(layout.contactRight, y);
      } else {
        ctx.lineTo(layout.contactRight - 10, y - 6);
      }
      ctx.moveTo(layout.contactRight, y);
      ctx.lineTo(layout.contactRight + 10, y);
      ctx.stroke();
      if (energized) ctx.restore();
    }
  }
}

function drawTimerSymbol(component) {
  const coilX = -25;
  const coilRadius = 8;
  const coilTermX = -50;
  const coilTermOffsetY = 16;
  const contactX = 15;
  const outputX = 45;
  const contactOffset = 10;
  const timerState = component.props.timerState || {};
  const closed = Boolean(timerState.outputClosed);
  const running = Boolean(timerState.running);
  const remainingMs = Number(timerState.remainingMs);

  ctx.beginPath();
  ctx.arc(coilX, 0, coilRadius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(coilTermX, -coilTermOffsetY);
  ctx.lineTo(coilX - coilRadius, -coilTermOffsetY);
  ctx.moveTo(coilTermX, coilTermOffsetY);
  ctx.lineTo(coilX - coilRadius, coilTermOffsetY);
  ctx.stroke();

  const upperY = -contactOffset;
  const lowerY = contactOffset;
  const targetY = closed ? upperY : lowerY;
  ctx.beginPath();
  ctx.moveTo(contactX - 10, 0);
  ctx.lineTo(contactX, 0);
  ctx.moveTo(outputX, upperY);
  ctx.lineTo(outputX + 10, upperY);
  ctx.moveTo(outputX, lowerY);
  ctx.lineTo(outputX + 10, lowerY);
  ctx.moveTo(contactX, 0);
  ctx.lineTo(outputX - 8, targetY);
  ctx.lineTo(outputX, targetY);
  ctx.stroke();

  if (running && Number.isFinite(remainingMs)) {
    ctx.save();
    ctx.fillStyle = "#2f2f34";
    ctx.font = "10px Space Grotesk";
    ctx.textAlign = "center";
    ctx.fillText(`${(remainingMs / 1000).toFixed(1)}s`, 0, 30);
    ctx.restore();
  }
}

function drawTimeTimerSymbol(component) {
  const contactX = -10;
  const outputX = 20;
  const contactOffset = 10;
  const timerState = component.props.timerState || {};
  const closed = Boolean(timerState.outputClosed);
  const upperY = -contactOffset;
  const lowerY = contactOffset;
  const targetY = closed ? upperY : lowerY;

  ctx.beginPath();
  ctx.arc(-25, 0, 10, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(-25, -6);
  ctx.lineTo(-25, 0);
  ctx.lineTo(-18, 2);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(contactX - 10, 0);
  ctx.lineTo(contactX, 0);
  ctx.moveTo(outputX, upperY);
  ctx.lineTo(outputX + 10, upperY);
  ctx.moveTo(outputX, lowerY);
  ctx.lineTo(outputX + 10, lowerY);
  ctx.moveTo(contactX, 0);
  ctx.lineTo(outputX - 8, targetY);
  ctx.lineTo(outputX, targetY);
  ctx.stroke();
}

function getTerminalLabels(component) {
  if (component.type === "voltage_source") {
    const type = component.props.supplyType || "DC";
    if (type === "AC3") {
      if ((component.props.connection || "Y") === "Delta") {
        return [
          { index: 0, label: "L1" },
          { index: 1, label: "L2" },
          { index: 2, label: "L3" },
        ];
      }
      return [
        { index: 0, label: "L1" },
        { index: 1, label: "L2" },
        { index: 2, label: "L3" },
        { index: 3, label: "N" },
      ];
    }
    if (type === "AC1") {
      return [
        { index: 0, label: "N" },
        { index: 1, label: "L" },
      ];
    }
    return [
      { index: 0, label: "-" },
      { index: 1, label: "+" },
    ];
  }
  if (component.type === "contactor") {
    const labels = [
      { index: 0, label: "A1" },
      { index: 1, label: "A2" },
    ];
    const poleCount = component.props.poles ? component.props.poles.length : 1;
    if ((component.props.contactType || "standard") === "changeover") {
      for (let i = 0; i < poleCount; i += 1) {
        labels.push({ index: 2 + i * 3, label: `C${i + 1}` });
        labels.push({ index: 3 + i * 3, label: `NO${i + 1}` });
        labels.push({ index: 4 + i * 3, label: `NC${i + 1}` });
      }
    } else {
      for (let i = 0; i < poleCount; i += 1) {
        labels.push({ index: 2 + i * 2, label: `L${i + 1}` });
        labels.push({ index: 3 + i * 2, label: `T${i + 1}` });
      }
    }
    return labels;
  }
  if (component.type === "timer") {
    return [
      { index: 0, label: "A1" },
      { index: 1, label: "A2" },
      { index: 2, label: "C" },
      { index: 3, label: "NO" },
      { index: 4, label: "NC" },
    ];
  }
  if (component.type === "time_timer") {
    return [
      { index: 0, label: "C" },
      { index: 1, label: "NO" },
      { index: 2, label: "NC" },
    ];
  }
  if (component.type === "switch_spdt") {
    return [
      { index: 0, label: "COM" },
      { index: 1, label: "1" },
      { index: 2, label: "2" },
    ];
  }
  if (component.type === "motor_3ph") {
    return [
      { index: 0, label: "L1" },
      { index: 1, label: "L2" },
      { index: 2, label: "L3" },
    ];
  }
  return [];
}

function drawTerminalLabels(component, terminals) {
  const labels = getTerminalLabels(component);
  if (!labels.length) return;
  ctx.save();
  ctx.fillStyle = "#2f2f34";
  ctx.font = "10px Space Grotesk";
  labels.forEach((labelInfo) => {
    const terminal = terminals[labelInfo.index];
    if (!terminal) return;
    const dx = terminal.x - component.x;
    const dy = terminal.y - component.y;
    const offsetX = dx >= 0 ? 10 : -10;
    const offsetY = dy >= 0 ? 10 : -10;
    ctx.textAlign = dx >= 0 ? "left" : "right";
    ctx.textBaseline = dy >= 0 ? "top" : "bottom";
    ctx.fillText(labelInfo.label, terminal.x + offsetX, terminal.y + offsetY);
  });
  ctx.restore();
}

function drawFaultBadge(component) {
  const message = state.faults[component.id] || state.solveErrors[component.id];
  if (!message) return;
  const { w, h } = getComponentSize(component);
  ctx.save();
  ctx.strokeStyle = "#c81e1e";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.rect(component.x - w / 2 - 6, component.y - h / 2 - 6, w + 12, h + 12);
  ctx.stroke();
  ctx.fillStyle = "#c81e1e";
  ctx.font = "11px Space Grotesk";
  ctx.textAlign = "center";
  ctx.fillText("FEL", component.x, component.y - h / 2 - 10);
  ctx.restore();
}

function drawFaultBadge(component) {
  const message = state.faults[component.id];
  if (!message) return;
  const { w, h } = getComponentSize(component);
  ctx.save();
  ctx.strokeStyle = "#c81e1e";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.rect(component.x - w / 2 - 6, component.y - h / 2 - 6, w + 12, h + 12);
  ctx.stroke();
  ctx.fillStyle = "#c81e1e";
  ctx.font = "11px Space Grotesk";
  ctx.textAlign = "center";
  ctx.fillText("FEL", component.x, component.y - h / 2 - 10);
  ctx.restore();
}

function drawComponent(component) {
  const isSelected = component.id === state.selectedId;
  ctx.save();
  ctx.translate(component.x, component.y);
  const rotation = (component.rotation || 0) * (Math.PI / 180);
  ctx.rotate(rotation);
  ctx.strokeStyle = isSelected ? "#e76f51" : "#2f2f34";
  ctx.lineWidth = 2;

  if (component.type === "ground") {
    ctx.beginPath();
    ctx.moveTo(0, -16);
    ctx.lineTo(0, 0);
    ctx.moveTo(-10, 0);
    ctx.lineTo(10, 0);
    ctx.moveTo(-7, 6);
    ctx.lineTo(7, 6);
    ctx.moveTo(-4, 12);
    ctx.lineTo(4, 12);
    ctx.stroke();
  } else if (component.type === "node") {
    ctx.beginPath();
    ctx.arc(0, 0, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#2f2f34";
    ctx.fill();
  } else if (component.type === "resistor") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(left + 10, 0);
    ctx.lineTo(left + 20, -8);
    ctx.lineTo(left + 30, 8);
    ctx.lineTo(left + 40, -8);
    ctx.lineTo(left + 50, 8);
    ctx.lineTo(left + 60, 0);
    ctx.lineTo(right, 0);
    ctx.stroke();
  } else if (component.type === "capacitor") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-8, 0);
    ctx.moveTo(-8, -12);
    ctx.lineTo(-8, 12);
    ctx.moveTo(8, -12);
    ctx.lineTo(8, 12);
    ctx.moveTo(8, 0);
    ctx.lineTo(right, 0);
    ctx.stroke();
  } else if (component.type === "inductor") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(left + 10, 0);
    for (let i = 0; i < 4; i += 1) {
      ctx.arc(left + 20 + i * 12, 0, 6, Math.PI, 0);
    }
    ctx.lineTo(right, 0);
    ctx.stroke();
  } else if (component.type === "switch") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-10, 0);
    if (component.props.closed) {
      ctx.lineTo(10, 0);
    } else {
      ctx.lineTo(8, -10);
    }
    ctx.lineTo(right, 0);
    ctx.stroke();
  } else if (component.type === "push_button") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-12, 0);
    if (component.props.closed) {
      ctx.lineTo(12, 0);
    } else {
      ctx.lineTo(10, -10);
    }
    ctx.lineTo(right, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, -6);
    ctx.lineTo(0, -20);
    ctx.stroke();
  } else if (component.type === "switch_spdt") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    const position = component.props.position || "up";
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-12, 0);
    if (position === "up") {
      ctx.lineTo(10, -10);
    } else {
      ctx.lineTo(10, 10);
    }
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(10, -12);
    ctx.lineTo(right, -12);
    ctx.moveTo(10, 12);
    ctx.lineTo(right, 12);
    ctx.stroke();
  } else if (component.type === "voltage_source") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-16, 0);
    ctx.moveTo(16, 0);
    ctx.lineTo(right, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, 16, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(-4, 0);
    ctx.lineTo(4, 0);
    ctx.moveTo(0, -4);
    ctx.lineTo(0, 4);
    ctx.stroke();
    ctx.font = "10px Space Grotesk";
    ctx.textAlign = "center";
    ctx.fillText(component.props.supplyType || "DC", 0, 24);
  } else if (component.type === "motor") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-18, 0);
    ctx.moveTo(18, 0);
    ctx.lineTo(right, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, 18, 0, Math.PI * 2);
    const running = isMotorRunning(component);
    if (running) {
      ctx.save();
      ctx.strokeStyle = "#5aa7ff";
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.restore();
    } else {
      ctx.stroke();
    }
    if (running) {
      const pulse = state.simRunning ? 0.5 + 0.5 * Math.sin(state.animTime * 8) : 0.5;
      ctx.save();
      ctx.strokeStyle = `rgba(90, 167, 255, ${0.3 + 0.3 * pulse})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(0, 0, 24, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
    ctx.font = "12px Space Grotesk";
    ctx.textAlign = "center";
    ctx.fillText("M", 0, 4);
  } else if (component.type === "motor_3ph") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, -12);
    ctx.lineTo(-18, -12);
    ctx.moveTo(left, 12);
    ctx.lineTo(-18, 12);
    ctx.moveTo(right, 0);
    ctx.lineTo(18, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, 18, 0, Math.PI * 2);
    ctx.stroke();
    const dir = state.motor3phDirection[component.id] || "stopped";
    if (dir !== "stopped") {
      const pulse = state.simRunning ? 0.5 + 0.5 * Math.sin(state.animTime * 8) : 0.5;
      ctx.save();
      ctx.strokeStyle = `rgba(90, 167, 255, ${0.35 + 0.35 * pulse})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(0, 0, 24, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
      ctx.save();
      ctx.strokeStyle = "#5aa7ff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (dir === "cw") {
        ctx.arc(0, 0, 12, 0.3 * Math.PI, 1.6 * Math.PI);
        ctx.lineTo(10, -6);
      } else {
        ctx.arc(0, 0, 12, 1.7 * Math.PI, 0.4 * Math.PI);
        ctx.lineTo(-10, -6);
      }
      ctx.stroke();
      ctx.restore();
    }
    ctx.font = "11px Space Grotesk";
    ctx.textAlign = "center";
    ctx.fillText("M3", 0, 4);
  } else if (component.type === "lamp") {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(-18, 0);
    ctx.moveTo(18, 0);
    ctx.lineTo(right, 0);
    ctx.stroke();
    const lit = isLampLit(component);
    const lampColor = component.props.litColor || "#f6c453";
    const rgb = hexToRgb(lampColor);
    ctx.beginPath();
    ctx.arc(0, 0, 18, 0, Math.PI * 2);
    if (lit) {
      ctx.save();
      ctx.strokeStyle = lampColor;
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.restore();
    } else {
      ctx.stroke();
    }
    if (lit) {
      const pulse = state.simRunning ? 0.5 + 0.5 * Math.sin(state.animTime * 6) : 0.5;
      ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${0.45 + 0.35 * pulse})`;
      ctx.fill();
      ctx.save();
      ctx.strokeStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.5)`;
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.arc(0, 0, 24, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
    ctx.beginPath();
    ctx.moveTo(-8, -6);
    ctx.lineTo(8, 6);
    ctx.moveTo(-8, 6);
    ctx.lineTo(8, -6);
    ctx.stroke();
    if (lit) {
      ctx.save();
      ctx.fillStyle = lampColor;
      ctx.font = "10px Space Grotesk";
      ctx.textAlign = "center";
      ctx.fillText("ON", 0, 30);
      ctx.restore();
    }
  } else if (component.type === "timer") {
    drawTimerSymbol(component);
  } else if (component.type === "time_timer") {
    drawTimeTimerSymbol(component);
  } else if (component.type === "contactor") {
    drawContactorSymbol(component);
  } else {
    const left = -COMPONENT_W / 2;
    const right = COMPONENT_W / 2;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(right, 0);
    ctx.stroke();

    ctx.beginPath();
    ctx.rect(-20, -12, 40, 24);
    ctx.stroke();
  }

  ctx.fillStyle = "#2f2f34";
  ctx.font = "12px Space Grotesk";
  ctx.textAlign = "center";
  if (!["motor", "motor_3ph", "lamp"].includes(component.type)) {
    ctx.fillText(componentLabels[component.type] || component.type, 0, -18);
  }
  ctx.restore();

  if (component.props.name) {
    ctx.save();
    ctx.fillStyle = "#1d1d1f";
    ctx.font = "12px Space Grotesk";
    ctx.textAlign = "left";
    ctx.fillText(component.props.name, component.x + 18, component.y - 18);
    ctx.restore();
  }

  if (component.type === "timer") {
    const timerState = state.timerStates[component.id] || component.props.timerState || {};
    let remainingMs = timerState.remainingMs;
    if (timerState.running && Number.isFinite(timerState.startAt)) {
      const delayMs = Number.isFinite(component.props.delayMs) ? component.props.delayMs : 0;
      remainingMs = Math.max(0, delayMs - (Date.now() - timerState.startAt));
    }
    if (Number.isFinite(remainingMs) && remainingMs > 0) {
      ctx.save();
      ctx.fillStyle = "#2f2f34";
      ctx.font = "11px Space Grotesk";
      ctx.textAlign = "left";
      ctx.fillText(`${(remainingMs / 1000).toFixed(1)}s`, component.x + 18, component.y + 18);
      ctx.restore();
    }
  }
  if (component.type === "time_timer") {
    const timerState = state.timerStates[component.id] || component.props.timerState || {};
    ctx.save();
    ctx.fillStyle = timerState.outputClosed ? "#2b6cb0" : "#6b6b72";
    ctx.font = "11px Space Grotesk";
    ctx.textAlign = "left";
    ctx.fillText(timerState.outputClosed ? "PÅ" : "AV", component.x + 18, component.y + 18);
    ctx.restore();
  }

  const terminals = getTerminals(component);
  ctx.save();
  ctx.fillStyle = isSelected ? "#e76f51" : "#2f2f34";
  terminals.forEach((t) => {
    ctx.beginPath();
    ctx.arc(t.x, t.y, TERMINAL_RADIUS, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
  drawTerminalLabels(component, terminals);
  drawFaultBadge(component);
}

function drawWire(wire) {
  const points = getWirePathPoints(wire);
  if (!points) return;
  const energized = isWireEnergized(wire);
  ctx.save();
  const baseColor = wire.color || state.wireDefaults.color;
  ctx.strokeStyle = energized ? lightenColor(baseColor, 0.25) : baseColor;
  const area = wire.area ?? state.wireDefaults.area;
  ctx.lineWidth = Math.max(2, Math.min(6, 2 + area / 2));
  if (energized) {
    ctx.setLineDash([10, 8]);
    ctx.lineDashOffset = -state.animTime * 20;
  }
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i += 1) {
    ctx.lineTo(points[i].x, points[i].y);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
  if (wire.id === state.selectedWireId && Array.isArray(wire.points)) {
    ctx.save();
    ctx.fillStyle = "#e76f51";
    wire.points.forEach((pt) => {
      ctx.beginPath();
      ctx.rect(pt.x - 4, pt.y - 4, 8, 8);
      ctx.fill();
    });
    ctx.restore();
  }
}

function render() {
  ctx.clearRect(0, 0, state.canvasWidth, state.canvasHeight);
  drawGrid();
  state.wires.forEach(drawWire);
  state.components.forEach(drawComponent);
  state.meters.forEach(drawMeter);

  if (state.wireStart) {
    const start = getTerminalByRef(state.wireStart);
    if (start) {
      const previewPoints = [
        { x: start.x, y: start.y },
        ...state.wirePoints,
        { x: state.wirePreview.x, y: state.wirePreview.y },
      ];
      ctx.save();
      ctx.strokeStyle = "#e76f51";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(previewPoints[0].x, previewPoints[0].y);
      for (let i = 1; i < previewPoints.length; i += 1) {
        ctx.lineTo(previewPoints[i].x, previewPoints[i].y);
      }
      ctx.stroke();
      ctx.restore();
    }
  }
}

function findComponentAt(x, y) {
  return state.components.find((comp) => {
    const { w, h } = getComponentSize(comp);
    return x >= comp.x - w / 2 && x <= comp.x + w / 2 && y >= comp.y - h / 2 && y <= comp.y + h / 2;
  });
}

function findTerminalAt(x, y) {
  for (const comp of state.components) {
    const terminals = getTerminals(comp);
    for (let i = 0; i < terminals.length; i += 1) {
      const t = terminals[i];
      const dx = t.x - x;
      const dy = t.y - y;
      if (Math.hypot(dx, dy) <= TERMINAL_RADIUS + 2) {
        return { compId: comp.id, index: i };
      }
    }
  }
  return null;
}

function getTerminalByRef(ref) {
  if (!ref) return null;
  const comp = state.components.find((c) => c.id === ref.compId);
  if (!comp) return null;
  return getTerminals(comp)[ref.index];
}

function getWirePathPoints(wire) {
  const from = getTerminalByRef(wire.from);
  const to = getTerminalByRef(wire.to);
  if (!from || !to) return null;
  const points = [{ x: from.x, y: from.y }];
  if (Array.isArray(wire.points)) {
    wire.points.forEach((pt) => points.push({ x: pt.x, y: pt.y }));
  }
  points.push({ x: to.x, y: to.y });
  return points;
}

function findWireAt(x, y) {
  for (const wire of state.wires) {
    const points = getWirePathPoints(wire);
    if (!points) continue;
    for (let i = 0; i < points.length - 1; i += 1) {
      const a = points[i];
      const b = points[i + 1];
      const dist = pointLineDistance(x, y, a.x, a.y, b.x, b.y);
      if (dist <= 6) return wire;
    }
  }
  return null;
}

function findWirePointAt(x, y) {
  for (const wire of state.wires) {
    if (!Array.isArray(wire.points)) continue;
    for (let i = 0; i < wire.points.length; i += 1) {
      const pt = wire.points[i];
      if (Math.hypot(pt.x - x, pt.y - y) <= 8) {
        return { wire, index: i };
      }
    }
  }
  return null;
}

function insertWirePoint(wire, x, y) {
  const points = getWirePathPoints(wire);
  if (!points) return;
  let best = { index: 0, dist: Infinity };
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    const dist = pointLineDistance(x, y, a.x, a.y, b.x, b.y);
    if (dist < best.dist) {
      best = { index: i, dist };
    }
  }
  if (!Array.isArray(wire.points)) wire.points = [];
  const insertIndex = Math.max(0, Math.min(wire.points.length, best.index));
  wire.points.splice(insertIndex, 0, { x: snap(x), y: snap(y) });
}

function pointLineDistance(px, py, x1, y1, x2, y2) {
  const A = px - x1;
  const B = py - y1;
  const C = x2 - x1;
  const D = y2 - y1;
  const dot = A * C + B * D;
  const lenSq = C * C + D * D;
  let param = -1;
  if (lenSq !== 0) param = dot / lenSq;
  let xx;
  let yy;
  if (param < 0) {
    xx = x1;
    yy = y1;
  } else if (param > 1) {
    xx = x2;
    yy = y2;
  } else {
    xx = x1 + param * C;
    yy = y1 + param * D;
  }
  return Math.hypot(px - xx, py - yy);
}

function hexToRgb(hex) {
  const cleaned = (hex || "").replace("#", "");
  if (cleaned.length !== 6) return { r: 246, g: 196, b: 83 };
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) {
    return { r: 246, g: 196, b: 83 };
  }
  return { r, g, b };
}

function lightenColor(hex, amount) {
  const rgb = hexToRgb(hex);
  const toChannel = (value) => Math.round(value + (255 - value) * amount);
  return `rgb(${toChannel(rgb.r)}, ${toChannel(rgb.g)}, ${toChannel(rgb.b)})`;
}

function getComplexDiffMagnitude(a, b) {
  if (!a || !b) return 0;
  const re = (a.re || 0) - (b.re || 0);
  const im = (a.im || 0) - (b.im || 0);
  return Math.hypot(re, im);
}

function isWireEnergized(wire) {
  if (!state.simRunning || !state.lastSolution) return false;
  const terminalNodes = state.lastSolution.terminalNodes || {};
  const keyA = `${wire.from.compId}:${wire.from.index}`;
  const keyB = `${wire.to.compId}:${wire.to.index}`;
  const nodeA = terminalNodes[keyA];
  const nodeB = terminalNodes[keyB];
  if (nodeA === undefined || nodeB === undefined) return false;
  let dv = 0;
  const dc = state.lastSolution.nodeVoltages;
  if (Array.isArray(dc) && dc[nodeA] !== undefined && dc[nodeB] !== undefined) {
    const vA = Math.abs(dc[nodeA]);
    const vB = Math.abs(dc[nodeB]);
    dv = Math.max(dv, vA, vB, Math.abs(dc[nodeA] - dc[nodeB]));
  }
  const ac = state.lastSolution.acNodeVoltages;
  if (Array.isArray(ac) && ac[nodeA] !== undefined && ac[nodeB] !== undefined) {
    const vA = Math.hypot(ac[nodeA].re || 0, ac[nodeA].im || 0);
    const vB = Math.hypot(ac[nodeB].re || 0, ac[nodeB].im || 0);
    dv = Math.max(dv, vA, vB, getComplexDiffMagnitude(ac[nodeA], ac[nodeB]));
  }
  return dv > WIRE_LIVE_THRESHOLD;
}

function formatMeterValue(meter) {
  if (meter.value === null || meter.value === undefined) return "--";
  if (Number.isNaN(meter.value)) return "N/A";
  const unit = meter.unit || "";
  return `${meter.value.toFixed(3)} ${unit}`.trim();
}

function getMeterBox(meter) {
  const text = formatMeterValue(meter);
  ctx.save();
  ctx.font = "12px Space Grotesk";
  const textWidth = ctx.measureText(text).width;
  ctx.restore();
  const paddingX = 10;
  const width = Math.max(70, textWidth + paddingX * 2);
  const height = 28;
  return {
    x: meter.x - width / 2,
    y: meter.y - height / 2,
    w: width,
    h: height,
  };
}

function drawMeter(meter) {
  const box = getMeterBox(meter);
  meter.box = box;

  ctx.save();
  ctx.lineWidth = 2;
  if (meter.mode === "current") {
    const comp = state.components.find((c) => c.id === meter.componentId);
    if (comp) {
      ctx.strokeStyle = "#e76f51";
      ctx.beginPath();
      ctx.moveTo(comp.x, comp.y);
      ctx.lineTo(meter.x, meter.y);
      ctx.stroke();
    }
  } else {
    const a = getTerminalByRef(meter.aRef);
    const b = getTerminalByRef(meter.bRef);
    if (a) {
      ctx.strokeStyle = "#d94f4f";
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(meter.x, meter.y);
      ctx.stroke();
    }
    if (b) {
      ctx.strokeStyle = "#2b6cb0";
      ctx.beginPath();
      ctx.moveTo(b.x, b.y);
      ctx.lineTo(meter.x, meter.y);
      ctx.stroke();
    }
  }
  ctx.restore();

  ctx.save();
  ctx.fillStyle = "#1f1e24";
  ctx.strokeStyle = "#f6c453";
  ctx.lineWidth = 2;
  ctx.beginPath();
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(box.x, box.y, box.w, box.h, 8);
  } else {
    const r = 8;
    ctx.moveTo(box.x + r, box.y);
    ctx.lineTo(box.x + box.w - r, box.y);
    ctx.quadraticCurveTo(box.x + box.w, box.y, box.x + box.w, box.y + r);
    ctx.lineTo(box.x + box.w, box.y + box.h - r);
    ctx.quadraticCurveTo(box.x + box.w, box.y + box.h, box.x + box.w - r, box.y + box.h);
    ctx.lineTo(box.x + r, box.y + box.h);
    ctx.quadraticCurveTo(box.x, box.y + box.h, box.x, box.y + box.h - r);
    ctx.lineTo(box.x, box.y + r);
    ctx.quadraticCurveTo(box.x, box.y, box.x + r, box.y);
  }
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "#fef4e6";
  ctx.font = "12px Space Grotesk";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(formatMeterValue(meter), meter.x, meter.y);

  const closeX = box.x + box.w - 14;
  const closeY = box.y + 6;
  ctx.strokeStyle = "#fef4e6";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(closeX, closeY);
  ctx.lineTo(closeX + 8, closeY + 8);
  ctx.moveTo(closeX + 8, closeY);
  ctx.lineTo(closeX, closeY + 8);
  ctx.stroke();
  ctx.restore();
}

function hitTestMeterClose(x, y) {
  for (const meter of state.meters) {
    const box = meter.box;
    if (!box) continue;
    const closeX = box.x + box.w - 14;
    const closeY = box.y + 6;
    if (x >= closeX && x <= closeX + 8 && y >= closeY && y <= closeY + 8) {
      return meter;
    }
  }
  return null;
}

function hitTestMeterBox(x, y) {
  for (const meter of state.meters) {
    const box = meter.box;
    if (!box) continue;
    if (x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h) {
      return meter;
    }
  }
  return null;
}

function updatePropsPanel() {
  const comp = state.components.find((c) => c.id === state.selectedId);
  const wire = state.wires.find((w) => w.id === state.selectedWireId);
  if (!comp) {
    if (wire) {
      const wireColor = wire.color || state.wireDefaults.color;
      const wireArea = wire.area ?? state.wireDefaults.area;
      const wireLength = wire.length ?? state.wireDefaults.length;
      const wireMaterial = wire.material || state.wireDefaults.material;
      propsEl.innerHTML = `
        <div><strong>Kabel</strong></div>
        <label>Färg
          <input type="color" name="wireColor" value="${wireColor}" />
        </label>
        <label>Area (mm²)
          <input type="number" step="0.1" name="wireArea" value="${wireArea}" />
        </label>
        <label>Längd (m)
          <input type="number" step="0.1" name="wireLength" value="${wireLength}" />
        </label>`;
      propsEl.innerHTML += `
        <label>Material
          <select name="wireMaterial">
            <option value="copper" ${wireMaterial === "copper" ? "selected" : ""}>Koppar</option>
            <option value="aluminum" ${wireMaterial === "aluminum" ? "selected" : ""}>Aluminium</option>
          </select>
        </label>`;
      propsEl.querySelectorAll("input, select").forEach((input) => {
        input.addEventListener("change", (event) => {
          const key = event.target.name;
          if (key === "wireColor") wire.color = event.target.value;
          if (key === "wireArea") wire.area = Number(event.target.value);
          if (key === "wireLength") wire.length = Number(event.target.value);
          if (key === "wireMaterial") wire.material = event.target.value;
          markDirty();
          render();
        });
      });
      return;
    }
    propsEl.innerHTML = `
      <div><strong>Kabelstandard</strong></div>
      <label>Färg
        <input type="color" name="defaultWireColor" value="${state.wireDefaults.color}" />
      </label>
      <label>Area (mm²)
        <input type="number" step="0.1" name="defaultWireArea" value="${state.wireDefaults.area}" />
      </label>
      <label>Längd (m)
        <input type="number" step="0.1" name="defaultWireLength" value="${state.wireDefaults.length}" />
      </label>`;
    propsEl.innerHTML += `
      <label>Material
        <select name="defaultWireMaterial">
          <option value="copper" ${state.wireDefaults.material === "copper" ? "selected" : ""}>Koppar</option>
          <option value="aluminum" ${state.wireDefaults.material === "aluminum" ? "selected" : ""}>Aluminium</option>
        </select>
      </label>`;
    propsEl.querySelectorAll("input, select").forEach((input) => {
      input.addEventListener("change", (event) => {
        const key = event.target.name;
        if (key === "defaultWireColor") state.wireDefaults.color = event.target.value;
        if (key === "defaultWireArea") state.wireDefaults.area = Number(event.target.value);
        if (key === "defaultWireLength") state.wireDefaults.length = Number(event.target.value);
        if (key === "defaultWireMaterial") state.wireDefaults.material = event.target.value;
      });
    });
    return;
  }
  if (comp.rotation === undefined || comp.rotation === null) comp.rotation = 0;

  let html = `<div><strong>${comp.type}</strong></div>`;
  html += `
    <label>Rotation
      <select name="rotation">
        <option value="0" ${comp.rotation === 0 ? "selected" : ""}>0°</option>
        <option value="90" ${comp.rotation === 90 ? "selected" : ""}>90°</option>
        <option value="180" ${comp.rotation === 180 ? "selected" : ""}>180°</option>
        <option value="270" ${comp.rotation === 270 ? "selected" : ""}>270°</option>
      </select>
    </label>`;
  if ("value" in comp.props) {
    html += `
      <label>Värde
        <input type="number" step="any" name="value" value="${comp.props.value}" />
      </label>`;
  }
  html += `
    <label>Namn
      <input type="text" name="name" value="${comp.props.name || ""}" />
    </label>`;
  if (comp.type === "voltage_source") {
    html += `
      <label>Typ
        <select name="supplyType">
          <option value="DC" ${comp.props.supplyType === "DC" ? "selected" : ""}>DC</option>
          <option value="AC1" ${comp.props.supplyType === "AC1" ? "selected" : ""}>AC 1-fas</option>
          <option value="AC3" ${comp.props.supplyType === "AC3" ? "selected" : ""}>AC 3-fas</option>
        </select>
      </label>`;
    if (comp.props.supplyType && comp.props.supplyType !== "DC") {
      html += `
        <label>Frekvens (Hz)
          <input type="number" step="1" name="frequency" value="${comp.props.frequency ?? 50}" />
        </label>`;
    }
    if (comp.props.supplyType === "AC3") {
      html += `
        <label>Koppling
          <select name="connection">
            <option value="Y" ${comp.props.connection === "Y" ? "selected" : ""}>Y (med N)</option>
            <option value="Delta" ${comp.props.connection === "Delta" ? "selected" : ""}>Delta</option>
          </select>
        </label>`;
    }
  }
  if ("threshold" in comp.props) {
    html += `
      <label>Tändspänning (V)
        <input type="number" step="any" name="threshold" value="${comp.props.threshold}" />
      </label>`;
  }
  if ("ratedVoltage" in comp.props) {
    html += `
      <label>Märkspänning (V)
        <input type="number" step="any" name="ratedVoltage" value="${comp.props.ratedVoltage}" />
      </label>`;
  }
  if (comp.type === "lamp") {
    html += `
      <label>Ljusfärg
        <input type="color" name="litColor" value="${comp.props.litColor || "#f6c453"}" />
      </label>`;
  }
  if ("startVoltage" in comp.props) {
    html += `
      <label>Startspänning (V)
        <input type="number" step="any" name="startVoltage" value="${comp.props.startVoltage}" />
      </label>`;
  }
  if (comp.type === "motor_3ph") {
    html += `
      <label>Koppling
        <select name="motor3phConnection">
          <option value="Y" ${comp.props.connection === "Y" ? "selected" : ""}>Y</option>
          <option value="Delta" ${comp.props.connection === "Delta" ? "selected" : ""}>Delta</option>
        </select>
      </label>`;
  }
  if (comp.type === "contactor") {
    html += `
      <label>Spolresistans (Ω)
        <input type="number" step="any" name="coilResistance" value="${comp.props.coilResistance}" />
      </label>
      <label>Inslagsspänning (V)
        <input type="number" step="any" name="pullInVoltage" value="${comp.props.pullInVoltage}" />
      </label>`;
    if ("coilRatedVoltage" in comp.props) {
      html += `
        <label>Spol-märkspänning (V)
          <input type="number" step="any" name="coilRatedVoltage" value="${comp.props.coilRatedVoltage}" />
        </label>`;
    }
    const closed = state.contactorStates[comp.id];
    html += `<div class="muted">Status: ${closed ? "Stängd" : "Öppen"}</div>`;
    const poleCount = Array.isArray(comp.props.poles) ? comp.props.poles.length : 1;
    html += `
      <label>Typ
        <select name="contactType">
          <option value="standard" ${comp.props.contactType === "standard" ? "selected" : ""}>Standard</option>
          <option value="changeover" ${comp.props.contactType === "changeover" ? "selected" : ""}>Omkastande</option>
        </select>
      </label>
      <label>Antal poler
        <input type="number" min="1" max="6" step="1" name="poleCount" value="${poleCount}" />
      </label>`;
    if (comp.props.contactType !== "changeover" && Array.isArray(comp.props.poles)) {
      html += `<div><strong>Poler</strong></div>`;
      comp.props.poles.forEach((pole, idx) => {
        html += `
          <label>Pol ${idx + 1}
            <select name="pole_${idx}">
              <option value="NO" ${pole === "NO" ? "selected" : ""}>NO</option>
              <option value="NC" ${pole === "NC" ? "selected" : ""}>NC</option>
            </select>
        </label>`;
      });
    }
  }
  if (comp.type === "timer") {
    const timerState = state.timerStates[comp.id] || comp.props.timerState || {};
    let remainingMs = timerState.remainingMs;
    if (timerState.running && Number.isFinite(timerState.startAt)) {
      const delayMs = Number.isFinite(comp.props.delayMs) ? comp.props.delayMs : 0;
      remainingMs = Math.max(0, delayMs - (Date.now() - timerState.startAt));
    }
    const remaining = Number.isFinite(remainingMs) ? (remainingMs / 1000).toFixed(1) : "-";
    html += `
      <label>Spolresistans (Ω)
        <input type="number" step="any" name="coilResistance" value="${comp.props.coilResistance}" />
      </label>
      <label>Inslagsspänning (V)
        <input type="number" step="any" name="pullInVoltage" value="${comp.props.pullInVoltage}" />
      </label>
      <label>Fördröjning (s)
        <input type="number" step="0.1" name="delaySeconds" value="${(comp.props.delayMs || 0) / 1000}" />
      </label>
      <label>Loop
        <select name="timerLoop">
          <option value="false" ${!comp.props.loop ? "selected" : ""}>Nej</option>
          <option value="true" ${comp.props.loop ? "selected" : ""}>Ja</option>
        </select>
      </label>
      <div class="muted">Status: ${timerState.outputClosed ? "Sluten" : "Öppen"}</div>
      <div class="muted">Kvar: ${remaining}s</div>`;
  }
  if (comp.type === "time_timer") {
    const timerState = state.timerStates[comp.id] || comp.props.timerState || {};
    html += `
      <label>Starttid
        <input type="time" name="startTime" value="${comp.props.startTime || "08:00"}" />
      </label>
      <label>Stopptid
        <input type="time" name="endTime" value="${comp.props.endTime || "17:00"}" />
      </label>
      <div class="muted">Status: ${timerState.outputClosed ? "PÅ" : "AV"}</div>`;
  }
  if ("closed" in comp.props) {
    html += `
      <label>Status
        <select name="closed">
          <option value="true" ${comp.props.closed ? "selected" : ""}>Stängd</option>
          <option value="false" ${!comp.props.closed ? "selected" : ""}>Öppen</option>
        </select>
      </label>`;
  }
  if (comp.type === "switch_spdt") {
    html += `
      <label>Läge
        <select name="position">
          <option value="up" ${comp.props.position === "up" ? "selected" : ""}>Övre</option>
          <option value="down" ${comp.props.position === "down" ? "selected" : ""}>Nedre</option>
        </select>
      </label>`;
  }
  if (comp.type === "push_button") {
    html += `<div class="muted">Momentan: håll inne i simläge.</div>`;
  }
  if (state.solveErrors[comp.id]) {
    html += `<div class="muted">Fel: ${state.solveErrors[comp.id]}</div>`;
  }
  if (state.faults[comp.id]) {
    html += `<div class="muted">Fel: ${state.faults[comp.id]}</div>`;
  }
  propsEl.innerHTML = html;

  propsEl.querySelectorAll("input, select").forEach((input) => {
    input.addEventListener("change", (event) => {
      const key = event.target.name;
      if (key === "value") comp.props.value = Number(event.target.value);
      if (key === "name") comp.props.name = event.target.value;
      if (key === "supplyType") comp.props.supplyType = event.target.value;
      if (key === "frequency") comp.props.frequency = Number(event.target.value);
      if (key === "connection") comp.props.connection = event.target.value;
      if (key === "threshold") comp.props.threshold = Number(event.target.value);
      if (key === "ratedVoltage") comp.props.ratedVoltage = Number(event.target.value);
      if (key === "litColor") comp.props.litColor = event.target.value;
      if (key === "startVoltage") comp.props.startVoltage = Number(event.target.value);
      if (key === "motor3phConnection") comp.props.connection = event.target.value;
      if (key === "coilResistance") comp.props.coilResistance = Number(event.target.value);
      if (key === "pullInVoltage") comp.props.pullInVoltage = Number(event.target.value);
      if (key === "coilRatedVoltage") comp.props.coilRatedVoltage = Number(event.target.value);
      if (key === "delaySeconds") {
        const seconds = Number(event.target.value);
        if (Number.isFinite(seconds)) {
          comp.props.delayMs = Math.max(0, seconds * 1000);
        }
      }
      if (key === "timerLoop") comp.props.loop = event.target.value === "true";
      if (key === "startTime") comp.props.startTime = event.target.value;
      if (key === "endTime") comp.props.endTime = event.target.value;
      if (key === "contactType") comp.props.contactType = event.target.value;
      if (key === "poleCount") {
        const nextCount = Math.max(1, Math.min(6, Number(event.target.value) || 1));
        const poles = Array.isArray(comp.props.poles) ? [...comp.props.poles] : ["NO"];
        if (nextCount > poles.length) {
          while (poles.length < nextCount) poles.push("NO");
        } else if (nextCount < poles.length) {
          poles.length = nextCount;
        }
        comp.props.poles = poles;
      }
      if (key === "closed") comp.props.closed = event.target.value === "true";
      if (key === "rotation") comp.rotation = Number(event.target.value);
      if (key.startsWith("pole_")) {
        const idx = Number(key.split("_")[1]);
        comp.props.poles[idx] = event.target.value;
      }
      if (key === "position") comp.props.position = event.target.value;
      markDirty();
      render();
    });
  });
}

function setActiveTool(tool) {
  state.activeTool = tool;
  state.placementType = null;
  state.wireStart = null;
  state.meter.picks = [];
  toolButtons.querySelectorAll("button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tool === tool);
  });
  render();
}

function buildLibrary() {
  libraryEl.innerHTML = "";
  libraryGroups.forEach((group) => {
    const wrapper = document.createElement("details");
    wrapper.className = "library-group";
    wrapper.open = group.name === "Källor";
    const title = document.createElement("summary");
    title.className = "library-title";
    title.textContent = group.name;
    wrapper.appendChild(title);
    group.items.forEach((item) => {
      const btn = document.createElement("button");
      btn.textContent = item.label;
      btn.addEventListener("click", () => {
        setActiveTool("select");
        state.placementType = item.id;
      });
      wrapper.appendChild(btn);
    });
    libraryEl.appendChild(wrapper);
  });
}

function rotateSelected(step = 90) {
  if (!state.selectedId) return;
  const comp = state.components.find((c) => c.id === state.selectedId);
  if (!comp) return;
  comp.rotation = ((comp.rotation || 0) + step + 360) % 360;
  markDirty();
  updatePropsPanel();
  render();
}

async function handleMeterClick(hit) {
  const mode = state.meter.mode;
  if (["current", "ac_current", "ac_power_p", "ac_power_q", "ac_power_s", "ac_pf"].includes(mode)) {
    if (!hit.component) {
      meterReadout.textContent = "Välj en komponent";
      return;
    }
    const unitMap = {
      current: "A",
      ac_current: "A",
      ac_power_p: "W",
      ac_power_q: "var",
      ac_power_s: "VA",
      ac_pf: "",
    };
    const meter = {
      id: crypto.randomUUID(),
      mode,
      componentId: hit.component.id,
      x: hit.component.x + 60,
      y: hit.component.y - 40,
      value: null,
      unit: unitMap[mode],
    };
    state.meters.push(meter);
    await updateMeterValue(meter);
    return;
  }

  if (hit.terminal) {
    state.meter.picks.push(hit.terminal);
    if (state.meter.picks.length === 2) {
      const aRef = state.meter.picks[0];
      const bRef = state.meter.picks[1];
      const a = getTerminalByRef(aRef);
      const b = getTerminalByRef(bRef);
      const midpoint = a && b ? { x: (a.x + b.x) / 2 + 40, y: (a.y + b.y) / 2 - 40 } : { x: 100, y: 100 };
      const unitMap = {
        voltage: "V",
        resistance: "Ω",
        ac_voltage: "V",
        ac_phase: "°",
      };
      const unit = unitMap[mode] || "";
      const meter = {
        id: crypto.randomUUID(),
        mode,
        aRef,
        bRef,
        x: midpoint.x,
        y: midpoint.y,
        value: null,
        unit,
      };
      state.meters.push(meter);
      await updateMeterValue(meter);
      state.meter.picks = [];
    }
  }
}

canvas.addEventListener("mousedown", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const snapped = { x: snap(x), y: snap(y) };

  const meterClose = hitTestMeterClose(x, y);
  if (meterClose) {
    state.meters = state.meters.filter((m) => m.id !== meterClose.id);
    render();
    return;
  }

  const meterBox = hitTestMeterBox(x, y);
  if (meterBox) {
    state.draggingMeter = { id: meterBox.id, offsetX: meterBox.x - x, offsetY: meterBox.y - y };
    return;
  }

  if (state.placementType) {
    addComponent(state.placementType, snapped.x, snapped.y);
    return;
  }

  const terminal = findTerminalAt(x, y);
  const component = findComponentAt(x, y);
  const wirePoint = findWirePointAt(x, y);

  if (state.activeTool === "select") {
    if (wirePoint) {
      recordHistory();
      state.selectedWireId = wirePoint.wire.id;
      state.selectedId = null;
      state.draggingWirePoint = { wireId: wirePoint.wire.id, index: wirePoint.index };
      updatePropsPanel();
      render();
      return;
    }
    if (component && state.simRunning) {
      if (component.type === "switch") {
        component.props.closed = !component.props.closed;
        markDirty();
        updatePropsPanel();
        render();
        return;
      }
      if (component.type === "push_button") {
        component.props.closed = true;
        state.activeMomentary = component.id;
        markDirty();
        updatePropsPanel();
        render();
        return;
      }
      if (component.type === "switch_spdt") {
        component.props.position = component.props.position === "up" ? "down" : "up";
        markDirty();
        updatePropsPanel();
        render();
        return;
      }
    }
    if (component) {
      recordHistory();
      state.selectedId = component.id;
      state.selectedWireId = null;
      state.dragging = { id: component.id, offsetX: component.x - x, offsetY: component.y - y };
      updatePropsPanel();
      render();
    } else {
      const wire = findWireAt(x, y);
      if (wire) {
        state.selectedWireId = wire.id;
        state.selectedId = null;
        updatePropsPanel();
        render();
      } else {
        state.selectedId = null;
        state.selectedWireId = null;
        updatePropsPanel();
        render();
      }
    }
  } else if (state.activeTool === "wire") {
    if (terminal) {
      if (!state.wireStart) {
        state.wireStart = terminal;
        state.wirePreview = { x: snapped.x, y: snapped.y };
        state.wirePoints = [];
      } else {
        if (terminal.compId !== state.wireStart.compId || terminal.index !== state.wireStart.index) {
          recordHistory();
          state.wires.push({
            id: crypto.randomUUID(),
            from: state.wireStart,
            to: terminal,
            points: [...state.wirePoints],
            color: state.wireDefaults.color,
            area: state.wireDefaults.area,
            length: state.wireDefaults.length,
            material: state.wireDefaults.material,
          });
          markDirty();
        }
        state.wireStart = null;
        state.wirePreview = null;
        state.wirePoints = [];
      }
      render();
    } else if (state.wireStart) {
      const lastPoint = state.wirePoints[state.wirePoints.length - 1];
      if (!lastPoint || lastPoint.x !== snapped.x || lastPoint.y !== snapped.y) {
        state.wirePoints.push({ x: snapped.x, y: snapped.y });
        state.wirePreview = { x: snapped.x, y: snapped.y };
        render();
      }
    }
  } else if (state.activeTool === "erase") {
    if (component) {
      recordHistory();
      state.components = state.components.filter((c) => c.id !== component.id);
      state.wires = state.wires.filter((w) => w.from.compId !== component.id && w.to.compId !== component.id);
      if (component.type === "contactor") delete state.contactorStates[component.id];
      state.selectedId = null;
      state.selectedWireId = null;
      markDirty();
      updatePropsPanel();
      render();
    } else {
      if (wirePoint) {
        recordHistory();
        wirePoint.wire.points.splice(wirePoint.index, 1);
        render();
        return;
      }
      const wire = findWireAt(x, y);
      if (wire) {
        recordHistory();
        state.wires = state.wires.filter((w) => w.id !== wire.id);
        state.selectedWireId = null;
        markDirty();
        render();
      }
    }
  } else if (state.activeTool === "meter") {
    handleMeterClick({ terminal, component });
  }
});

canvas.addEventListener("mousemove", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (state.draggingMeter) {
    const meter = state.meters.find((m) => m.id === state.draggingMeter.id);
    if (meter) {
      meter.x = x + state.draggingMeter.offsetX;
      meter.y = y + state.draggingMeter.offsetY;
      render();
    }
    return;
  }
  if (state.draggingWirePoint) {
    const wire = state.wires.find((w) => w.id === state.draggingWirePoint.wireId);
    if (wire && Array.isArray(wire.points)) {
      wire.points[state.draggingWirePoint.index] = { x: snap(x), y: snap(y) };
      render();
    }
    return;
  }
  if (state.dragging) {
    const comp = state.components.find((c) => c.id === state.dragging.id);
    if (comp) {
      comp.x = snap(x + state.dragging.offsetX);
      comp.y = snap(y + state.dragging.offsetY);
      render();
    }
  } else if (state.wireStart) {
    state.wirePreview = { x: snap(x), y: snap(y) };
    render();
  }
});

canvas.addEventListener("mouseup", () => {
  state.dragging = null;
  state.draggingWirePoint = null;
  state.draggingMeter = null;
  if (state.activeMomentary) {
    const comp = state.components.find((c) => c.id === state.activeMomentary);
    if (comp && comp.type === "push_button") {
      comp.props.closed = false;
      state.activeMomentary = null;
      markDirty();
      updatePropsPanel();
    }
  }
  if (state.simRunning && state.simDirty) render();
});

canvas.addEventListener("dblclick", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const wire = findWireAt(x, y);
  if (!wire) return;
  insertWirePoint(wire, x, y);
  state.selectedWireId = wire.id;
  render();
});

canvas.addEventListener("mouseleave", () => {
  state.dragging = null;
  state.draggingWirePoint = null;
  if (state.activeMomentary) {
    const comp = state.components.find((c) => c.id === state.activeMomentary);
    if (comp && comp.type === "push_button") {
      comp.props.closed = false;
      state.activeMomentary = null;
      markDirty();
      updatePropsPanel();
    }
  }
});

buildLibrary();
updatePropsPanel();
updateSimToggle();
renderSaveList();
renderDebugLog();

toolButtons.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  setActiveTool(button.dataset.tool);
});

if (debugClear) {
  debugClear.addEventListener("click", () => {
    state.debugEntries = [];
    renderDebugLog();
  });
}

if (canvasResizer) {
  canvasResizer.addEventListener("mousedown", (event) => {
    event.preventDefault();
    const startWidth = state.canvasWidth || canvas.clientWidth;
    const startHeight = state.canvasHeight || canvas.clientHeight;
    state.canvasResizing = {
      startX: event.clientX,
      startY: event.clientY,
      startWidth,
      startHeight,
    };
  });
}

if (undoBtn) {
  undoBtn.addEventListener("click", () => {
    const snapshot = state.undoStack.pop();
    if (snapshot) {
      restoreSnapshot(snapshot);
    }
  });
}

runBtn.addEventListener("click", () => {
  state.simRunning = true;
  markDirty();
  updatePropsPanel();
  updateSimToggle();
  render();
});

clearBtn.addEventListener("click", () => {
  recordHistory();
  state.components = [];
  state.wires = [];
  state.selectedId = null;
  state.wireStart = null;
  state.wirePoints = [];
  state.selectedWireId = null;
  state.lastSolution = null;
  state.contactorStates = {};
  state.lampLit = {};
  state.motorRunning = {};
  state.motor3phDirection = {};
  state.timerStates = {};
  state.faults = {};
  state.solveErrors = {};
  state.meters = [];
  state.simPending = false;
  state.simRunning = false;
  state.simDirty = true;
  state.draggingWirePoint = null;
  clearSimSchedule();
  meterReadout.textContent = "-";
  simStatus.textContent = "Rensad.";
  updatePropsPanel();
  updateSimToggle();
  render();
  renderSaveList();
});

gridToggle.addEventListener("click", () => {
  state.showGrid = !state.showGrid;
  gridToggle.textContent = `Rutnät: ${state.showGrid ? "På" : "Av"}`;
  render();
});

simToggle.addEventListener("click", () => {
  state.simRunning = !state.simRunning;
  if (state.simRunning) {
    markDirty();
  } else {
    simStatus.textContent = "Simulering pausad.";
    clearSimSchedule();
  }
  updatePropsPanel();
  updateSimToggle();
  render();
});

rotateBtn.addEventListener("click", () => {
  rotateSelected(90);
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    const snapshot = state.undoStack.pop();
    if (snapshot) {
      restoreSnapshot(snapshot);
    }
    return;
  }
  if (event.key.toLowerCase() !== "r") return;
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  rotateSelected(90);
});

document.addEventListener("mousemove", (event) => {
  if (!state.canvasResizing) return;
  const dx = event.clientX - state.canvasResizing.startX;
  const dy = event.clientY - state.canvasResizing.startY;
  applyCanvasSize(state.canvasResizing.startWidth + dx, state.canvasResizing.startHeight + dy);
  render();
});

document.addEventListener("mouseup", () => {
  if (state.canvasResizing) {
    state.canvasResizing = null;
  }
});

document.querySelectorAll("input[name=\"meterMode\"]").forEach((input) => {
  input.addEventListener("change", (event) => {
    state.meter.mode = event.target.value;
    state.meter.picks = [];
    meterReadout.textContent = "-";
  });
});

saveBtn.addEventListener("click", async () => {
  if (!saveNameInput) return;
  const name = saveNameInput.value.trim();
  if (!name) return;
  try {
    await saveCurrent(name);
  } catch (error) {
    simStatus.textContent = error.message || "Kunde inte spara.";
  }
});

if (saveNameInput) {
  saveNameInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      const name = saveNameInput.value.trim();
      if (!name) return;
      try {
        await saveCurrent(name);
      } catch (error) {
        simStatus.textContent = error.message || "Kunde inte spara.";
      }
    }
  });
}

function animationLoop(time) {
  state.animTime = time / 1000;
  if (state.simRunning) render();
  requestAnimationFrame(animationLoop);
}

requestAnimationFrame(animationLoop);

function isLampLit(component) {
  return Boolean(state.lampLit[component.id]);
}

function isMotorRunning(component) {
  return Boolean(state.motorRunning[component.id]);
}
