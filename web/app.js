"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

let S = null;            // settings (server)
let doc = null;          // loaded document
let order = [];          // [{id, on}]
let st = null;           // last machine status
let job = null;          // last job status
let logSeq = 0;
let resumeInfo = null;
let startSel = null;     // {id, path} – start point (original path index)
let pickMode = false;
let jogStep = 10;
const view = { s: 1, ox: 0, oy: 0 };
let serverArea = null;   // allowed area from the server (incl. firmware limits)
const area = () => serverArea || [0, 0, S.machine.max_x, S.machine.max_y];

// ------------------------------------------------------------------ helpers
async function api(path, body) {
  try {
    const r = await fetch(path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const j = await r.json();
    if (j && j.error) logLocal("err", j.error);
    return j;
  } catch (e) {
    logLocal("err", "Can't reach the Nib server – is it still running?");
    return { error: String(e) };
  }
}
const getPath = (o, p) => p.split(".").reduce((a, k) => (a ? a[k] : undefined), o);
function setPath(o, p, v) {
  const ks = p.split("."); let a = o;
  ks.slice(0, -1).forEach((k) => (a = a[k] = a[k] || {}));
  a[ks[ks.length - 1]] = v;
}
function nested(p, v) { const o = {}; setPath(o, p, v); return o; }
const fmtNum = (v, d = 0) => Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
const jobActive = () => job && ["running", "paused", "pen_change"].includes(job.state);
const connected = () => st && st.connected;

let saveTimer = null;
function saveSettings(partial) {
  clearTimeout(saveTimer);
  pendingSave = deepMerge(pendingSave, partial);
  saveTimer = setTimeout(() => { api("/api/settings", pendingSave); pendingSave = {}; }, 300);
}
let pendingSave = {};
const stable = (o) => JSON.stringify(Object.keys(o).sort().map((k) => [k, o[k]]));
const saveTimer_active = () => Object.keys(pendingSave).length > 0;
let lastVmax = "";
function applySpeedLimits(v) {
  const key = JSON.stringify(v || null);
  if (key === lastVmax) return;
  lastVmax = key;
  const [vxy, vz] = v || [null, null];
  for (const k of ["feed_draw", "feed_travel", "jog_feed", "z_feed"]) {
    const el = $(`[data-set="machine.${k}"]`);
    const lim = k === "z_feed" ? vz : vxy;
    if (lim) { el.max = lim; el.title = `max ${lim} mm/min (plotter firmware)`; }
    else { el.removeAttribute("max"); el.title = ""; }
  }
  $("#speedHint").textContent = vxy ? `Plotter maximum: X/Y ${fmtNum(vxy)} mm/min, Z ${fmtNum(vz)} mm/min` : "";
}
function deepMerge(a, b) {
  const o = { ...a };
  for (const k in b) o[k] = (b[k] && typeof b[k] === "object" && !Array.isArray(b[k])) ? deepMerge(o[k] || {}, b[k]) : b[k];
  return o;
}

// ------------------------------------------------------------ placement
// identical to gcode.py make_placer()
function placedSize() {
  const b = doc.bbox, p = S.place;
  let w = b[2] - b[0], h = b[3] - b[1];
  if (((p.rotate | 0) % 180) === 90) [w, h] = [h, w];
  return [w * p.scale, h * p.scale];
}
function makePlacer() {
  const [minx, miny, maxx, maxy] = doc.bbox;
  const w = maxx - minx, h = maxy - miny;
  const { x: ox, y: oy, scale: s } = S.place;
  const r = ((S.place.rotate | 0) % 360 + 360) % 360;
  return (x, y) => {
    let u = x - minx, v = y - miny;
    if (r === 90) [u, v] = [h - v, u];
    else if (r === 180) [u, v] = [w - u, h - v];
    else if (r === 270) [u, v] = [v, w - u];
    return [ox + u * s, oy + v * s];
  };
}
function machineToPaper(x, y) {
  const m = S.machine;
  if (m.invert_x) x = -x;
  if (m.invert_y) y = -y;
  if (m.swap_xy) [x, y] = [y, x];
  return [x, y];
}

// ---------------------------------------------------------------- time
function layerSeconds(l) {
  const m = S.machine, s = S.place.scale;
  const fd = Math.max(m.feed_draw, 1) / 60, ft = Math.max(m.feed_travel, 1) / 60, zf = Math.max(m.z_feed, 1) / 60;
  const zt = Math.abs(m.z_down - m.z_up) / zf * 2;
  const delays = (+m.pen_up_delay || 0) + (+m.pen_down_delay || 0);
  return (l.draw_len * s / fd + l.travel_len * s / ft + l.lifts * (zt + delays + 0.05)) * 1.15;
}

// --------------------------------------------------------------- Theme
// preview colors come from the CSS variables (light/dark)
let TC = {};
function readTheme() {
  const cs = getComputedStyle(document.documentElement);
  for (const k of ["accent", "accent-text", "text", "muted", "faint", "bad", "ok", "paper", "grid", "table", "panel"])
    TC[k] = cs.getPropertyValue("--" + k).trim();
  TC.dark = cs.getPropertyValue("color-scheme").trim() === "dark";
}
const THEMES = ["system", "light", "dark"];
const THEME_ICON = { system: "#i-auto", light: "#i-sun", dark: "#i-moon" };
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  $("#btnTheme use").setAttribute("href", THEME_ICON[t] || THEME_ICON.system);
  $("#btnTheme").title = `Theme: ${t} (click to change)`;
  readTheme(); scheduleDraw();
}
let theme = "system";
try { theme = localStorage.getItem("theme") || "system"; } catch (e) { /* ignore */ }
$("#btnTheme").onclick = () => {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  try { localStorage.setItem("theme", theme); } catch (e) { /* ignore */ }
  applyTheme(theme);
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readTheme(); scheduleDraw(); });

// collapsible sections (state is remembered)
(function folds() {
  let F = {};
  try { F = JSON.parse(localStorage.getItem("folds")) || {}; } catch (e) { F = {}; }
  const DEFAULT_CLOSED = { secMachine: true, secOpt: true };
  $$("section.fold").forEach((sec) => {
    const closed = sec.id in F ? F[sec.id] : !!DEFAULT_CLOSED[sec.id];
    sec.classList.toggle("closed", closed);
    sec.querySelector("h2").onclick = () => {
      F[sec.id] = sec.classList.toggle("closed");
      try { localStorage.setItem("folds", JSON.stringify(F)); } catch (e) { /* ignore */ }
    };
  });
})();

// --------------------------------------------------------------- Canvas
const cv = $("#cv"), ctx = cv.getContext("2d");
let drawQueued = false;
function scheduleDraw() { if (!drawQueued) { drawQueued = true; requestAnimationFrame(draw); } }
function resizeCanvas() {
  const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1;
  cv.width = Math.round(r.width * d); cv.height = Math.round(r.height * d);
  scheduleDraw();
}
function fitView() {
  const r = cv.getBoundingClientRect();
  const pw = S.paper.w, ph = S.paper.h, pad = 30;
  view.s = Math.min((r.width - 2 * pad) / pw, (r.height - 2 * pad) / ph);
  view.ox = (r.width - pw * view.s) / 2; view.oy = (r.height - ph * view.s) / 2;
  scheduleDraw();
}
const toScreen = (x, y) => [x * view.s + view.ox, y * view.s + view.oy];
const toPaper = (sx, sy) => [(sx - view.ox) / view.s, (sy - view.oy) / view.s];

const isReverse = () => !!(S && S.job && S.job.reverse);
const enabledIds = () => order.filter((o) => o.on).map((o) => o.id);

/* What is already on paper? Returns a function idx -> true/false (or null = no display).
   During/after a plot: the plot's progress. Otherwise: the chosen start point
   (everything before it counts as already plotted). */
function doneFn(layerId) {
  const showJob = job && job.layer_ids && (jobActive() || (["aborted", "done"].includes(job.state) && !startSel));
  if (showJob) {
    const i = job.layer_ids.indexOf(layerId);
    if (i < 0) return null;
    if (job.state === "done" || i < job.layer) return () => true;
    if (i > job.layer) return () => false;
    return job.reverse ? (idx) => idx > job.path : (idx) => idx < job.path;
  }
  if (startSel) {
    const ids = enabledIds(), pos = ids.indexOf(startSel.id), i = ids.indexOf(layerId);
    if (pos < 0 || i < 0) return null;
    if (i < pos) return () => true;
    if (i > pos) return () => false;
    return isReverse() ? (idx) => idx > startSel.path : (idx) => idx < startSel.path;
  }
  return null;
}

function draw() {
  drawQueued = false;
  if (!S) return;
  const d = devicePixelRatio || 1;
  ctx.setTransform(d, 0, 0, d, 0, 0);
  const W = cv.width / d, H = cv.height / d;
  ctx.clearRect(0, 0, W, H);

  // sheet with a soft shadow
  const [px, py] = toScreen(0, 0);
  const pw = S.paper.w * view.s, ph = S.paper.h * view.s;
  ctx.save();
  ctx.shadowColor = TC.dark ? "rgba(0,0,0,.65)" : "rgba(60,40,10,.22)"; ctx.shadowBlur = 28; ctx.shadowOffsetY = 4;
  ctx.fillStyle = TC.paper; ctx.fillRect(px, py, pw, ph);
  ctx.restore();
  ctx.strokeStyle = "rgba(60,40,10,.12)"; ctx.lineWidth = 1; ctx.strokeRect(Math.round(px) + .5, Math.round(py) + .5, Math.round(pw), Math.round(ph));
  // grid: 10 mm fine, 50 mm a little stronger
  for (const [step, alpha] of [[10, 1], [50, 2.2]]) {
    ctx.strokeStyle = TC.grid; ctx.globalAlpha = Math.min(1, alpha); ctx.lineWidth = alpha > 1 ? 1.2 : 1; ctx.beginPath();
    for (let x = step; x < S.paper.w; x += step) { const [sx] = toScreen(x, 0); ctx.moveTo(Math.round(sx) + .5, py); ctx.lineTo(Math.round(sx) + .5, py + ph); }
    for (let y = step; y < S.paper.h; y += step) { const [, sy] = toScreen(0, y); ctx.moveTo(px, Math.round(sy) + .5); ctx.lineTo(px + pw, Math.round(sy) + .5); }
    ctx.stroke();
  }
  ctx.globalAlpha = 1;

  if (doc) {
    const place = makePlacer();
    const lw = Math.max(0.6, 0.3 * view.s);
    const showTravel = $("#showTravel").checked;
    let last = null;
    const travel = new Path2D();
    for (const o of order) {
      if (!o.on) continue;
      const l = doc.layers.find((x) => x.id === o.id);
      if (!l) continue;
      const done = doneFn(l.id);
      const pDone = new Path2D(), pTodo = new Path2D();
      l.paths.forEach((p, idx) => {
        const target = (done === null || done(idx)) ? pDone : pTodo;
        let [x, y] = toScreen(...place(p[0], p[1]));
        if (showTravel && last) { travel.moveTo(last[0], last[1]); travel.lineTo(x, y); }
        target.moveTo(x, y);
        for (let i = 2; i < p.length; i += 2) {
          [x, y] = toScreen(...place(p[i], p[i + 1]));
          target.lineTo(x, y);
        }
        last = [x, y];
      });
      ctx.lineWidth = lw; ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.strokeStyle = l.color; ctx.globalAlpha = 0.9; ctx.stroke(pDone);
      ctx.globalAlpha = done === null ? 0.9 : 0.22; ctx.stroke(pTodo);
      ctx.globalAlpha = 1;
    }
    drawMarker(place);
    if (showTravel) {
      ctx.strokeStyle = TC.accent; ctx.globalAlpha = .55; ctx.lineWidth = 0.7; ctx.setLineDash([3, 3]);
      ctx.stroke(travel); ctx.setLineDash([]); ctx.globalAlpha = 1;
    }
    // frame of the design
    const [w, h] = placedSize();
    const [bx, by] = toScreen(S.place.x, S.place.y);
    ctx.strokeStyle = "rgba(60,45,25,.45)"; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
    ctx.strokeRect(Math.round(bx) + .5, Math.round(by) + .5, w * view.s, h * view.s); ctx.setLineDash([]);
    // reference point for X/Y
    const [qx, qy] = toScreen(S.place.x + anchor[0] * w, S.place.y + anchor[1] * h);
    ctx.fillStyle = TC.accent; ctx.strokeStyle = TC.paper; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.rect(qx - 4, qy - 4, 8, 8); ctx.fill(); ctx.stroke();
    const out = ([x0, y0, x1, y1]) => S.place.x < x0 - 0.01 || S.place.y < y0 - 0.01 || S.place.x + w > x1 + 0.01 || S.place.y + h > y1 + 0.01;
    const msg = S.machine.limits_on && out(area()) ? "Outside the allowed area – the plot won't start"
      : out([0, 0, S.paper.w, S.paper.h]) ? "Design extends beyond the sheet" : "";
    if (msg) { ctx.fillStyle = TC.bad; ctx.font = "500 12px 'Plex Sans', sans-serif"; ctx.fillText(msg, bx, by - 7); }
  }

  // work area
  if (S.machine.limits_on) {
    const [x0, y0, x1, y1] = area();
    const [ax, ay] = toScreen(x0, y0);
    ctx.strokeStyle = TC.bad; ctx.globalAlpha = .55; ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
    ctx.strokeRect(ax, ay, (x1 - x0) * view.s, (y1 - y0) * view.s); ctx.setLineDash([]); ctx.globalAlpha = 1;
  }

  // origin: corner mark at the sheet corner
  ctx.strokeStyle = TC.accent; ctx.lineWidth = 2; ctx.lineCap = "square"; ctx.beginPath();
  ctx.moveTo(px, py + 16); ctx.lineTo(px, py); ctx.lineTo(px + 16, py); ctx.stroke(); ctx.lineCap = "round";

  // plot head: crosshair ring; pen down = filled
  if (connected()) {
    const [x, y] = machineToPaper(st.wpos[0], st.wpos[1]);
    const [sx, sy] = toScreen(x, y);
    const down = Math.abs(st.wpos[2] - S.machine.z_down) < Math.abs(st.wpos[2] - S.machine.z_up);
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,.25)"; ctx.shadowBlur = 4;
    ctx.beginPath(); ctx.arc(sx, sy, 9, 0, Math.PI * 2);
    ctx.fillStyle = down ? TC.accent : "rgba(255,255,255,.55)"; ctx.fill();
    ctx.restore();
    ctx.strokeStyle = down ? TC.paper : "#2a2622"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(sx, sy, 9, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(sx - 14, sy); ctx.lineTo(sx - 4, sy); ctx.moveTo(sx + 4, sy); ctx.lineTo(sx + 14, sy);
    ctx.moveTo(sx, sy - 14); ctx.lineTo(sx, sy - 4); ctx.moveTo(sx, sy + 4); ctx.lineTo(sx, sy + 14);
    ctx.strokeStyle = down ? TC.accent : "#2a2622"; ctx.stroke();
    ctx.beginPath(); ctx.arc(sx, sy, 1.6, 0, Math.PI * 2); ctx.fillStyle = down ? TC.paper : "#2a2622"; ctx.fill();
  }
}

// mark the start point (or resume point)
function markerPoint() {
  if (jobActive()) return null;
  const sel = startSel;
  if (!sel) return null;
  const l = doc.layers.find((x) => x.id === sel.id);
  const p = l && l.paths[sel.path];
  if (!p) return null;
  return { l, p, rev: isReverse() };
}
function drawMarker(place) {
  const m = markerPoint();
  if (!m) return;
  const { l, p, rev } = m;
  // highlight the chosen path in bold
  ctx.beginPath();
  let [x, y] = toScreen(...place(p[0], p[1])); ctx.moveTo(x, y);
  for (let i = 2; i < p.length; i += 2) { [x, y] = toScreen(...place(p[i], p[i + 1])); ctx.lineTo(x, y); }
  ctx.strokeStyle = TC.accent; ctx.lineWidth = Math.max(2.5, 0.8 * view.s); ctx.globalAlpha = 1; ctx.stroke();
  // where the pen starts (forward: path start, reverse: path end)
  const k = rev ? p.length - 2 : 0;
  const [sx, sy] = toScreen(...place(p[k], p[k + 1]));
  ctx.beginPath(); ctx.arc(sx, sy, 9, 0, Math.PI * 2);
  ctx.strokeStyle = TC.accent; ctx.lineWidth = 2.5; ctx.stroke();
  ctx.beginPath(); ctx.arc(sx, sy, 3, 0, Math.PI * 2); ctx.fillStyle = TC.accent; ctx.fill();
  const label = `Start · ${l.name.split("  ")[0]} · path ${fmtNum(startSel.path + 1)}${rev ? " (reverse)" : ""}`;
  ctx.font = "600 12px 'Plex Sans', sans-serif";
  const tw = ctx.measureText(label).width;
  ctx.fillStyle = TC.accent; ctx.beginPath(); ctx.roundRect(sx + 12, sy - 26, tw + 14, 20, 4); ctx.fill();
  ctx.fillStyle = "#fff"; ctx.fillText(label, sx + 19, sy - 12);
}

// find the path under the mouse pointer (enabled layers only)
function pickPath(sx, sy) {
  const place = makePlacer();
  let best = null, bd = Infinity;
  for (const o of order) {
    if (!o.on) continue;
    const l = doc.layers.find((x) => x.id === o.id);
    l.paths.forEach((p, idx) => {
      for (let i = 0; i < p.length; i += 2) {
        const [x, y] = toScreen(...place(p[i], p[i + 1]));
        const d = (x - sx) ** 2 + (y - sy) ** 2;
        if (d < bd) { bd = d; best = { id: l.id, path: idx }; }
      }
    });
  }
  return bd <= 30 * 30 ? best : null;
}
function setStartSel(sel) {
  startSel = sel;
  renderStartInfo(); scheduleDraw();
}
function renderStartInfo() {
  if (startSel && !enabledIds().includes(startSel.id)) startSel = null;
  const ids = enabledIds();
  const sel = $("#startLayer");
  if (startSel && doc) {
    const l = doc.layers.find((x) => x.id === startSel.id);
    $("#startInfo").textContent = `layer ${ids.indexOf(startSel.id) + 1} “${l.name.split("  ")[0]}”, path ${fmtNum(startSel.path + 1)} of ${fmtNum(l.count)}` + (isReverse() ? " – reverse" : "");
    sel.value = String(ids.indexOf(startSel.id));
    $("#startPath").value = startSel.path + 1;
  } else {
    $("#startInfo").textContent = isReverse() ? "the end (last path of the first layer)" : "the beginning";
    $("#startPath").value = "";
  }
}
$("#btnPick").onclick = () => {
  pickMode = !pickMode;
  $("#btnPick").classList.toggle("on", pickMode);
  cv.classList.toggle("picking", pickMode);
  if (pickMode) logLocal("info", "Click the path in the preview where the plot should start.");
};
$("#btnStartReset").onclick = () => setStartSel(null);
$("#startLayer").onchange = () => {
  const id = enabledIds()[+$("#startLayer").value];
  if (!id) return;
  const l = doc.layers.find((x) => x.id === id);
  setStartSel({ id, path: isReverse() ? l.count - 1 : 0 });
};
$("#startPath").onchange = () => {
  const ids = enabledIds(), id = ids[+$("#startLayer").value] || ids[0];
  if (!id) return;
  const l = doc.layers.find((x) => x.id === id);
  const n = Math.round(+$("#startPath").value);
  if (!(n >= 1)) { setStartSel(null); return; }
  setStartSel({ id, path: Math.min(n, l.count) - 1 });
};

// mouse: move the design / pan the view / zoom
let drag = null;
function overDesign(sx, sy) {
  if (!doc || jobActive()) return false;
  const [x, y] = toPaper(sx, sy), [w, h] = placedSize();
  return x >= S.place.x && x <= S.place.x + w && y >= S.place.y && y <= S.place.y + h;
}
cv.addEventListener("mousedown", (e) => {
  const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
  if (pickMode && e.button === 0 && doc) {
    const hit = pickPath(sx, sy);
    if (hit) {
      setStartSel(hit);
      pickMode = false; $("#btnPick").classList.remove("on"); cv.classList.remove("picking");
    } else logLocal("warn", "No path nearby – click closer to a line.");
    return;
  }
  if (e.button === 0 && overDesign(sx, sy)) drag = { mode: "design", sx, sy, x0: S.place.x, y0: S.place.y };
  else drag = { mode: "pan", sx, sy, ox: view.ox, oy: view.oy };
  cv.classList.add("dragging");
});
window.addEventListener("mousemove", (e) => {
  const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
  if (!drag) { cv.classList.toggle("over-design", overDesign(sx, sy)); return; }
  if (drag.mode === "pan") { view.ox = drag.ox + sx - drag.sx; view.oy = drag.oy + sy - drag.sy; }
  else {
    let nx = drag.x0 + (sx - drag.sx) / view.s, ny = drag.y0 + (sy - drag.sy) / view.s;
    if (!e.altKey) { nx = Math.round(nx * 2) / 2; ny = Math.round(ny * 2) / 2; }
    S.place.x = nx; S.place.y = ny; updatePlaceInputs();
  }
  scheduleDraw();
});
window.addEventListener("mouseup", () => {
  if (drag && drag.mode === "design") saveSettings({ place: S.place });
  drag = null; cv.classList.remove("dragging");
});
cv.addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
  const f = Math.exp(-e.deltaY * 0.0015);
  const [x, y] = toPaper(sx, sy);
  view.s = Math.min(200, Math.max(0.2, view.s * f));
  view.ox = sx - x * view.s; view.oy = sy - y * view.s;
  scheduleDraw();
}, { passive: false });
new ResizeObserver(resizeCanvas).observe($("#canvasWrap"));
$("#btnFit").onclick = fitView;
$("#showTravel").onchange = scheduleDraw;

// ----------------------------------------------------------- settings
function bindSettings() {
  $$("[data-set]").forEach((el) => {
    const p = el.dataset.set, v = getPath(S, p);
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
    el.onchange = () => {
      const val = el.type === "checkbox" ? el.checked : parseFloat(el.value);
      if (el.type !== "checkbox" && !isFinite(val)) return;
      setPath(S, p, val); saveSettings(nested(p, val));
      renderLayers(); scheduleDraw();
    };
  });
  $$("[data-opt]").forEach((el) => {
    const k = el.dataset.opt, v = S.optimize[k];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
    showOptDefault(el, k);
    el.onchange = () => {
      S.optimize[k] = el.type === "checkbox" ? el.checked : (el.tagName === "SELECT" ? el.value : parseFloat(el.value));
      showOptDefault(el, k);
      $("#btnProcess").classList.add("primary");
    };
  });
  // paper
  const key = `${S.paper.w}x${S.paper.h}`;
  const sel = $("#paper");
  sel.value = [...sel.options].some((o) => o.value === key) ? key : "custom";
  $("#customPaper").hidden = sel.value !== "custom";
  $("#paperW").value = S.paper.w; $("#paperH").value = S.paper.h;
  $("#baud").value = String(S.connection.baud);
}
$("#paper").onchange = () => {
  const v = $("#paper").value;
  $("#customPaper").hidden = v !== "custom";
  if (v !== "custom") {
    const [w, h] = v.split("x").map(Number);
    S.paper = { name: $("#paper").selectedOptions[0].text, w, h };
    $("#paperW").value = w; $("#paperH").value = h;
    saveSettings({ paper: S.paper }); fitView();
  }
};
["#paperW", "#paperH"].forEach((id) => $(id).onchange = () => {
  S.paper = { name: "Custom", w: +$("#paperW").value || 100, h: +$("#paperH").value || 100 };
  saveSettings({ paper: S.paper }); fitView();
});

// --------------------------------------------------------------- placement
// reference point (3×3 grid): X/Y refer to this corner/center of the design.
// internally S.place.x/y is always the top-left corner.
let anchor = [0, 0];
try { const a = JSON.parse(localStorage.getItem("anchor")); if (Array.isArray(a) && a.length === 2) anchor = a; } catch (e) { /* ignore */ }
function anchorPoint() {
  const [w, h] = doc ? placedSize() : [0, 0];
  return [S.place.x + anchor[0] * w, S.place.y + anchor[1] * h];
}
// apply size/rotation changes so that the reference point stays put
function keepAnchor(fn) {
  const [ax, ay] = anchorPoint();
  fn();
  const [w, h] = doc ? placedSize() : [0, 0];
  S.place.x = ax - anchor[0] * w; S.place.y = ay - anchor[1] * h;
}
function renderAnchor() {
  $$("#anchor button").forEach((b) => b.classList.toggle("on", b.dataset.a === anchor.join(",")));
}
$$("#anchor button").forEach((b) => b.onclick = () => {
  anchor = b.dataset.a.split(",").map(Number);
  try { localStorage.setItem("anchor", JSON.stringify(anchor)); } catch (e) { /* ignore */ }
  renderAnchor(); updatePlaceInputs(); scheduleDraw();
});
renderAnchor();

function updatePlaceInputs() {
  const p = S.place;
  const [ax, ay] = anchorPoint();
  $("#plX").value = +ax.toFixed(1); $("#plY").value = +ay.toFixed(1);
  $("#plS").value = +(p.scale * 100).toFixed(2); $("#plR").value = String(p.rotate | 0);
  if (doc) { const [w, h] = placedSize(); $("#plW").value = +w.toFixed(1); $("#plH").value = +h.toFixed(1); }
  else { $("#plW").value = ""; $("#plH").value = ""; }
}
function placeChanged() { updatePlaceInputs(); saveSettings({ place: S.place }); renderLayers(); scheduleDraw(); }
$("#plX").onchange = () => { const [w] = doc ? placedSize() : [0]; S.place.x = (+$("#plX").value || 0) - anchor[0] * w; placeChanged(); };
$("#plY").onchange = () => { const [, h] = doc ? placedSize() : [0, 0]; S.place.y = (+$("#plY").value || 0) - anchor[1] * h; placeChanged(); };
$("#plS").onchange = () => { const v = +$("#plS").value; if (v > 0) keepAnchor(() => { S.place.scale = v / 100; }); placeChanged(); };
$("#plR").onchange = () => { keepAnchor(() => { S.place.rotate = +$("#plR").value; }); placeChanged(); };
$("#plW").onchange = () => {
  if (!doc) return; const [w] = placedSize(); const v = +$("#plW").value;
  if (v > 0 && w > 0) keepAnchor(() => { S.place.scale *= v / w; }); placeChanged();
};
$("#plH").onchange = () => {
  if (!doc) return; const [, h] = placedSize(); const v = +$("#plH").value;
  if (v > 0 && h > 0) keepAnchor(() => { S.place.scale *= v / h; }); placeChanged();
};
$("#btnCenter").onclick = () => {
  if (!doc) return; const [w, h] = placedSize();
  S.place.x = (S.paper.w - w) / 2; S.place.y = (S.paper.h - h) / 2; placeChanged();
};
$("#btnFitPaper").onclick = () => {
  if (!doc) return; const m = 10; const [w, h] = placedSize();
  const f = Math.min((S.paper.w - 2 * m) / w, (S.paper.h - 2 * m) / h);
  S.place.scale *= f; const [w2, h2] = placedSize();
  S.place.x = (S.paper.w - w2) / 2; S.place.y = (S.paper.h - h2) / 2; placeChanged();
};
$("#btnOrig").onclick = () => {
  if (!doc) return; S.place = { x: doc.bbox[0], y: doc.bbox[1], scale: 1, rotate: 0 }; placeChanged();
};
$("#btnFrame").onclick = () => api("/api/frame", { place: S.place });

// --------------------------------------------------------------- file
$("#btnOpen").onclick = () => $("#file").click();
$("#file").onchange = () => { if ($("#file").files[0]) uploadFile($("#file").files[0]); $("#file").value = ""; };
const wrap = $("#canvasWrap");
window.addEventListener("dragover", (e) => { e.preventDefault(); $("#drop").classList.remove("hidden"); $("#drop").classList.add("active"); });
window.addEventListener("dragleave", (e) => { if (e.relatedTarget === null) { $("#drop").classList.remove("active"); if (doc) $("#drop").classList.add("hidden"); } });
window.addEventListener("drop", (e) => {
  e.preventDefault(); $("#drop").classList.remove("active");
  if (doc) $("#drop").classList.add("hidden");
  const f = e.dataTransfer.files[0];
  if (f) uploadFile(f);
});

async function uploadFile(f) {
  if (jobActive()) { logLocal("err", "You can't load a new file while plotting."); return; }
  if (!/\.svg$/i.test(f.name)) { logLocal("err", "Please choose an SVG file."); return; }
  $("#busy").hidden = false; $("#busy").textContent = `Processing “${f.name}”…`;
  try {
    const r = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(f.name) }, body: f });
    const j = await r.json();
    if (j.error) { logLocal("err", j.error); return; }
    const newFile = !doc || doc.hash !== j.doc.hash;
    setDoc(j, newFile);
    logLocal("info", `${f.name} loaded (${fmtNum(j.took, 1)} s)`);
  } catch (e) {
    logLocal("err", "Couldn't load the file: " + e);
  } finally { $("#busy").hidden = true; }
}

// show the optimization defaults next to the fields
let DEF = null;
function showOptDefault(el, k) {
  if (!DEF) return;
  const d = DEF.optimize[k];
  const lbl = el.closest("label");
  if (!lbl) return;
  let tag = lbl.querySelector(".def");
  if (!tag) { tag = document.createElement("small"); tag.className = "def"; lbl.appendChild(tag); }
  const opt = el.tagName === "SELECT" ? el.querySelector(`option[value="${d}"]`) : null;
  const txt = el.type === "checkbox" ? (d ? "on" : "off") + ")"
    : el.tagName === "SELECT" ? (opt ? opt.textContent : d)
    : String(d).replace(".", ",") + " mm";
  tag.textContent = el.type === "checkbox" ? `(default ${txt}` : `Default: ${txt}`;
  const cur = el.type === "checkbox" ? el.checked : el.tagName === "SELECT" ? el.value : parseFloat(el.value);
  tag.classList.toggle("changed", cur !== d);
}
$("#btnOptDefaults").onclick = () => {
  if (!DEF) return;
  S.optimize = { ...S.optimize, ...DEF.optimize };
  bindSettings();
  $("#btnProcess").classList.add("primary");
  logLocal("info", "Optimization reset to defaults – click “Recalculate” to apply.");
};

$("#btnProcess").onclick = async () => {
  if (!doc) return;
  $("#busy").hidden = false; $("#busy").textContent = "Recalculating…";
  const j = await api("/api/process", S.optimize);
  $("#busy").hidden = true;
  $("#btnProcess").classList.remove("primary");
  if (j.doc) setDoc(j, false);
};

function setDoc(j, resetPlacement) {
  const prevOrder = order;
  doc = j.doc;
  resumeInfo = j.resume;
  if (!doc) return;
  // keep order/selection when the layers are the same
  const ids = doc.layers.map((l) => l.id);
  if (!resetPlacement && prevOrder.length && prevOrder.every((o) => ids.includes(o.id)) && prevOrder.length === ids.length) order = prevOrder;
  else order = ids.map((id) => ({ id, on: true }));
  if (resumeInfo) {
    S.place = resumeInfo.place;
  } else if (resetPlacement) {
    // take the position from the file (Illustrator artboard = sheet)
    S.place = { x: doc.bbox[0], y: doc.bbox[1], scale: 1, rotate: 0 };
  }
  saveSettings({ place: S.place });
  $("#drop").classList.add("hidden");
  const [w, h] = placedSize();
  const nl = doc.layers.length;
  const info = `${fmtNum(doc.bbox[2] - doc.bbox[0], 1)} × ${fmtNum(doc.bbox[3] - doc.bbox[1], 1)} mm · ${nl} layer${nl === 1 ? "" : "s"} · ` +
    `${fmtNum(doc.layers.reduce((a, l) => a + l.count, 0))} paths · ${fmtNum(doc.layers.reduce((a, l) => a + l.draw_len, 0) / 1000, 1)} m of line`;
  $("#docInfo").innerHTML = `<b>${esc(doc.name)}</b> · ${info}`;
  $("#docInfo").title = `${doc.name}\n${info}`;
  const wn = doc.warnings.length;
  $("#warnings").textContent = wn ? `⚠ ${wn} note${wn > 1 ? "s" : ""}` : "";
  $("#warnings").title = doc.warnings.join("\n");
  $("#warnings").onclick = () => doc.warnings.forEach((w) => logLocal("warn", w));
  void w; void h;
  updatePlaceInputs(); renderLayers(); renderResume(); scheduleDraw();
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// --------------------------------------------------------------- layers
function renderLayers() {
  const box = $("#layers");
  if (!doc) { box.textContent = "–"; $("#totalTime").textContent = ""; return; }
  box.classList.remove("muted");
  let total = 0;
  box.innerHTML = "";
  order.forEach((o, i) => {
    const l = doc.layers.find((x) => x.id === o.id);
    const secs = layerSeconds(l);
    if (o.on) total += secs;
    const row = document.createElement("div");
    row.className = "layer";
    if (job && job.layer_ids && jobActive()) {
      const ji = job.layer_ids.indexOf(o.id);
      if (ji === job.layer) row.classList.add("current");
      if (ji >= 0 && ji < job.layer) row.classList.add("done");
    }
    row.innerHTML = `<input type="checkbox" ${o.on ? "checked" : ""} ${jobActive() ? "disabled" : ""}>
      <span class="sw" style="background:${l.color}"></span>
      <span class="nm" title="${esc(l.name)}">${esc(l.name)}</span>
      <span class="meta">${fmtNum(l.count)} paths<br>${fmtNum(l.draw_len * S.place.scale / 1000, 1)} m · ${fmtTime(secs)}</span>
      <span class="mv"><button title="Move up"><svg class="ic"><use href="#i-up"/></svg></button><button title="Move down"><svg class="ic"><use href="#i-down"/></svg></button></span>`;
    row.querySelector("input").onchange = (e) => { o.on = e.target.checked; renderLayers(); scheduleDraw(); };
    const [up, dn] = row.querySelectorAll(".mv button");
    up.disabled = i === 0 || jobActive(); dn.disabled = i === order.length - 1 || jobActive();
    up.onclick = () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; renderLayers(); scheduleDraw(); };
    dn.onclick = () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; renderLayers(); scheduleDraw(); };
    box.appendChild(row);
    // show/hide Illustrator layers within the pen color
    (l.subs || []).forEach((sb) => {
      const sr = document.createElement("label");
      sr.className = "sublayer" + (o.on ? "" : " off");
      sr.innerHTML = `<input type="checkbox" ${sb.hidden ? "" : "checked"} ${jobActive() ? "disabled" : ""}>
        <span class="nm" title="${esc(sb.name)}">${esc(sb.name)}</span><span class="meta">${fmtNum(sb.count)}</span>`;
      sr.querySelector("input").onchange = (e) => toggleSub(l.id, sb.name, !e.target.checked);
      box.appendChild(sr);
    });
  });
  $("#totalTime").textContent = `≈ ${fmtTime(total)}`;
  // start selection
  const sel = $("#startLayer"), prev = sel.value;
  sel.innerHTML = order.filter((o) => o.on).map((o, i) => `<option value="${i}">${i + 1}. ${esc(doc.layers.find((x) => x.id === o.id).name)}</option>`).join("");
  if (prev && +prev < sel.options.length) sel.value = prev;
  renderStartInfo();
}

async function toggleSub(layerId, name, hide) {
  const key = `${layerId}/${name}`;
  const hidden = new Set(doc.hidden || []);
  if (hide) hidden.add(key); else hidden.delete(key);
  $("#busy").hidden = false; $("#busy").textContent = "Recalculating…";
  const j = await api("/api/process", { ...S.optimize, hidden: [...hidden] });
  $("#busy").hidden = true;
  startSel = null;
  if (j.doc) setDoc(j, false);
}

// --------------------------------------------------------------- Plot
async function startPlot(layerIds, startLayer, startPath, reverse) {
  if (!connected()) { logLocal("err", "Connect the plotter first."); return; }
  if (!doc) { logLocal("err", "Load a file first."); return; }
  layerIds = layerIds.filter((id) => (doc.layers.find((l) => l.id === id) || {}).count);
  if (!layerIds.length) { logLocal("err", "No layer selected."); return; }
  if (!(st && st.zero_set) && !confirm("Is the origin set?\n\nThe pen should sit at the top-left corner of the sheet, and “Set origin” should have been pressed there.\n\nStart anyway?")) return;
  const r = await api("/api/job/start", { layers: layerIds, start_layer: startLayer, start_path: startPath, place: S.place, reverse: !!reverse });
  if (r.ok) { resumeInfo = null; startSel = null; renderResume(); renderStartInfo(); }
}
$("#btnStart").onclick = () => {
  const ids = enabledIds();
  if (startSel) startPlot(ids, ids.indexOf(startSel.id), startSel.path, isReverse());
  else startPlot(ids, 0, null, isReverse());
};
$("#btnPause").onclick = () => {
  if (!job) return;
  if (job.state === "running") api("/api/job/pause", {});
  else if (job.state === "paused") api("/api/job/resume", {});
};
$("#btnStop").onclick = () => { if (jobActive() && confirm("Abort the plot?\n(You can resume from this point later.)")) api("/api/job/stop", {}); };
$("#btnEstop").onclick = () => { if (jobActive()) api("/api/job/stop", {}); else api("/api/reset", {}); };

function renderResume() {
  const box = $("#resumeBox");
  if (!resumeInfo || jobActive()) { box.hidden = true; return; }
  const r = resumeInfo;
  box.hidden = false;
  box.innerHTML = `The last plot of this file was interrupted (${esc(r.time)}):<br>
    <b>Layer ${r.layer + 1} “${esc(String(r.layer_name).split("  ")[0])}”, path ${fmtNum(r.path + 1)}</b>${r.reverse ? " (reverse)" : ""}.
    ${r.moved ? "<br><small>The line was found again – its number changed because sublayers were shown or hidden.</small>" : ""}
    <button class="primary"><svg class="ic"><use href="#i-pick"/></svg>Show &amp; resume here</button>`;
  box.querySelector("button").onclick = () => {
    const ids = doc.layers.map((l) => l.id);
    if (!r.layer_ids.every((id) => ids.includes(id))) { logLocal("err", "The layers no longer match the file."); return; }
    order = r.layer_ids.map((id) => ({ id, on: true })).concat(ids.filter((id) => !r.layer_ids.includes(id)).map((id) => ({ id, on: false })));
    S.place = r.place; updatePlaceInputs();
    S.job.reverse = !!r.reverse; $("#chkReverse").checked = S.job.reverse; saveSettings({ job: { reverse: S.job.reverse }, place: S.place });
    startSel = { id: r.layer_ids[r.layer], path: r.path };
    renderLayers(); scheduleDraw();
    logLocal("info", "Resume point set (marked in the preview). Plotted lines are solid, the rest is faded – press Plot to continue.");
  };
}

function renderJob() {
  const active = jobActive();
  $("#btnStart").disabled = active || !doc || !connected();
  $("#btnPause").disabled = !job || !["running", "paused"].includes(job.state);
  const paused = !!(job && job.state === "paused");
  if ($("#btnPause").dataset.p !== String(paused)) {
    $("#btnPause").dataset.p = String(paused);
    $("#btnPause").innerHTML = paused ? '<svg class="ic"><use href="#i-play"/></svg>Resume' : '<svg class="ic"><use href="#i-pause"/></svg>Pause';
  }
  $("#btnStop").disabled = !active;
  const pc = $("#penChange");
  if (job && job.state === "pen_change") {
    pc.hidden = false;
    const nl = job.layers[job.layer];
    const html = `${esc(job.message)}<br><small>If you stop now, the plot resumes later at layer ${job.layer + 1}${nl ? ` “${esc(nl.name)}”` : ""}, path 1.</small><button class="primary"><svg class="ic"><use href="#i-play"/></svg>Continue – pen changed</button>`;
    if (pc.dataset.html !== html) { pc.innerHTML = html; pc.dataset.html = html; }
    pc.querySelector("button").onclick = () => api("/api/job/resume", {});
  } else { pc.hidden = true; pc.dataset.html = ""; }

  if (!job) { $("#progText").textContent = "Ready"; $("#progBar").style.width = "0"; $("#sbJob").textContent = ""; return; }
  let total = 0, done = 0, estTotal = 0, estDone = 0;
  job.layers.forEach((l, i) => {
    const dl = doc && doc.layers.find((x) => x.id === l.id);
    const secs = dl ? layerSeconds(dl) : 0;
    total += l.count; estTotal += secs;
    let d = i < job.layer ? l.count : i === job.layer ? (job.reverse ? l.count - 1 - job.path : job.path) : 0;
    if (job.state === "done") d = l.count;
    done += d; estDone += l.count ? secs * d / l.count : 0;
  });
  const frac = total ? done / total : 0;
  const efrac = estTotal ? estDone / estTotal : frac;
  $("#progBar").style.width = (efrac * 100).toFixed(1) + "%";
  let remain = estTotal - estDone;
  if (job.elapsed > 60 && efrac > 0.02 && job.state !== "done") {
    const startFrac = job._startFrac ?? efrac;
    void startFrac;
    remain = remain * 0.5 + (job.elapsed / Math.max(efrac, 0.001)) * (1 - efrac) * 0.5;
  }
  const L = job.layers[Math.min(job.layer, job.layers.length - 1)];
  const parts = [];
  const stateName = { "running": "Plotting", "paused": "Paused", "pen_change": "Pen change" }[job.state] || "";
  if (job.state === "done") parts.push(`Done in ${fmtTime(job.elapsed)}`);
  else if (job.state === "aborted") parts.push(job.message);
  else {
    parts.push(`${stateName} · layer ${job.layer + 1}/${job.layers.length} “${L ? L.name : ""}”`);
    parts.push(`Path ${fmtNum(job.path + 1)}/${fmtNum(L ? L.count : 0)} · ${fmtNum(efrac * 100, 1)} %`);
    parts.push(`${fmtTime(job.elapsed)} elapsed · ~${fmtTime(remain)} left`);
  }
  if (job.errors) parts.push(`${job.errors} error${job.errors > 1 ? "s" : ""} – see console`);
  $("#progText").innerHTML = parts.map(esc).join("<br>");
  $("#sbJob").textContent = jobActive() ? `${stateName} · ${fmtNum(efrac * 100, 1)} % · ~${fmtTime(remain)} left`
    : job.state === "done" ? `Done in ${fmtTime(job.elapsed)}` : "";
}

// --------------------------------------------------------------- control
$$("[data-jog]").forEach((b) => b.onclick = () => {
  const [dx, dy] = b.dataset.jog.split(",").map(Number);
  api("/api/jog", { x: dx * jogStep, y: dy * jogStep });
});
$$("[data-zjog]").forEach((b) => b.onclick = () => api("/api/jog", { z: +b.dataset.zjog }));
// take the current Z height as pen up/down
function takeZ(key, label) {
  if (!st || !st.connected) return;
  const z = Math.round(st.wpos[2] * 100) / 100;
  const other = key === "z_up" ? S.machine.z_down : S.machine.z_up;
  if (key === "z_up" ? z >= other : z <= other) {
    logLocal("warn", `Careful: “pen up” must be smaller than “pen down” (Z ${z} vs. ${other}).`);
  }
  S.machine[key] = z;
  saveSettings({ machine: { [key]: z } });
  bindSettings();
  logLocal("info", `${label} set to ${z} mm`);
}
$("#btnZasUp").onclick = () => takeZ("z_up", "Pen up");
$("#btnZasDown").onclick = () => takeZ("z_down", "Pen down");

function setJogStep(v) {
  if (!(v > 0)) return;
  jogStep = v;
  $("#jogCustom").value = v;
  $$("#jogStep [data-step]").forEach((x) => x.classList.toggle("on", +x.dataset.step === v));
  try { localStorage.setItem("jogStep", String(v)); } catch (e) { /* ignore */ }
}
$$("#jogStep [data-step]").forEach((b) => b.onclick = () => setJogStep(+b.dataset.step));
$("#jogCustom").onchange = () => setJogStep(parseFloat($("#jogCustom").value));
try { const v = parseFloat(localStorage.getItem("jogStep")); if (v > 0) setJogStep(v); } catch (e) { /* ignore */ }
$("#btnPenUp").onclick = () => api("/api/pen", { down: false });
$("#btnPenDown").onclick = () => api("/api/pen", { down: true });
$("#btnZero").onclick = async () => {
  const r = await api("/api/zero", {});
  if (r && r.error && job && job.state === "pen_change") alert(r.error);
};
$("#btnGoZero").onclick = () => api("/api/goto_zero", {});
$("#btnMachineZero").onclick = () => api("/api/goto_machine_zero", {});
$("#btnUnlock").onclick = () => api("/api/unlock", {});

// closing the window: save pending settings and tell the server (it then exits)
window.addEventListener("pagehide", () => {
  if (saveTimer_active()) {
    clearTimeout(saveTimer);
    navigator.sendBeacon("/api/settings", new Blob([JSON.stringify(pendingSave)], { type: "application/json" }));
    pendingSave = {};
  }
  navigator.sendBeacon("/api/bye", new Blob(["{}"], { type: "application/json" }));
});

window.addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  const map = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  // enabled when no plot is running – or during a pen change
  const free = !jobActive() || job.state === "pen_change";
  if (map[e.key] && connected() && free) {
    e.preventDefault(); api("/api/jog", { x: map[e.key][0] * jogStep, y: map[e.key][1] * jogStep });
  } else if (e.key === "PageUp" && free) { e.preventDefault(); api("/api/pen", { down: false }); }
  else if (e.key === "PageDown" && free) { e.preventDefault(); api("/api/pen", { down: true }); }
  else if (e.key === " ") {
    e.preventDefault();
    if (job && job.state === "running") api("/api/job/pause", {});
    else if (connected()) api("/api/jog/cancel", {});
  }
});

// connection
async function loadPorts() {
  const j = await api("/api/ports");
  const sel = $("#port");
  sel.innerHTML = (j.ports || []).map((p) => `<option value="${esc(p.port)}">${esc(p.port)} – ${esc(p.desc)}</option>`).join("");
  const want = S.connection.port;
  if ([...sel.options].some((o) => o.value === want)) sel.value = want;
}
$("#btnPorts").onclick = loadPorts;
$("#btnConnect").onclick = async () => {
  const b = $("#btnConnect");
  if (connected()) { await api("/api/disconnect", {}); return; }
  b.disabled = true; b.textContent = "Connecting…";
  await api("/api/connect", { port: $("#port").value, baud: +$("#baud").value });
  b.disabled = false;
};

// console
$("#cmdForm").onsubmit = (e) => {
  e.preventDefault();
  const v = $("#cmd").value.trim();
  if (v) api("/api/command", { gcode: v });
  $("#cmd").value = "";
};
function addLog(e) {
  const box = $("#log");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
  const div = document.createElement("div");
  div.className = e.k;
  div.innerHTML = `<span class="t">${esc(e.t)}</span>${esc(e.m)}`;
  box.appendChild(div);
  while (box.childElementCount > 500) box.firstChild.remove();
  if (atBottom) box.scrollTop = box.scrollHeight;
}
function logLocal(k, m) { addLog({ k, m, t: new Date().toLocaleTimeString("en-GB") }); }

// --------------------------------------------------------------- Status
let lastJobKey = "";
async function poll() {
  try {
    const r = await fetch(`/api/status?log=${logSeq}`);
    const j = await r.json();
    st = j.machine;
    serverArea = j.area;
    // take over settings the server changed (firmware limits)
    if (j.mset && stable(j.mset) !== stable(S.machine) && !saveTimer_active()) {
      S.machine = j.mset; bindSettings(); renderLayers();
    }
    applySpeedLimits(j.vmax);
    const prevActive = jobActive();
    job = j.job;
    j.log.forEach((e) => { addLog(e); logSeq = Math.max(logSeq, e.n); });
    renderStatus();
    renderJob();
    const key = job ? `${job.state}|${job.layer}|${Math.floor(job.path / 50)}` : "";
    if (key !== lastJobKey) { lastJobKey = key; renderLayers(); }
    if (prevActive && !jobActive() && job && job.state === "aborted" && doc) {
      resumeInfo = { layer_ids: job.layer_ids, layer: job.resume[0], path: job.resume[1], place: S.place, reverse: job.reverse,
        layer_name: job.layers[job.resume[0]] ? job.layers[job.resume[0]].name : "", time: "just now" };
      renderResume();
    }
    scheduleDraw();
  } catch (e) {
    st = null; renderStatus();
  }
  setTimeout(poll, 300);
}
function renderStatus() {
  const pill = $("#statePill");
  const s = st && st.connected ? st.state : "Disconnected";
  const cls = !st || !st.connected ? "off" : /^Idle/.test(s) ? "idle" : /^(Run|Jog|Home)/.test(s) ? "run" : /^(Hold|Door)/.test(s) ? "hold" : /^Alarm/.test(s) ? "alarm" : "off";
  const names = { Idle: "Ready", Run: "Running", Jog: "Jogging", Hold: "Hold", Alarm: "Alarm", Door: "Door", Home: "Homing", Sleep: "Sleep", Check: "Check mode" };
  pill.className = "state " + cls;
  pill.textContent = names[s.split(":")[0]] || s;
  const on = st && st.connected;
  $("#posX").textContent = on ? st.wpos[0].toFixed(2) : "–";
  $("#posY").textContent = on ? st.wpos[1].toFixed(2) : "–";
  $("#posZ").textContent = on ? st.wpos[2].toFixed(2) : "–";
  $("#zNow").textContent = on ? st.wpos[2].toFixed(2) : "–";
  const so = $("#sbOrigin");
  so.textContent = !on ? "" : st.zero_set ? "Origin set" : "Origin not set";
  so.classList.toggle("warn", !!(on && !st.zero_set));
  $("#btnZasUp").disabled = $("#btnZasDown").disabled = !on || jobActive();
  $("#btnConnect").textContent = on ? "Disconnect" : "Connect";
  $("#btnConnect").classList.toggle("primary", !on);
  $("#port").disabled = on; $("#baud").disabled = on;
  const ctl = on && !jobActive();
  $$(".panel.left button, #btnFrame, #cmdForm button").forEach((b) => b.disabled = !ctl);
  // during a pen change: jogging, pen up/down, setting the origin and going to the origin are allowed
  if (on && job && job.state === "pen_change")
    $$("[data-jog], [data-step], #jogCustom, #btnGoZero, #btnPenUp, #btnPenDown, #btnZero, [data-zjog]").forEach((b) => b.disabled = false);
  $("#btnUnlock").disabled = !on;
}

// --------------------------------------------------------------- Start
(async function init() {
  applyTheme(theme);
  S = await api("/api/settings");
  DEF = await api("/api/defaults");
  bindSettings();
  updatePlaceInputs();
  await loadPorts();
  resizeCanvas(); fitView();
  const d = await api("/api/doc");
  if (d.doc) setDoc(d, false);
  poll();
})();

// --------------------------------------------------------------- resizing panels
(function layoutResize() {
  const DEFAULTS = { lw: 290, rw: 330, ch: 150 };
  const lay = $(".layout");
  let L = {};
  try { L = JSON.parse(localStorage.getItem("layout")) || {}; } catch (e) { L = {}; }
  const limits = (k) => k === "ch"
    ? [60, Math.max(80, $(".stage").clientHeight - 200)]
    : [200, Math.max(260, (window.innerWidth - (k === "lw" ? (L.rw || DEFAULTS.rw) : (L.lw || DEFAULTS.lw))) - 300)];
  function apply() {
    for (const k of ["lw", "rw", "ch"]) {
      const [lo, hi] = limits(k);
      const v = Math.round(Math.min(hi, Math.max(lo, L[k] || DEFAULTS[k])));
      lay.style.setProperty("--" + k, v + "px");
    }
  }
  function save() { try { localStorage.setItem("layout", JSON.stringify(L)); } catch (e) { /* ignore */ } }
  apply();
  window.addEventListener("resize", apply);
  $$(".gutter").forEach((g) => {
    const k = g.dataset.g;
    g.addEventListener("dblclick", () => { delete L[k]; save(); apply(); });
    g.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      g.setPointerCapture(e.pointerId);
      const start = k === "ch" ? e.clientY : e.clientX;
      const from = k === "lw" ? $(".panel.left").offsetWidth : k === "rw" ? $(".panel.right").offsetWidth : $(".console").offsetHeight;
      g.classList.add("drag");
      document.body.classList.add("resizing", k === "ch" ? "row" : "col");
      const move = (ev) => {
        const d = (k === "ch" ? ev.clientY : ev.clientX) - start;
        // the left panel grows to the right, the right panel and the console grow to the left/up
        L[k] = from + (k === "lw" ? d : -d);
        apply();
      };
      const up = () => {
        g.classList.remove("drag");
        document.body.classList.remove("resizing", "row", "col");
        g.removeEventListener("pointermove", move);
        g.removeEventListener("pointerup", up);
        const v = parseFloat(lay.style.getPropertyValue("--" + k));
        if (v) L[k] = v;
        save();
      };
      g.addEventListener("pointermove", move);
      g.addEventListener("pointerup", up);
    });
  });
})();
