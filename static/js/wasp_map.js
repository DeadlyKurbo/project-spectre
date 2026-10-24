/*
 * W.A.S.P. live war map.
 *
 * A Leaflet satellite map that shows the shared war state (factions, units,
 * zones, front lines and SITREP events) to every signed-in operator and lets
 * owners/admins edit it in place.  Viewers poll /api/wasp-map/state with an
 * ETag every few seconds; admin edits go to /api/wasp-map/ops as small
 * operations that the server applies against the latest stored copy.
 */
(function () {
  "use strict";

  const BOOT = window.WASP_MAP_BOOTSTRAP || {};
  const CAN_EDIT = Boolean(BOOT.canEdit);
  const CAN_VIEW = Boolean(BOOT.canView);
  const STATE_URL = "/api/wasp-map/state";
  const OPS_URL = "/api/wasp-map/ops";
  const POLL_INTERVAL_MS = 5000;
  const STALE_AFTER_MS = 20000;
  const RECENT_EVENT_MS = 12 * 3600 * 1000;
  const OLD_EVENT_MS = 7 * 24 * 3600 * 1000;
  const PREFS_KEY = "wasp-map-prefs-v1";

  const $ = (id) => document.getElementById(id);

  if (typeof window.L === "undefined") {
    const name = $("wm-op-name");
    if (name) name.textContent = "Map engine failed to load — refresh the page.";
    return;
  }
  const L = window.L;

  // -------------------------------------------------------------------------
  // Vocabulary
  // -------------------------------------------------------------------------

  const UNIT_TYPES = {
    infantry: "Infantry",
    mechanized: "Mechanized infantry",
    armor: "Armor",
    artillery: "Artillery",
    air_defense: "Air defense",
    air: "Fixed-wing air",
    helicopter: "Helicopter",
    drone: "Drone / UAV",
    naval: "Naval surface",
    submarine: "Submarine",
    missile: "Missile",
    recon: "Reconnaissance",
    special_forces: "Special forces",
    hq: "Headquarters",
    logistics: "Logistics",
  };
  const UNIT_TYPE_SHORT = {
    infantry: "Inf", mechanized: "Mech", armor: "Armor", artillery: "Arty", air_defense: "AD",
    air: "Air", helicopter: "Helo", drone: "UAV", naval: "Naval", submarine: "Sub",
    missile: "Msl", recon: "Recon", special_forces: "SF", hq: "HQ", logistics: "Log",
  };
  const ECHELONS = { "": "None", company: "Company", battalion: "Battalion", brigade: "Brigade", division: "Division", corps: "Corps", army: "Army" };
  const ECHELON_MARK = { company: "I", battalion: "II", brigade: "X", division: "XX", corps: "XXX", army: "XXXX" };
  const UNIT_STATUSES = { active: "Active", engaged: "Engaged", damaged: "Damaged", retreating: "Retreating", destroyed: "Destroyed" };
  const STANCES = { friendly: "Friendly", hostile: "Hostile", neutral: "Neutral", unknown: "Unknown" };
  const ZONE_KINDS = { control: "Controlled territory", contested: "Contested area", exclusion: "Exclusion zone", objective: "Objective area" };
  const LINE_KINDS = { front: "Front line", advance: "Advance arrow", supply: "Supply route", border: "Boundary" };
  const EVENT_KINDS = {
    battle: { label: "Battle", color: "#f87171", icon: '<path d="M4 4l16 16M20 4L4 20M14 20l6-6M4 14l6 6"/>' },
    strike: { label: "Strike", color: "#fb923c", icon: '<path d="M12 2l2 6 6-2-4 5 5 4-6 1 1 6-4-4-4 4 1-6-6-1 5-4-4-5 6 2z"/>' },
    movement: { label: "Movement", color: "#7dd3fc", icon: '<path d="M4 12h14M13 6l6 6-6 6"/>' },
    intel: { label: "Intel", color: "#c4b5fd", icon: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>' },
    political: { label: "Political", color: "#facc15", icon: '<path d="M5 21V4h11l-2 4 2 4H5"/>' },
    report: { label: "Report", color: "#e5e7eb", icon: '<path d="M5 6h14M5 12h14M5 18h9"/>' },
  };
  const WAR_STATUSES = { standby: "Standby", active: "Active", ceasefire: "Ceasefire", concluded: "Concluded" };
  const THREAT_LABELS = ["", "Low", "Guarded", "Elevated", "High", "Critical"];
  const UNALIGNED = { id: "", name: "Unaligned", short: "UNK", color: "#9ca3af", stance: "unknown" };
  const COLLECTION_LABEL = { units: "Unit", zones: "Zone", lines: "Line", events: "SITREP" };

  // -------------------------------------------------------------------------
  // Small helpers
  // -------------------------------------------------------------------------

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** Build a DOM element. Children may be nodes or strings (inserted as text). */
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value == null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "svg") node.innerHTML = value; // trusted, generated markup only
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "value") node.value = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child == null || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function newId(prefix) {
    const bytes = new Uint8Array(5);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return `${prefix}-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
  }

  function parseTs(value) {
    const t = Date.parse(value || "");
    return Number.isFinite(t) ? t : null;
  }

  function relTime(value) {
    const t = parseTs(value);
    if (t == null) return "";
    const seconds = Math.round((Date.now() - t) / 1000);
    if (seconds < 45) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 14) return `${days}d ago`;
    return new Date(t).toISOString().slice(0, 10);
  }

  function zulu(value) {
    const t = parseTs(value);
    if (t == null) return "";
    const iso = new Date(t).toISOString();
    return `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
  }

  function fmtLatLng(lat, lng) {
    return `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}  ${Math.abs(lng).toFixed(4)}°${lng >= 0 ? "E" : "W"}`;
  }

  function fmtKm(km) {
    if (km >= 100) return `${Math.round(km).toLocaleString()} km`;
    return `${km.toFixed(1)} km`;
  }

  function isLight(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return false;
    const n = parseInt(m[1], 16);
    const channel = (v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const lum = 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
    return lum > 0.42;
  }

  function strengthColor(value) {
    if (value >= 70) return "#4ade80";
    if (value >= 40) return "#fbbf24";
    return "#f87171";
  }

  function polygonAreaKm2(points) {
    // Spherical excess approximation; good enough for a briefing readout.
    const R = 6371.0088;
    const rad = Math.PI / 180;
    let total = 0;
    for (let i = 0; i < points.length; i += 1) {
      const [lat1, lng1] = points[i];
      const [lat2, lng2] = points[(i + 1) % points.length];
      total += (lng2 - lng1) * rad * (2 + Math.sin(lat1 * rad) + Math.sin(lat2 * rad));
    }
    return Math.abs((total * R * R) / 2);
  }

  function pathLengthKm(points) {
    let total = 0;
    for (let i = 1; i < points.length; i += 1) total += L.latLng(points[i - 1]).distanceTo(L.latLng(points[i]));
    return total / 1000;
  }

  function loadPrefs() {
    try {
      return JSON.parse(window.localStorage.getItem(PREFS_KEY) || "{}") || {};
    } catch (_err) {
      return {};
    }
  }

  function savePrefs() {
    try {
      window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (_err) {
      /* storage unavailable: preferences just won't persist */
    }
  }

  // -------------------------------------------------------------------------
  // Military symbols (APP-6 inspired)
  // -------------------------------------------------------------------------

  const FRAMES = {
    friendly: { shape: '<rect x="3.5" y="16.5" width="33" height="21" rx="1.5"/>', box: [3.5, 16.5, 36.5, 37.5], top: 16.5 },
    hostile: { shape: '<path d="M20 12 L35 27 L20 42 L5 27 Z"/>', box: [12.5, 19.5, 27.5, 34.5], top: 12 },
    neutral: { shape: '<rect x="8" y="15" width="24" height="24" rx="1"/>', box: [8, 15, 32, 39], top: 15 },
    unknown: { shape: '<circle cx="20" cy="27" r="13"/>', box: [11, 18, 29, 36], top: 14 },
  };

  function glyph(type, box, ink) {
    const [x0, y0, x1, y1] = box;
    const w = x1 - x0;
    const ht = y1 - y0;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const s = Math.min(w, ht) * 0.3;
    const n = (v) => v.toFixed(2);
    const stroke = (d, width = 1.8) => `<path d="${d}" fill="none" stroke="${ink}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;
    const fill = (d) => `<path d="${d}" fill="${ink}"/>`;
    const text = (t) => `<text x="${n(cx)}" y="${n(cy)}" dy="0.36em" text-anchor="middle" font-family="system-ui,sans-serif" font-weight="800" font-size="${n(Math.min(w, ht) * 0.46)}" fill="${ink}">${t}</text>`;
    const cross = `M${n(x0)} ${n(y0)}L${n(x1)} ${n(y1)}M${n(x0)} ${n(y1)}L${n(x1)} ${n(y0)}`;
    const ovalW = w * 0.62;
    const ovalH = ht * 0.46;
    const oval = `<rect x="${n(cx - ovalW / 2)}" y="${n(cy - ovalH / 2)}" width="${n(ovalW)}" height="${n(ovalH)}" rx="${n(ovalH / 2)}" fill="none" stroke="${ink}" stroke-width="1.8"/>`;
    switch (type) {
      case "infantry": return stroke(cross);
      case "mechanized": return stroke(cross) + oval;
      case "armor": return oval;
      case "artillery": return `<circle cx="${n(cx)}" cy="${n(cy)}" r="${n(s * 0.55)}" fill="${ink}"/>`;
      case "air_defense": return stroke(`M${n(cx - s * 1.3)} ${n(cy + s * 0.7)}Q${n(cx)} ${n(cy - s * 1.5)} ${n(cx + s * 1.3)} ${n(cy + s * 0.7)}`);
      case "air": return fill(
        `M${n(cx)} ${n(cy)}C${n(cx - s * 0.5)} ${n(cy - s * 0.95)} ${n(cx - s * 1.6)} ${n(cy - s * 0.95)} ${n(cx - s * 1.6)} ${n(cy)}` +
        `C${n(cx - s * 1.6)} ${n(cy + s * 0.95)} ${n(cx - s * 0.5)} ${n(cy + s * 0.95)} ${n(cx)} ${n(cy)}` +
        `C${n(cx + s * 0.5)} ${n(cy - s * 0.95)} ${n(cx + s * 1.6)} ${n(cy - s * 0.95)} ${n(cx + s * 1.6)} ${n(cy)}` +
        `C${n(cx + s * 1.6)} ${n(cy + s * 0.95)} ${n(cx + s * 0.5)} ${n(cy + s * 0.95)} ${n(cx)} ${n(cy)}Z`);
      case "helicopter": return fill(
        `M${n(cx - s * 1.6)} ${n(cy - s * 0.85)}L${n(cx)} ${n(cy)}L${n(cx - s * 1.6)} ${n(cy + s * 0.85)}Z` +
        `M${n(cx + s * 1.6)} ${n(cy - s * 0.85)}L${n(cx)} ${n(cy)}L${n(cx + s * 1.6)} ${n(cy + s * 0.85)}Z`);
      case "drone": return fill(`M${n(cx - s * 1.6)} ${n(cy - s * 0.7)}L${n(cx)} ${n(cy + s * 0.75)}L${n(cx + s * 1.6)} ${n(cy - s * 0.7)}L${n(cx)} ${n(cy - s * 0.05)}Z`);
      case "naval": return fill(`M${n(cx - s * 1.5)} ${n(cy + s * 0.15)}L${n(cx + s * 1.5)} ${n(cy + s * 0.15)}L${n(cx + s * 1.05)} ${n(cy + s * 0.9)}L${n(cx - s * 1.05)} ${n(cy + s * 0.9)}Z`) +
        stroke(`M${n(cx)} ${n(cy - s)}L${n(cx)} ${n(cy + s * 0.15)}M${n(cx - s * 0.55)} ${n(cy - s * 0.45)}L${n(cx + s * 0.55)} ${n(cy - s * 0.45)}`);
      case "submarine": return `<ellipse cx="${n(cx)}" cy="${n(cy + s * 0.3)}" rx="${n(s * 1.55)}" ry="${n(s * 0.42)}" fill="${ink}"/>` +
        `<rect x="${n(cx - s * 0.32)}" y="${n(cy - s * 0.45)}" width="${n(s * 0.64)}" height="${n(s * 0.62)}" rx="${n(s * 0.12)}" fill="${ink}"/>`;
      case "missile": return fill(`M${n(cx)} ${n(cy - s * 1.15)}L${n(cx + s * 0.6)} ${n(cy - s * 0.3)}L${n(cx + s * 0.22)} ${n(cy - s * 0.3)}L${n(cx + s * 0.22)} ${n(cy + s * 1.05)}L${n(cx - s * 0.22)} ${n(cy + s * 1.05)}L${n(cx - s * 0.22)} ${n(cy - s * 0.3)}L${n(cx - s * 0.6)} ${n(cy - s * 0.3)}Z`);
      case "recon": return stroke(`M${n(x0)} ${n(y1)}L${n(x1)} ${n(y0)}`);
      case "special_forces": return text("SF");
      case "hq": return text("HQ");
      case "logistics": return stroke(`M${n(x0 + w * 0.1)} ${n(y1 - ht * 0.26)}L${n(x1 - w * 0.1)} ${n(y1 - ht * 0.26)}`, 2.6);
      default: return "";
    }
  }

  function symbolSvg(unit, faction) {
    const f = faction || UNALIGNED;
    const frame = FRAMES[f.stance] || FRAMES.unknown;
    const ink = isLight(f.color) ? "#0b0f0c" : "#ffffff";
    const mark = ECHELON_MARK[unit.echelon] || "";
    const echelon = mark
      ? `<text x="20" y="${(frame.top - 2.5).toFixed(1)}" text-anchor="middle" font-family="system-ui,sans-serif" font-weight="900" font-size="8.5" fill="#fff" stroke="#0b0f0c" stroke-width="2.4" paint-order="stroke">${mark}</text>`
      : "";
    const destroyed = unit.status === "destroyed"
      ? '<path d="M5 14L35 41M35 14L5 41" stroke="#0b0f0c" stroke-width="4.6" stroke-linecap="round"/><path d="M5 14L35 41M35 14L5 41" stroke="#ff5a5a" stroke-width="2.2" stroke-linecap="round"/>'
      : "";
    return `<svg class="wm-sym" viewBox="0 0 40 44" width="40" height="44" aria-hidden="true" focusable="false">` +
      `<g fill="${esc(f.color)}" stroke="#0b0f0c" stroke-width="1.6">${frame.shape}</g>` +
      glyph(unit.type, frame.box, ink) + echelon + destroyed + "</svg>";
  }

  function eventIconSvg(kind) {
    const spec = EVENT_KINDS[kind] || EVENT_KINDS.report;
    return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${spec.icon}</svg>`;
  }

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------

  const prefs = Object.assign(
    { base: "satellite", labels: true, unitLabels: true, units: true, zones: true, lines: true, events: true, destroyed: true },
    loadPrefs(),
  );

  let state = null;
  let etag = null;
  const index = { factions: new Map(), units: new Map(), zones: new Map(), lines: new Map(), events: new Map() };
  let selected = null; // { collection, id, draft? }
  let inspectorDirty = false;
  let tool = "select";
  const toolOpts = { faction: "", unitType: "infantry", echelon: "battalion", zoneKind: "control", lineKind: "front", eventKind: "battle" };
  let pickHandler = null; // one-shot map click handler (e.g. "pick location")
  let busy = false; // true while the operator is dragging something
  let deferredState = null;
  const seenEvents = new Set();
  const myEventIds = new Set();
  let unreadEvents = 0;
  let activeTab = "brief";

  function factionOf(id) {
    return index.factions.get(id) || UNALIGNED;
  }

  function factionList() {
    return state ? state.factions : [];
  }

  function buildIndex() {
    for (const key of Object.keys(index)) {
      index[key] = new Map((state[key] || []).map((item) => [item.id, item]));
    }
    if (!index.factions.has(toolOpts.faction)) toolOpts.faction = state.factions.length ? state.factions[0].id : "";
  }

  function isSelected(collection, id) {
    return Boolean(selected && selected.collection === collection && selected.id === id);
  }

  // -------------------------------------------------------------------------
  // Map
  // -------------------------------------------------------------------------

  const mapEl = $("wm-map");
  const map = L.map(mapEl, {
    zoomControl: false,
    worldCopyJump: true,
    minZoom: 2,
    maxZoom: 18,
    maxBounds: [[-88, -540], [88, 540]],
    maxBoundsViscosity: 1.0,
    wheelPxPerZoomLevel: 90,
  }).setView([28, 15], 3);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>');
  L.control.zoom({ position: "bottomright" }).addTo(map);
  // The scale bar lives in the status strip beside the legend, not in a map corner.
  $("wm-statusbar").append(L.control.scale({ position: "bottomleft", imperial: false }).addTo(map).getContainer());

  function makePane(name, zIndex) {
    map.createPane(name).style.zIndex = String(zIndex);
  }
  makePane("wm-zones", 405);
  makePane("wm-lines", 415);
  makePane("wm-arrows", 416);
  makePane("wm-events", 615);
  makePane("wm-units", 625);
  makePane("wm-draft", 640);
  makePane("wm-handles", 645);
  const zoneRenderer = L.svg({ pane: "wm-zones", padding: 0.5 });
  const lineRenderer = L.svg({ pane: "wm-lines", padding: 0.5 });
  const draftRenderer = L.svg({ pane: "wm-draft", padding: 0.5 });

  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
  const basemaps = {
    satellite: {
      label: "Satellite",
      layer: L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
        maxNativeZoom: 17,
        maxZoom: 18,
        attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, GIS User Community",
      }),
    },
    terrain: {
      label: "Terrain",
      layer: L.tileLayer(`${ESRI}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`, {
        maxNativeZoom: 18,
        maxZoom: 18,
        attribution: "Basemap &copy; Esri and contributors",
      }),
    },
    dark: {
      label: "Dark tactical",
      layer: L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        subdomains: "abcd",
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>',
      }),
    },
  };
  const labelsLayer = L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, {
    maxNativeZoom: 17,
    maxZoom: 18,
    zIndex: 5,
    attribution: "Labels &copy; Esri",
  });

  const groups = {
    zones: L.layerGroup().addTo(map),
    lines: L.layerGroup().addTo(map),
    events: L.layerGroup().addTo(map),
    units: L.layerGroup().addTo(map),
  };
  const handleLayer = L.layerGroup().addTo(map);
  const draftLayer = L.layerGroup().addTo(map);
  const rendered = { units: new Map(), zones: new Map(), lines: new Map(), events: new Map() };

  function applyBasemap() {
    if (!basemaps[prefs.base]) prefs.base = "satellite";
    for (const [key, spec] of Object.entries(basemaps)) {
      if (key === prefs.base) spec.layer.addTo(map);
      else map.removeLayer(spec.layer);
    }
    if (prefs.labels && prefs.base !== "terrain") labelsLayer.addTo(map);
    else map.removeLayer(labelsLayer);
  }

  function applyLayerVisibility() {
    for (const key of ["zones", "lines", "events", "units"]) {
      if (prefs[key]) groups[key].addTo(map);
      else map.removeLayer(groups[key]);
    }
    mapEl.classList.toggle("wm-show-labels", Boolean(prefs.unitLabels));
  }

  function updateZoomBand() {
    const zoom = map.getZoom();
    mapEl.dataset.zoomBand = zoom < 5 ? "far" : zoom < 8 ? "mid" : "near";
  }
  map.on("zoomend", updateZoomBand);
  updateZoomBand();

  const coordsEl = $("wm-coords");
  map.on("mousemove", (e) => {
    const ll = e.latlng.wrap();
    coordsEl.textContent = fmtLatLng(ll.lat, ll.lng);
    if (draft.points.length) updateRubberBand(e.latlng);
  });
  map.on("mouseout", () => {
    coordsEl.textContent = "";
  });

  // ---------- units ----------

  function unitIcon(unit) {
    const classes = ["wm-unit", `wm-unit--${unit.status}`];
    if (isSelected("units", unit.id)) classes.push("is-selected");
    let badge = "";
    if (unit.status === "damaged") badge = '<span class="wm-unit__badge">!</span>';
    if (unit.status === "retreating") badge = '<span class="wm-unit__badge">&laquo;</span>';
    const bar = unit.strength < 100 && unit.status !== "destroyed"
      ? `<span class="wm-unit__bar" style="--wm-strength:${strengthColor(unit.strength)}"><i style="width:${unit.strength}%"></i></span>`
      : "";
    return L.divIcon({
      className: "wm-unit-icon",
      iconSize: [40, 44],
      iconAnchor: [20, 27],
      html: `<div class="${classes.join(" ")}"><div class="wm-unit__sym">${symbolSvg(unit, factionOf(unit.faction))}</div>${badge}${bar}<div class="wm-unit__label">${esc(unit.name)}</div></div>`,
    });
  }

  function createUnitLayer(unit) {
    const marker = L.marker([unit.lat, unit.lng], {
      icon: unitIcon(unit),
      pane: "wm-units",
      draggable: CAN_EDIT,
      autoPan: true,
      keyboard: true,
      riseOnHover: true,
    });
    marker.on("click", (e) => onObjectClick("units", unit.id, e.latlng));
    marker.on("dblclick", finishDraftFromMarker);
    if (CAN_EDIT) {
      marker.on("dragstart", () => {
        busy = true;
        const entry = rendered.units.get(unit.id);
        if (entry) entry.dragging = true;
        if (!isSelected("units", unit.id) && !inspectorDirty) select("units", unit.id);
      });
      marker.on("dragend", () => {
        busy = false;
        deferredState = null;
        const entry = rendered.units.get(unit.id);
        if (entry) {
          entry.dragging = false;
          entry.sig = ""; // rebuild from server data, even if the save fails
        }
        const ll = marker.getLatLng().wrap();
        sendOps([{ op: "upsert", collection: "units", item: { id: unit.id, lat: ll.lat, lng: ll.lng } }]).catch(() => {});
      });
    }
    return marker;
  }

  // ---------- zones ----------

  function zoneStyle(zone) {
    const color = factionOf(zone.faction).color;
    const chosen = isSelected("zones", zone.id);
    const style = { renderer: zoneRenderer, color, weight: chosen ? 3.5 : 2, opacity: 0.95, fillColor: color, fillOpacity: 0.22, lineJoin: "round" };
    if (zone.kind === "contested") Object.assign(style, { dashArray: "9 7", fillOpacity: 0.12 });
    if (zone.kind === "exclusion") Object.assign(style, { dashArray: "2 7", weight: chosen ? 4 : 3, fillOpacity: 0.08, lineCap: "round" });
    if (zone.kind === "objective") Object.assign(style, { color: "#facc15", dashArray: "12 6", fillOpacity: 0.1 });
    if (chosen) style.fillOpacity += 0.08;
    return style;
  }

  function createZoneLayer(zone, points) {
    const polygon = L.polygon(points || zone.points, zoneStyle(zone));
    polygon.bindTooltip(esc(zone.name), { permanent: true, direction: "center", className: "wm-zone-label", interactive: false });
    polygon.on("click", (e) => {
      L.DomEvent.stop(e);
      onObjectClick("zones", zone.id, e.latlng);
    });
    return polygon;
  }

  // ---------- lines ----------

  function arrowHead(points, color) {
    const end = L.latLng(points[points.length - 1]);
    const prev = L.latLng(points[points.length - 2]);
    // Mercator is conformal, so the on-screen angle is the same at every zoom.
    const a = map.project(prev, 4);
    const b = map.project(end, 4);
    const deg = (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI;
    return L.marker(end, {
      pane: "wm-arrows",
      interactive: false,
      keyboard: false,
      icon: L.divIcon({
        className: "wm-arrow-icon",
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        html: `<svg width="32" height="32" viewBox="-16 -16 32 32" style="transform:rotate(${deg.toFixed(1)}deg)"><path d="M9 0L-11 -10L-6 0L-11 10Z" fill="${esc(color)}" stroke="#0b0f0c" stroke-width="1.6" stroke-linejoin="round"/></svg>`,
      }),
    });
  }

  function createLineLayer(line, points) {
    const pts = points || line.points;
    const faction = factionOf(line.faction);
    const chosen = isSelected("lines", line.id);
    const color = line.kind === "border" && !line.faction ? "#ffffff" : faction.color;
    const group = L.featureGroup();
    const base = { renderer: lineRenderer, lineCap: "round", lineJoin: "round" };
    const casing = (weight, extra) => L.polyline(pts, Object.assign({}, base, { color: "#0b0f0c", opacity: 0.55, weight, interactive: false }, extra || {})).addTo(group);
    let main;
    if (line.kind === "front") {
      casing(chosen ? 11 : 9);
      main = L.polyline(pts, Object.assign({}, base, { color, weight: chosen ? 6 : 4.5, opacity: 1 }));
    } else if (line.kind === "advance") {
      casing(chosen ? 10 : 8);
      main = L.polyline(pts, Object.assign({}, base, { color, weight: chosen ? 6 : 4.5, opacity: 1 }));
    } else if (line.kind === "supply") {
      casing(chosen ? 7 : 5, { dashArray: "10 8", lineCap: "butt" });
      main = L.polyline(pts, Object.assign({}, base, { color, weight: chosen ? 4 : 3, dashArray: "10 8", lineCap: "butt" }));
    } else {
      main = L.polyline(pts, Object.assign({}, base, { color, weight: chosen ? 4 : 3, dashArray: "1 8", opacity: 0.95 }));
    }
    main.addTo(group);
    // A wide invisible stroke makes thin lines easy to click.
    const hit = L.polyline(pts, Object.assign({}, base, { color: "#000", opacity: 0, weight: 18 })).addTo(group);
    hit.bindTooltip(esc(line.name), { sticky: true, className: "wm-tip", direction: "top", offset: [0, -8] });
    if (line.kind === "advance" && pts.length >= 2) arrowHead(pts, color).addTo(group);
    group.on("click", (e) => {
      L.DomEvent.stop(e);
      onObjectClick("lines", line.id, e.latlng);
    });
    return group;
  }

  // ---------- events ----------

  function eventAgeClass(event) {
    const t = parseTs(event.ts);
    if (t == null) return "";
    const age = Date.now() - t;
    if (age < RECENT_EVENT_MS) return "is-recent";
    if (age > OLD_EVENT_MS) return "is-old";
    return "";
  }

  function eventIcon(event, extraClass) {
    const spec = EVENT_KINDS[event.kind] || EVENT_KINDS.report;
    const classes = ["wm-event", eventAgeClass(event), extraClass || ""];
    if (isSelected("events", event.id)) classes.push("is-selected");
    return L.divIcon({
      className: "wm-event-icon",
      iconSize: [26, 26],
      iconAnchor: [13, 13],
      html: `<div class="${classes.join(" ").trim()}" style="--wm-kind:${spec.color}">${eventIconSvg(event.kind)}</div>`,
    });
  }

  function createEventLayer(event) {
    const marker = L.marker([event.lat, event.lng], { icon: eventIcon(event), pane: "wm-events", keyboard: true, riseOnHover: true });
    marker.bindTooltip(esc(event.title), { className: "wm-tip", direction: "top", offset: [0, -14] });
    marker.on("click", (e) => onObjectClick("events", event.id, e.latlng));
    marker.on("dblclick", finishDraftFromMarker);
    return marker;
  }

  // ---------- diff rendering ----------

  function signature(collection, item) {
    const faction = item.faction !== undefined ? factionOf(item.faction) : null;
    const extra = collection === "events" ? eventAgeClass(item) : "";
    return JSON.stringify([item, faction && [faction.color, faction.stance, faction.name], isSelected(collection, item.id), extra]);
  }

  function renderCollection(collection, items, create, shouldShow) {
    const registry = rendered[collection];
    const keep = new Set();
    for (const item of items) {
      if (shouldShow && !shouldShow(item)) continue;
      keep.add(item.id);
      const sig = signature(collection, item);
      const existing = registry.get(item.id);
      if (existing && existing.sig === sig) continue;
      if (existing && existing.dragging) continue;
      if (existing) groups[collection].removeLayer(existing.layer);
      const layer = create(item);
      groups[collection].addLayer(layer);
      registry.set(item.id, { sig, layer });
    }
    for (const [id, entry] of registry) {
      if (!keep.has(id)) {
        groups[collection].removeLayer(entry.layer);
        registry.delete(id);
      }
    }
  }

  function renderLayers() {
    renderCollection("zones", state.zones, (z) => createZoneLayer(z));
    renderCollection("lines", state.lines, (l) => createLineLayer(l));
    renderCollection("events", state.events, createEventLayer, (e) => e.lat != null && e.lng != null);
    renderCollection("units", state.units, createUnitLayer, (u) => prefs.destroyed || u.status !== "destroyed");
  }

  function rerenderItem(collection, id) {
    const entry = rendered[collection].get(id);
    if (entry) entry.sig = ""; // force rebuild on next render
    if (state) renderLayers();
  }

  // -------------------------------------------------------------------------
  // Live sync
  // -------------------------------------------------------------------------

  const liveEl = $("wm-live");
  const liveTextEl = $("wm-live-text");
  let lastSyncAt = 0;
  let failures = 0;
  let pollTimer = null;
  let polling = false;
  let saving = 0;
  let locked = !CAN_VIEW;

  function setLive(kind, text, title) {
    liveEl.dataset.state = kind;
    liveTextEl.textContent = text;
    liveEl.title = title || text;
  }

  function refreshLive() {
    if (locked) return setLive("locked", "Sign in", "Sign in to receive live updates");
    if (saving) return setLive("live", "Saving…");
    if (!lastSyncAt) return setLive("connecting", "Connecting");
    if (failures >= 3) return setLive("offline", "Offline", "Can't reach the server — retrying");
    const age = Date.now() - lastSyncAt;
    const ago = Math.max(0, Math.round(age / 1000));
    if (age > STALE_AFTER_MS) return setLive("stale", "Reconnecting", `Last synced ${ago}s ago`);
    return setLive("live", "Live", `Synced ${ago}s ago`);
  }

  function schedulePoll() {
    window.clearTimeout(pollTimer);
    if (document.hidden || locked) return;
    const delay = failures ? Math.min(30000, POLL_INTERVAL_MS * 2 ** failures) : POLL_INTERVAL_MS;
    pollTimer = window.setTimeout(poll, delay);
  }

  async function poll() {
    if (polling || locked) return;
    polling = true;
    try {
      const headers = { Accept: "application/json" };
      if (etag) headers["If-None-Match"] = etag;
      const response = await fetch(STATE_URL, { headers, credentials: "same-origin", cache: "no-store" });
      if (response.status === 401 || response.status === 403) {
        locked = true;
        document.body.classList.add("is-locked");
        toast(["Your session ended. ", h("a", { href: `/login?next=${encodeURIComponent(window.location.pathname)}`, text: "Sign in again" }), " to keep watching."], "error", null, 600000);
      } else if (response.status === 304) {
        failures = 0;
        lastSyncAt = Date.now();
      } else if (response.ok) {
        const data = await response.json();
        etag = response.headers.get("ETag");
        failures = 0;
        lastSyncAt = Date.now();
        receiveState(data);
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (_err) {
      failures += 1;
    } finally {
      polling = false;
      refreshLive();
      schedulePoll();
    }
  }

  function receiveState(data) {
    if (busy) {
      deferredState = data;
      return;
    }
    applyState(data);
  }

  let opChain = Promise.resolve();

  /** Send edit operations; resolves with the new state or rejects after showing an error. */
  function sendOps(ops) {
    const run = async () => {
      saving += 1;
      refreshLive();
      try {
        const response = await fetch(OPS_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ ops }),
        });
        if (!response.ok) {
          let detail = `Save failed (HTTP ${response.status})`;
          try {
            const body = await response.json();
            if (body && typeof body.detail === "string") detail = body.detail;
          } catch (_err) { /* keep generic message */ }
          throw new Error(detail);
        }
        const data = await response.json();
        etag = response.headers.get("ETag") || etag;
        lastSyncAt = Date.now();
        failures = 0;
        applyState(data);
        return data;
      } catch (err) {
        toast(err && err.message ? err.message : "Save failed", "error");
        etag = null; // force a full reload so the map shows the real state again
        window.setTimeout(poll, 50);
        throw err;
      } finally {
        saving -= 1;
        refreshLive();
      }
    };
    const result = opChain.then(run, run);
    opChain = result.catch(() => {});
    return result;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) window.clearTimeout(pollTimer);
    else poll();
  });

  // -------------------------------------------------------------------------
  // Applying state
  // -------------------------------------------------------------------------

  let initialised = false;

  function applyState(next) {
    state = next;
    buildIndex();
    renderLayers();
    renderChrome();
    if (selected && !selected.draft) {
      if (!index[selected.collection].has(selected.id)) {
        closeInspector(true);
      } else if (!inspectorDirty) {
        renderInspector();
      }
      refreshHandles();
    }
    if (!initialised) {
      initialised = true;
      state.events.forEach((event) => seenEvents.add(event.id));
      initialView();
    } else {
      announceNewEvents();
    }
  }

  function announceNewEvents() {
    const fresh = state.events.filter((event) => !seenEvents.has(event.id));
    fresh.forEach((event) => seenEvents.add(event.id));
    const foreign = fresh.filter((event) => !myEventIds.has(event.id));
    if (!foreign.length) return;
    if (activeTab !== "sitrep" || document.body.classList.contains("panel-hidden")) {
      unreadEvents += foreign.length;
      renderBadge();
    }
    foreign.slice(0, 3).forEach((event) => {
      const spec = EVENT_KINDS[event.kind] || EVENT_KINDS.report;
      toast([h("b", { text: spec.label.toUpperCase() }), " ", event.title], "event", () => focusItem("events", event.id), 9000);
    });
    flashFeedItems(foreign.map((event) => event.id));
  }

  /** Horizontal distance (px) from the map's centre to the centre of the area not covered by the panel. */
  function panelOffset() {
    const panelOpen = !document.body.classList.contains("panel-hidden") && window.innerWidth > 760;
    return panelOpen ? Math.round(($("wm-panel").offsetWidth + 12) / 2) : 0;
  }

  function initialView() {
    const view = state.meta.view;
    if (view) {
      map.setView([view.lat, view.lng], view.zoom, { animate: false });
      map.panBy([-panelOffset(), 0], { animate: false });
    } else if (!fitTheatre(false)) {
      map.setView([28, 15], 3);
    }
  }

  function theatreBounds() {
    const bounds = L.latLngBounds([]);
    state.units.forEach((u) => bounds.extend([u.lat, u.lng]));
    state.zones.forEach((z) => z.points.forEach((p) => bounds.extend(p)));
    state.lines.forEach((l) => l.points.forEach((p) => bounds.extend(p)));
    state.events.forEach((e) => { if (e.lat != null) bounds.extend([e.lat, e.lng]); });
    return bounds;
  }

  function mapPadding() {
    const panelOpen = !document.body.classList.contains("panel-hidden") && window.innerWidth > 760;
    return {
      paddingTopLeft: [panelOpen ? 380 : 40, 90],
      paddingBottomRight: [CAN_EDIT ? 100 : 70, 50],
    };
  }

  function fitTheatre(animate = true) {
    if (!state) return false;
    const bounds = theatreBounds();
    if (!bounds.isValid()) return false;
    map.fitBounds(bounds, Object.assign({ maxZoom: 9, animate }, mapPadding()));
    return true;
  }

  // -------------------------------------------------------------------------
  // Chrome: top bar, brief, forces, SITREP feed
  // -------------------------------------------------------------------------

  function renderTopbar() {
    const meta = state.meta;
    $("wm-op-name").textContent = meta.operation;
    $("wm-op-theatre").textContent = meta.theatre;
    document.title = `${meta.operation} · W.A.S.P. War Map`;
    const statusEl = $("wm-status");
    statusEl.dataset.status = meta.status;
    statusEl.textContent = WAR_STATUSES[meta.status] || meta.status;
    const threatEl = $("wm-threat");
    threatEl.dataset.level = String(meta.threatLevel);
    $("wm-threat-text").textContent = THREAT_LABELS[meta.threatLevel] || "";
    renderDay();
  }

  function renderDay() {
    const dayEl = $("wm-day");
    const start = state && state.meta.warStart ? Date.parse(`${state.meta.warStart}T00:00:00Z`) : NaN;
    if (!Number.isFinite(start)) {
      dayEl.hidden = true;
      return;
    }
    const diff = Math.floor((Date.now() - start) / 86400000);
    dayEl.hidden = false;
    dayEl.textContent = diff >= 0 ? `DAY ${diff + 1}` : `T−${-diff}D`;
  }

  function renderBrief() {
    const meta = state.meta;
    const summaryEl = $("wm-summary");
    summaryEl.textContent = meta.summary || (CAN_EDIT ? "No briefing written yet. Open Operation settings to describe the war." : "No briefing has been issued for this theatre yet.");
    summaryEl.classList.toggle("is-empty", !meta.summary);

    const alive = state.units.filter((u) => u.status !== "destroyed");
    const dayAgo = Date.now() - 24 * 3600 * 1000;
    const kpis = [
      [alive.length, "Units"],
      [state.zones.length, "Zones"],
      [state.lines.length, "Lines"],
      [state.events.filter((e) => (parseTs(e.ts) || 0) > dayAgo).length, "SITREP 24h"],
    ];
    $("wm-kpis").replaceChildren(...kpis.map(([value, label]) => h("div", { class: "wm-kpi" }, h("b", { text: String(value) }), h("span", { text: label }))));

    const rows = factionList().map((faction) => {
      const units = state.units.filter((u) => u.faction === faction.id);
      const active = units.filter((u) => u.status !== "destroyed").length;
      const lost = units.length - active;
      const zones = state.zones.filter((z) => z.faction === faction.id && z.kind === "control").length;
      return h("div", { class: "wm-faction", style: `--wm-faction:${faction.color}` },
        h("span", { class: "wm-faction__bar" }),
        h("div", {},
          h("div", { class: "wm-faction__name", text: faction.name }),
          h("div", { class: "wm-faction__meta", text: `${STANCES[faction.stance]} · ${zones} zone${zones === 1 ? "" : "s"} held${lost ? ` · ${lost} lost` : ""}` })),
        h("div", { class: "wm-faction__count" }, String(active), h("small", { text: "units" })));
    });
    $("wm-factions").replaceChildren(...rows);

    const updated = $("wm-updated");
    updated.textContent = state.updatedAt
      ? `Last update ${relTime(state.updatedAt)}${state.updatedBy ? ` by ${state.updatedBy}` : ""}`
      : "No changes recorded yet.";
  }

  function renderForces() {
    const query = ($("wm-unit-search").value || "").trim().toLowerCase();
    const hideDestroyed = $("wm-hide-destroyed").checked;
    const matches = state.units.filter((u) => {
      if (hideDestroyed && u.status === "destroyed") return false;
      if (!query) return true;
      const faction = factionOf(u.faction);
      return [u.name, u.notes, UNIT_TYPES[u.type], ECHELONS[u.echelon], faction.name, faction.short, UNIT_STATUSES[u.status]]
        .some((text) => String(text || "").toLowerCase().includes(query));
    });
    $("wm-forces-count").textContent = state.units.length ? String(state.units.filter((u) => u.status !== "destroyed").length) : "";

    const container = $("wm-forces");
    if (!state.units.length) {
      container.replaceChildren(h("p", { class: "wm-empty", text: CAN_EDIT ? "No forces deployed yet. Pick the Unit tool on the right and click the map to deploy one." : "No forces have been deployed in this theatre yet." }));
      return;
    }
    if (!matches.length) {
      container.replaceChildren(h("p", { class: "wm-empty", text: "No units match your search." }));
      return;
    }
    const buckets = new Map();
    for (const faction of factionList()) buckets.set(faction.id, []);
    for (const unit of matches) {
      const key = index.factions.has(unit.faction) ? unit.faction : "";
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(unit);
    }
    const sections = [];
    for (const [factionId, units] of buckets) {
      if (!units.length) continue;
      const faction = factionOf(factionId);
      units.sort((a, b) => a.name.localeCompare(b.name));
      sections.push(h("section", { class: "wm-force-group" },
        h("h4", {}, h("span", { class: "wm-swatch", style: `background:${faction.color}` }), faction.name, h("span", { class: "wm-count", text: String(units.length) })),
        units.map((unit) => h("button", {
          type: "button",
          class: `wm-unit-row${isSelected("units", unit.id) ? " is-selected" : ""}${unit.status === "destroyed" ? " is-destroyed" : ""}`,
          onclick: () => focusItem("units", unit.id),
        },
        h("span", { class: "wm-unit-row__sym", svg: symbolSvg(unit, faction) }),
        h("span", { style: "min-width:0" },
          h("div", { class: "wm-unit-row__name", text: unit.name }),
          h("div", { class: "wm-unit-row__meta", text: [UNIT_TYPES[unit.type], unit.echelon ? ECHELONS[unit.echelon] : ""].filter(Boolean).join(" · ") })),
        h("span", { class: "wm-unit-row__right" },
          h("span", { class: "wm-status-dot", "data-status": unit.status, text: UNIT_STATUSES[unit.status] }),
          unit.status !== "destroyed" ? h("span", { class: "wm-strength", style: `--wm-strength:${strengthColor(unit.strength)}`, title: `Strength ${unit.strength}%` }, h("i", { style: `width:${unit.strength}%` })) : null)))));
    }
    container.replaceChildren(...sections);
  }

  function renderFeed() {
    const feed = $("wm-feed");
    if (!state.events.length) {
      feed.replaceChildren(h("li", { class: "wm-empty", text: CAN_EDIT ? "No situation reports yet. Post one to start the war log." : "No situation reports have been filed yet." }));
      return;
    }
    feed.replaceChildren(...state.events.map((event) => {
      const spec = EVENT_KINDS[event.kind] || EVENT_KINDS.report;
      const meta = [spec.label.toUpperCase(), relTime(event.ts), event.author, event.lat == null ? "no location" : ""].filter(Boolean).join(" · ");
      const item = h("li", {
        class: `wm-feed-item${isSelected("events", event.id) ? " is-selected" : ""}`,
        tabindex: "0",
        role: "button",
        "data-id": event.id,
        style: `--wm-kind:${spec.color}`,
        title: zulu(event.ts),
        onclick: () => focusItem("events", event.id),
        onkeydown: (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            focusItem("events", event.id);
          }
        },
      },
      h("span", { class: "wm-feed-item__icon", svg: eventIconSvg(event.kind) }),
      h("div", { style: "min-width:0" },
        h("div", { class: "wm-feed-item__title", text: event.title }),
        h("div", { class: "wm-feed-item__meta", text: meta }),
        event.body ? h("p", { class: "wm-feed-item__body", text: event.body }) : null));
      return item;
    }));
  }

  function flashFeedItems(ids) {
    ids.forEach((id) => {
      const node = document.querySelector(`.wm-feed-item[data-id="${CSS.escape(id)}"]`);
      if (node) node.classList.add("is-new");
    });
  }

  function renderBadge() {
    const badge = $("wm-sitrep-badge");
    badge.hidden = unreadEvents <= 0;
    badge.textContent = unreadEvents > 9 ? "9+" : String(unreadEvents);
  }

  function renderChrome() {
    renderTopbar();
    renderBrief();
    renderForces();
    renderFeed();
    if (CAN_EDIT && tool !== "select") renderToolOptions();
  }

  // ---------- tabs / panel ----------

  function setTab(name) {
    activeTab = name;
    document.querySelectorAll(".wm-tab").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
    document.querySelectorAll(".wm-tabpanel").forEach((panel) => {
      panel.hidden = panel.dataset.tabpanel !== name;
    });
    if (name === "sitrep") {
      unreadEvents = 0;
      renderBadge();
    }
  }

  document.querySelectorAll(".wm-tab").forEach((tab) => tab.addEventListener("click", () => setTab(tab.dataset.tab)));

  function setPanelHidden(hidden) {
    document.body.classList.toggle("panel-hidden", hidden);
    $("wm-panel-show").hidden = !hidden;
  }
  $("wm-panel-hide").addEventListener("click", () => setPanelHidden(true));
  $("wm-panel-show").addEventListener("click", () => {
    setPanelHidden(false);
    if (activeTab === "sitrep") {
      unreadEvents = 0;
      renderBadge();
    }
  });
  if (window.innerWidth <= 760) setPanelHidden(true);

  $("wm-unit-search").addEventListener("input", () => state && renderForces());
  $("wm-hide-destroyed").addEventListener("change", () => state && renderForces());
  $("wm-fit").addEventListener("click", () => {
    if (!fitTheatre(true)) toast("Nothing on the map yet.");
  });

  // -------------------------------------------------------------------------
  // Selection + inspector
  // -------------------------------------------------------------------------

  const inspectorEl = $("wm-inspector");

  function onObjectClick(collection, id, latlng) {
    if (pickHandler && latlng) {
      const handler = pickHandler;
      pickHandler = null;
      handler(latlng.wrap());
      return;
    }
    if (CAN_EDIT && (tool === "zone" || tool === "line") && latlng) {
      addDraftPoint(latlng);
      return;
    }
    if (CAN_EDIT && tool === "event" && latlng) {
      openEventDraft(latlng.wrap());
      return;
    }
    select(collection, id);
  }

  function select(collection, id, options = {}) {
    if (isSelected(collection, id) && !selected.draft) {
      if (!inspectorDirty) renderInspector(options);
      return;
    }
    if (inspectorDirty && !window.confirm("Discard unsaved changes?")) return;
    const previous = selected;
    removeEventDraft();
    selected = { collection, id };
    inspectorDirty = false;
    if (previous && !previous.draft) rerenderItem(previous.collection, previous.id);
    rerenderItem(collection, id);
    renderInspector(options);
    refreshHandles();
    renderForces();
    renderFeed();
  }

  function closeInspector(force) {
    if (!force && inspectorDirty && !window.confirm("Discard unsaved changes?")) return false;
    const previous = selected;
    selected = null;
    inspectorDirty = false;
    pickHandler = null;
    removeEventDraft();
    inspectorEl.hidden = true;
    inspectorEl.replaceChildren();
    handleLayer.clearLayers();
    if (previous && !previous.draft && state) {
      rerenderItem(previous.collection, previous.id);
      renderForces();
      renderFeed();
    }
    return true;
  }

  function focusItem(collection, id) {
    const item = index[collection].get(id);
    if (!item) return;
    if (collection === "units" && !prefs.destroyed && item.status === "destroyed") {
      prefs.destroyed = true;
      savePrefs();
      renderLayers();
    }
    if (window.innerWidth <= 760) setPanelHidden(true);
    select(collection, id);
    if (item.lat != null && item.lng != null) {
      map.flyTo([item.lat, item.lng], Math.max(map.getZoom(), 7), { duration: 0.8 });
    } else if (item.points) {
      map.flyToBounds(L.latLngBounds(item.points), Object.assign({ maxZoom: 10, duration: 0.8 }, mapPadding()));
    }
  }

  function inspectorHead(eyebrow, title, symbol) {
    return h("div", { class: "wm-inspector__head" },
      symbol ? h("span", { svg: symbol }) : null,
      h("div", { class: "wm-inspector__titles" },
        h("div", { class: "wm-inspector__eyebrow", text: eyebrow }),
        h("h2", { class: "wm-inspector__title", id: "wm-inspector-title", text: title })),
      h("button", { type: "button", class: "wm-icon-btn wm-inspector__close", "aria-label": "Close", title: "Close (Esc)", onclick: () => closeInspector(), svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' }));
  }

  function factionFact(id) {
    const faction = factionOf(id);
    return [h("span", { class: "wm-swatch", style: `background:${faction.color}` }), faction.name];
  }

  function facts(rows) {
    return h("dl", { class: "wm-facts" }, rows.filter(Boolean).flatMap(([label, value]) => [h("dt", { text: label }), h("dd", {}, value)]));
  }

  function currentItem() {
    if (!selected) return null;
    if (selected.draft) return selected.draft;
    return index[selected.collection].get(selected.id) || null;
  }

  function renderInspector(options = {}) {
    const item = currentItem();
    if (!item) {
      inspectorEl.hidden = true;
      return;
    }
    const collection = selected.collection;
    const nodes = CAN_EDIT ? editorNodes(collection, item) : viewerNodes(collection, item);
    inspectorEl.replaceChildren(...nodes);
    inspectorEl.hidden = false;
    if (options.focusName) {
      const field = inspectorEl.querySelector('[name="name"], [name="title"]');
      if (field) {
        field.focus();
        field.select();
      }
    }
  }

  function viewerNodes(collection, item) {
    if (collection === "units") {
      const faction = factionOf(item.faction);
      return [
        inspectorHead(`${faction.name} · ${UNIT_TYPES[item.type]}`, item.name, symbolSvg(item, faction)),
        facts([
          ["Faction", factionFact(item.faction)],
          ["Type", UNIT_TYPES[item.type]],
          item.echelon ? ["Size", ECHELONS[item.echelon]] : null,
          ["Status", h("span", { class: "wm-status-dot", "data-status": item.status, text: UNIT_STATUSES[item.status] })],
          item.status !== "destroyed" ? ["Strength", [h("span", { class: "wm-strength", style: `--wm-strength:${strengthColor(item.strength)}` }, h("i", { style: `width:${item.strength}%` })), `${item.strength}%`]] : null,
          ["Position", h("span", { class: "wm-coord", text: fmtLatLng(item.lat, item.lng) })],
        ]),
        item.notes ? h("p", { class: "wm-notes", text: item.notes }) : null,
      ].filter(Boolean);
    }
    if (collection === "zones" || collection === "lines") {
      const kinds = collection === "zones" ? ZONE_KINDS : LINE_KINDS;
      const measure = collection === "zones" ? ["Area", `${Math.round(polygonAreaKm2(item.points)).toLocaleString()} km²`] : ["Length", fmtKm(pathLengthKm(item.points))];
      return [
        inspectorHead(kinds[item.kind], item.name),
        facts([["Faction", factionFact(item.faction)], measure]),
        item.notes ? h("p", { class: "wm-notes", text: item.notes }) : null,
      ].filter(Boolean);
    }
    const spec = EVENT_KINDS[item.kind] || EVENT_KINDS.report;
    return [
      inspectorHead(`SITREP · ${spec.label}`, item.title),
      facts([
        ["Filed", `${zulu(item.ts)} (${relTime(item.ts)})`],
        item.author ? ["By", item.author] : null,
        item.lat != null ? ["Location", h("span", { class: "wm-coord", text: fmtLatLng(item.lat, item.lng) })] : null,
      ]),
      item.body ? h("p", { class: "wm-notes", text: item.body }) : null,
    ].filter(Boolean);
  }

  // ---------- editor forms ----------

  function selectInput(name, options, value) {
    return h("select", { name }, Object.entries(options).map(([key, label]) => h("option", { value: key, selected: key === value }, label)));
  }

  function factionSelect(name, value) {
    const options = {};
    factionList().forEach((faction) => { options[faction.id] = faction.name; });
    if (value && !options[value]) options[value] = "Deleted faction";
    if (!value) options[""] = "Unaligned";
    return selectInput(name, options, value);
  }

  function field(label, control) {
    return h("label", { class: "wm-field" }, h("span", { text: label }), control);
  }

  function editorNodes(collection, item) {
    const isDraft = Boolean(selected.draft);
    const form = h("form", { class: "wm-inspector-form", style: "display:grid;gap:12px", novalidate: true });
    const markDirty = () => { inspectorDirty = true; };
    form.addEventListener("input", markDirty);
    form.addEventListener("change", markDirty);

    let head;
    let body = [];
    let extra = [];
    if (collection === "units") {
      const faction = factionOf(item.faction);
      head = inspectorHead(`Unit · ${faction.short}`, item.name, symbolSvg(item, faction));
      const strengthOut = h("output", { text: `${item.strength}%` });
      const strength = h("input", { type: "range", name: "strength", min: "0", max: "100", step: "5", value: String(item.strength) });
      strength.addEventListener("input", () => { strengthOut.textContent = `${strength.value}%`; });
      body = [
        field("Name", h("input", { type: "text", name: "name", value: item.name, maxlength: "60", required: true })),
        h("div", { class: "wm-row" }, field("Faction", factionSelect("faction", item.faction)), field("Type", selectInput("type", UNIT_TYPES, item.type))),
        h("div", { class: "wm-row" }, field("Size", selectInput("echelon", ECHELONS, item.echelon)), field("Status", selectInput("status", UNIT_STATUSES, item.status))),
        h("label", { class: "wm-field" }, h("span", {}, "Strength ", strengthOut), strength),
        field("Notes", h("textarea", { name: "notes", maxlength: "600", rows: "3" }, item.notes)),
      ];
      extra = [h("p", { class: "wm-inspector__note" }, h("span", { class: "wm-coord", text: fmtLatLng(item.lat, item.lng) }), " — drag the marker to reposition.")];
    } else if (collection === "zones" || collection === "lines") {
      const kinds = collection === "zones" ? ZONE_KINDS : LINE_KINDS;
      head = inspectorHead(kinds[item.kind], item.name);
      body = [
        field("Name", h("input", { type: "text", name: "name", value: item.name, maxlength: "60", required: true })),
        h("div", { class: "wm-row" }, field("Faction", factionSelect("faction", item.faction)), field("Kind", selectInput("kind", kinds, item.kind))),
        field("Notes", h("textarea", { name: "notes", maxlength: "600", rows: "3" }, item.notes)),
      ];
      const measure = collection === "zones" ? `${Math.round(polygonAreaKm2(item.points)).toLocaleString()} km²` : fmtKm(pathLengthKm(item.points));
      extra = [h("p", { class: "wm-inspector__note", text: `${measure} · drag the white handles to reshape, drag a small dot to add a corner, double-click a handle to remove it.` })];
      if (collection === "lines") {
        extra.push(h("div", {}, h("button", {
          type: "button",
          class: "wm-btn wm-btn--small",
          onclick: () => sendOps([{ op: "upsert", collection: "lines", item: { id: item.id, points: item.points.slice().reverse() } }]).catch(() => {}),
        }, "Reverse direction")));
      }
    } else {
      const spec = EVENT_KINDS[item.kind] || EVENT_KINDS.report;
      head = inspectorHead(isDraft ? "New SITREP" : `SITREP · ${spec.label}`, isDraft ? "Situation report" : item.title);
      const kindOptions = {};
      Object.entries(EVENT_KINDS).forEach(([key, value]) => { kindOptions[key] = value.label; });
      const location = h("span", { class: "wm-coord", text: item.lat != null ? fmtLatLng(item.lat, item.lng) : "No map location" });
      body = [
        field("Kind", selectInput("kind", kindOptions, item.kind)),
        field("Headline", h("input", { type: "text", name: "title", value: isDraft ? "" : item.title, maxlength: "90", placeholder: "e.g. Armored push breaks through north of the river", required: true })),
        field("Report", h("textarea", { name: "body", maxlength: "1200", rows: "5", placeholder: "What happened, who was involved, what changed." }, item.body || "")),
      ];
      extra = [
        h("div", { class: "wm-field" }, h("span", { text: "Location" }), location,
          h("div", { style: "display:flex;gap:6px;flex-wrap:wrap" },
            h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: () => pickEventLocation(location) }, item.lat != null ? "Move on map" : "Pick on map"),
            item.lat != null ? h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: () => setEventLocation(null, location) }, "Remove location") : null)),
        isDraft ? null : h("p", { class: "wm-inspector__note", text: `Filed ${zulu(item.ts)}${item.author ? ` by ${item.author}` : ""}` }),
      ].filter(Boolean);
    }

    const saveLabel = isDraft ? "Post SITREP" : "Save";
    const actions = h("div", { class: "wm-inspector__actions" },
      h("button", { type: "submit", class: "wm-btn wm-btn--accent" }, saveLabel),
      isDraft ? h("button", { type: "button", class: "wm-btn", onclick: () => closeInspector(true) }, "Cancel")
        : h("button", { type: "button", class: "wm-btn wm-btn--danger", onclick: () => deleteSelected() }, "Delete"));
    form.append(...body, ...extra, actions);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      saveInspector(form, collection, item, isDraft);
    });
    return [head, form];
  }

  function formValues(form) {
    const values = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      values[el.name] = el.type === "range" ? Number(el.value) : el.value;
    }
    return values;
  }

  async function saveInspector(form, collection, item, isDraft) {
    const values = formValues(form);
    const nameKey = collection === "events" ? "title" : "name";
    if (!String(values[nameKey] || "").trim()) {
      toast(collection === "events" ? "Give the report a headline." : "Give it a name.", "error");
      const input = form.querySelector(`[name="${nameKey}"]`);
      if (input) input.focus();
      return;
    }
    const patch = Object.assign({ id: item.id }, values);
    if (collection === "events") {
      const current = selected.draft || index.events.get(item.id) || item;
      patch.lat = current.lat;
      patch.lng = current.lng;
      if (isDraft) myEventIds.add(item.id);
    }
    const submit = form.querySelector('[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      await sendOps([{ op: "upsert", collection, item: patch }]);
      inspectorDirty = false;
      if (isDraft) {
        seenEvents.add(item.id);
        select("events", item.id);
        toast("SITREP posted.");
      } else {
        renderInspector();
        toast("Saved.");
      }
    } catch (_err) {
      if (submit) submit.disabled = false;
    }
  }

  async function deleteSelected() {
    const item = currentItem();
    if (!item || selected.draft) return;
    const label = item.name || item.title;
    if (!window.confirm(`Delete ${COLLECTION_LABEL[selected.collection].toLowerCase()} "${label}"? This cannot be undone.`)) return;
    const { collection, id } = selected;
    inspectorDirty = false;
    closeInspector(true);
    try {
      await sendOps([{ op: "delete", collection, id }]);
      toast(`${COLLECTION_LABEL[collection]} deleted.`);
    } catch (_err) { /* error already shown */ }
  }

  // ---------- SITREP drafts ----------

  let eventDraftMarker = null;

  function removeEventDraft() {
    if (eventDraftMarker) {
      draftLayer.removeLayer(eventDraftMarker);
      eventDraftMarker = null;
    }
  }

  function showEventDraftMarker(item) {
    removeEventDraft();
    if (item.lat == null) return;
    eventDraftMarker = L.marker([item.lat, item.lng], { icon: eventIcon(item, "is-draft is-recent"), pane: "wm-events", interactive: false }).addTo(draftLayer);
  }

  function openEventDraft(latlng) {
    if (!CAN_EDIT) return;
    if (inspectorDirty && !window.confirm("Discard unsaved changes?")) return;
    const draftItem = { id: newId("e"), kind: toolOpts.eventKind, title: "", body: "", lat: latlng ? latlng.lat : null, lng: latlng ? latlng.lng : null, ts: new Date().toISOString() };
    const previous = selected;
    selected = { collection: "events", id: draftItem.id, draft: draftItem };
    inspectorDirty = false;
    handleLayer.clearLayers();
    if (previous && !previous.draft) rerenderItem(previous.collection, previous.id);
    showEventDraftMarker(draftItem);
    renderInspector({ focusName: true });
    if (tool === "event") setTool("select");
  }

  function setEventLocation(latlng, locationEl) {
    const item = currentItem();
    if (!item) return;
    if (selected.draft) {
      item.lat = latlng ? latlng.lat : null;
      item.lng = latlng ? latlng.lng : null;
      showEventDraftMarker(item);
      rerenderInspectorKeepingForm();
      return;
    }
    sendOps([{ op: "upsert", collection: "events", item: { id: item.id, lat: latlng ? latlng.lat : null, lng: latlng ? latlng.lng : null } }]).catch(() => {});
    if (locationEl) locationEl.textContent = latlng ? fmtLatLng(latlng.lat, latlng.lng) : "No map location";
  }

  function rerenderInspectorKeepingForm() {
    const before = inspectorEl.querySelector("form");
    const values = before ? formValues(before) : null;
    const wasDirty = inspectorDirty;
    renderInspector();
    const after = inspectorEl.querySelector("form");
    if (!values || !after) return;
    for (const [name, value] of Object.entries(values)) {
      const el = after.elements.namedItem(name);
      if (el && "value" in el) el.value = value;
    }
    inspectorDirty = wasDirty;
  }

  function pickEventLocation(locationEl) {
    locationEl.textContent = "Click the map…";
    mapEl.classList.add("is-placing");
    pickHandler = (latlng) => {
      mapEl.classList.toggle("is-placing", tool === "unit" || tool === "event");
      setEventLocation(latlng, locationEl);
    };
  }

  // ---------- shape vertex handles ----------

  const handleIcon = L.divIcon({ className: "wm-handle-icon", html: '<div class="wm-handle"></div>', iconSize: [14, 14], iconAnchor: [7, 7] });
  const midIcon = L.divIcon({ className: "wm-handle-icon", html: '<div class="wm-handle wm-handle--mid"></div>', iconSize: [14, 14], iconAnchor: [7, 7] });

  function replaceShapeLayer(collection, item, points) {
    const entry = rendered[collection].get(item.id);
    if (!entry) return;
    groups[collection].removeLayer(entry.layer);
    entry.layer = collection === "zones" ? createZoneLayer(item, points) : createLineLayer(item, points);
    entry.sig = "";
    entry.dragging = true;
    groups[collection].addLayer(entry.layer);
  }

  function commitPoints(collection, item, points) {
    const entry = rendered[collection].get(item.id);
    if (entry) entry.dragging = false;
    busy = false;
    deferredState = null;
    sendOps([{ op: "upsert", collection, item: { id: item.id, points: points.map((p) => [p.lat, p.lng]) } }]).catch(() => {});
  }

  function refreshHandles() {
    handleLayer.clearLayers();
    if (!CAN_EDIT || !selected || selected.draft) return;
    const { collection, id } = selected;
    if (collection !== "zones" && collection !== "lines") return;
    const item = index[collection].get(id);
    if (!item) return;
    const closed = collection === "zones";
    const minimum = closed ? 3 : 2;
    const points = item.points.map((p) => L.latLng(p[0], p[1]));

    points.forEach((point, i) => {
      const handle = L.marker(point, { icon: handleIcon, draggable: true, pane: "wm-handles", keyboard: false, title: "Drag to move · double-click to remove" });
      handle.on("dragstart", () => { busy = true; });
      handle.on("drag", (e) => {
        points[i] = e.target.getLatLng();
        replaceShapeLayer(collection, item, points);
      });
      handle.on("dragend", () => commitPoints(collection, item, points));
      handle.on("dblclick", (e) => {
        L.DomEvent.stop(e);
        if (points.length <= minimum) {
          toast(`A ${closed ? "zone" : "line"} needs at least ${minimum} points.`);
          return;
        }
        points.splice(i, 1);
        commitPoints(collection, item, points);
      });
      handle.on("click", (e) => L.DomEvent.stop(e));
      handleLayer.addLayer(handle);
    });

    const segments = closed ? points.length : points.length - 1;
    for (let i = 0; i < segments; i += 1) {
      const a = points[i];
      const b = points[(i + 1) % points.length];
      const mid = L.latLng((a.lat + b.lat) / 2, (a.lng + b.lng) / 2);
      const handle = L.marker(mid, { icon: midIcon, draggable: true, pane: "wm-handles", keyboard: false, title: "Drag to add a corner" });
      let inserted = false;
      handle.on("dragstart", () => {
        busy = true;
        points.splice(i + 1, 0, handle.getLatLng());
        inserted = true;
      });
      handle.on("drag", (e) => {
        if (!inserted) return;
        points[i + 1] = e.target.getLatLng();
        replaceShapeLayer(collection, item, points);
      });
      handle.on("dragend", () => commitPoints(collection, item, points));
      handle.on("click", (e) => L.DomEvent.stop(e));
      handleLayer.addLayer(handle);
    }
  }

  // -------------------------------------------------------------------------
  // Admin tools
  // -------------------------------------------------------------------------

  const draft = { points: [], line: null, rubber: null, dots: [] };

  function clearDraft() {
    draft.points = [];
    draftLayer.clearLayers();
    draft.line = null;
    draft.rubber = null;
    draft.dots = [];
    eventDraftMarker = null;
    if (selected && selected.draft) showEventDraftMarker(selected.draft);
    map.doubleClickZoom.enable();
    if (tool === "zone" || tool === "line") renderToolOptions();
  }

  function draftColor() {
    return factionOf(toolOpts.faction).color;
  }

  function redrawDraft() {
    const color = draftColor();
    if (draft.line) draftLayer.removeLayer(draft.line);
    draft.dots.forEach((dot) => draftLayer.removeLayer(dot));
    draft.dots = [];
    const opts = { renderer: draftRenderer, color, weight: 3, dashArray: "6 6", interactive: false };
    if (tool === "zone" && draft.points.length >= 3) {
      draft.line = L.polygon(draft.points, Object.assign({ fillColor: color, fillOpacity: 0.15 }, opts)).addTo(draftLayer);
    } else {
      draft.line = L.polyline(draft.points, opts).addTo(draftLayer);
    }
    draft.points.forEach((point, i) => {
      const isFirst = i === 0 && tool === "zone";
      const dot = L.marker(point, {
        pane: "wm-draft",
        interactive: isFirst,
        keyboard: false,
        icon: L.divIcon({ className: "wm-handle-icon", html: `<div class="wm-draft-dot${isFirst ? " is-first" : ""}"></div>`, iconSize: [10, 10], iconAnchor: [5, 5] }),
      });
      if (isFirst) {
        dot.on("click", (e) => {
          L.DomEvent.stop(e);
          finishDraft();
        });
      }
      draft.dots.push(dot.addTo(draftLayer));
    });
    renderToolOptions();
  }

  function updateRubberBand(latlng) {
    if (!draft.points.length || (tool !== "zone" && tool !== "line")) return;
    const last = draft.points[draft.points.length - 1];
    const pts = tool === "zone" && draft.points.length >= 2 ? [last, latlng, draft.points[0]] : [last, latlng];
    if (draft.rubber) draft.rubber.setLatLngs(pts);
    else draft.rubber = L.polyline(pts, { renderer: draftRenderer, color: "#ffffff", weight: 1.5, dashArray: "4 6", opacity: 0.8, interactive: false }).addTo(draftLayer);
  }

  function addDraftPoint(latlng) {
    const point = latlng.wrap();
    const last = draft.points[draft.points.length - 1];
    if (last && map.latLngToContainerPoint(last).distanceTo(map.latLngToContainerPoint(point)) < 4) return;
    draft.points.push(point);
    map.doubleClickZoom.disable();
    redrawDraft();
  }

  function undoDraftPoint() {
    draft.points.pop();
    if (draft.rubber) {
      draftLayer.removeLayer(draft.rubber);
      draft.rubber = null;
    }
    if (!draft.points.length) clearDraft();
    else redrawDraft();
  }

  async function finishDraft() {
    const collection = tool === "zone" ? "zones" : "lines";
    const minimum = collection === "zones" ? 3 : 2;
    const points = draft.points.slice();
    if (points.length < minimum) {
      toast(`Add at least ${minimum} points first.`);
      return;
    }
    const faction = factionOf(toolOpts.faction);
    const kind = collection === "zones" ? toolOpts.zoneKind : toolOpts.lineKind;
    const kindLabel = (collection === "zones" ? ZONE_KINDS : LINE_KINDS)[kind];
    const id = newId(collection === "zones" ? "z" : "l");
    const item = { id, name: `${faction.short} ${kindLabel.toLowerCase()}`, faction: faction.id, kind, points: points.map((p) => [p.lat, p.lng]) };
    clearDraft();
    setTool("select");
    try {
      await sendOps([{ op: "upsert", collection, item }]);
      select(collection, id, { focusName: true });
    } catch (_err) { /* error already shown */ }
  }

  function nextUnitName(faction, type) {
    const base = `${faction.short} ${UNIT_TYPE_SHORT[type] || "Unit"}`;
    const taken = new Set(state.units.map((u) => u.name));
    let n = 1;
    while (taken.has(`${base} ${n}`)) n += 1;
    return `${base} ${n}`;
  }

  async function placeUnit(latlng) {
    const faction = factionOf(toolOpts.faction);
    const id = newId("u");
    const item = {
      id,
      name: nextUnitName(faction, toolOpts.unitType),
      faction: faction.id,
      type: toolOpts.unitType,
      echelon: toolOpts.echelon,
      status: "active",
      strength: 100,
      lat: latlng.lat,
      lng: latlng.lng,
    };
    try {
      await sendOps([{ op: "upsert", collection: "units", item }]);
      select("units", id, { focusName: window.innerWidth > 760 });
    } catch (_err) { /* error already shown */ }
  }

  function setTool(next) {
    if (!CAN_EDIT) return;
    if (draft.points.length && next !== tool) clearDraft();
    tool = next;
    pickHandler = null;
    document.querySelectorAll(".wm-tool[data-tool]").forEach((button) => {
      const active = button.dataset.tool === tool;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    mapEl.classList.toggle("is-placing", tool === "unit" || tool === "event");
    mapEl.classList.toggle("is-drawing", tool === "zone" || tool === "line");
    renderToolOptions();
  }

  function optionSelect(key, options, label) {
    const control = h("select", { "aria-label": label }, Object.entries(options).map(([value, text]) => h("option", { value, selected: toolOpts[key] === value }, text)));
    control.addEventListener("change", () => {
      toolOpts[key] = control.value;
      if (key === "faction" && draft.points.length) redrawDraft();
    });
    return control;
  }

  function renderToolOptions() {
    const box = $("wm-toolopts");
    if (!box) return;
    if (tool === "select" || !state) {
      box.hidden = true;
      box.replaceChildren();
      return;
    }
    const factionOptions = {};
    factionList().forEach((faction) => { factionOptions[faction.id] = faction.name; });
    const parts = [];
    if (tool === "unit") {
      parts.push(optionSelect("faction", factionOptions, "Faction"), optionSelect("unitType", UNIT_TYPES, "Unit type"), optionSelect("echelon", ECHELONS, "Unit size"));
      parts.push(h("span", { class: "wm-toolopts__hint" }, h("b", { text: "Click the map" }), " to deploy · Esc to stop"));
    } else if (tool === "zone" || tool === "line") {
      const kinds = tool === "zone" ? ZONE_KINDS : LINE_KINDS;
      parts.push(optionSelect("faction", factionOptions, "Faction"), optionSelect(tool === "zone" ? "zoneKind" : "lineKind", kinds, "Kind"));
      const count = draft.points.length;
      let hint;
      if (!count) hint = [h("b", { text: "Click the map" }), tool === "zone" ? " to add corners" : " to add points"];
      else if (tool === "line") hint = [`${count} point${count === 1 ? "" : "s"} · ${fmtKm(pathLengthKm(draft.points.map((p) => [p.lat, p.lng])))} · double-click or Enter to finish`];
      else hint = [`${count} corner${count === 1 ? "" : "s"} · click the first corner, double-click or Enter to close`];
      parts.push(h("span", { class: "wm-toolopts__hint" }, hint));
      if (count) {
        parts.push(
          h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: undoDraftPoint }, "Undo point"),
          h("button", { type: "button", class: "wm-btn wm-btn--small wm-btn--accent", onclick: finishDraft }, "Finish"),
          h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: clearDraft }, "Clear"));
      }
    } else if (tool === "event") {
      const kindOptions = {};
      Object.entries(EVENT_KINDS).forEach(([key, value]) => { kindOptions[key] = value.label; });
      parts.push(optionSelect("eventKind", kindOptions, "Event kind"));
      parts.push(h("span", { class: "wm-toolopts__hint" }, h("b", { text: "Click the map" }), " where it happened"));
    }
    parts.push(h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: () => setTool("select") }, "Done"));
    box.replaceChildren(...parts);
    box.hidden = false;
  }

  map.on("click", (e) => {
    if (pickHandler) {
      const handler = pickHandler;
      pickHandler = null;
      handler(e.latlng.wrap());
      return;
    }
    if (!CAN_EDIT || tool === "select") {
      if (selected) closeInspector();
      return;
    }
    if (tool === "unit") placeUnit(e.latlng.wrap());
    else if (tool === "zone" || tool === "line") addDraftPoint(e.latlng);
    else if (tool === "event") openEventDraft(e.latlng.wrap());
  });

  map.on("dblclick", (e) => {
    if (draft.points.length && (tool === "zone" || tool === "line")) {
      L.DomEvent.stop(e);
      finishDraft();
    }
  });

  // Markers don't pass double-clicks to the map, so finish drawings from them too.
  function finishDraftFromMarker(e) {
    if (draft.points.length && (tool === "zone" || tool === "line")) {
      L.DomEvent.stop(e);
      finishDraft();
    }
  }

  if (CAN_EDIT) {
    document.querySelectorAll(".wm-tool[data-tool]").forEach((button) => button.addEventListener("click", () => setTool(button.dataset.tool)));
    const postButton = $("wm-post-sitrep");
    if (postButton) postButton.addEventListener("click", () => openEventDraft(null));
    const settingsButtons = [$("wm-open-settings"), $("wm-toolbar-settings")];
    settingsButtons.forEach((button) => button && button.addEventListener("click", openSettings));
  }

  // -------------------------------------------------------------------------
  // Operation settings (admin)
  // -------------------------------------------------------------------------

  function openSettings() {
    if (!state) return;
    const dialog = $("wm-settings");
    const meta = state.meta;
    let pendingView; // undefined = unchanged, null = cleared, object = new view

    const viewText = h("span", { class: "wm-coord" });
    const describeView = () => {
      const view = pendingView === undefined ? meta.view : pendingView;
      viewText.textContent = view ? `${fmtLatLng(view.lat, view.lng)} · zoom ${view.zoom}` : "Auto-fit to everything on the map";
    };
    describeView();

    const factionRows = h("div", { style: "display:grid;gap:8px" });
    const addFactionRow = (faction) => {
      const row = h("div", { class: "wm-faction-edit", "data-id": faction.id },
        h("input", { type: "color", name: "color", value: faction.color, "aria-label": "Colour" }),
        h("input", { type: "text", name: "name", value: faction.name, maxlength: "48", placeholder: "Faction name", "aria-label": "Name" }),
        h("input", { type: "text", name: "short", value: faction.short, maxlength: "6", placeholder: "TAG", "aria-label": "Short tag" }),
        selectInput("stance", STANCES, faction.stance),
        h("button", {
          type: "button",
          class: "wm-icon-btn",
          "aria-label": `Remove ${faction.name}`,
          title: "Remove faction",
          svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
          onclick: () => {
            if (factionRows.children.length <= 1) {
              toast("Keep at least one faction.", "error");
              return;
            }
            const used = state.units.some((u) => u.faction === faction.id) || state.zones.some((z) => z.faction === faction.id) || state.lines.some((l) => l.faction === faction.id);
            if (used && !window.confirm(`${faction.name} still has forces on the map. They will show as "Deleted faction" until reassigned. Remove it?`)) return;
            row.remove();
          },
        }));
      factionRows.append(row);
    };
    state.factions.forEach(addFactionRow);

    const threatPick = h("div", { class: "wm-threat-pick", role: "radiogroup", "aria-label": "Threat level" },
      [1, 2, 3, 4, 5].map((level) => h("label", {},
        h("input", { type: "radio", name: "threatLevel", value: String(level), checked: meta.threatLevel === level }),
        h("span", { text: `${level} ${THREAT_LABELS[level]}` }))));

    const importInput = h("input", { type: "file", accept: "application/json,.json", hidden: true });
    importInput.addEventListener("change", () => {
      const file = importInput.files && importInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        let parsed;
        try {
          parsed = JSON.parse(String(reader.result));
        } catch (_err) {
          toast("That file is not valid JSON.", "error");
          return;
        }
        if (!window.confirm("Replace the entire war map with the imported file? Everything currently on the map will be overwritten.")) return;
        sendOps([{ op: "replace", state: parsed }]).then(() => {
          dialog.close();
          closeInspector(true);
          fitTheatre(true);
          toast("War map imported.");
        }).catch(() => {});
      };
      reader.readAsText(file);
      importInput.value = "";
    });

    const clearButton = (collection, label) => h("button", {
      type: "button",
      class: "wm-btn wm-btn--danger wm-btn--small",
      onclick: () => {
        const count = state[collection].length;
        if (!count) {
          toast(`No ${label.toLowerCase()} to clear.`);
          return;
        }
        if (!window.confirm(`Remove all ${count} ${label.toLowerCase()} from the map? This cannot be undone.`)) return;
        closeInspector(true);
        sendOps([{ op: "clear", collection }]).then(() => toast(`${label} cleared.`)).catch(() => {});
      },
    }, `Clear ${label.toLowerCase()}`);

    const form = h("form", { method: "dialog", novalidate: true },
      h("div", { class: "wm-dialog__head" },
        h("h2", { id: "wm-settings-title", text: "Operation settings" }),
        h("button", { type: "button", class: "wm-icon-btn", "aria-label": "Close", onclick: () => dialog.close(), svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' })),
      h("div", { class: "wm-row" },
        field("Operation name", h("input", { type: "text", name: "operation", value: meta.operation, maxlength: "60" })),
        field("Theatre", h("input", { type: "text", name: "theatre", value: meta.theatre, maxlength: "60", placeholder: "e.g. Eastern Europe" }))),
      field("Briefing", h("textarea", { name: "summary", maxlength: "600", rows: "4", placeholder: "Who is fighting whom, and why. Shown to every viewer in the Brief tab." }, meta.summary)),
      h("div", { class: "wm-row" },
        field("War status", selectInput("status", WAR_STATUSES, meta.status)),
        field("War started (Day 1)", h("input", { type: "date", name: "warStart", value: meta.warStart }))),
      h("div", { class: "wm-field" }, h("span", { text: "Threat level" }), threatPick),
      h("section", {},
        h("h3", { text: "Starting view" }),
        h("p", { class: "wm-inspector__note" }, "Viewers open the map at: ", viewText),
        h("div", { class: "wm-data-actions" },
          h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: () => {
            const center = map.containerPointToLatLng(map.getSize().divideBy(2).add([panelOffset(), 0])).wrap();
            pendingView = { lat: Number(center.lat.toFixed(5)), lng: Number(center.lng.toFixed(5)), zoom: Math.round(map.getZoom() * 100) / 100 };
            describeView();
          } }, "Use current view"),
          h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: () => { pendingView = null; describeView(); } }, "Auto-fit instead"))),
      h("section", {},
        h("h3", { text: "Factions" }),
        factionRows,
        h("div", {}, h("button", {
          type: "button",
          class: "wm-btn wm-btn--small",
          onclick: () => {
            if (factionRows.children.length >= 12) {
              toast("Twelve factions is the limit.", "error");
              return;
            }
            addFactionRow({ id: newId("f"), name: "New Faction", short: "NEW", color: "#a855f7", stance: "unknown" });
          },
        }, "Add faction"))),
      h("section", {},
        h("h3", { text: "Data" }),
        h("div", { class: "wm-data-actions" },
          h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: exportState }, "Export JSON"),
          h("button", { type: "button", class: "wm-btn wm-btn--small", onclick: () => importInput.click() }, "Import JSON"),
          importInput),
        h("div", { class: "wm-data-actions" },
          clearButton("units", "Units"),
          clearButton("zones", "Zones"),
          clearButton("lines", "Lines"),
          clearButton("events", "SITREPs"))),
      h("div", { class: "wm-dialog__foot" },
        h("button", { type: "button", class: "wm-btn", onclick: () => dialog.close() }, "Cancel"),
        h("button", { type: "submit", class: "wm-btn wm-btn--accent", value: "save" }, "Save changes")));

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const values = formValues(form);
      const patch = {
        operation: values.operation,
        theatre: values.theatre,
        summary: values.summary,
        status: values.status,
        warStart: values.warStart,
        threatLevel: Number((form.querySelector('input[name="threatLevel"]:checked') || {}).value || meta.threatLevel),
      };
      if (pendingView !== undefined) patch.view = pendingView;
      const ops = [{ op: "meta", patch }];
      const keptIds = new Set();
      factionRows.querySelectorAll(".wm-faction-edit").forEach((row) => {
        const id = row.dataset.id;
        keptIds.add(id);
        ops.push({
          op: "upsert",
          collection: "factions",
          item: {
            id,
            name: row.querySelector('[name="name"]').value,
            short: row.querySelector('[name="short"]').value,
            color: row.querySelector('[name="color"]').value,
            stance: row.querySelector('[name="stance"]').value,
          },
        });
      });
      state.factions.filter((f) => !keptIds.has(f.id)).forEach((f) => ops.push({ op: "delete", collection: "factions", id: f.id }));
      sendOps(ops).then(() => {
        dialog.close();
        toast("Operation settings saved.");
      }).catch(() => {});
    });

    dialog.replaceChildren(form);
    dialog.showModal();
  }

  function exportState() {
    if (!state) return;
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const slug = (state.meta.operation || "war-map").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const link = h("a", { href: url, download: `wasp-${slug || "war-map"}-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // -------------------------------------------------------------------------
  // Layers popover + legend
  // -------------------------------------------------------------------------

  const layersBtn = $("wm-layers-btn");
  const layersBox = $("wm-layers");

  function renderLayersBox() {
    const check = (key, label) => {
      const input = h("input", { type: "checkbox", checked: Boolean(prefs[key]) });
      input.addEventListener("change", () => {
        prefs[key] = input.checked;
        savePrefs();
        if (key === "labels") applyBasemap();
        else if (key === "destroyed") renderLayers();
        else applyLayerVisibility();
      });
      return h("label", {}, input, label);
    };
    const bases = Object.entries(basemaps).map(([key, spec]) => {
      const input = h("input", { type: "radio", name: "wm-base", value: key, checked: prefs.base === key });
      input.addEventListener("change", () => {
        prefs.base = key;
        savePrefs();
        applyBasemap();
      });
      return h("label", {}, input, spec.label);
    });
    layersBox.replaceChildren(
      h("fieldset", {}, h("legend", { text: "Basemap" }), bases, check("labels", "Borders & place names")),
      h("fieldset", {}, h("legend", { text: "Overlays" }),
        check("units", "Units"), check("unitLabels", "Unit names"), check("destroyed", "Destroyed units"),
        check("zones", "Zones"), check("lines", "Fronts & routes"), check("events", "Events")));
  }

  layersBtn.addEventListener("click", () => {
    const open = layersBox.hidden;
    if (open) renderLayersBox();
    layersBox.hidden = !open;
    layersBtn.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", (e) => {
    if (!layersBox.hidden && !$("wm-mapctl").contains(e.target)) {
      layersBox.hidden = true;
      layersBtn.setAttribute("aria-expanded", "false");
    }
  });

  function renderLegend() {
    const sample = (type, stance, color) => symbolSvg({ type, echelon: "", status: "active" }, { color, stance });
    const item = (svg, label) => h("div", { class: "wm-legend__item" }, h("span", { svg }), h("span", { text: label }));
    const frames = h("div", { class: "wm-legend__group" }, h("h5", { text: "Frame = stance" }),
      item(sample("", "friendly", "#3b82f6"), "Friendly"),
      item(sample("", "hostile", "#ef4444"), "Hostile"),
      item(sample("", "neutral", "#22c55e"), "Neutral"),
      item(sample("", "unknown", "#facc15"), "Unknown"));
    const types = h("div", { class: "wm-legend__group" }, h("h5", { text: "Symbol = unit type" }),
      Object.entries(UNIT_TYPES).map(([type, label]) => item(sample(type, "friendly", "#64748b"), label)));
    const lineSample = (kind) => {
      const dash = { front: "", advance: "", supply: "6 4", border: "1 5" }[kind];
      const head = kind === "advance" ? '<path d="M26 5L18 1L20 5L18 9Z" fill="#e5e7eb"/>' : "";
      return `<svg class="wm-legend__line" viewBox="0 0 26 10" aria-hidden="true"><path d="M1 5H${kind === "advance" ? 19 : 25}" stroke="#e5e7eb" stroke-width="${kind === "front" || kind === "advance" ? 3 : 2}" stroke-dasharray="${dash}" stroke-linecap="round" fill="none"/>${head}</svg>`;
    };
    const lines = h("div", { class: "wm-legend__group" }, h("h5", { text: "Lines" }),
      Object.entries(LINE_KINDS).map(([kind, label]) => item(lineSample(kind), label)));
    const zoneSample = (kind) => {
      const dash = { control: "", contested: "4 3", exclusion: "1 3", objective: "5 3" }[kind];
      const color = kind === "objective" ? "#facc15" : "#e5e7eb";
      return `<svg class="wm-legend__line" viewBox="0 0 26 10" aria-hidden="true"><rect x="1" y="1" width="24" height="8" rx="1" fill="${color}" fill-opacity="${kind === "control" ? 0.35 : 0.15}" stroke="${color}" stroke-width="1.5" stroke-dasharray="${dash}"/></svg>`;
    };
    const zones = h("div", { class: "wm-legend__group" }, h("h5", { text: "Zones" }),
      Object.entries(ZONE_KINDS).map(([kind, label]) => item(zoneSample(kind), label)));
    const events = h("div", { class: "wm-legend__group" }, h("h5", { text: "Events" }),
      Object.entries(EVENT_KINDS).map(([kind, spec]) => h("div", { class: "wm-legend__item" },
        h("span", { class: "wm-event", style: `--wm-kind:${spec.color};width:22px;height:22px`, svg: eventIconSvg(kind) }),
        h("span", { text: spec.label }))));
    $("wm-legend-body").replaceChildren(frames, types, lines, zones, events);
  }

  // -------------------------------------------------------------------------
  // Toasts, clock, fullscreen, keyboard
  // -------------------------------------------------------------------------

  function toast(content, kind, onClick, duration) {
    const node = h("div", { class: `wm-toast${kind ? ` wm-toast--${kind}` : ""}` }, content);
    if (onClick) {
      node.setAttribute("role", "button");
      node.tabIndex = 0;
      node.addEventListener("click", () => {
        onClick();
        node.remove();
      });
    }
    const box = $("wm-toasts");
    box.append(node);
    while (box.children.length > 4) box.firstElementChild.remove();
    window.setTimeout(() => node.remove(), duration || (kind === "error" ? 6000 : 3000));
  }

  function tick() {
    const now = new Date();
    $("wm-clock").textContent = `${now.toISOString().slice(11, 19)}Z`;
    refreshLive();
  }
  window.setInterval(tick, 1000);
  tick();
  // Relative times ("5m ago"), event pulse age and the war day drift: refresh them each minute.
  window.setInterval(() => {
    if (!state) return;
    renderBrief();
    renderFeed();
    renderDay();
    renderLayers();
  }, 60000);

  $("wm-fullscreen").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => toast("Fullscreen isn't available here."));
  });

  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
    const dialog = $("wm-settings");
    if (dialog && dialog.open) return;
    if (e.key === "Escape") {
      if (typing) {
        target.blur();
        return;
      }
      if (pickHandler) {
        pickHandler = null;
        mapEl.classList.toggle("is-placing", tool === "unit" || tool === "event");
        rerenderInspectorKeepingForm();
      } else if (draft.points.length) clearDraft();
      else if (tool !== "select") setTool("select");
      else if (selected) closeInspector();
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (draft.points.length && e.key === "Enter") {
      e.preventDefault();
      finishDraft();
      return;
    }
    if (draft.points.length && e.key === "Backspace") {
      e.preventDefault();
      undoDraftPoint();
      return;
    }
    const key = e.key.toLowerCase();
    if (key === "f") fitTheatre(true);
    if (!CAN_EDIT) return;
    const tools = { v: "select", u: "unit", z: "zone", l: "line", e: "event" };
    if (tools[key]) setTool(tools[key]);
  });

  // -------------------------------------------------------------------------
  // Boot
  // -------------------------------------------------------------------------

  applyBasemap();
  applyLayerVisibility();
  renderLegend();
  refreshLive();
  if (CAN_VIEW) poll();
})();
