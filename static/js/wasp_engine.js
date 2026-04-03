import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";
import {
    createEntityManager,
    createMapLoader,
    createCameraController,
    createStarLayer,
    createGlobeRuntime,
    latLonToVector3,
} from "./wasp/index.js?v=20260403m";

const container = document.getElementById("map-container");

if (!container) {
    throw new Error("W.A.S.P map container was not found.");
}

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x030812);
scene.fog = new THREE.Fog(0x030812, 180, 560);

const entityManager = createEntityManager();
const units = entityManager.units;
const mapLoader = createMapLoader();
let mapStateEtag = null;
let isApplyingRemoteState = false;
let hasPendingLocalChanges = false;
let isPersistingSharedState = false;
let queuedPersistRequest = false;
let queuedRemoteState = null;
let localStateRevision = 0;
let syncFailureCount = 0;
let syncTimerId = null;
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let spawnPosition = null;
const pointerDownPosition = { x: 0, y: 0 };
let pointerDownStartedOnMap = false;
const rightPointerDownPosition = { x: 0, y: 0 };
let rightPointerDownStartedOnMap = false;
const CLICK_DRAG_TOLERANCE_PX = 12;
const KEYBOARD_MOVE_SPEED_UNITS_PER_SECOND = 80;
const KEYBOARD_FAST_MOVE_MULTIPLIER = 1.8;
const KEYBOARD_MOVE_KEYS = {
    KeyW: new THREE.Vector2(0, 1),
    ArrowUp: new THREE.Vector2(0, 1),
    KeyS: new THREE.Vector2(0, -1),
    ArrowDown: new THREE.Vector2(0, -1),
    KeyA: new THREE.Vector2(-1, 0),
    ArrowLeft: new THREE.Vector2(-1, 0),
    KeyD: new THREE.Vector2(1, 0),
    ArrowRight: new THREE.Vector2(1, 0),
};
const activeMoveKeys = new Set();
const keyboardMoveDirection = new THREE.Vector2();
const keyboardForwardVector = new THREE.Vector3();
const keyboardRightVector = new THREE.Vector3();
const keyboardMoveOffset = new THREE.Vector3();
const keyboardClock = new THREE.Clock();

let selectedUnit = null;
let placingUnitType = null;
let placingUnitCategory = "infantry";
let isMoveMode = false;
let suppressUnitPanelSync = false;
let isDraggingSelectedUnit = false;
let hasDraggedSelectedUnit = false;
let isSnapToGridEnabled = false;
const GRID_SNAP_SIZE = 5;
let syncStatusTimerId = null;
const MAX_HISTORY_ENTRIES = 40;
const undoHistory = [];
const redoHistory = [];
let isApplyingHistorySnapshot = false;
let unitSearchCursor = -1;
let terrainPointCloud = null;
let terrainTick = 0;
let hudTick = 0;
let fpsAccumulator = 0;
let fpsFrameCount = 0;
let renderTier = "high";
const tacticalOverlayGroup = new THREE.Group();
tacticalOverlayGroup.name = "tactical-overlays";
scene.add(tacticalOverlayGroup);
const tacticalLayerGroups = {
    SIGINT: new THREE.Group(),
    SAT: new THREE.Group(),
    THREAT: new THREE.Group(),
    BLUE_FORCE: new THREE.Group(),
    JAMMED: new THREE.Group(),
};
Object.entries(tacticalLayerGroups).forEach(([name, group]) => {
    group.name = `tactical-${name.toLowerCase()}`;
    tacticalOverlayGroup.add(group);
});
const overlayVisibility = {
    SIGINT: true,
    SAT: true,
    THREAT: true,
    BLUE_FORCE: true,
    JAMMED: true,
};
let tacticalOverlaySignature = null;
let tacticalOverlayTick = 0;
const tacticalPulseTargets = [];
const planningGroup = new THREE.Group();
planningGroup.name = "planning-layer";
scene.add(planningGroup);
const planningObjects = {
    routes: [],
    zones: [],
    annotations: [],
};
let planningVersion = 0;
let planningEtag = null;
let planningSaveTimerId = null;
let isSavingPlanningState = false;
let pendingPlanningSave = false;
let selectedPlanningObjectId = "";
let selectedPlanningObjectType = "";
let planningMode = "none";
let planningDrawDraft = [];
const countryDrilldownGroup = new THREE.Group();
countryDrilldownGroup.name = "country-drilldown";
scene.add(countryDrilldownGroup);
const cityMarkerGroup = new THREE.Group();
cityMarkerGroup.name = "country-city-markers";
countryDrilldownGroup.add(cityMarkerGroup);
const cityLabelGroup = new THREE.Group();
cityLabelGroup.name = "country-city-labels";
countryDrilldownGroup.add(cityLabelGroup);
const cityMarkerTargets = [];
const countryDrilldownCache = new Map();
const countryStatusEtags = new Map();
let activeCountryDrilldownIso3 = "";
let activeCountryDrilldownIso2 = "";
let activeCountryDrilldownName = "";
let activeDrilldownCities = [];
let selectedCityName = "";
let drilldownFetchTimerId = null;
let drilldownLastFetchAt = 0;
let catalogCitiesBootstrapStarted = false;
const cityPopoverWorld = new THREE.Vector3();
let cityPopoverVisible = false;
const DRILLDOWN_FETCH_DEBOUNCE_MS = 300;
const DRILLDOWN_CACHE_TTL_MS = 1000 * 60 * 5;
const GLOBE_DEFAULT_MIN_DISTANCE = 260;
const GLOBE_DEFAULT_MAX_DISTANCE = 1320;
const MISSION_PHASE_ORDER = ["recon", "engagement", "extraction", "afteraction"];
let currentMissionPhase = "recon";
const spiderfyOverlayGroup = new THREE.Group();
spiderfyOverlayGroup.name = "spiderfy-overlay";
scene.add(spiderfyOverlayGroup);
const spiderfyHitTargets = [];
let spiderfySignature = null;
let spiderfyTick = 0;
const SPIDERFY_CLUSTER_RADIUS = 14;
const SPIDERFY_HEIGHT = 5.5;
let spiderfyFadeValue = 0;
let spiderfyFadeTarget = 0;
const SPIDERFY_FADE_SPEED = 0.12;
const SIM_SYNC_INTERVAL_MS = 1200;
const SIM_OUTCOME_BUCKET = ["hit", "kill", "miss"];
let lastSimulationSyncAt = 0;
let simulationTickCarry = 0;
let missions = [];
let engagements = [];
let simulationEvents = [];
let simulationRunner = {
    status: "idle",
    tick: 0,
    speed: 1,
    startedBy: "",
    startedAt: null,
    updatedAt: null,
    seed: 1,
};
let engagementTargetId = "";
let engagementFriendlyIds = [];

const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    1000,
);

camera.position.set(0, 80, 180);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.screenSpacePanning = true;
controls.minDistance = 15;
controls.maxDistance = 700;
controls.maxPolarAngle = Math.PI / 2.1;

const mapBootstrap = typeof window.WASP_MAP_BOOTSTRAP === "object" && window.WASP_MAP_BOOTSTRAP
    ? window.WASP_MAP_BOOTSTRAP
    : {};
const mapMode = String(mapBootstrap.mapMode || "globe").toLowerCase();
const canEditWaspMap = Boolean(mapBootstrap.canEditWaspMap);
const planningGuildId = typeof mapBootstrap.guildId === "string" && mapBootstrap.guildId.trim()
    ? mapBootstrap.guildId.trim()
    : "";
const cameraController = createCameraController(camera, controls, { mapMode });
let starLayer = null;
let globeRuntime = null;

/* GRID */
const grid = new THREE.GridHelper(800, 80, 0x00ffff, 0x004444);
scene.add(grid);
grid.material.opacity = 0.18;
grid.material.transparent = true;

const hemiLight = new THREE.HemisphereLight(0x8ad8ff, 0x071018, 0.36);
hemiLight.position.set(0, 200, 0);
scene.add(hemiLight);

const fillLight = new THREE.DirectionalLight(0x88c8ff, 0.22);
fillLight.position.set(140, 260, 120);
scene.add(fillLight);

if (mapMode === "galaxy") {
    scene.fog = new THREE.Fog(0x030812, 760, 3200);
    camera.far = 10000;
    camera.updateProjectionMatrix();
    camera.position.set(0, 400, 600);
    controls.target.set(0, 0, 0);
    controls.minDistance = 100;
    controls.maxDistance = 2500;
    grid.visible = false;
}
if (mapMode === "globe") {
    scene.fog = new THREE.Fog(0x030812, 320, 1200);
    camera.far = 2400;
    camera.updateProjectionMatrix();
    grid.visible = false;
    globeRuntime = createGlobeRuntime({
        THREE,
        scene,
        camera,
        controls,
        container,
    });
    void globeRuntime.loadCountryBoundaries("/static/data/world.geo.json").then(() => {
        void bootstrapCatalogCitiesLayer();
    });
}

/* SELECTION RING */
const ringGeo = new THREE.RingGeometry(3, 3.6, 32);
const ringMat = new THREE.MeshBasicMaterial({
    color: 0xb8d58b,
    side: THREE.DoubleSide,
});
const selectionRing = new THREE.Mesh(ringGeo, ringMat);
selectionRing.rotation.x = -Math.PI / 2;
selectionRing.visible = false;
scene.add(selectionRing);

const dragTargetRingGeo = new THREE.RingGeometry(3.2, 4.2, 32);
const dragTargetRingMat = new THREE.MeshBasicMaterial({
    color: 0xe2f2b8,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.85,
});
const dragTargetRing = new THREE.Mesh(dragTargetRingGeo, dragTargetRingMat);
dragTargetRing.rotation.x = -Math.PI / 2;
dragTargetRing.visible = false;
scene.add(dragTargetRing);

/* UNIT FACTORY */
const unitColors = {
    enemy: 0xff6b5f,
    friendly: 0xb8d58b,
    neutral: 0xe6d88a,
    objective: 0xe6d88a,
};

const UNIT_ICON_SCALE = 6;
const HIT_PLANE_SIZE = 12;
const LABEL_VISIBILITY_DISTANCE = 80;
const LABEL_OVERLAP_DISTANCE = 5;
const CLUSTER_RADIUS = 14;
const CLUSTER_ZOOM_THRESHOLD = 95;
const UNIT_LABEL_MAX_LENGTH = 22;
const UNIT_COUNTRY_MAX_LENGTH = 20;

function truncateLabelText(value, maxLength) {
    if (typeof value !== "string") {
        return "";
    }
    const normalized = value.trim();
    if (normalized.length <= maxLength) {
        return normalized;
    }
    return `${normalized.slice(0, Math.max(1, maxLength - 1))}…`;
}

function createIconTexture(type = "infantry") {
    const canvas = document.createElement("canvas");
    canvas.width = 192;
    canvas.height = 192;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Could not create icon texture context.");
    const cx = 96;
    const cy = 96;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.arc(cx, cy, 82, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "rgba(245, 250, 255, 0.98)";
    if (type === "aircraft") {
        ctx.beginPath();
        ctx.moveTo(96, 28);
        ctx.lineTo(116, 74);
        ctx.lineTo(162, 96);
        ctx.lineTo(116, 118);
        ctx.lineTo(96, 164);
        ctx.lineTo(76, 118);
        ctx.lineTo(30, 96);
        ctx.lineTo(76, 74);
        ctx.closePath();
        ctx.fill();
    } else if (type === "tank") {
        ctx.fillRect(44, 86, 102, 36);
        ctx.fillRect(58, 66, 66, 24);
        ctx.fillRect(120, 74, 34, 8);
        ctx.strokeStyle = "rgba(245, 250, 255, 0.95)";
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(64, 128, 8, 0, Math.PI * 2);
        ctx.arc(84, 128, 8, 0, Math.PI * 2);
        ctx.arc(104, 128, 8, 0, Math.PI * 2);
        ctx.arc(124, 128, 8, 0, Math.PI * 2);
        ctx.stroke();
    } else if (type === "missile") {
        ctx.beginPath();
        ctx.moveTo(96, 26);
        ctx.lineTo(118, 58);
        ctx.lineTo(106, 150);
        ctx.lineTo(86, 150);
        ctx.lineTo(74, 58);
        ctx.closePath();
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(74, 58);
        ctx.lineTo(52, 84);
        ctx.lineTo(80, 84);
        ctx.closePath();
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(118, 58);
        ctx.lineTo(140, 84);
        ctx.lineTo(112, 84);
        ctx.closePath();
        ctx.fill();
    } else {
        ctx.beginPath();
        ctx.arc(96, 58, 16, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillRect(84, 74, 24, 64);
        ctx.fillRect(60, 88, 18, 42);
        ctx.fillRect(114, 88, 18, 42);
        ctx.fillRect(78, 136, 16, 32);
        ctx.fillRect(98, 136, 16, 32);
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
}

function createSideRingTexture() {
    const canvas = document.createElement("canvas");
    canvas.width = 192;
    canvas.height = 192;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
        throw new Error("Could not create side ring texture context.");
    }
    const cx = 96;
    const cy = 96;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    ctx.lineWidth = 11;
    ctx.beginPath();
    ctx.arc(cx, cy, 86, 0, Math.PI * 2);
    ctx.stroke();
    return new THREE.CanvasTexture(canvas);
}

const icons = {
    aircraft: createIconTexture("aircraft"),
    tank: createIconTexture("tank"),
    infantry: createIconTexture("infantry"),
    missile: createIconTexture("missile"),
};
const sideRingTexture = createSideRingTexture();

function getIconByType(type = "") {
    return icons[type] ?? icons.infantry;
}

function resolveUnitColor(side = "enemy") {
    return unitColors[side] ?? unitColors.enemy;
}

function createUnitLabel(name, country) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    canvas.width = 384;
    canvas.height = 112;

    if (!ctx) {
        throw new Error("Could not create label context.");
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const displayName = truncateLabelText(name, UNIT_LABEL_MAX_LENGTH) || "Unknown";
    const displayCountry = truncateLabelText(country, UNIT_COUNTRY_MAX_LENGTH) || "Unknown";

    ctx.fillStyle = "rgba(5, 12, 28, 0.82)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(0, 255, 255, 0.78)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);

    ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
    ctx.font = "bold 25px Inter, Segoe UI, sans-serif";
    ctx.fillText(displayName, 12, 42);

    ctx.fillStyle = "rgba(127, 255, 212, 0.95)";
    ctx.font = "21px Inter, Segoe UI, sans-serif";
    ctx.fillText(displayCountry, 12, 82);

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;

    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
    });

    const sprite = new THREE.Sprite(material);
    sprite.scale.set(14, 4, 1);

    return sprite;
}

function updateUnitVisuals(unit) {
    if (!unit?.mesh?.material) return;
    unit.mesh.material.map = getIconByType(unit.type);
    unit.mesh.material.color.setHex(0xffffff);
    unit.mesh.material.needsUpdate = true;
    if (unit.sideRing?.material) {
        unit.sideRing.material.color.setHex(resolveUnitColor(unit.side));
        unit.sideRing.material.needsUpdate = true;
    }
}

function updateUnitEmphasisVisuals() {
    units.forEach((unit) => {
        if (!unit?.sideRing) {
            return;
        }
        const isSelected = unit === selectedUnit;
        unit.sideRing.visible = isSelected;
        if (unit.sideRing.material) {
            unit.sideRing.material.opacity = isSelected ? 0.76 : 0;
        }
        if (isSelected) {
            unit.sideRing.scale.set(UNIT_ICON_SCALE + 0.9, UNIT_ICON_SCALE + 0.9, 1);
        }
    });
}

function clearSpiderfyOverlay() {
    while (spiderfyOverlayGroup.children.length > 0) {
        const child = spiderfyOverlayGroup.children.pop();
        if (!child) {
            continue;
        }
        spiderfyOverlayGroup.remove(child);
        child.geometry?.dispose?.();
        if (child.material) {
            if (Array.isArray(child.material)) {
                child.material.forEach((material) => {
                    material.map?.dispose?.();
                    material.dispose?.();
                });
            } else {
                child.material.map?.dispose?.();
                child.material.dispose?.();
            }
        }
    }
    spiderfyHitTargets.length = 0;
}

function registerSpiderfyMaterial(material, baseOpacity) {
    if (!material) {
        return;
    }
    material.transparent = true;
    material.userData = material.userData ?? {};
    material.userData.spiderfyBaseOpacity = baseOpacity;
    material.opacity = baseOpacity * spiderfyFadeValue;
}

function applySpiderfyFadeToOverlay() {
    spiderfyOverlayGroup.children.forEach((child) => {
        const material = child.material;
        if (!material) {
            return;
        }
        if (Array.isArray(material)) {
            material.forEach((entry) => {
                const base = entry.userData?.spiderfyBaseOpacity;
                if (typeof base === "number") {
                    entry.opacity = base * spiderfyFadeValue;
                }
            });
            return;
        }
        const base = material.userData?.spiderfyBaseOpacity;
        if (typeof base === "number") {
            material.opacity = base * spiderfyFadeValue;
        }
    });
}

function getUnitThreatPriority(unit) {
    const typePriority = {
        missile: 120,
        aircraft: 95,
        tank: 72,
        infantry: 55,
    };
    const sidePriority = unit.side === "enemy" ? 100 : unit.side === "friendly" ? 45 : 20;
    return sidePriority + (typePriority[unit.type] ?? 10);
}

function createSpiderfyMarkerTexture(unit, isSelectedMarker = false) {
    const canvas = document.createElement("canvas");
    canvas.width = 96;
    canvas.height = 96;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
        return null;
    }

    const unitColor = resolveUnitColor(unit.side);
    const colorHex = `#${unitColor.toString(16).padStart(6, "0")}`;
    const typeGlyph = {
        aircraft: "A",
        tank: "T",
        infantry: "I",
        missile: "M",
    }[unit.type] ?? "?";
    const sideGlyph = unit.side === "enemy" ? "E" : unit.side === "friendly" ? "F" : "N";

    ctx.clearRect(0, 0, 96, 96);
    ctx.fillStyle = "rgba(2, 9, 18, 0.78)";
    ctx.beginPath();
    ctx.arc(48, 48, 36, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = isSelectedMarker ? "rgba(255,255,255,0.95)" : "rgba(0,255,255,0.75)";
    ctx.lineWidth = isSelectedMarker ? 7 : 4;
    ctx.beginPath();
    ctx.arc(48, 48, 33, 0, Math.PI * 2);
    ctx.stroke();

    ctx.fillStyle = colorHex;
    ctx.beginPath();
    ctx.arc(48, 48, 20, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
    ctx.font = "bold 23px Inter, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(typeGlyph, 48, 48);

    ctx.fillStyle = "rgba(159, 255, 255, 0.95)";
    ctx.font = "bold 13px Inter, Segoe UI, sans-serif";
    ctx.fillText(sideGlyph, 48, 70);

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
}

function getSpiderfyClusterUnits() {
    if (!selectedUnit?.mesh?.position) {
        return [];
    }
    const center = selectedUnit.mesh.position;
    return units.filter((unit) => unit.mesh.position.distanceTo(center) <= SPIDERFY_CLUSTER_RADIUS);
}

function buildSpiderfyOverlay() {
    const clusterUnits = getSpiderfyClusterUnits();
    if (clusterUnits.length < 2) {
        spiderfyFadeTarget = 0;
        spiderfyHitTargets.length = 0;
        return;
    }

    clearSpiderfyOverlay();
    spiderfyFadeValue = 0;
    spiderfyFadeTarget = 1;

    const orderedUnits = [...clusterUnits].sort((a, b) => {
        if (a === selectedUnit) return -1;
        if (b === selectedUnit) return 1;
        const threatDelta = getUnitThreatPriority(b) - getUnitThreatPriority(a);
        if (threatDelta !== 0) {
            return threatDelta;
        }
        return String(a.id).localeCompare(String(b.id));
    });

    const center = selectedUnit.mesh.position.clone();
    const total = orderedUnits.length;
    const dynamicRadius = Math.max(16, Math.min(40, 10 + (total * 2.6)));
    const dynamicHeight = SPIDERFY_HEIGHT + Math.min(2.4, total * 0.22);
    const markerBaseScale = Math.max(3.4, Math.min(5.2, 6 - (total * 0.12)));
    const startAngle = -Math.PI / 2;
    const angleStep = (Math.PI * 2) / total;

    orderedUnits.forEach((unit, index) => {
        const angle = startAngle + (index * angleStep);
        const markerX = center.x + (Math.cos(angle) * dynamicRadius);
        const markerZ = center.z + (Math.sin(angle) * dynamicRadius);

        const spokeGeometry = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(center.x, 0.35, center.z),
            new THREE.Vector3(markerX, dynamicHeight - 0.4, markerZ),
        ]);
        const spoke = new THREE.Line(
            spokeGeometry,
            new THREE.LineBasicMaterial({
                color: 0x7fffd4,
                transparent: true,
                opacity: 0.45,
            }),
        );
        registerSpiderfyMaterial(spoke.material, 0.45);
        spiderfyOverlayGroup.add(spoke);

        const markerTexture = createSpiderfyMarkerTexture(unit, unit === selectedUnit);
        if (!markerTexture) {
            return;
        }
        const marker = new THREE.Sprite(new THREE.SpriteMaterial({
            map: markerTexture,
            transparent: true,
            depthWrite: false,
        }));
        registerSpiderfyMaterial(marker.material, unit === selectedUnit ? 0.98 : 0.86);
        const markerScale = unit === selectedUnit ? markerBaseScale + 0.7 : markerBaseScale;
        marker.position.set(markerX, dynamicHeight, markerZ);
        marker.scale.set(markerScale, markerScale, 1);
        marker.userData.unit = unit;
        spiderfyOverlayGroup.add(marker);
        spiderfyHitTargets.push(marker);
    });
}

function updateSpiderfyOverlay() {
    spiderfyTick += 1;
    if (spiderfyTick % 5 !== 0) {
        return;
    }

    if (!selectedUnit) {
        spiderfySignature = null;
        spiderfyFadeTarget = 0;
        spiderfyHitTargets.length = 0;
        return;
    }

    const signature = getSpiderfyClusterUnits()
        .map((unit) => `${unit.id}:${unit.mesh.position.x.toFixed(1)}:${unit.mesh.position.z.toFixed(1)}:${selectedUnit?.id ?? ""}`)
        .sort()
        .join("|");

    if (signature === spiderfySignature) {
        return;
    }
    spiderfySignature = signature;
    buildSpiderfyOverlay();
}

function replaceUnitLabel(unit) {
    if (!unit?.mesh) {
        return;
    }

    if (unit.label) {
        unit.mesh.remove(unit.label);
        if (unit.label.material?.map) {
            unit.label.material.map.dispose();
        }
        unit.label.material?.dispose();
    }

    const label = createUnitLabel(unit.name, unit.country);
    label.position.set(0, 6, 0);
    unit.mesh.add(label);
    unit.label = label;
}

function createUnit(data) {
    const unitData = {
        id: typeof data?.id === "string" && data.id.trim() ? data.id.trim() : `unit-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        type: typeof data?.type === "string" ? data.type.toLowerCase() : "unknown",
        name: typeof data?.name === "string" && data.name.trim() ? data.name.trim() : "Unknown",
        country: typeof data?.country === "string" && data.country.trim() ? data.country.trim() : "Unknown",
        side: typeof data?.side === "string" ? data.side.toLowerCase() : "enemy",
        x: toNumber(data?.x),
        z: toNumber(data?.z),
    };

    const material = new THREE.SpriteMaterial({
        map: getIconByType(unitData.type),
        color: 0xffffff,
        transparent: true,
    });
    const mesh = new THREE.Sprite(material);
    mesh.scale.set(UNIT_ICON_SCALE, UNIT_ICON_SCALE, 1);
    mesh.position.set(unitData.x, 2, unitData.z);

    const sideRingMaterial = new THREE.SpriteMaterial({
        map: sideRingTexture,
        color: resolveUnitColor(unitData.side),
        transparent: true,
        depthWrite: false,
        opacity: 0,
    });
    const sideRing = new THREE.Sprite(sideRingMaterial);
    sideRing.scale.set(UNIT_ICON_SCALE + 0.9, UNIT_ICON_SCALE + 0.9, 1);
    sideRing.position.set(0, 0, -0.01);
    sideRing.visible = false;
    mesh.add(sideRing);

    const hitPlaneGeometry = new THREE.PlaneGeometry(HIT_PLANE_SIZE, HIT_PLANE_SIZE);
    const hitPlaneMaterial = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
        side: THREE.DoubleSide,
    });
    const hitPlane = new THREE.Mesh(hitPlaneGeometry, hitPlaneMaterial);
    hitPlane.position.set(0, 0, 0);
    hitPlane.visible = true;
    mesh.add(hitPlane);

    const label = createUnitLabel(unitData.name, unitData.country);
    label.position.set(0, 6, 0);
    mesh.add(label);

    scene.add(mesh);

    const unit = {
        id: unitData.id,
        mesh,
        sideRing,
        hitPlane,
        label,
        type: unitData.type,
        name: unitData.name,
        country: unitData.country,
        side: unitData.side,
    };

    mesh.userData = { ...unit };
    hitPlane.userData.unit = unit;

    entityManager.register(unit, "unit");
    updateUnitEmphasisVisuals();
    return unit;
}

function setSelectedUnit(unit) {
    selectedUnit = unit;
    if (!selectedUnit && isMoveMode) {
        isMoveMode = false;
    }
    if (selectedUnit) {
        openUnitPanel(selectedUnit);
    } else {
        openUnitPanel(null);
    }
    updateInteractionStatus();
    updateUnitEmphasisVisuals();
    updateUnitSearchMeta();
}

function resolveUnitFromIntersect(intersects) {
    if (!Array.isArray(intersects) || intersects.length === 0) {
        return null;
    }

    for (const intersect of intersects) {
        const obj = intersect.object;
        const unit = obj.userData?.unit ?? units.find((entry) => entry.mesh === obj || entry.hitPlane === obj);
        if (unit) {
            return unit;
        }
        let node = obj.parent;
        while (node) {
            const u = units.find((entry) => entry.mesh === node);
            if (u) return u;
            node = node.parent;
        }
    }

    return null;
}

function toNumber(value, fallback = 0) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : fallback;
}

function nowIso() {
    return new Date().toISOString();
}

function toInt(value, fallback = 0) {
    const numericValue = Number.parseInt(value, 10);
    return Number.isFinite(numericValue) ? numericValue : fallback;
}

function safeArray(value) {
    return Array.isArray(value) ? value : [];
}

function normalizeRunner(value) {
    const runner = value && typeof value === "object" ? value : {};
    const speed = Math.max(0.1, Math.min(25, toNumber(runner.speed, 1)));
    return {
        status: typeof runner.status === "string" ? runner.status : "idle",
        tick: Math.max(0, toInt(runner.tick, 0)),
        speed,
        startedBy: typeof runner.startedBy === "string" ? runner.startedBy : "",
        startedAt: typeof runner.startedAt === "string" ? runner.startedAt : null,
        updatedAt: typeof runner.updatedAt === "string" ? runner.updatedAt : null,
        seed: Math.max(1, toInt(runner.seed, 1)),
    };
}

function normalizeMission(entry, index) {
    const mission = entry && typeof entry === "object" ? entry : {};
    return {
        id: typeof mission.id === "string" && mission.id.trim() ? mission.id.trim() : `mission-${index + 1}`,
        attackerId: typeof mission.attackerId === "string" ? mission.attackerId : "",
        targetId: typeof mission.targetId === "string" ? mission.targetId : "",
        weaponType: typeof mission.weaponType === "string" ? mission.weaponType : "missile",
        priority: Math.max(1, Math.min(10, toInt(mission.priority, 5))),
        status: typeof mission.status === "string" ? mission.status : "queued",
        createdAt: typeof mission.createdAt === "string" ? mission.createdAt : null,
        startedAt: typeof mission.startedAt === "string" ? mission.startedAt : null,
        resolvedAt: typeof mission.resolvedAt === "string" ? mission.resolvedAt : null,
        lastProgress: Math.max(0, Math.min(1, toNumber(mission.lastProgress, 0))),
        notes: typeof mission.notes === "string" ? mission.notes : "",
    };
}

function normalizeEngagement(entry, index) {
    const item = entry && typeof entry === "object" ? entry : {};
    return {
        id: typeof item.id === "string" && item.id.trim() ? item.id.trim() : `engagement-${index + 1}`,
        missionId: typeof item.missionId === "string" ? item.missionId : "",
        attackerId: typeof item.attackerId === "string" ? item.attackerId : "",
        targetId: typeof item.targetId === "string" ? item.targetId : "",
        tickStarted: Math.max(0, toInt(item.tickStarted, 0)),
        tickResolved: Math.max(0, toInt(item.tickResolved, 0)),
        outcome: typeof item.outcome === "string" ? item.outcome : "pending",
        damage: Math.max(0, Math.min(100, toInt(item.damage, 0))),
    };
}

function normalizeEvent(entry, index) {
    const item = entry && typeof entry === "object" ? entry : {};
    return {
        id: typeof item.id === "string" && item.id.trim() ? item.id.trim() : `event-${index + 1}`,
        tick: Math.max(0, toInt(item.tick, 0)),
        type: typeof item.type === "string" ? item.type : "log",
        message: typeof item.message === "string" ? item.message : "",
        missionId: typeof item.missionId === "string" ? item.missionId : "",
        attackerId: typeof item.attackerId === "string" ? item.attackerId : "",
        targetId: typeof item.targetId === "string" ? item.targetId : "",
        createdAt: typeof item.createdAt === "string" ? item.createdAt : null,
    };
}

function updateSimulationStatusUi() {
    const stateNode = document.getElementById("sim-runner-state");
    const tickNode = document.getElementById("sim-runner-tick");
    const targetNode = document.getElementById("sim-target-readout");
    const rosterNode = document.getElementById("sim-roster-readout");
    if (stateNode) {
        stateNode.textContent = `Runner: ${simulationRunner.status}`;
    }
    if (tickNode) {
        tickNode.textContent = `Tick: ${simulationRunner.tick}`;
    }
    if (targetNode) {
        const targetUnit = findUnitById(engagementTargetId);
        targetNode.textContent = `Target: ${targetUnit?.name ?? "none"}`;
    }
    if (rosterNode) {
        const aliveFriendlies = engagementFriendlyIds.filter((id) => Boolean(findUnitById(id)));
        if (aliveFriendlies.length !== engagementFriendlyIds.length) {
            engagementFriendlyIds = aliveFriendlies;
        }
        rosterNode.textContent = `Roster: ${engagementFriendlyIds.length}`;
    }
}

function updateSimulationControlAvailability() {
    const controlsToToggle = [
        "sim-set-target-btn",
        "sim-add-friendly-btn",
        "sim-clear-roster-btn",
        "sim-engage-btn",
        "sim-hold-btn",
        "sim-reset-btn",
        "sim-clear-all-units-btn",
    ];
    controlsToToggle.forEach((id) => {
        const node = document.getElementById(id);
        if (node) {
            node.disabled = !canEditWaspMap;
        }
    });
    document.querySelectorAll("[data-phase]").forEach((node) => {
        if (node instanceof HTMLButtonElement) {
            node.disabled = !canEditWaspMap;
        }
    });
}

function setSelectedAsTarget() {
    if (!canEditWaspMap || !selectedUnit) {
        return;
    }
    if (selectedUnit.side !== "enemy" && selectedUnit.side !== "objective") {
        setSyncStatus("error", "Select enemy/objective as target");
        return;
    }
    engagementTargetId = selectedUnit.id;
    updateSimulationStatusUi();
    setSyncStatus("synced", "Target designated");
}

function addSelectedFriendlyToRoster() {
    if (!canEditWaspMap || !selectedUnit) {
        return;
    }
    if (selectedUnit.side !== "friendly") {
        setSyncStatus("error", "Select friendly unit first");
        return;
    }
    if (!engagementFriendlyIds.includes(selectedUnit.id)) {
        engagementFriendlyIds.push(selectedUnit.id);
    }
    updateSimulationStatusUi();
    setSyncStatus("synced", "Friendly added to roster");
}

function clearEngagementRoster() {
    engagementFriendlyIds = [];
    updateSimulationStatusUi();
}

function titleCasePhase(phase) {
    if (typeof phase !== "string") {
        return "RECON";
    }
    return phase.trim().toUpperCase();
}

function renderMissionPhaseUi() {
    const phaseNode = document.getElementById("tme-active-phase");
    if (phaseNode) {
        phaseNode.textContent = `Phase: ${titleCasePhase(currentMissionPhase)}`;
    }
    document.querySelectorAll("[data-phase]").forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) {
            return;
        }
        const phase = String(button.dataset.phase || "").toLowerCase();
        button.classList.toggle("is-active", phase === currentMissionPhase);
    });
    if (document.body) {
        document.body.dataset.missionPhase = currentMissionPhase;
    }
}

function eventSeverity(type) {
    const value = String(type || "").toLowerCase();
    if (value === "kill" || value === "abort") {
        return "critical";
    }
    if (value === "hit" || value === "launch") {
        return "warning";
    }
    return "info";
}

function renderIncidentTicker() {
    const feedNode = document.getElementById("tme-incident-feed");
    const badgeNode = document.getElementById("tme-incident-badge");
    if (!feedNode || !badgeNode) {
        return;
    }
    const latest = simulationEvents.slice(-12).reverse();
    feedNode.innerHTML = "";
    let activeCount = 0;
    latest.forEach((entry, index) => {
        const severity = eventSeverity(entry?.type);
        if (severity !== "info") {
            activeCount += 1;
        }
        const row = document.createElement("li");
        row.className = "tme-incident-item";
        row.dataset.severity = severity;
        const shortCode = String(entry?.type || "log").toUpperCase().slice(0, 6) || "LOG";
        const tick = Number(entry?.tick || 0);
        const message = String(entry?.message || "Operational update");
        row.innerHTML = `<code>#${String(index + 1).padStart(2, "0")} ${shortCode} · T${tick}</code><div>${message}</div>`;
        feedNode.appendChild(row);
    });
    badgeNode.textContent = `${activeCount} active`;
}

function setMissionPhase(nextPhase, options = {}) {
    const normalized = String(nextPhase || "").trim().toLowerCase();
    if (!MISSION_PHASE_ORDER.includes(normalized) || normalized === currentMissionPhase) {
        return;
    }
    currentMissionPhase = normalized;
    renderMissionPhaseUi();
    renderIncidentTicker();
    if (!options.silent) {
        registerSimulationEvent("phase", `Mission phase set to ${titleCasePhase(currentMissionPhase)}`, null, simulationRunner.tick || 0);
    }
    queuePlanningSave("phase-update");
    if (canEditWaspMap) {
        scheduleStateSync();
    }
}

function registerSimulationEvent(type, message, mission, tick) {
    const eventId = `event-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`;
    simulationEvents.push({
        id: eventId,
        tick,
        type,
        message,
        missionId: mission?.id ?? "",
        attackerId: mission?.attackerId ?? "",
        targetId: mission?.targetId ?? "",
        createdAt: nowIso(),
    });
    if (simulationEvents.length > 300) {
        simulationEvents = simulationEvents.slice(-300);
    }
    renderIncidentTicker();
}

function resolveSimulationOutcome(mission, tick) {
    const basis = `${mission.id}:${mission.attackerId}:${mission.targetId}:${tick}:${simulationRunner.seed}`;
    let hash = 0;
    for (let index = 0; index < basis.length; index += 1) {
        hash = ((hash << 5) - hash) + basis.charCodeAt(index);
        hash |= 0;
    }
    const outcome = SIM_OUTCOME_BUCKET[Math.abs(hash) % SIM_OUTCOME_BUCKET.length];
    return outcome || "hit";
}

/* FLIGHT PATH */
const flightPaths = [];

function createFlightPath(start, end) {
    const mid = new THREE.Vector3(
        (start.x + end.x) / 2,
        10,
        (start.z + end.z) / 2,
    );

    const curve = new THREE.QuadraticBezierCurve3(
        new THREE.Vector3(start.x, 0, start.z),
        mid,
        new THREE.Vector3(end.x, 0, end.z),
    );

    const points = curve.getPoints(100);
    const lineGeometry = new THREE.BufferGeometry().setFromPoints(points);

    const lineMaterial = new THREE.LineBasicMaterial({
        color: 0x00ffff,
        transparent: true,
        opacity: 0.35,
    });

    const line = new THREE.Line(lineGeometry, lineMaterial);
    scene.add(line);

    flightPaths.push({
        curve,
        progress: 0,
    });

    return line;
}

const WASP = {
    spawnUnit(data = {}) {
        return createUnit(data);
    },

    spawnMarker(x, z, side = "enemy") {
        return createUnit({
            type: "unknown",
            name: `Unit-${units.length + 1}`,
            country: "Unknown",
            side,
            x,
            z,
        });
    },

    spawnPath(start, end) {
        const normalizedStart = {
            x: toNumber(start?.x),
            z: toNumber(start?.z),
        };

        const normalizedEnd = {
            x: toNumber(end?.x),
            z: toNumber(end?.z),
        };

        return createFlightPath(normalizedStart, normalizedEnd);
    },
};

window.WASP = Object.freeze(WASP);

function spawnEnemy() {
    if (!canEditWaspMap) {
        return;
    }
    recordHistoryCheckpoint();
    const x = (Math.random() * 200) - 100;
    const z = (Math.random() * 200) - 100;
    WASP.spawnUnit({
        type: "tank",
        name: `Enemy-${units.length + 1}`,
        country: "Unknown",
        side: "enemy",
        x,
        z,
    });
    scheduleStateSync();
}

function spawnFriendly() {
    if (!canEditWaspMap) {
        return;
    }
    recordHistoryCheckpoint();
    const x = (Math.random() * 200) - 100;
    const z = (Math.random() * 200) - 100;
    WASP.spawnUnit({
        type: "aircraft",
        name: `Friendly-${units.length + 1}`,
        country: "Unknown",
        side: "friendly",
        x,
        z,
    });
    scheduleStateSync();
}

function toWorldPointFromMouseClick(event) {
    const bounds = renderer.domElement.getBoundingClientRect();
    const withinBounds = event.clientX >= bounds.left
        && event.clientX <= bounds.right
        && event.clientY >= bounds.top
        && event.clientY <= bounds.bottom;

    if (!withinBounds) {
        return null;
    }

    mouse.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    mouse.y = -(((event.clientY - bounds.top) / bounds.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);

    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const point = new THREE.Vector3();
    const didIntersect = raycaster.ray.intersectPlane(plane, point);
    return didIntersect ? point : null;
}

function setRaycasterFromEvent(event) {
    const bounds = renderer.domElement.getBoundingClientRect();
    const withinBounds = event.clientX >= bounds.left
        && event.clientX <= bounds.right
        && event.clientY >= bounds.top
        && event.clientY <= bounds.bottom;
    if (!withinBounds) {
        return false;
    }
    mouse.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    mouse.y = -(((event.clientY - bounds.top) / bounds.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);
    return true;
}

function snapValueToGrid(value) {
    if (!isSnapToGridEnabled) {
        return value;
    }
    return Math.round(value / GRID_SNAP_SIZE) * GRID_SNAP_SIZE;
}

function normalizeUnitPlacement(point) {
    return {
        x: snapValueToGrid(point.x),
        z: snapValueToGrid(point.z),
    };
}

function setPlacementMode(side = null) {
    if (!canEditWaspMap) {
        return;
    }
    placingUnitType = side;
    const placementTypeNode = document.getElementById("placement-type");
    if (typeof placementTypeNode?.value === "string" && placementTypeNode.value.trim()) {
        placingUnitCategory = placementTypeNode.value.trim().toLowerCase();
    }
    isMoveMode = false;
    updateInteractionStatus();
}

function enableMoveMode() {
    if (!canEditWaspMap) {
        return;
    }
    isMoveMode = selectedUnit !== null;
    placingUnitType = null;
    updateInteractionStatus();
}

function clearInteractionMode() {
    placingUnitType = null;
    isMoveMode = false;
    setPlanningMode("none");
    planningDrawDraft = [];
    updateInteractionStatus();
}

function deleteSelectedUnit() {
    if (!canEditWaspMap) {
        return;
    }
    // #region agent log
    fetch('http://127.0.0.1:7936/ingest/33d48e70-00aa-44e1-bdf8-b483e1ee0ce1',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'cf0b84'},body:JSON.stringify({sessionId:'cf0b84',runId:'run1',hypothesisId:'H2',location:'static/js/wasp_engine.js:deleteSelectedUnit:entry',message:'Delete button invoked',data:{selectedUnitId:selectedUnit?.id??null,selectedUnitName:selectedUnit?.name??null,unitsCount:units.length,isMoveMode,hasPendingLocalChanges,isPersistingSharedState},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    if (!selectedUnit) {
        return;
    }

    recordHistoryCheckpoint();
    scene.remove(selectedUnit.mesh);
    const index = units.indexOf(selectedUnit);

    if (index > -1) {
        units.splice(index, 1);
    }

    setSelectedUnit(null);
    clearInteractionMode();
    scheduleStateSync();
}

function clearAllUnits() {
    if (!canEditWaspMap) {
        return;
    }
    if (!units.length) {
        setSyncStatus("idle", "No units to clear");
        return;
    }
    recordHistoryCheckpoint();
    removeAllUnits();
    scheduleStateSync();
    setSyncStatus("synced", "All units cleared");
}

function setSyncStatus(state, message) {
    const syncNode = document.getElementById("sync-state");
    if (!syncNode) {
        return;
    }
    syncNode.className = `status-value sync-${state}`;
    syncNode.textContent = message;
}

function clearSyncStatusTimer() {
    if (!syncStatusTimerId) {
        return;
    }
    window.clearTimeout(syncStatusTimerId);
    syncStatusTimerId = null;
}

function openUnitPanel(unit) {
    const title = document.getElementById("unit-name");
    const nameInput = document.getElementById("edit-name");
    const countryInput = document.getElementById("edit-country");
    const typeInput = document.getElementById("edit-type");

    if (title) {
        title.innerText = unit?.name ?? "No unit selected";
    }

    if (!unit) {
        if (nameInput) {
            nameInput.value = "";
        }
        if (countryInput) {
            countryInput.value = "";
        }
        if (typeInput) {
            typeInput.value = "infantry";
        }
        return;
    }

    if (suppressUnitPanelSync) {
        return;
    }

    if (nameInput) {
        nameInput.value = unit.name;
    }
    if (countryInput) {
        countryInput.value = unit.country;
    }
    if (typeInput) {
        typeInput.value = unit.type;
    }
}

function updateUnit() {
    if (!canEditWaspMap) {
        return;
    }
    if (!selectedUnit) {
        return;
    }

    recordHistoryCheckpoint();
    const nameInput = document.getElementById("edit-name");
    const countryInput = document.getElementById("edit-country");
    const typeInput = document.getElementById("edit-type");

    selectedUnit.name = typeof nameInput?.value === "string" && nameInput.value.trim()
        ? nameInput.value.trim()
        : selectedUnit.name;
    selectedUnit.country = typeof countryInput?.value === "string" && countryInput.value.trim()
        ? countryInput.value.trim()
        : selectedUnit.country;
    selectedUnit.type = typeof typeInput?.value === "string" && typeInput.value.trim()
        ? typeInput.value.trim().toLowerCase()
        : selectedUnit.type;

    updateUnitVisuals(selectedUnit);
    replaceUnitLabel(selectedUnit);
    openUnitPanel(selectedUnit);
    updateInteractionStatus();
    scheduleStateSync();
}

function isEditingUnitPanel() {
    const activeElement = document.activeElement;
    return activeElement instanceof Element
        && Boolean(activeElement.closest("#unit-panel"));
}

function captureUnitPanelDraft() {
    const nameInput = document.getElementById("edit-name");
    const countryInput = document.getElementById("edit-country");
    const typeInput = document.getElementById("edit-type");

    return {
        name: typeof nameInput?.value === "string" ? nameInput.value : "",
        country: typeof countryInput?.value === "string" ? countryInput.value : "",
        type: typeof typeInput?.value === "string" ? typeInput.value : "infantry",
    };
}

function restoreUnitPanelDraft(draft) {
    if (!draft) {
        return;
    }

    const nameInput = document.getElementById("edit-name");
    const countryInput = document.getElementById("edit-country");
    const typeInput = document.getElementById("edit-type");

    if (nameInput) {
        nameInput.value = draft.name;
    }
    if (countryInput) {
        countryInput.value = draft.country;
    }
    if (typeInput) {
        typeInput.value = draft.type;
    }
}

function updateInteractionStatus() {
    const selectionNode = document.getElementById("selected-unit");
    const modeNode = document.getElementById("interaction-mode");
    const moveButton = document.getElementById("move-selected-btn");
    const deleteButton = document.getElementById("delete-selected-btn");

    if (selectionNode) {
        selectionNode.textContent = selectedUnit
            ? `${selectedUnit.name} · ${selectedUnit.country} · ${selectedUnit.type}`
            : "None";
    }

    if (moveButton) {
        moveButton.disabled = selectedUnit === null;
    }
    if (deleteButton) {
        deleteButton.disabled = selectedUnit === null;
    }

    if (modeNode) {
        if (planningMode !== "none") {
            modeNode.textContent = `Plan ${planningMode}`;
            return;
        }
        if (placingUnitType) {
            modeNode.textContent = `Place ${placingUnitType} (${placingUnitCategory})`;
            return;
        }

        if (isMoveMode) {
            modeNode.textContent = "Move selected";
            return;
        }

        modeNode.textContent = "Select";
    }
}


function hideSpawnMenu() {
    const menu = document.getElementById("spawn-menu");

    if (menu) {
        menu.style.display = "none";
    }
}

function spawnUnitFromMenu(type) {
    if (!canEditWaspMap) {
        return;
    }
    if (!spawnPosition) {
        return;
    }

    recordHistoryCheckpoint();
    const placement = normalizeUnitPlacement(spawnPosition);

    createUnit({
        type,
        name: `${type.toUpperCase()}-${Math.floor(Math.random() * 100)}`,
        country: "Unknown",
        side: "enemy",
        x: placement.x,
        z: placement.z,
    });

    hideSpawnMenu();
    scheduleStateSync();
}

function onMouseClick(event) {
    const clickedInsidePanel = event.target instanceof Element
        && event.target.closest("#admin-panel, #global-wasp-audio-widget, #tme-command-center, #tme-command-bar, #tme-city-popover");

    if (clickedInsidePanel) {
        return;
    }

    if (mapMode === "globe" && setRaycasterFromEvent(event)) {
        if (cityMarkerTargets.length > 0) {
            const cityHits = raycaster.intersectObjects(cityMarkerTargets, true);
            if (cityHits.length > 0) {
                const hitObj = cityHits[0]?.object;
                const ud = hitObj?.userData;
                const cityName = String(ud?.cityName || "").trim();
                if (cityName && ud) {
                    selectedCityName = cityName;
                    activeCountryDrilldownIso3 = String(ud.countryIso3 || "").trim().toUpperCase();
                    activeCountryDrilldownIso2 = String(ud.countryIso2 || "").trim();
                    activeCountryDrilldownName = String(ud.countryName || "");
                    const cached = countryDrilldownCache.get(activeCountryDrilldownIso3);
                    activeDrilldownCities = cached?.cities ? cached.cities.slice() : [];
                    if (globeRuntime && activeCountryDrilldownIso3) {
                        const st = String(cached?.country?.status || "contested");
                        globeRuntime.setSelectedCountry(activeCountryDrilldownIso3, st);
                    }
                    showCityPopoverFromHit(ud, cityHits[0].point);
                    updateCountryDrilldownUi();
                    return;
                }
            }
        }
        const backdrop = globeRuntime?.pickableGlobeMeshes || [];
        if (backdrop.length > 0) {
            const globeHits = raycaster.intersectObjects(backdrop, false);
            if (globeHits.length > 0) {
                hideCityPopover();
                const countryAtPoint = globeRuntime.getCountryAtScreenPoint(
                    event.clientX,
                    event.clientY,
                    renderer.domElement,
                );
                if (countryAtPoint?.iso3) {
                    const code = countryAtPoint.iso3;
                    const cached = countryDrilldownCache.get(code);
                    if (cached) {
                        activeCountryDrilldownIso3 = code;
                        activeCountryDrilldownIso2 = cached.country.iso2 || "";
                        activeCountryDrilldownName = cached.country.name || code;
                        activeDrilldownCities = cached.cities.slice();
                        selectedCityName = "";
                        globeRuntime.setSelectedCountry(code, cached.country.status || "contested");
                        updateCountryDrilldownUi();
                    } else {
                        scheduleCountryDrilldownFetch(code);
                    }
                } else {
                    clearCountryDrilldownState();
                }
                return;
            }
        }
    }

    const worldPoint = toWorldPointFromMouseClick(event);

    if (!worldPoint) {
        return;
    }

    const planningTargets = planningGroup.children.filter(Boolean);
    const planningIntersects = raycaster.intersectObjects(planningTargets, true);
    const clickedPlanning = detectClickedPlanningObject(planningIntersects);
    if (clickedPlanning) {
        selectedPlanningObjectId = clickedPlanning.id;
        selectedPlanningObjectType = clickedPlanning.type;
        renderPlanningObjects();
        updatePlanningSummaryUi();
        syncPlanningEditorInputs();
        return;
    }

    if (canEditWaspMap && planningMode === "annotation") {
        addAnnotationAt(worldPoint);
        return;
    }
    if (canEditWaspMap && planningMode === "route") {
        planningDrawDraft.push(worldPoint.clone());
        if (planningDrawDraft.length >= 2 && event.detail >= 2) {
            commitRouteDraft();
        }
        return;
    }
    if (canEditWaspMap && planningMode === "zone") {
        planningDrawDraft.push(worldPoint.clone());
        if (planningDrawDraft.length >= 3 && event.detail >= 2) {
            commitZoneDraft();
        }
        return;
    }

    const hitTargets = units.map((unit) => unit.hitPlane).filter(Boolean).concat(spiderfyHitTargets);
    const intersects = raycaster.intersectObjects(hitTargets, true);
    const clickedUnit = resolveUnitFromIntersect(intersects);

    if (canEditWaspMap && isMoveMode && selectedUnit) {
        recordHistoryCheckpoint();
        const placement = normalizeUnitPlacement(worldPoint);
        selectedUnit.mesh.position.set(placement.x, 2, placement.z);
        isMoveMode = false;
        updateInteractionStatus();
        scheduleStateSync();
        return;
    }

    if (clickedUnit) {
        setSelectedUnit(clickedUnit);
        return;
    }

    setSelectedUnit(null);

    if (canEditWaspMap && placingUnitType) {
        recordHistoryCheckpoint();
        const placement = normalizeUnitPlacement(worldPoint);
        createUnit({
            type: placingUnitCategory,
            name: `${placingUnitType}-${placingUnitCategory}-${units.length + 1}`,
            country: "Unknown",
            side: placingUnitType,
            x: placement.x,
            z: placement.z,
        });
        scheduleStateSync();
        return;
    }

}

function shouldCaptureMapKeyboardInput() {
    const activeElement = document.activeElement;

    if (!(activeElement instanceof Element)) {
        return true;
    }

    if (activeElement === document.body) {
        return true;
    }

    if (activeElement instanceof HTMLInputElement
        || activeElement instanceof HTMLTextAreaElement
        || activeElement instanceof HTMLSelectElement
        || activeElement.isContentEditable) {
        return false;
    }

    return !activeElement.closest("#admin-panel, #spawn-menu, #global-wasp-audio-widget, #tme-command-center, #tme-command-bar");
}

function updateKeyboardMoveDirection() {
    keyboardMoveDirection.set(0, 0);

    activeMoveKeys.forEach((keyCode) => {
        const keyDirection = KEYBOARD_MOVE_KEYS[keyCode];
        if (!keyDirection) {
            return;
        }

        keyboardMoveDirection.add(keyDirection);
    });

    if (keyboardMoveDirection.lengthSq() > 1) {
        keyboardMoveDirection.normalize();
    }
}

function applyKeyboardMapNavigation(deltaSeconds) {
    if (!activeMoveKeys.size || deltaSeconds <= 0) {
        return;
    }

    updateKeyboardMoveDirection();
    if (keyboardMoveDirection.lengthSq() === 0) {
        return;
    }

    camera.getWorldDirection(keyboardForwardVector);
    keyboardForwardVector.y = 0;
    if (keyboardForwardVector.lengthSq() < 1e-6) {
        return;
    }
    keyboardForwardVector.normalize();

    keyboardRightVector.crossVectors(keyboardForwardVector, camera.up);
    keyboardRightVector.y = 0;
    if (keyboardRightVector.lengthSq() < 1e-6) {
        return;
    }
    keyboardRightVector.normalize();

    const speedMultiplier = activeMoveKeys.has("ShiftLeft") || activeMoveKeys.has("ShiftRight")
        ? KEYBOARD_FAST_MOVE_MULTIPLIER
        : 1;
    const movementDistance = KEYBOARD_MOVE_SPEED_UNITS_PER_SECOND * speedMultiplier * deltaSeconds;

    keyboardMoveOffset.copy(keyboardForwardVector).multiplyScalar(keyboardMoveDirection.y * movementDistance);
    keyboardMoveOffset.addScaledVector(keyboardRightVector, keyboardMoveDirection.x * movementDistance);

    camera.position.add(keyboardMoveOffset);
    controls.target.add(keyboardMoveOffset);
}


function serializeUnits() {
    return units.map((unit) => ({
        id: unit.id,
        type: unit.type,
        name: unit.name,
        country: unit.country,
        side: unit.side,
        x: Number(unit.mesh.position.x.toFixed(3)),
        z: Number(unit.mesh.position.z.toFixed(3)),
    }));
}

function serializeSimulationState() {
    return {
        missions: missions.map((mission) => ({ ...mission })),
        engagements: engagements.map((entry) => ({ ...entry })),
        runner: { ...simulationRunner },
        events: simulationEvents.map((entry) => ({ ...entry })),
        missionPhase: currentMissionPhase,
    };
}

function removeAllUnits() {
    const list = [...units];
    list.forEach((unit) => {
        if (unit?.mesh) {
            scene.remove(unit.mesh);
        }
        if (unit?.hitPlane?.geometry) {
            unit.hitPlane.geometry.dispose();
        }
        if (unit?.hitPlane?.material) {
            unit.hitPlane.material.dispose();
        }
        if (unit?.sideRing?.material) {
            unit.sideRing.material.dispose();
        }
    });
    entityManager.clear("unit");
    selectedUnit = null;
    isMoveMode = false;
    placingUnitType = null;
    spiderfySignature = null;
    clearSpiderfyOverlay();
    updateInteractionStatus();
}

function findUnitById(unitId) {
    if (typeof unitId !== "string" || !unitId.trim()) {
        return null;
    }
    return entityManager.findById(unitId) ?? null;
}

function applyStateToScene(state) {
    const payloadUnits = Array.isArray(state?.units) ? state.units : [];
    const previousSelectedUnitId = selectedUnit?.id ?? null;
    const shouldPreserveMoveMode = Boolean(isMoveMode && previousSelectedUnitId);
    const shouldPreserveDraft = Boolean(isEditingUnitPanel() && previousSelectedUnitId);
    const unitPanelDraft = shouldPreserveDraft ? captureUnitPanelDraft() : null;

    isApplyingRemoteState = true;
    // #region agent log
    fetch('http://127.0.0.1:7936/ingest/33d48e70-00aa-44e1-bdf8-b483e1ee0ce1',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'cf0b84'},body:JSON.stringify({sessionId:'cf0b84',runId:'run1',hypothesisId:'H2',location:'static/js/wasp_engine.js:applyStateToScene',message:'Applying remote/shared state to scene',data:{payloadUnitsCount:payloadUnits.length,previousSelectedUnitId,shouldPreserveMoveMode,shouldPreserveDraft,hasPendingLocalChanges,mapStateEtag},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    removeAllUnits();
    payloadUnits.forEach((entry) => createUnit(entry));
    missions = safeArray(state?.missions).map(normalizeMission);
    engagements = safeArray(state?.engagements).map(normalizeEngagement);
    simulationEvents = safeArray(state?.events).map(normalizeEvent);
    simulationRunner = normalizeRunner(state?.runner);
    if (typeof state?.missionPhase === "string" && MISSION_PHASE_ORDER.includes(state.missionPhase.toLowerCase())) {
        currentMissionPhase = state.missionPhase.toLowerCase();
    }

    const restoredSelection = previousSelectedUnitId
        ? findUnitById(previousSelectedUnitId)
        : null;

    suppressUnitPanelSync = shouldPreserveDraft && restoredSelection !== null;
    setSelectedUnit(restoredSelection);
    suppressUnitPanelSync = false;

    if (shouldPreserveDraft && restoredSelection !== null) {
        restoreUnitPanelDraft(unitPanelDraft);
    }

    isMoveMode = shouldPreserveMoveMode && restoredSelection !== null;
    updateInteractionStatus();
    updateSimulationStatusUi();
    renderMissionPhaseUi();
    renderIncidentTicker();

    isApplyingRemoteState = false;
}

async function fetchSharedState() {
    if (isPersistingSharedState) {
        return;
    }

    const requestRevision = localStateRevision;
    const headers = {};
    if (mapStateEtag) {
        headers["If-None-Match"] = mapStateEtag;
    }

    const response = await fetch("/api/wasp-map/state", {
        method: "GET",
        headers,
        cache: "no-store",
    });

    if (response.status === 304) {
        return;
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch state (${response.status})`);
    }

    if (hasPendingLocalChanges || requestRevision !== localStateRevision) {
        return;
    }

    const nextEtag = response.headers.get("ETag");
    const payload = await response.json();
    const nextStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;

    if (isEditingUnitPanel() || isMoveMode) {
        queuedRemoteState = {
            payload,
            etag: nextStateEtag,
        };
        return;
    }

    applyStateToScene(payload);
    mapStateEtag = nextStateEtag;
    updateUnitSearchMeta();
}

async function persistSharedState() {
    if (!canEditWaspMap) {
        return;
    }
    if (isApplyingRemoteState || isApplyingHistorySnapshot) {
        return;
    }
    if (isPersistingSharedState) {
        queuedPersistRequest = true;
        return;
    }

    isPersistingSharedState = true;
    hasPendingLocalChanges = true;
    setSyncStatus("saving", "Saving...");
    clearSyncStatusTimer();

    const headers = {
        "Content-Type": "application/json",
    };

    if (mapStateEtag) {
        headers["If-Match"] = mapStateEtag;
    }

    let response;
    const maxAttempts = 3;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
            response = await fetch("/api/wasp-map/state", {
                method: "PUT",
                headers,
                body: JSON.stringify({
                    units: serializeUnits(),
                    ...serializeSimulationState(),
                }),
            });
        } catch (error) {
            if (attempt >= maxAttempts) {
                throw error;
            }
            const backoffMs = 300 * (2 ** (attempt - 1));
            await new Promise((resolve) => window.setTimeout(resolve, backoffMs));
            continue;
        }

        if (response.ok || response.status === 409 || response.status < 500 || attempt >= maxAttempts) {
            break;
        }

        const backoffMs = 300 * (2 ** (attempt - 1));
        await new Promise((resolve) => window.setTimeout(resolve, backoffMs));
    }

    if (!response) {
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
        setSyncStatus("error", "Sync failed");
        syncFailureCount += 1;
        throw new Error("Failed to persist state (no response)");
    }

    const nextEtag = response.headers.get("ETag");

    if (response.status === 409) {
        const conflictPayload = await response.json();
        applyStateToScene(conflictPayload.state);
        mapStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
        setSyncStatus("conflict", "Conflict resolved from remote");
        syncStatusTimerId = window.setTimeout(() => {
            setSyncStatus("synced", "Synced");
        }, 2000);
        if (queuedPersistRequest) {
            queuedPersistRequest = false;
            return persistSharedState();
        }
        return;
    }

    if (!response.ok) {
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
        syncFailureCount += 1;
        setSyncStatus("error", `Sync failed (${response.status})`);
        throw new Error(`Failed to persist state (${response.status})`);
    }

    mapStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
    hasPendingLocalChanges = false;
    isPersistingSharedState = false;
    // #region agent log
    fetch('http://127.0.0.1:7936/ingest/33d48e70-00aa-44e1-bdf8-b483e1ee0ce1',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'cf0b84'},body:JSON.stringify({sessionId:'cf0b84',runId:'run1',hypothesisId:'H2',location:'static/js/wasp_engine.js:persistSharedState:success',message:'Persist completed',data:{status:response.status,nextEtag:mapStateEtag,unitsCount:units.length,selectedUnitId:selectedUnit?.id??null,queuedPersistRequest},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    syncFailureCount = 0;
    setSyncStatus("synced", "Synced");
    clearSyncStatusTimer();
    syncStatusTimerId = window.setTimeout(() => {
        if (!hasPendingLocalChanges && !isPersistingSharedState) {
            setSyncStatus("idle", "Idle");
        }
    }, 2500);
    if (queuedPersistRequest) {
        queuedPersistRequest = false;
        return persistSharedState();
    }
}

function scheduleStateSync() {
    if (!canEditWaspMap) {
        setSyncStatus("error", "Read-only");
        return;
    }
    if (isApplyingHistorySnapshot) {
        return;
    }
    updateUnitSearchMeta();
    localStateRevision += 1;
    hasPendingLocalChanges = true;
    setSyncStatus("saving", "Saving...");
    void persistSharedState().catch((error) => {
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
        setSyncStatus("error", "Sync failed");
        console.error("Unable to persist W.A.S.P shared map state", error);
    });
}

function flushQueuedRemoteStateIfSafe() {
    if (!queuedRemoteState) {
        return;
    }
    if (hasPendingLocalChanges || isMoveMode || isEditingUnitPanel() || isPersistingSharedState) {
        return;
    }

    const snapshot = queuedRemoteState;
    queuedRemoteState = null;
    applyStateToScene(snapshot.payload);
    mapStateEtag = snapshot.etag;
    updateUnitSearchMeta();
}

async function callSimulationEndpoint(path, payload = null) {
    if (!canEditWaspMap) {
        return;
    }
    const options = {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
    };
    if (payload !== null) {
        options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    if (!response.ok) {
        throw new Error(`Simulation endpoint failed (${response.status})`);
    }
    const nextState = await response.json();
    applyStateToScene(nextState);
}

async function startSimulation() {
    const speed = 1;
    await callSimulationEndpoint("/api/wasp-map/simulation/start", { speed });
    updateSimulationStatusUi();
}

async function pauseSimulation() {
    await callSimulationEndpoint("/api/wasp-map/simulation/pause", {});
    updateSimulationStatusUi();
}

async function resetSimulation() {
    await callSimulationEndpoint("/api/wasp-map/simulation/reset", {});
    setMissionPhase("recon", { silent: true });
    updateSimulationStatusUi();
}

async function advanceSimulationTick() {
    const speed = Math.max(1, Math.round(simulationRunner.speed || 1));
    await callSimulationEndpoint("/api/wasp-map/simulation/tick", { ticks: speed });
    updateSimulationStatusUi();
}

async function engageRoster() {
    if (!canEditWaspMap) {
        return;
    }
    if (!engagementTargetId) {
        setSyncStatus("error", "No target selected");
        return;
    }
    if (!engagementFriendlyIds.length) {
        setSyncStatus("error", "Roster is empty");
        return;
    }
    const target = findUnitById(engagementTargetId);
    if (!target) {
        setSyncStatus("error", "Target no longer exists");
        return;
    }
    const friendlyIds = engagementFriendlyIds.filter((id) => {
        const unit = findUnitById(id);
        return unit && unit.side === "friendly";
    });
    if (!friendlyIds.length) {
        setSyncStatus("error", "No valid friendlies in roster");
        return;
    }

    for (const friendlyId of friendlyIds) {
        const response = await fetch("/api/wasp-map/missions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                attackerId: friendlyId,
                targetId: engagementTargetId,
                notes: `engage:${target.name || target.id}`,
            }),
        });
        if (!response.ok) {
            throw new Error(`Mission creation failed (${response.status})`);
        }
        const nextState = await response.json();
        applyStateToScene(nextState);
    }
    await startSimulation();
    setMissionPhase("engagement");
    setSyncStatus("synced", "Engagement launched");
}

async function holdSimulation() {
    await pauseSimulation();
    if (currentMissionPhase === "engagement") {
        setMissionPhase("extraction");
    }
    setSyncStatus("synced", "Engagement held");
}

function stepSimulation(deltaSeconds) {
    if (!canEditWaspMap || simulationRunner.status !== "running" || missions.length === 0) {
        return;
    }

    const speed = Math.max(0.1, simulationRunner.speed || 1);
    simulationTickCarry += deltaSeconds * speed;
    const tickDelta = Math.floor(simulationTickCarry);
    if (tickDelta <= 0) {
        return;
    }
    simulationTickCarry -= tickDelta;
    simulationRunner.tick += tickDelta;
    simulationRunner.updatedAt = nowIso();

    const nowTick = simulationRunner.tick;
    let hasStateMutation = false;
    missions.forEach((mission) => {
        if (mission.status === "completed" || mission.status === "aborted") {
            return;
        }
        const attacker = findUnitById(mission.attackerId);
        const target = findUnitById(mission.targetId);
        if (!attacker || !target) {
            mission.status = "aborted";
            mission.resolvedAt = nowIso();
            registerSimulationEvent("abort", `Mission ${mission.id} aborted: attacker/target unavailable`, mission, nowTick);
            hasStateMutation = true;
            return;
        }
        if (mission.status === "queued") {
            mission.status = "active";
            mission.startedAt = nowIso();
            registerSimulationEvent("launch", `Mission ${mission.id} launched`, mission, nowTick);
            hasStateMutation = true;
        }
        const distance = attacker.mesh.position.distanceTo(target.mesh.position);
        const distanceFactor = Math.max(0.02, Math.min(0.2, 14 / Math.max(1, distance)));
        mission.lastProgress = Math.max(0, Math.min(1, mission.lastProgress + (distanceFactor * tickDelta)));
        if (mission.lastProgress < 1) {
            return;
        }
        const outcome = resolveSimulationOutcome(mission, nowTick);
        mission.status = "completed";
        mission.resolvedAt = nowIso();
        const isKill = outcome === "kill";
        if (isKill) {
            const index = units.indexOf(target);
            if (index > -1) {
                scene.remove(target.mesh);
                units.splice(index, 1);
                entityManager.unregister(target, "unit");
            }
        }
        engagements.push({
            id: `engagement-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
            missionId: mission.id,
            attackerId: mission.attackerId,
            targetId: mission.targetId,
            tickStarted: Math.max(0, nowTick - Math.max(1, tickDelta)),
            tickResolved: nowTick,
            outcome,
            damage: outcome === "kill" ? 100 : outcome === "hit" ? 65 : 10,
        });
        registerSimulationEvent(outcome, `Mission ${mission.id} resolved as ${outcome}`, mission, nowTick);
        hasStateMutation = true;
    });

    if (!hasStateMutation) {
        return;
    }
    if (missions.every((mission) => mission.status === "completed" || mission.status === "aborted")) {
        setMissionPhase("afteraction", { silent: true });
    }
    updateSimulationStatusUi();
    const nowMs = Date.now();
    if ((nowMs - lastSimulationSyncAt) >= SIM_SYNC_INTERVAL_MS) {
        lastSimulationSyncAt = nowMs;
        scheduleStateSync();
    }
}

function resetCameraView() {
    if (mapMode === "galaxy") {
        camera.position.set(0, 400, 600);
    } else if (mapMode === "globe") {
        camera.position.set(0, 360, 620);
        controls.minDistance = GLOBE_DEFAULT_MIN_DISTANCE;
        controls.maxDistance = GLOBE_DEFAULT_MAX_DISTANCE;
        controls.enablePan = true;
    } else {
        camera.position.set(0, 80, 180);
    }
    controls.target.set(0, 0, 0);
    controls.update();
}

function createHistorySnapshot() {
    return {
        units: serializeUnits(),
        selectedUnitId: selectedUnit?.id ?? null,
        placingUnitType,
        isMoveMode: Boolean(isMoveMode && selectedUnit),
    };
}

function snapshotsEqual(a, b) {
    if (!a || !b) {
        return false;
    }
    return JSON.stringify(a) === JSON.stringify(b);
}

function pushUndoSnapshot(snapshot) {
    const lastSnapshot = undoHistory.at(-1);
    if (lastSnapshot && snapshotsEqual(lastSnapshot, snapshot)) {
        return;
    }

    undoHistory.push(snapshot);
    if (undoHistory.length > MAX_HISTORY_ENTRIES) {
        undoHistory.shift();
    }
}

function recordHistoryCheckpoint() {
    if (isApplyingRemoteState || isApplyingHistorySnapshot) {
        return;
    }
    pushUndoSnapshot(createHistorySnapshot());
    redoHistory.length = 0;
}

function applyHistorySnapshot(snapshot) {
    if (!snapshot || !Array.isArray(snapshot.units)) {
        return;
    }

    isApplyingHistorySnapshot = true;
    removeAllUnits();
    snapshot.units.forEach((entry) => createUnit(entry));
    const restoredSelection = snapshot.selectedUnitId
        ? findUnitById(snapshot.selectedUnitId)
        : null;
    setSelectedUnit(restoredSelection);
    placingUnitType = typeof snapshot.placingUnitType === "string" ? snapshot.placingUnitType : null;
    isMoveMode = Boolean(snapshot.isMoveMode && restoredSelection);
    updateInteractionStatus();
    updateUnitSearchMeta();
    isApplyingHistorySnapshot = false;
}

function undoMapAction() {
    if (!canEditWaspMap) {
        return;
    }
    if (!undoHistory.length) {
        return;
    }
    const currentSnapshot = createHistorySnapshot();
    const previousSnapshot = undoHistory.pop();
    redoHistory.push(currentSnapshot);
    applyHistorySnapshot(previousSnapshot);
    scheduleStateSync();
}

function redoMapAction() {
    if (!canEditWaspMap) {
        return;
    }
    if (!redoHistory.length) {
        return;
    }
    const currentSnapshot = createHistorySnapshot();
    const nextSnapshot = redoHistory.pop();
    pushUndoSnapshot(currentSnapshot);
    applyHistorySnapshot(nextSnapshot);
    scheduleStateSync();
}

function getSearchFilters() {
    const searchInput = document.getElementById("unit-search-input");
    const sideFilter = document.getElementById("unit-search-side-filter");
    const query = typeof searchInput?.value === "string"
        ? searchInput.value.trim().toLowerCase()
        : "";
    const side = typeof sideFilter?.value === "string"
        ? sideFilter.value.trim().toLowerCase()
        : "all";
    return { query, side };
}

function getSearchMatches() {
    const { query, side } = getSearchFilters();
    return units.filter((unit) => {
        const sideMatches = side === "all" || unit.side === side;
        if (!sideMatches) {
            return false;
        }
        if (!query) {
            return true;
        }
        const haystack = `${unit.name} ${unit.country} ${unit.type} ${unit.id}`.toLowerCase();
        return haystack.includes(query);
    });
}

function updateUnitSearchMeta() {
    const metaNode = document.getElementById("unit-search-meta");
    if (!metaNode) {
        return;
    }
    const { query, side } = getSearchFilters();
    const matches = getSearchMatches();
    if (!query && side === "all") {
        metaNode.textContent = `No active search · ${units.length} units loaded`;
        return;
    }
    metaNode.textContent = `${matches.length} match(es) · filter: ${side}${query ? ` · query: "${query}"` : ""}`;
}

function jumpToUnit(unit) {
    if (!unit?.mesh) {
        return;
    }
    const offset = camera.position.clone().sub(controls.target);
    controls.target.set(unit.mesh.position.x, 0, unit.mesh.position.z);
    camera.position.copy(controls.target.clone().add(offset));
    controls.update();
}

function findNextUnit() {
    const matches = getSearchMatches();
    updateUnitSearchMeta();
    if (!matches.length) {
        return;
    }
    unitSearchCursor = (unitSearchCursor + 1) % matches.length;
    const nextUnit = matches[unitSearchCursor];
    setSelectedUnit(nextUnit);
    jumpToUnit(nextUnit);
}

function jumpToSelectedUnit() {
    if (!selectedUnit) {
        return;
    }
    jumpToUnit(selectedUnit);
}

function updateGridSnapUi() {
    const button = document.getElementById("grid-snap-btn");
    if (!button) {
        return;
    }
    button.textContent = `Grid Snap: ${isSnapToGridEnabled ? "On" : "Off"}`;
    button.setAttribute("aria-pressed", isSnapToGridEnabled ? "true" : "false");
}

function toggleSnapToGrid() {
    isSnapToGridEnabled = !isSnapToGridEnabled;
    updateGridSnapUi();
}

window.spawnEnemy = spawnEnemy;
window.spawnFriendly = spawnFriendly;
window.deleteSelectedUnit = deleteSelectedUnit;
window.placeEnemyUnit = () => setPlacementMode("enemy");
window.placeFriendlyUnit = () => setPlacementMode("friendly");
window.enableMoveMode = enableMoveMode;
window.clearInteractionMode = clearInteractionMode;
window.openUnitPanel = openUnitPanel;
window.updateUnit = updateUnit;
window.spawnUnitFromMenu = spawnUnitFromMenu;
window.resetCameraView = resetCameraView;
window.toggleSnapToGrid = toggleSnapToGrid;
window.undoMapAction = undoMapAction;
window.redoMapAction = redoMapAction;
window.findNextUnit = findNextUnit;
window.jumpToSelectedUnit = jumpToSelectedUnit;
window.startSimulation = () => {
    void startSimulation().catch((error) => {
        setSyncStatus("error", "Simulation start failed");
        console.error("Unable to start WASP simulation", error);
    });
};
window.holdSimulation = () => {
    void holdSimulation().catch((error) => {
        setSyncStatus("error", "Simulation hold failed");
        console.error("Unable to hold WASP simulation", error);
    });
};
window.resetSimulation = () => {
    void resetSimulation().catch((error) => {
        setSyncStatus("error", "Simulation reset failed");
        console.error("Unable to reset WASP simulation", error);
    });
};
window.advanceSimulationTick = () => {
    void advanceSimulationTick().catch((error) => {
        setSyncStatus("error", "Simulation tick failed");
        console.error("Unable to advance WASP simulation tick", error);
    });
};
window.engageRoster = () => {
    void engageRoster().catch((error) => {
        setSyncStatus("error", "Engagement launch failed");
        console.error("Unable to launch engagement roster", error);
    });
};
window.setSelectedAsTarget = setSelectedAsTarget;
window.addSelectedFriendlyToRoster = addSelectedFriendlyToRoster;
window.clearEngagementRoster = clearEngagementRoster;

const panelClock = document.getElementById("admin-clock");
const panelGreeting = document.getElementById("admin-greeting");

if (panelClock) {
    const updateClock = () => {
        const now = new Date();
        panelClock.textContent = now.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: false,
            timeZoneName: "short",
        });

        if (panelGreeting) {
            const hour = now.getHours();
            const timeGreeting = hour < 12
                ? "Good morning"
                : hour < 18
                    ? "Good afternoon"
                    : "Good evening";
            const operatorName = typeof mapBootstrap.displayName === "string" && mapBootstrap.displayName.trim()
                ? mapBootstrap.displayName.trim()
                : "Operator";
            panelGreeting.textContent = `${timeGreeting}, ${operatorName}.`;
        }
    };

    updateClock();
    window.setInterval(updateClock, 1000);
}

updateInteractionStatus();
openUnitPanel(null);
updateGridSnapUi();
setSyncStatus("idle", "Idle");
updateUnitSearchMeta();
updateSimulationStatusUi();
updateSimulationControlAvailability();
applyOverlayVisibility();
renderMissionPhaseUi();
renderIncidentTicker();
updatePlanningSummaryUi();
syncPlanningEditorInputs();
setRenderTier("high");
updateCountryDrilldownUi();

document.querySelectorAll("[data-layer-toggle]").forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) {
        return;
    }
    button.addEventListener("click", () => {
        const layer = String(button.dataset.layerToggle || "").toUpperCase();
        if (!(layer in overlayVisibility)) {
            return;
        }
        overlayVisibility[layer] = !overlayVisibility[layer];
        applyOverlayVisibility();
    });
});

document.querySelectorAll("[data-phase]").forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) {
        return;
    }
    button.addEventListener("click", () => {
        if (!canEditWaspMap) {
            return;
        }
        setMissionPhase(button.dataset.phase || "recon");
    });
});

const planRouteButton = document.getElementById("plan-mode-route");
const planZoneButton = document.getElementById("plan-mode-zone");
const planAnnotationButton = document.getElementById("plan-mode-annotation");
const planDeleteButton = document.getElementById("plan-delete-selected-btn");
const planClearButton = document.getElementById("plan-clear-btn");
if (planRouteButton) {
    planRouteButton.addEventListener("click", () => {
        setPlanningMode(planningMode === "route" ? "none" : "route");
    });
}
if (planZoneButton) {
    planZoneButton.addEventListener("click", () => {
        setPlanningMode(planningMode === "zone" ? "none" : "zone");
    });
}
if (planAnnotationButton) {
    planAnnotationButton.addEventListener("click", () => {
        setPlanningMode(planningMode === "annotation" ? "none" : "annotation");
    });
}
if (planDeleteButton) {
    planDeleteButton.addEventListener("click", () => {
        if (!canEditWaspMap) {
            return;
        }
        deleteSelectedPlanningObject();
    });
}
if (planClearButton) {
    planClearButton.addEventListener("click", () => {
        if (!canEditWaspMap) {
            return;
        }
        clearPlanningObjects();
    });
}

const unitSearchInput = document.getElementById("unit-search-input");
const unitSearchSideFilter = document.getElementById("unit-search-side-filter");
const drilldownCitySelect = document.getElementById("tme-city-select");
if (unitSearchInput) {
    unitSearchInput.addEventListener("input", () => {
        unitSearchCursor = -1;
        updateUnitSearchMeta();
    });
}
if (unitSearchSideFilter) {
    unitSearchSideFilter.addEventListener("change", () => {
        unitSearchCursor = -1;
        updateUnitSearchMeta();
    });
}
if (drilldownCitySelect instanceof HTMLSelectElement) {
    drilldownCitySelect.addEventListener("change", () => {
        selectedCityName = String(drilldownCitySelect.value || "").trim();
        updateCountryDrilldownUi();
    });
}

const placementTypeNode = document.getElementById("placement-type");
if (placementTypeNode) {
    placementTypeNode.addEventListener("change", () => {
        if (typeof placementTypeNode.value === "string" && placementTypeNode.value.trim()) {
            placingUnitCategory = placementTypeNode.value.trim().toLowerCase();
            updateInteractionStatus();
        }
    });
}

window.addEventListener("contextmenu", (event) => {
    event.preventDefault();

    const clickedInsidePanel = event.target instanceof Element
        && event.target.closest("#admin-panel, #spawn-menu, #global-wasp-audio-widget, #tme-command-center, #tme-command-bar");

    if (clickedInsidePanel) {
        return;
    }

    if (!rightPointerDownStartedOnMap) {
        return;
    }

    const rightPointerTravel = Math.hypot(
        event.clientX - rightPointerDownPosition.x,
        event.clientY - rightPointerDownPosition.y,
    );
    rightPointerDownStartedOnMap = false;

    // Do not open spawn menu when RMB was used to pan/drag the map.
    if (rightPointerTravel > CLICK_DRAG_TOLERANCE_PX) {
        return;
    }

    const point = toWorldPointFromMouseClick(event);

    if (!point) {
        return;
    }

    spawnPosition = point.clone();

    const menu = document.getElementById("spawn-menu");

    if (!menu) {
        return;
    }

    menu.style.display = "block";
    const viewportPadding = 10;
    const menuWidth = menu.offsetWidth;
    const menuHeight = menu.offsetHeight;
    const maxLeft = Math.max(viewportPadding, window.innerWidth - menuWidth - viewportPadding);
    const maxTop = Math.max(viewportPadding, window.innerHeight - menuHeight - viewportPadding);
    const left = Math.max(viewportPadding, Math.min(event.clientX, maxLeft));
    const top = Math.max(viewportPadding, Math.min(event.clientY, maxTop));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
});

window.addEventListener("pointerdown", (event) => {
    pointerDownPosition.x = event.clientX;
    pointerDownPosition.y = event.clientY;
    pointerDownStartedOnMap = event.target instanceof Element
        && container.contains(event.target)
        && !event.target.closest("#admin-panel, #spawn-menu, #global-wasp-audio-widget, #tme-command-center, #tme-command-bar");

    if (event.button === 2) {
        rightPointerDownPosition.x = event.clientX;
        rightPointerDownPosition.y = event.clientY;
        rightPointerDownStartedOnMap = pointerDownStartedOnMap;
    }

    if (event.button !== 0) {
        return;
    }

    if (!pointerDownStartedOnMap || !isMoveMode || !selectedUnit) {
        return;
    }

    const point = toWorldPointFromMouseClick(event);
    if (!point) {
        return;
    }

    isDraggingSelectedUnit = true;
    hasDraggedSelectedUnit = false;
    recordHistoryCheckpoint();
    controls.enabled = false;
    const placement = normalizeUnitPlacement(point);
    selectedUnit.mesh.position.set(placement.x, 2, placement.z);
    dragTargetRing.position.set(placement.x, 0.1, placement.z);
    dragTargetRing.visible = true;
    hasDraggedSelectedUnit = true;
});

window.addEventListener("pointermove", (event) => {
    if (!isDraggingSelectedUnit || !selectedUnit) {
        return;
    }

    const point = toWorldPointFromMouseClick(event);
    if (!point) {
        return;
    }

    hasDraggedSelectedUnit = true;
    const placement = normalizeUnitPlacement(point);
    selectedUnit.mesh.position.set(placement.x, 2, placement.z);
    dragTargetRing.position.set(placement.x, 0.1, placement.z);
    dragTargetRing.visible = true;
});

window.addEventListener("pointerup", () => {
    if (!isDraggingSelectedUnit) {
        return;
    }

    isDraggingSelectedUnit = false;
    controls.enabled = true;
    dragTargetRing.visible = false;

    if (hasDraggedSelectedUnit) {
        hasDraggedSelectedUnit = false;
        isMoveMode = false;
        updateInteractionStatus();
        scheduleStateSync();
    }
});

window.addEventListener("click", (event) => {
    if (hasDraggedSelectedUnit || isDraggingSelectedUnit) {
        return;
    }

    const pointerTravel = Math.hypot(
        event.clientX - pointerDownPosition.x,
        event.clientY - pointerDownPosition.y,
    );

    if (pointerTravel > CLICK_DRAG_TOLERANCE_PX) {
        return;
    }

    const clickedInsideMenu = event.target instanceof Element
        && event.target.closest("#spawn-menu");

    if (!clickedInsideMenu) {
        hideSpawnMenu();
    }

    const clickedOnMap = pointerDownStartedOnMap && event.target instanceof Element
        && container.contains(event.target)
        && !event.target.closest("#admin-panel, #spawn-menu, #global-wasp-audio-widget, #tme-command-center, #tme-command-bar");

    if (!clickedOnMap) {
        return;
    }

    onMouseClick(event);
});

window.addEventListener("keydown", (event) => {
    const isUndoShortcut = (event.ctrlKey || event.metaKey) && !event.shiftKey && event.code === "KeyZ";
    const isRedoShortcut = ((event.ctrlKey || event.metaKey) && event.code === "KeyY")
        || ((event.ctrlKey || event.metaKey) && event.shiftKey && event.code === "KeyZ");
    if (isUndoShortcut && shouldCaptureMapKeyboardInput()) {
        event.preventDefault();
        undoMapAction();
        return;
    }
    if (isRedoShortcut && shouldCaptureMapKeyboardInput()) {
        event.preventDefault();
        redoMapAction();
        return;
    }

    if (event.code === "KeyR" && shouldCaptureMapKeyboardInput()) {
        event.preventDefault();
        resetCameraView();
        return;
    }

    if (event.code === "Escape") {
        planningDrawDraft = [];
        setPlanningMode("none");
        return;
    }
    if (event.code === "Enter" && planningMode === "route") {
        event.preventDefault();
        commitRouteDraft();
        return;
    }
    if (event.code === "Enter" && planningMode === "zone") {
        event.preventDefault();
        commitZoneDraft();
        return;
    }

    if (!(event.code in KEYBOARD_MOVE_KEYS) && event.code !== "ShiftLeft" && event.code !== "ShiftRight") {
        return;
    }

    if (!shouldCaptureMapKeyboardInput()) {
        return;
    }

    if (event.code in KEYBOARD_MOVE_KEYS) {
        event.preventDefault();
    }

    activeMoveKeys.add(event.code);
});

window.addEventListener("keyup", (event) => {
    activeMoveKeys.delete(event.code);
});

window.addEventListener("blur", () => {
    activeMoveKeys.clear();
    rightPointerDownStartedOnMap = false;
    if (isDraggingSelectedUnit) {
        isDraggingSelectedUnit = false;
        hasDraggedSelectedUnit = false;
        dragTargetRing.visible = false;
        controls.enabled = true;
    }
});

if (mapMode !== "galaxy") {
    void fetchSharedState().catch((error) => {
        setSyncStatus("error", "Sync unavailable");
        console.error("Unable to load shared W.A.S.P map state", error);
    });

    syncTimerId = window.setInterval(() => {
        void fetchSharedState().catch((error) => {
            if (!hasPendingLocalChanges && !isPersistingSharedState) {
                setSyncStatus("error", "Sync unavailable");
            }
            console.error("Unable to refresh shared W.A.S.P map state", error);
        });
    }, 3000);
}

void loadPlanningState().catch((error) => {
    if (planningApiUrl()) {
        setPlanningSaveStatusUi("Load failed");
    }
    console.error("Unable to load WASP planning state", error);
});

/* GALAXY LAYER (InstancedMesh stars) */
async function loadGalaxyLayer() {
    try {
        const data = await mapLoader.loadGalaxy("galaxy");
        const stars = data?.stars ?? [];
        starLayer = createStarLayer(stars, {
            size: 2,
            color: 0xffffff,
            opacity: 0.95,
        });
        scene.add(starLayer.mesh);
        stars.forEach((s) => entityManager.register({ ...s, type: "star" }, "star"));
    } catch (error) {
        console.error("Galaxy layer failed to load", error);
    }
}

/* WORLD MAP LAYER */
async function loadWorldMap() {
    if (mapMode === "galaxy" || mapMode === "globe") return;
    try {
        const response = await fetch("/static/data/world.geo.json");

        if (!response.ok) {
            throw new Error(`Unable to load world map: ${response.status}`);
        }

        const data = await response.json();

        const mapMaterial = new THREE.LineBasicMaterial({
            color: 0x8af5ff,
            transparent: true,
            opacity: 0.5,
        });

        const drawRing = (ring) => {
            const points = ring.map((coord) => {
                const lon = coord[0];
                const lat = coord[1];
                const x = lon * 1.5;
                const z = lat * 1.5;
                return new THREE.Vector3(x, 0.05, -z);
            });

            const ringGeometry = new THREE.BufferGeometry().setFromPoints(points);
            const line = new THREE.Line(ringGeometry, mapMaterial);
            scene.add(line);
        };

        data.features.forEach((feature) => {
            const coords = feature.geometry.coordinates;

            if (feature.geometry.type === "Polygon") {
                coords.forEach((ring) => drawRing(ring));
                return;
            }

            if (feature.geometry.type === "MultiPolygon") {
                coords.forEach((polygon) => {
                    polygon.forEach((ring) => drawRing(ring));
                });
            }
        });

        const TERRAIN_WIDTH = 540;
        const TERRAIN_HEIGHT = 260;
        const TERRAIN_STEP = 4;
        const TERRAIN_AMPLITUDE = 7;
        const positions = [];
        const colors = [];
        const color = new THREE.Color();
        const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
        const pseudoNoise = (x, z) => {
            const n1 = Math.sin((x * 0.06) + (z * 0.021));
            const n2 = Math.cos((x * 0.033) - (z * 0.057));
            const n3 = Math.sin((x + z) * 0.0125);
            return (n1 + (n2 * 0.7) + (n3 * 0.45)) / 2.15;
        };

        for (let z = -TERRAIN_HEIGHT / 2; z <= TERRAIN_HEIGHT / 2; z += TERRAIN_STEP) {
            for (let x = -TERRAIN_WIDTH / 2; x <= TERRAIN_WIDTH / 2; x += TERRAIN_STEP) {
                const noise = pseudoNoise(x, z);
                const elevation = Math.max(0, noise) * TERRAIN_AMPLITUDE;
                if (elevation <= 0.15) {
                    continue;
                }
                positions.push(x, 0.35 + elevation, z);

                const glow = clamp(0.35 + (elevation / TERRAIN_AMPLITUDE), 0, 1);
                color.setRGB(
                    0.08 + (glow * 0.20),
                    0.30 + (glow * 0.40),
                    0.22 + (glow * 0.15),
                );
                colors.push(color.r, color.g, color.b);
            }
        }

        const pointGeometry = new THREE.BufferGeometry();
        pointGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
        pointGeometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
        const pointMaterial = new THREE.PointsMaterial({
            size: 1.1,
            transparent: true,
            opacity: 0.75,
            vertexColors: true,
            depthWrite: false,
        });
        terrainPointCloud = new THREE.Points(pointGeometry, pointMaterial);
        scene.add(terrainPointCloud);
    } catch (error) {
        console.error("World map layer failed to load", error);
    }
}

void loadWorldMap();

if (mapMode === "galaxy") {
    void loadGalaxyLayer();
}

/* LABEL & CLUSTER UPDATES */
const clusterMarkers = [];

function createClusterTexture(count) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    canvas.width = 152;
    canvas.height = 80;
    if (!ctx) return null;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(8, 18, 34, 0.86)";
    ctx.fillRect(4, 6, canvas.width - 8, canvas.height - 12);
    ctx.strokeStyle = "rgba(127, 255, 212, 0.95)";
    ctx.lineWidth = 3;
    ctx.strokeRect(5.5, 7.5, canvas.width - 11, canvas.height - 15);
    ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
    ctx.font = "bold 27px Inter, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(`${count} UNITS`, canvas.width / 2, canvas.height / 2);
    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
}

function updateLabels() {
    const camPos = camera.position;
    units.forEach((unit) => {
        const dist = camPos.distanceTo(unit.mesh.position);
        if (unit.label) {
            const isSelected = unit === selectedUnit;
            const shouldShowEnemyLabel = unit.side !== "enemy" || dist < (LABEL_VISIBILITY_DISTANCE * 0.52);
            unit.label.visible = isSelected || (dist < LABEL_VISIBILITY_DISTANCE && shouldShowEnemyLabel);
            if (unit.label.material) {
                const normalized = Math.min(1, Math.max(0, 1 - (dist / LABEL_VISIBILITY_DISTANCE)));
                unit.label.material.opacity = 0.35 + (normalized * 0.65);
            }
        }
    });
}

function getLabelOverlapGroups() {
    const groups = [];
    units.forEach((unit) => {
        let found = false;
        for (const group of groups) {
            if (unit.mesh.position.distanceTo(group.position) < LABEL_OVERLAP_DISTANCE) {
                group.units.push(unit);
                found = true;
                break;
            }
        }
        if (!found) {
            groups.push({
                position: unit.mesh.position.clone(),
                units: [unit],
            });
        }
    });
    return groups;
}

function resolveLabelOverlap() {
    const groups = getLabelOverlapGroups();
    groups.forEach((group) => {
        group.units.forEach((u, idx) => {
            if (u.label) u.label.position.y = 6 + idx * 3;
        });
    });
}

function clusterUnits() {
    const clusters = [];
    units.forEach((unit) => {
        let found = false;
        for (const cluster of clusters) {
            if (unit.mesh.position.distanceTo(cluster.position) < CLUSTER_RADIUS) {
                cluster.units.push(unit);
                found = true;
                break;
            }
        }
        if (!found) {
            clusters.push({
                position: unit.mesh.position.clone(),
                units: [unit],
            });
        }
    });
    return clusters;
}

function updateClusterMarkers() {
    const camDist = camera.position.distanceTo(controls.target);
    const useClusters = camDist > CLUSTER_ZOOM_THRESHOLD;

    if (!useClusters) {
        clusterMarkers.forEach((m) => {
            m.visible = false;
        });
        units.forEach((u) => {
            u.mesh.visible = true;
        });
        return;
    }

    const clusters = clusterUnits();
    const multiClusters = clusters.filter((c) => c.units.length > 1);

    units.forEach((u) => {
        u.mesh.visible = true;
    });

    while (clusterMarkers.length > multiClusters.length) {
        const m = clusterMarkers.pop();
        scene.remove(m);
        m.material?.map?.dispose();
        m.material?.dispose();
    }

    multiClusters.forEach((cluster, i) => {
        const centroid = new THREE.Vector3(0, 0, 0);
        cluster.units.forEach((u) => centroid.add(u.mesh.position));
        centroid.divideScalar(cluster.units.length);

        let marker = clusterMarkers[i];
        if (!marker) {
            const tex = createClusterTexture(cluster.units.length);
            const mat = new THREE.SpriteMaterial({
                map: tex,
                color: 0x00ffff,
                transparent: true,
            });
            marker = new THREE.Sprite(mat);
            marker.scale.set(13.5, 6, 1);
            scene.add(marker);
            clusterMarkers.push(marker);
        } else {
            marker.material.map?.dispose();
            marker.material.map = createClusterTexture(cluster.units.length);
        }
        marker.position.copy(centroid);
        marker.position.y = 4;
        marker.visible = true;

        cluster.units.forEach((u) => {
            if (u !== selectedUnit) {
                u.mesh.visible = false;
            }
        });
    });
}

function updateSelectionRing() {
    if (selectedUnit && !isDraggingSelectedUnit) {
        selectionRing.visible = true;
        selectionRing.position.copy(selectedUnit.mesh.position);
    } else {
        selectionRing.visible = false;
    }
}

function updateHudOverlay() {
    hudTick += 1;
    if (hudTick % 6 !== 0) {
        return;
    }

    const nowNode = document.getElementById("tme-datetime");
    if (nowNode) {
        nowNode.textContent = new Date().toLocaleString();
    }

    let enemyAir = 0;
    let enemyGround = 0;
    let enemyNaval = 0;

    units.forEach((unit) => {
        if (unit.side !== "enemy") {
            return;
        }
        if (unit.type === "aircraft" || unit.type === "missile") {
            enemyAir += 1;
            return;
        }
        if (unit.type === "tank" || unit.type === "infantry") {
            enemyGround += 1;
            return;
        }
        enemyNaval += 1;
    });

    const airNode = document.getElementById("tme-air-total");
    const groundNode = document.getElementById("tme-ground-total");
    const navalNode = document.getElementById("tme-naval-total");
    const totalNode = document.getElementById("tme-overall-total");
    if (airNode) airNode.textContent = `Air: ${enemyAir}`;
    if (groundNode) groundNode.textContent = `Ground: ${enemyGround}`;
    if (navalNode) navalNode.textContent = `Naval: ${enemyNaval}`;
    if (totalNode) totalNode.textContent = `Total: ${enemyAir + enemyGround + enemyNaval}`;

    const coordNode = document.getElementById("tme-coord-readout");
    if (coordNode) {
        if (selectedUnit?.mesh?.position) {
            coordNode.textContent = `X=${selectedUnit.mesh.position.x.toFixed(2)}  Z=${selectedUnit.mesh.position.z.toFixed(2)}`;
        } else {
            coordNode.textContent = `X=${controls.target.x.toFixed(2)}  Z=${controls.target.z.toFixed(2)}`;
        }
    }

    const miniCanvas = document.getElementById("tme-mini-canvas");
    if (!(miniCanvas instanceof HTMLCanvasElement)) {
        renderIncidentTicker();
        return;
    }

    const miniCtx = miniCanvas.getContext("2d");
    if (!miniCtx) {
        return;
    }

    const width = miniCanvas.width;
    const height = miniCanvas.height;
    miniCtx.clearRect(0, 0, width, height);
    miniCtx.fillStyle = "rgba(2, 8, 16, 0.82)";
    miniCtx.fillRect(0, 0, width, height);
    miniCtx.strokeStyle = "rgba(0, 255, 255, 0.28)";
    miniCtx.lineWidth = 1;
    miniCtx.strokeRect(0.5, 0.5, width - 1, height - 1);

    const toMini = (value, domain, size) => {
        const normalized = (value + (domain / 2)) / domain;
        return Math.max(2, Math.min(size - 2, normalized * size));
    };

    units.forEach((unit) => {
        const x = toMini(unit.mesh.position.x, 540, width);
        const y = toMini(-unit.mesh.position.z, 260, height);
        miniCtx.beginPath();
        miniCtx.arc(x, y, unit === selectedUnit ? 3 : 2, 0, Math.PI * 2);
        if (unit.side === "friendly") {
            miniCtx.fillStyle = "rgba(0, 255, 255, 0.95)";
        } else if (unit.side === "enemy") {
            miniCtx.fillStyle = "rgba(255, 72, 72, 0.95)";
        } else {
            miniCtx.fillStyle = "rgba(255, 220, 90, 0.9)";
        }
        miniCtx.fill();
    });
    renderIncidentTicker();
}

function createOverlayTextSprite(text, color = "rgba(159, 255, 255, 0.95)") {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 72;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
        return null;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(0, 10, 20, 0.72)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(0, 255, 255, 0.45)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
    ctx.fillStyle = color;
    ctx.font = "bold 22px Inter, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);

    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(12, 3.2, 1);
    return sprite;
}

function addOverlayObject(layer, object3d, shouldPulse = false) {
    const group = tacticalLayerGroups[layer] || tacticalLayerGroups.SIGINT;
    group.add(object3d);
    if (shouldPulse) {
        tacticalPulseTargets.push(object3d);
    }
}

function clearOverlayGroup(group) {
    while (group.children.length > 0) {
        const child = group.children.pop();
        if (!child) {
            continue;
        }
        group.remove(child);
        if (child.geometry) {
            child.geometry.dispose();
        }
        if (child.material) {
            if (Array.isArray(child.material)) {
                child.material.forEach((m) => {
                    if (m.map) {
                        m.map.dispose();
                    }
                    m.dispose();
                });
            } else {
                if (child.material.map) {
                    child.material.map.dispose();
                }
                child.material.dispose();
            }
        }
        if (Array.isArray(child.children)) {
            child.children.forEach((nested) => {
                if (nested.material?.map) {
                    nested.material.map.dispose();
                }
                nested.material?.dispose?.();
                nested.geometry?.dispose?.();
            });
        }
    }
}

function clearTacticalOverlays() {
    Object.values(tacticalLayerGroups).forEach((group) => clearOverlayGroup(group));
    tacticalPulseTargets.length = 0;
}

function getNearestUnit(sourceUnit, candidates) {
    let nearest = null;
    let minDistSq = Infinity;
    candidates.forEach((candidate) => {
        const distSq = sourceUnit.mesh.position.distanceToSquared(candidate.mesh.position);
        if (distSq < minDistSq) {
            minDistSq = distSq;
            nearest = candidate;
        }
    });
    return nearest;
}

function buildTacticalOverlays() {
    clearTacticalOverlays();

    const enemyUnits = units.filter((unit) => unit.side === "enemy");
    const friendlyUnits = units.filter((unit) => unit.side === "friendly");

    const fallbackObjectives = [
        { label: "OBJ-A", x: -120, z: 40, color: 0x33f7ff },
        { label: "OBJ-B", x: 30, z: -20, color: 0x33f7ff },
        { label: "OBJ-C", x: 140, z: 55, color: 0xff6f6f },
    ];

    if (enemyUnits.length === 0 && friendlyUnits.length === 0) {
        fallbackObjectives.forEach((entry) => {
            const ring = new THREE.Mesh(
                new THREE.RingGeometry(8, 9.2, 36),
                new THREE.MeshBasicMaterial({ color: entry.color, side: THREE.DoubleSide, transparent: true, opacity: 0.8 }),
            );
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(entry.x, 0.2, entry.z);
            addOverlayObject("SIGINT", ring, true);
            const label = createOverlayTextSprite(entry.label);
            if (label) {
                label.position.set(entry.x, 5.8, entry.z);
                addOverlayObject("SIGINT", label);
            }
        });
        return;
    }

    // Helper centroid function used by dynamic overlays.
    const createCentroid = (entries) => {
        const centroid = new THREE.Vector3();
        entries.forEach((entry) => centroid.add(entry.mesh.position));
        centroid.divideScalar(Math.max(1, entries.length));
        return centroid;
    };

    // SIGINT: uncertainty ellipses around highest-priority threats.
    enemyUnits
        .slice()
        .sort((a, b) => b.mesh.position.lengthSq() - a.mesh.position.lengthSq())
        .slice(0, 8)
        .forEach((unit, index) => {
            const ring = new THREE.Mesh(
                new THREE.RingGeometry(7 + (index % 3), 8.3 + (index % 3), 36),
                new THREE.MeshBasicMaterial({
                    color: 0x9ee7b2,
                    transparent: true,
                    opacity: 0.45,
                    side: THREE.DoubleSide,
                }),
            );
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(unit.mesh.position.x, 0.23, unit.mesh.position.z);
            addOverlayObject("SIGINT", ring, true);
        });

    // SAT: vector routes + orbital revisit cones over hostile clusters.
    const routePairs = [];
    friendlyUnits.slice(0, 5).forEach((friendly) => {
        const nearestEnemy = getNearestUnit(friendly, enemyUnits);
        if (!nearestEnemy) {
            return;
        }
        routePairs.push({ from: friendly, to: nearestEnemy });
    });

    routePairs.forEach((pair) => {
        const start = pair.from.mesh.position.clone();
        const end = pair.to.mesh.position.clone();
        const control = new THREE.Vector3(
            (start.x + end.x) / 2,
            12,
            (start.z + end.z) / 2,
        );
        const curve = new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(start.x, 0.25, start.z),
            control,
            new THREE.Vector3(end.x, 0.25, end.z),
        );
        const points = curve.getPoints(42);
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(
            geometry,
            new THREE.LineDashedMaterial({
                color: 0x7fffd4,
                dashSize: 4,
                gapSize: 2,
                transparent: true,
                opacity: 0.74,
            }),
        );
        line.computeLineDistances();
        addOverlayObject("SAT", line);
    });
    enemyUnits.slice(0, 4).forEach((enemy, index) => {
        const cone = new THREE.Mesh(
            new THREE.ConeGeometry(4 + (index * 0.3), 18, 20, 1, true),
            new THREE.MeshBasicMaterial({
                color: 0x8fe6ff,
                transparent: true,
                opacity: 0.18,
                side: THREE.DoubleSide,
                depthWrite: false,
            }),
        );
        cone.position.set(enemy.mesh.position.x, 9.2, enemy.mesh.position.z);
        cone.rotation.x = Math.PI;
        addOverlayObject("SAT", cone);
    });

    // THREAT: heat volumes around enemy units.
    enemyUnits.slice(0, 12).forEach((enemy) => {
        const volume = new THREE.Mesh(
            new THREE.CylinderGeometry(2.8, 5.2, 10, 18),
            new THREE.MeshBasicMaterial({
                color: 0xff5f5f,
                transparent: true,
                opacity: 0.19,
                depthWrite: false,
            }),
        );
        volume.position.set(enemy.mesh.position.x, 5.1, enemy.mesh.position.z);
        addOverlayObject("THREAT", volume);
    });

    // BLUE_FORCE: protective sectors around friendly groups.
    friendlyUnits.slice(0, 8).forEach((friendly) => {
        const sector = new THREE.Mesh(
            new THREE.CircleGeometry(11, 32, -Math.PI / 3, (Math.PI * 2) / 3),
            new THREE.MeshBasicMaterial({
                color: 0x4ecf8d,
                transparent: true,
                opacity: 0.2,
                side: THREE.DoubleSide,
                depthWrite: false,
            }),
        );
        sector.rotation.x = -Math.PI / 2;
        sector.rotation.z = ((friendly.mesh.position.x + friendly.mesh.position.z) * 0.01) % (Math.PI * 2);
        sector.position.set(friendly.mesh.position.x, 0.21, friendly.mesh.position.z);
        addOverlayObject("BLUE_FORCE", sector);
    });

    // JAMMED/THREAT corridors between centroids.
    if (friendlyUnits.length > 0 && enemyUnits.length > 0) {
        const friendlyCore = createCentroid(friendlyUnits);
        const enemyCore = createCentroid(enemyUnits);
        const direction = enemyCore.clone().sub(friendlyCore);
        const corridorLength = Math.max(16, direction.length());
        const corridorMid = friendlyCore.clone().add(enemyCore).multiplyScalar(0.5);
        const corridor = new THREE.Mesh(
            new THREE.PlaneGeometry(corridorLength, 26),
            new THREE.MeshBasicMaterial({
                color: 0xff2d2d,
                transparent: true,
                opacity: 0.14,
                side: THREE.DoubleSide,
                depthWrite: false,
            }),
        );
        corridor.rotation.x = -Math.PI / 2;
        corridor.rotation.z = Math.atan2(direction.z, direction.x);
        corridor.position.set(corridorMid.x, 0.12, corridorMid.z);
        addOverlayObject("JAMMED", corridor);

        const threatSpine = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(friendlyCore.x, 1.6, friendlyCore.z),
                new THREE.Vector3(corridorMid.x, 6.8, corridorMid.z),
                new THREE.Vector3(enemyCore.x, 1.6, enemyCore.z),
            ]),
            new THREE.LineBasicMaterial({
                color: 0xff7e7e,
                transparent: true,
                opacity: 0.62,
            }),
        );
        addOverlayObject("THREAT", threatSpine);

        const jamDome = new THREE.Mesh(
            new THREE.SphereGeometry(15, 26, 20),
            new THREE.MeshBasicMaterial({
                color: 0xff9b3d,
                transparent: true,
                opacity: 0.11,
                wireframe: true,
                depthWrite: false,
            }),
        );
        jamDome.position.set(corridorMid.x, 6, corridorMid.z);
        addOverlayObject("JAMMED", jamDome, true);
    }
}

function updateTacticalOverlays() {
    tacticalOverlayTick += 1;
    if (tacticalOverlayTick % 12 !== 0) {
        return;
    }

    const signature = units
        .map((unit) => `${unit.id}:${unit.side}:${unit.type}:${unit.mesh.position.x.toFixed(1)}:${unit.mesh.position.z.toFixed(1)}`)
        .sort()
        .join("|");

    if (signature === tacticalOverlaySignature) {
        return;
    }
    tacticalOverlaySignature = signature;
    buildTacticalOverlays();
    applyOverlayVisibility();
}

function applyOverlayVisibility() {
    Object.entries(tacticalLayerGroups).forEach(([layer, group]) => {
        group.visible = overlayVisibility[layer] !== false;
    });
    document.querySelectorAll("[data-layer-toggle]").forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) {
            return;
        }
        const layer = String(button.dataset.layerToggle || "").toUpperCase();
        const isOn = overlayVisibility[layer] !== false;
        button.classList.toggle("is-off", !isOn);
        button.setAttribute("aria-pressed", isOn ? "true" : "false");
    });
}

function setRenderTier(nextTier) {
    if (renderTier === nextTier) {
        return;
    }
    renderTier = nextTier;
    if (document.body) {
        document.body.dataset.renderTier = renderTier;
    }
    if (renderTier === "low") {
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1));
        if (globeRuntime?.root) {
            globeRuntime.root.visible = true;
        }
        if (terrainPointCloud) {
            terrainPointCloud.visible = false;
        }
    } else if (renderTier === "medium") {
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.25));
        if (terrainPointCloud) {
            terrainPointCloud.visible = mapMode !== "globe";
        }
    } else {
        renderer.setPixelRatio(window.devicePixelRatio);
        if (terrainPointCloud) {
            terrainPointCloud.visible = mapMode !== "globe";
        }
    }
}

function updateAdaptiveRenderTier(deltaSeconds) {
    fpsAccumulator += deltaSeconds;
    fpsFrameCount += 1;
    if (fpsAccumulator < 1.2) {
        return;
    }
    const fps = fpsFrameCount / Math.max(0.001, fpsAccumulator);
    fpsAccumulator = 0;
    fpsFrameCount = 0;
    if (fps < 28) {
        setRenderTier("low");
    } else if (fps < 45) {
        setRenderTier("medium");
    } else {
        setRenderTier("high");
    }
}

function drilldownApiUrl(countryCode) {
    const code = String(countryCode || "").trim().toUpperCase();
    if (!code) {
        return "";
    }
    const params = new URLSearchParams();
    params.set("max_cities", "15");
    if (planningGuildId) {
        params.set("guild_id", planningGuildId);
    }
    return `/api/tme/country-drilldown/${encodeURIComponent(code)}?${params.toString()}`;
}

function countryStatusApiUrl(countryCode) {
    const code = String(countryCode || "").trim().toUpperCase();
    if (!code) {
        return "";
    }
    const params = new URLSearchParams();
    if (planningGuildId) {
        params.set("guild_id", planningGuildId);
    }
    const query = params.toString();
    return `/api/tme/country-status/${encodeURIComponent(code)}${query ? `?${query}` : ""}`;
}

function statusToColor(status) {
    const normalized = String(status || "contested").toLowerCase();
    if (normalized === "friendly") {
        return 0x72e29a;
    }
    if (normalized === "enemy") {
        return 0xff6f6f;
    }
    return 0xffd88c;
}

function normalizeCountryDrilldownPayload(code, payload, fetchedAt) {
    const now = fetchedAt ?? Date.now();
    return {
        country: {
            iso2: String(payload?.country?.iso2 || ""),
            iso3: String(payload?.country?.iso3 || code),
            name: String(payload?.country?.name || code),
            status: String(payload?.country?.status || "contested"),
        },
        statusState: payload?.status && typeof payload.status === "object"
            ? { ...payload.status }
            : null,
        cities: Array.isArray(payload?.cities)
            ? payload.cities
                .filter((entry) => entry && typeof entry === "object")
                .map((entry) => ({
                    name: String(entry.name || "").trim(),
                    lat: Number(entry.lat || 0),
                    lon: Number(entry.lon || 0),
                    population: Number(entry.population || 0),
                    iso2: String(entry.iso2 || payload?.country?.iso2 || ""),
                    status: String(entry.status || "contested"),
                    statusSource: String(entry.statusSource || "auto"),
                }))
                .filter((entry) => entry.name && Number.isFinite(entry.lat) && Number.isFinite(entry.lon))
            : [],
        fetchedAt: now,
    };
}

function formatTmePopulation(n) {
    const v = Number(n) || 0;
    if (v >= 1_000_000) {
        return `${(v / 1_000_000).toFixed(1)}M`;
    }
    if (v >= 1000) {
        return `${(v / 1000).toFixed(1)}k`;
    }
    return String(Math.max(0, Math.round(v)));
}

async function bootstrapCatalogCitiesLayer() {
    if (mapMode !== "globe" || !globeRuntime || catalogCitiesBootstrapStarted) {
        return;
    }
    catalogCitiesBootstrapStarted = true;
    try {
        const params = new URLSearchParams({ max_cities: "20" });
        if (planningGuildId) {
            params.set("guild_id", planningGuildId);
        }
        const response = await fetch(`/api/tme/catalog-cities?${params.toString()}`, { method: "GET", cache: "no-store" });
        if (!response.ok) {
            throw new Error(`catalog cities ${response.status}`);
        }
        const data = await response.json();
        const etags = data.countryEtags && typeof data.countryEtags === "object" ? data.countryEtags : {};
        Object.entries(etags).forEach(([iso2, tag]) => {
            countryStatusEtags.set(String(iso2).toUpperCase(), String(tag).replaceAll('"', ""));
        });
        const blocks = Array.isArray(data.countries) ? data.countries : [];
        blocks.forEach((block) => {
            const iso3 = String(block?.country?.iso3 || "").trim().toUpperCase();
            if (!iso3) {
                return;
            }
            const normalized = normalizeCountryDrilldownPayload(iso3, block, Date.now());
            countryDrilldownCache.set(iso3, normalized);
        });
        renderAllCatalogCityMarkers();
        updateCountryDrilldownUi();
    } catch (error) {
        console.error("Unable to bootstrap catalog cities", error);
        catalogCitiesBootstrapStarted = false;
    }
}

function renderAllCatalogCityMarkers() {
    clearOverlayGroup(cityMarkerGroup);
    clearOverlayGroup(cityLabelGroup);
    cityMarkerTargets.length = 0;
    const radius = (globeRuntime?.earthRadius || 260) * 1.018;
    countryDrilldownCache.forEach((cached, iso3) => {
        const cities = cached.cities || [];
        cities.forEach((city) => {
            const position = latLonToVector3(city.lat, city.lon, radius);
            const marker = new THREE.Mesh(
                new THREE.SphereGeometry(0.4, 6, 6),
                new THREE.MeshBasicMaterial({
                    color: statusToColor(city.status),
                    transparent: true,
                    opacity: 0.9,
                    depthTest: true,
                    depthWrite: false,
                }),
            );
            marker.position.set(position.x, position.y, position.z);
            marker.userData.cityName = city.name;
            marker.userData.countryIso3 = iso3;
            marker.userData.countryIso2 = String(city.iso2 || cached.country.iso2 || "");
            marker.userData.countryName = String(cached.country.name || "");
            marker.userData.population = Number(city.population || 0);
            cityMarkerGroup.add(marker);
            cityMarkerTargets.push(marker);
        });
    });
}

function refreshCatalogCityDotColors() {
    cityMarkerTargets.forEach((marker) => {
        const iso3 = marker.userData.countryIso3;
        const name = marker.userData.cityName;
        const cached = countryDrilldownCache.get(iso3);
        const city = cached?.cities?.find((c) => c.name === name);
        if (city?.status && marker.material?.color) {
            marker.material.color.setHex(statusToColor(city.status));
        }
    });
}

function hideCityPopover() {
    cityPopoverVisible = false;
    const el = document.getElementById("tme-city-popover");
    if (el instanceof HTMLElement) {
        el.style.display = "none";
        el.setAttribute("aria-hidden", "true");
    }
}

function showCityPopoverFromHit(userData, worldPoint) {
    const pop = document.getElementById("tme-city-popover");
    const countryEl = document.getElementById("tme-city-popover-country");
    const cityEl = document.getElementById("tme-city-popover-city");
    const popEl = document.getElementById("tme-city-popover-population");
    if (!(pop instanceof HTMLElement) || !countryEl || !cityEl || !popEl) {
        return;
    }
    cityPopoverWorld.copy(worldPoint);
    cityPopoverVisible = true;
    countryEl.textContent = String(userData.countryName || "");
    cityEl.textContent = String(userData.cityName || "");
    const popn = Number(userData.population || 0);
    popEl.textContent = popn > 0 ? `Population: ${formatTmePopulation(popn)}` : "Population: —";
    pop.style.display = "flex";
    pop.setAttribute("aria-hidden", "false");
    updateCityPopoverScreenPosition();
}

function updateCityPopoverScreenPosition() {
    if (!cityPopoverVisible) {
        return;
    }
    const pop = document.getElementById("tme-city-popover");
    if (!(pop instanceof HTMLElement)) {
        return;
    }
    const rect = renderer.domElement.getBoundingClientRect();
    const v = cityPopoverWorld.clone().project(camera);
    const x = rect.left + ((v.x * 0.5) + 0.5) * rect.width;
    const y = rect.top + ((-v.y * 0.5) + 0.5) * rect.height;
    const offsetX = 18;
    const offsetY = -18;
    pop.style.left = `${Math.round(THREE.MathUtils.clamp(x + offsetX, 8, window.innerWidth - pop.offsetWidth - 8))}px`;
    pop.style.top = `${Math.round(THREE.MathUtils.clamp(y + offsetY, 8, window.innerHeight - pop.offsetHeight - 8))}px`;
}

function clearCountryDrilldownVisuals() {
    clearOverlayGroup(cityMarkerGroup);
    clearOverlayGroup(cityLabelGroup);
    cityMarkerTargets.length = 0;
}

function createCityLabelSprite(name) {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 62;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
        return null;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(5, 12, 18, 0.82)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(154, 231, 183, 0.6)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
    ctx.fillStyle = "rgba(227, 255, 224, 0.95)";
    ctx.font = "bold 22px Inter, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(name || "").slice(0, 22), canvas.width / 2, canvas.height / 2);
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(20, 4.8, 1);
    return sprite;
}

function updateCountryDrilldownUi() {
    const countryNode = document.getElementById("tme-drilldown-country-name");
    const cityCountNode = document.getElementById("tme-drilldown-city-count");
    const countryStatusSelect = document.getElementById("tme-country-status-select");
    const citySelect = document.getElementById("tme-city-select");
    const cityStatusSelect = document.getElementById("tme-city-status-select");
    if (countryNode) {
        countryNode.textContent = activeCountryDrilldownName || "none";
    }
    if (cityCountNode) {
        cityCountNode.textContent = String(activeDrilldownCities.length);
    }
    if (citySelect instanceof HTMLSelectElement) {
        const current = citySelect.value;
        citySelect.innerHTML = '<option value="">none</option>';
        activeDrilldownCities.forEach((city) => {
            const option = document.createElement("option");
            option.value = city.name;
            option.textContent = `${city.name} (${city.status})`;
            citySelect.appendChild(option);
        });
        if (selectedCityName && activeDrilldownCities.some((city) => city.name === selectedCityName)) {
            citySelect.value = selectedCityName;
        } else if (current && activeDrilldownCities.some((city) => city.name === current)) {
            citySelect.value = current;
            selectedCityName = current;
        } else {
            citySelect.value = "";
            selectedCityName = "";
        }
    }
    const selectedCity = activeDrilldownCities.find((city) => city.name === selectedCityName);
    if (countryStatusSelect instanceof HTMLSelectElement && activeCountryDrilldownIso3) {
        const cached = countryDrilldownCache.get(activeCountryDrilldownIso3);
        countryStatusSelect.value = String(
            cached?.statusState?.effectiveCountryStatus
            || cached?.country?.status
            || "contested",
        );
    }
    if (cityStatusSelect instanceof HTMLSelectElement) {
        cityStatusSelect.value = String(selectedCity?.status || "contested");
    }
}

function renderCountryDrilldownCities() {
    renderAllCatalogCityMarkers();
}

function clearCountryDrilldownState() {
    activeCountryDrilldownIso3 = "";
    activeCountryDrilldownIso2 = "";
    activeCountryDrilldownName = "";
    activeDrilldownCities = [];
    selectedCityName = "";
    hideCityPopover();
    if (globeRuntime) {
        globeRuntime.setSelectedCountry("", "contested");
    }
    updateCountryDrilldownUi();
}

async function fetchCountryDrilldown(countryIso3) {
    const code = String(countryIso3 || "").trim().toUpperCase();
    if (!code || mapMode !== "globe") {
        return;
    }
    const now = Date.now();
    const cached = countryDrilldownCache.get(code);
    if (cached && (now - cached.fetchedAt) < DRILLDOWN_CACHE_TTL_MS) {
        activeCountryDrilldownIso3 = code;
        activeCountryDrilldownIso2 = cached.country.iso2 || "";
        activeCountryDrilldownName = cached.country.name || code;
        activeDrilldownCities = cached.cities.slice();
        if (globeRuntime) {
            globeRuntime.setSelectedCountry(code, cached.country.status || "contested");
        }
        renderAllCatalogCityMarkers();
        updateCountryDrilldownUi();
        return;
    }
    const url = drilldownApiUrl(code);
    if (!url) {
        return;
    }
    const response = await fetch(url, { method: "GET", cache: "no-store" });
    if (!response.ok) {
        throw new Error(`Country drilldown failed (${response.status})`);
    }
    const responseEtag = response.headers.get("ETag");
    const payload = await response.json();
    const normalized = normalizeCountryDrilldownPayload(code, payload, now);
    countryDrilldownCache.set(code, normalized);
    activeCountryDrilldownIso3 = code;
    activeCountryDrilldownIso2 = normalized.country.iso2;
    activeCountryDrilldownName = normalized.country.name;
    activeDrilldownCities = normalized.cities.slice();
    if (globeRuntime) {
        globeRuntime.setSelectedCountry(code, normalized.country.status || "contested");
    }
    if (responseEtag && normalized.country.iso2) {
        countryStatusEtags.set(normalized.country.iso2.toUpperCase(), responseEtag.replaceAll('"', ""));
    }
    renderAllCatalogCityMarkers();
    updateCountryDrilldownUi();
}

function scheduleCountryDrilldownFetch(countryIso3) {
    if (drilldownFetchTimerId) {
        window.clearTimeout(drilldownFetchTimerId);
        drilldownFetchTimerId = null;
    }
    drilldownFetchTimerId = window.setTimeout(() => {
        drilldownFetchTimerId = null;
        drilldownLastFetchAt = Date.now();
        void fetchCountryDrilldown(countryIso3).catch((error) => {
            console.error("Unable to load country drilldown", error);
        });
    }, DRILLDOWN_FETCH_DEBOUNCE_MS);
}

async function persistCountryStatusOverrides(countryIso2, payload) {
    const url = countryStatusApiUrl(countryIso2);
    if (!url || !canEditWaspMap || !planningGuildId) {
        return null;
    }
    const headers = { "Content-Type": "application/json" };
    const etag = countryStatusEtags.get(String(countryIso2 || "").toUpperCase());
    if (etag) {
        headers["If-Match"] = etag;
    }
    const response = await fetch(url, {
        method: "PUT",
        headers,
        body: JSON.stringify(payload),
    });
    const nextEtag = response.headers.get("ETag");
    if (response.status === 409) {
        const conflict = await response.json();
        if (nextEtag) {
            countryStatusEtags.set(String(countryIso2 || "").toUpperCase(), nextEtag.replaceAll('"', ""));
        }
        return { conflict };
    }
    if (!response.ok) {
        throw new Error(`Country status update failed (${response.status})`);
    }
    const nextPayload = await response.json();
    if (nextEtag) {
        countryStatusEtags.set(String(countryIso2 || "").toUpperCase(), nextEtag.replaceAll('"', ""));
    }
    return nextPayload;
}

function planningApiUrl() {
    if (!planningGuildId) {
        return "";
    }
    return `/api/wasp-map/guild/${encodeURIComponent(planningGuildId)}/planning`;
}

function setPlanningSaveStatusUi(state) {
    const node = document.getElementById("tme-planning-save-state");
    if (node) {
        node.textContent = state;
    }
}

function updatePlanningSummaryUi() {
    const countNode = document.getElementById("tme-plan-count");
    const guildNode = document.getElementById("tme-planning-guild-state");
    const count = planningObjects.routes.length + planningObjects.zones.length + planningObjects.annotations.length;
    if (countNode) {
        countNode.textContent = String(count);
    }
    if (guildNode) {
        guildNode.textContent = planningGuildId || "No guild selected";
    }
    const selectedNode = document.getElementById("tme-selected-plan-id");
    if (selectedNode) {
        selectedNode.textContent = selectedPlanningObjectId
            ? `${selectedPlanningObjectType || "plan"} · ${selectedPlanningObjectId}`
            : "none";
    }
}

function planningObjectId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`;
}

function planningRouteMaterial() {
    return new THREE.LineDashedMaterial({
        color: 0xa8ffca,
        dashSize: 4,
        gapSize: 2,
        transparent: true,
        opacity: 0.88,
    });
}

function clearPlanningSceneLayer() {
    clearOverlayGroup(planningGroup);
}

function renderPlanningObjects() {
    clearPlanningSceneLayer();
    const addVertex = (point, color = 0xa8ffca, size = 1.4) => {
        const marker = new THREE.Mesh(
            new THREE.SphereGeometry(size, 10, 10),
            new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 }),
        );
        marker.position.set(point.x, 0.7, point.z);
        planningGroup.add(marker);
        return marker;
    };

    planningObjects.routes.forEach((route) => {
        const worldPoints = safeArray(route?.waypoints).map((entry) => new THREE.Vector3(
            toNumber(entry?.x),
            0.35,
            toNumber(entry?.z),
        ));
        if (worldPoints.length < 2) {
            return;
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(worldPoints);
        const line = new THREE.Line(geometry, planningRouteMaterial());
        line.computeLineDistances();
        line.userData.planId = route.id;
        line.userData.planType = "route";
        planningGroup.add(line);
        worldPoints.forEach((point) => {
            const marker = addVertex(point, 0x8fe6ff, route.id === selectedPlanningObjectId ? 1.9 : 1.4);
            marker.userData.planId = route.id;
            marker.userData.planType = "route";
        });
    });

    planningObjects.zones.forEach((zone) => {
        const points = safeArray(zone?.points).map((entry) => new THREE.Vector2(
            toNumber(entry?.x),
            toNumber(entry?.z),
        ));
        if (points.length < 3) {
            return;
        }
        const shape = new THREE.Shape(points);
        const geometry = new THREE.ShapeGeometry(shape);
        const mesh = new THREE.Mesh(
            geometry,
            new THREE.MeshBasicMaterial({
                color: 0xff8d66,
                transparent: true,
                opacity: zone.id === selectedPlanningObjectId ? 0.36 : 0.2,
                side: THREE.DoubleSide,
                depthWrite: false,
            }),
        );
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.y = 0.16;
        mesh.userData.planId = zone.id;
        mesh.userData.planType = "zone";
        planningGroup.add(mesh);
        points.forEach((point) => {
            const marker = addVertex({ x: point.x, z: point.y }, 0xffc3ad, zone.id === selectedPlanningObjectId ? 1.9 : 1.4);
            marker.userData.planId = zone.id;
            marker.userData.planType = "zone";
        });
    });

    planningObjects.annotations.forEach((annotation) => {
        const label = createOverlayTextSprite(annotation.title || "NOTE", "rgba(213, 255, 187, 0.98)");
        if (!label) {
            return;
        }
        label.position.set(toNumber(annotation.x), 4.8, toNumber(annotation.z));
        label.scale.set(8.4, 2.2, 1);
        label.userData.planId = annotation.id;
        label.userData.planType = "annotation";
        planningGroup.add(label);
        const marker = addVertex({ x: annotation.x, z: annotation.z }, annotation.id === selectedPlanningObjectId ? 0xddff8f : 0xb7ff9c, annotation.id === selectedPlanningObjectId ? 2 : 1.5);
        marker.userData.planId = annotation.id;
        marker.userData.planType = "annotation";
    });
}

function getPlanningObjectById(id) {
    if (!id) {
        return null;
    }
    const route = planningObjects.routes.find((entry) => entry.id === id);
    if (route) {
        return { type: "route", entry: route };
    }
    const zone = planningObjects.zones.find((entry) => entry.id === id);
    if (zone) {
        return { type: "zone", entry: zone };
    }
    const annotation = planningObjects.annotations.find((entry) => entry.id === id);
    if (annotation) {
        return { type: "annotation", entry: annotation };
    }
    return null;
}

function syncPlanningEditorInputs() {
    const labelInput = document.getElementById("tme-plan-label-input");
    const statusInput = document.getElementById("tme-plan-status-input");
    const priorityInput = document.getElementById("tme-plan-priority-input");
    if (!(labelInput instanceof HTMLInputElement) || !(statusInput instanceof HTMLSelectElement) || !(priorityInput instanceof HTMLSelectElement)) {
        return;
    }
    const payload = getPlanningObjectById(selectedPlanningObjectId);
    if (!payload) {
        labelInput.value = "";
        statusInput.value = "active";
        priorityInput.value = "3";
        return;
    }
    if (payload.type === "route") {
        labelInput.value = String(payload.entry.label || "");
        statusInput.value = "active";
        priorityInput.value = "3";
        return;
    }
    if (payload.type === "zone") {
        labelInput.value = String(payload.entry.label || "");
        statusInput.value = String(payload.entry.status || "active");
        priorityInput.value = "3";
        return;
    }
    labelInput.value = String(payload.entry.title || "");
    statusInput.value = "active";
    priorityInput.value = String(payload.entry.priority || 3);
}

function normalizePlanningPayload(payload) {
    const asArray = (value) => (Array.isArray(value) ? value : []);
    const toPoints = (entries) => asArray(entries).map((entry) => ({
        x: Number(toNumber(entry?.x).toFixed(3)),
        z: Number(toNumber(entry?.z).toFixed(3)),
    }));
    planningObjects.routes = asArray(payload?.routes).map((route) => ({
        id: String(route?.id || planningObjectId("route")),
        label: String(route?.label || "Route"),
        waypoints: toPoints(route?.waypoints),
    })).filter((route) => route.waypoints.length >= 2);
    planningObjects.zones = asArray(payload?.zones).map((zone) => ({
        id: String(zone?.id || planningObjectId("zone")),
        label: String(zone?.label || "Zone"),
        threatType: String(zone?.threatType || "unknown"),
        status: String(zone?.status || "active"),
        points: toPoints(zone?.points),
    })).filter((zone) => zone.points.length >= 3);
    planningObjects.annotations = asArray(payload?.annotations).map((annotation) => ({
        id: String(annotation?.id || planningObjectId("annotation")),
        title: String(annotation?.title || "NOTE"),
        note: String(annotation?.note || ""),
        priority: Number.isFinite(Number(annotation?.priority)) ? Math.max(1, Math.min(5, Number(annotation.priority))) : 3,
        x: Number(toNumber(annotation?.x).toFixed(3)),
        z: Number(toNumber(annotation?.z).toFixed(3)),
    }));
    if (typeof payload?.phase === "string" && MISSION_PHASE_ORDER.includes(payload.phase.toLowerCase())) {
        currentMissionPhase = payload.phase.toLowerCase();
    }
    if (selectedPlanningObjectId && !getPlanningObjectById(selectedPlanningObjectId)) {
        selectedPlanningObjectId = "";
        selectedPlanningObjectType = "";
    }
    planningVersion += 1;
    updatePlanningSummaryUi();
    syncPlanningEditorInputs();
    renderPlanningObjects();
    renderMissionPhaseUi();
}

function serializePlanningPayload() {
    return {
        version: planningVersion,
        phase: currentMissionPhase,
        routes: planningObjects.routes.map((entry) => ({
            id: entry.id,
            label: entry.label,
            waypoints: entry.waypoints.map((point) => ({ x: point.x, z: point.z })),
        })),
        zones: planningObjects.zones.map((entry) => ({
            id: entry.id,
            label: entry.label,
            threatType: entry.threatType,
            status: entry.status,
            points: entry.points.map((point) => ({ x: point.x, z: point.z })),
        })),
        annotations: planningObjects.annotations.map((entry) => ({
            id: entry.id,
            title: entry.title,
            note: entry.note,
            priority: entry.priority,
            x: entry.x,
            z: entry.z,
        })),
    };
}

async function savePlanningState() {
    const url = planningApiUrl();
    if (!url || !canEditWaspMap) {
        return;
    }
    if (isSavingPlanningState) {
        pendingPlanningSave = true;
        return;
    }
    isSavingPlanningState = true;
    setPlanningSaveStatusUi("Saving...");
    const headers = { "Content-Type": "application/json" };
    if (planningEtag) {
        headers["If-Match"] = planningEtag;
    }
    const response = await fetch(url, {
        method: "PUT",
        headers,
        body: JSON.stringify(serializePlanningPayload()),
    });
    const nextEtag = response.headers.get("ETag");
    if (response.status === 409) {
        const payload = await response.json();
        planningEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
        normalizePlanningPayload(payload?.state || {});
        isSavingPlanningState = false;
        setPlanningSaveStatusUi("Conflict resolved");
        if (pendingPlanningSave) {
            pendingPlanningSave = false;
            return savePlanningState();
        }
        return;
    }
    if (!response.ok) {
        isSavingPlanningState = false;
        setPlanningSaveStatusUi(`Error (${response.status})`);
        throw new Error(`Planning save failed (${response.status})`);
    }
    const payload = await response.json();
    planningEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
    normalizePlanningPayload(payload);
    isSavingPlanningState = false;
    setPlanningSaveStatusUi("Synced");
    if (pendingPlanningSave) {
        pendingPlanningSave = false;
        return savePlanningState();
    }
}

function queuePlanningSave(reason = "change") {
    if (!planningApiUrl() || !canEditWaspMap) {
        return;
    }
    if (planningSaveTimerId) {
        window.clearTimeout(planningSaveTimerId);
    }
    setPlanningSaveStatusUi(`Pending (${reason})`);
    planningSaveTimerId = window.setTimeout(() => {
        planningSaveTimerId = null;
        void savePlanningState().catch((error) => {
            console.error("Unable to save planning state", error);
        });
    }, 450);
}

async function loadPlanningState() {
    const url = planningApiUrl();
    if (!url) {
        updatePlanningSummaryUi();
        return;
    }
    const headers = {};
    if (planningEtag) {
        headers["If-None-Match"] = planningEtag;
    }
    const response = await fetch(url, {
        method: "GET",
        headers,
        cache: "no-store",
    });
    if (response.status === 304) {
        return;
    }
    if (!response.ok) {
        throw new Error(`Planning load failed (${response.status})`);
    }
    const payload = await response.json();
    const etag = response.headers.get("ETag");
    planningEtag = etag ? etag.replaceAll('"', "") : null;
    normalizePlanningPayload(payload);
    setPlanningSaveStatusUi("Loaded");
}

function setPlanningMode(mode = "none") {
    const normalized = String(mode || "none").toLowerCase();
    if (!canEditWaspMap && normalized !== "none") {
        return;
    }
    planningMode = normalized;
    planningDrawDraft = [];
    document.querySelectorAll(".tme-plan-btn").forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) {
            return;
        }
        const id = button.id || "";
        const isActive = (
            (normalized === "route" && id === "plan-mode-route")
            || (normalized === "zone" && id === "plan-mode-zone")
            || (normalized === "annotation" && id === "plan-mode-annotation")
        );
        button.classList.toggle("is-active", isActive);
    });
    updateInteractionStatus();
}

function commitRouteDraft() {
    if (planningDrawDraft.length < 2) {
        return;
    }
    planningObjects.routes.push({
        id: planningObjectId("route"),
        label: `Route ${planningObjects.routes.length + 1}`,
        waypoints: planningDrawDraft.map((point) => ({ x: Number(point.x.toFixed(3)), z: Number(point.z.toFixed(3)) })),
    });
    planningDrawDraft = [];
    planningVersion += 1;
    updatePlanningSummaryUi();
    renderPlanningObjects();
    queuePlanningSave("route");
}

function commitZoneDraft() {
    if (planningDrawDraft.length < 3) {
        return;
    }
    planningObjects.zones.push({
        id: planningObjectId("zone"),
        label: `Zone ${planningObjects.zones.length + 1}`,
        threatType: "hostile",
        status: "active",
        points: planningDrawDraft.map((point) => ({ x: Number(point.x.toFixed(3)), z: Number(point.z.toFixed(3)) })),
    });
    planningDrawDraft = [];
    planningVersion += 1;
    updatePlanningSummaryUi();
    renderPlanningObjects();
    queuePlanningSave("zone");
}

function addAnnotationAt(point) {
    const title = window.prompt("Annotation title", `Note ${planningObjects.annotations.length + 1}`) || "";
    if (!title.trim()) {
        return;
    }
    const note = window.prompt("Brief note", "") || "";
    const priorityRaw = window.prompt("Priority (1-5)", "3");
    const parsedPriority = Number.parseInt(String(priorityRaw || "3"), 10);
    planningObjects.annotations.push({
        id: planningObjectId("annotation"),
        title: title.trim(),
        note: note.trim(),
        priority: Number.isFinite(parsedPriority) ? Math.max(1, Math.min(5, parsedPriority)) : 3,
        x: Number(point.x.toFixed(3)),
        z: Number(point.z.toFixed(3)),
    });
    planningVersion += 1;
    updatePlanningSummaryUi();
    renderPlanningObjects();
    queuePlanningSave("annotation");
}

function deleteSelectedPlanningObject() {
    if (!selectedPlanningObjectId) {
        return;
    }
    const removeById = (entry) => entry.id !== selectedPlanningObjectId;
    planningObjects.routes = planningObjects.routes.filter(removeById);
    planningObjects.zones = planningObjects.zones.filter(removeById);
    planningObjects.annotations = planningObjects.annotations.filter(removeById);
    selectedPlanningObjectId = "";
    selectedPlanningObjectType = "";
    planningVersion += 1;
    updatePlanningSummaryUi();
    syncPlanningEditorInputs();
    renderPlanningObjects();
    queuePlanningSave("delete");
}

function clearPlanningObjects() {
    planningObjects.routes = [];
    planningObjects.zones = [];
    planningObjects.annotations = [];
    selectedPlanningObjectId = "";
    selectedPlanningObjectType = "";
    planningDrawDraft = [];
    planningVersion += 1;
    updatePlanningSummaryUi();
    syncPlanningEditorInputs();
    renderPlanningObjects();
    queuePlanningSave("clear");
}

function detectClickedPlanningObject(intersects) {
    for (const intersect of intersects) {
        const candidate = intersect?.object;
        if (!candidate?.userData?.planId) {
            continue;
        }
        return {
            id: String(candidate.userData.planId),
            type: String(candidate.userData.planType || ""),
        };
    }
    return null;
}

window.toggleOverlayLayer = function toggleOverlayLayer(layer) {
    const key = String(layer || "").toUpperCase();
    if (!(key in overlayVisibility)) {
        return;
    }
    overlayVisibility[key] = !overlayVisibility[key];
    applyOverlayVisibility();
};

window.setMissionPhaseFromUi = function setMissionPhaseFromUi(phase) {
    setMissionPhase(phase);
};

window.setPlanningModeFromUi = function setPlanningModeFromUi(mode) {
    const normalized = String(mode || "").toLowerCase();
    setPlanningMode(planningMode === normalized ? "none" : normalized);
};

window.deleteSelectedPlanningObjectFromUi = function deleteSelectedPlanningObjectFromUi() {
    if (!canEditWaspMap) {
        return;
    }
    deleteSelectedPlanningObject();
};

window.clearPlanningLayerFromUi = function clearPlanningLayerFromUi() {
    if (!canEditWaspMap) {
        return;
    }
    clearPlanningObjects();
};

window.clearAllUnitsFromUi = function clearAllUnitsFromUi() {
    if (!canEditWaspMap) {
        return;
    }
    const confirmed = window.confirm("Clear all units from the tactical map?");
    if (!confirmed) {
        return;
    }
    clearAllUnits();
};

window.applyCountryStatusFromUi = function applyCountryStatusFromUi() {
    if (!activeCountryDrilldownIso3) {
        return;
    }
    const countryStatusSelect = document.getElementById("tme-country-status-select");
    const citySelect = document.getElementById("tme-city-select");
    const cityStatusSelect = document.getElementById("tme-city-status-select");
    const countryStatus = countryStatusSelect instanceof HTMLSelectElement
        ? String(countryStatusSelect.value || "contested")
        : "contested";
    const cityName = citySelect instanceof HTMLSelectElement ? String(citySelect.value || "").trim() : "";
    const cityStatus = cityStatusSelect instanceof HTMLSelectElement
        ? String(cityStatusSelect.value || "contested")
        : "contested";

    const cached = countryDrilldownCache.get(activeCountryDrilldownIso3) || {
        country: {
            iso2: activeCountryDrilldownIso2,
            iso3: activeCountryDrilldownIso3,
            name: activeCountryDrilldownName,
            status: "contested",
        },
        statusState: {
            autoStatus: "contested",
            countryOverride: null,
            cityOverrides: {},
            effectiveCountryStatus: "contested",
        },
        cities: activeDrilldownCities.slice(),
        fetchedAt: Date.now(),
    };
    cached.country.status = countryStatus;
    cached.statusState = cached.statusState || {
        autoStatus: "contested",
        countryOverride: null,
        cityOverrides: {},
        effectiveCountryStatus: countryStatus,
    };
    cached.statusState.countryOverride = countryStatus;
    cached.statusState.effectiveCountryStatus = countryStatus;
    cached.statusState.cityOverrides = cached.statusState.cityOverrides || {};
    if (cityName) {
        cached.statusState.cityOverrides[cityName] = cityStatus;
    }
    cached.cities = (cached.cities || []).map((city) => {
        if (city.name !== cityName) {
            return city;
        }
        return {
            ...city,
            status: cityStatus,
            statusSource: "manual",
        };
    });
    countryDrilldownCache.set(activeCountryDrilldownIso3, cached);
    activeDrilldownCities = cached.cities.slice();
    if (cityName) {
        selectedCityName = cityName;
    }
    if (globeRuntime) {
        globeRuntime.setSelectedCountry(activeCountryDrilldownIso3, countryStatus);
    }
    refreshCatalogCityDotColors();
    updateCountryDrilldownUi();

    const persistPayload = {
        autoStatus: "contested",
        countryOverride: countryStatus,
        cityOverrides: { ...cached.statusState.cityOverrides },
    };
    void persistCountryStatusOverrides(activeCountryDrilldownIso2, persistPayload)
        .then((result) => {
            if (!result || result.conflict) {
                return;
            }
            cached.statusState = {
                ...cached.statusState,
                ...result,
                effectiveCountryStatus: result.effectiveCountryStatus || countryStatus,
            };
            countryDrilldownCache.set(activeCountryDrilldownIso3, cached);
            refreshCatalogCityDotColors();
            updateCountryDrilldownUi();
        })
        .catch((error) => {
            console.error("Unable to persist country status", error);
        });
};

window.addPlanningVertexFromUi = function addPlanningVertexFromUi() {
    if (!canEditWaspMap || !selectedPlanningObjectId) {
        return;
    }
    const payload = getPlanningObjectById(selectedPlanningObjectId);
    if (!payload) {
        return;
    }
    const addOffsetPoint = (points) => {
        const last = points.at(-1);
        const fallback = selectedUnit?.mesh?.position
            ? { x: selectedUnit.mesh.position.x, z: selectedUnit.mesh.position.z }
            : { x: controls.target.x, z: controls.target.z };
        const anchor = last || fallback;
        points.push({ x: Number((anchor.x + 8).toFixed(3)), z: Number((anchor.z + 4).toFixed(3)) });
    };
    if (payload.type === "route") {
        addOffsetPoint(payload.entry.waypoints);
    } else if (payload.type === "zone") {
        addOffsetPoint(payload.entry.points);
    } else {
        return;
    }
    planningVersion += 1;
    renderPlanningObjects();
    updatePlanningSummaryUi();
    queuePlanningSave("vertex-add");
};

window.trimPlanningVertexFromUi = function trimPlanningVertexFromUi() {
    if (!canEditWaspMap || !selectedPlanningObjectId) {
        return;
    }
    const payload = getPlanningObjectById(selectedPlanningObjectId);
    if (!payload) {
        return;
    }
    if (payload.type === "route" && payload.entry.waypoints.length > 2) {
        payload.entry.waypoints.pop();
    } else if (payload.type === "zone" && payload.entry.points.length > 3) {
        payload.entry.points.pop();
    } else {
        return;
    }
    planningVersion += 1;
    renderPlanningObjects();
    updatePlanningSummaryUi();
    queuePlanningSave("vertex-trim");
};

window.applyPlanningMetadataFromUi = function applyPlanningMetadataFromUi() {
    if (!canEditWaspMap || !selectedPlanningObjectId) {
        return;
    }
    const payload = getPlanningObjectById(selectedPlanningObjectId);
    if (!payload) {
        return;
    }
    const labelInput = document.getElementById("tme-plan-label-input");
    const statusInput = document.getElementById("tme-plan-status-input");
    const priorityInput = document.getElementById("tme-plan-priority-input");
    const labelValue = labelInput instanceof HTMLInputElement ? labelInput.value.trim() : "";
    const statusValue = statusInput instanceof HTMLSelectElement ? statusInput.value.trim() : "active";
    const priorityValue = priorityInput instanceof HTMLSelectElement ? Number.parseInt(priorityInput.value, 10) : 3;
    if (payload.type === "route") {
        payload.entry.label = labelValue || payload.entry.label || "Route";
    } else if (payload.type === "zone") {
        payload.entry.label = labelValue || payload.entry.label || "Zone";
        payload.entry.status = statusValue || "active";
    } else if (payload.type === "annotation") {
        payload.entry.title = labelValue || payload.entry.title || "NOTE";
        payload.entry.priority = Number.isFinite(priorityValue) ? Math.max(1, Math.min(5, priorityValue)) : 3;
    }
    planningVersion += 1;
    renderPlanningObjects();
    updatePlanningSummaryUi();
    syncPlanningEditorInputs();
    queuePlanningSave("metadata");
};

/* ANIMATION LOOP */
function animate() {
    requestAnimationFrame(animate);

    const deltaSeconds = keyboardClock.getDelta();
    updateAdaptiveRenderTier(deltaSeconds);
    stepSimulation(deltaSeconds);
    applyKeyboardMapNavigation(deltaSeconds);
    flushQueuedRemoteStateIfSafe();

    cameraController.updateZoomLevel();
    updateLabels();
    resolveLabelOverlap();
    updateClusterMarkers();
    updateSelectionRing();
    updateHudOverlay();
    updateTacticalOverlays();
    updateSpiderfyOverlay();
    if (globeRuntime) {
        globeRuntime.update(deltaSeconds);
    }
    updateCityPopoverScreenPosition();

    if (spiderfyFadeValue !== spiderfyFadeTarget) {
        const fadeDelta = spiderfyFadeTarget - spiderfyFadeValue;
        if (Math.abs(fadeDelta) <= SPIDERFY_FADE_SPEED) {
            spiderfyFadeValue = spiderfyFadeTarget;
        } else {
            spiderfyFadeValue += Math.sign(fadeDelta) * SPIDERFY_FADE_SPEED;
        }
        spiderfyFadeValue = Math.max(0, Math.min(1, spiderfyFadeValue));
        applySpiderfyFadeToOverlay();

        if (spiderfyFadeValue === 0 && spiderfyFadeTarget === 0 && spiderfyOverlayGroup.children.length > 0) {
            clearSpiderfyOverlay();
        }
    }

    if (terrainPointCloud?.material) {
        terrainTick += 0.018;
        terrainPointCloud.material.opacity = 0.52 + (Math.sin(terrainTick) * 0.1);
    }

    if (tacticalPulseTargets.length > 0) {
        const pulse = 0.68 + (Math.sin(terrainTick * 1.7) * 0.22);
        tacticalPulseTargets.forEach((target) => {
            if (target?.material) {
                target.material.opacity = pulse;
            }
        });
    }

    units.forEach((unit) => {
        if (unit.label) {
            unit.label.quaternion.copy(camera.quaternion);
        }
        if (unit.hitPlane) {
            unit.hitPlane.quaternion.copy(camera.quaternion);
        }
    });

    clusterMarkers.forEach((marker) => {
        if (marker.visible) {
            marker.quaternion.copy(camera.quaternion);
        }
    });
    cityLabelGroup.children.forEach((label) => {
        if (label?.quaternion) {
            label.quaternion.copy(camera.quaternion);
        }
    });

    controls.update();
    renderer.render(scene, camera);
}

animate();

/* RESIZE HANDLER */
window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});
