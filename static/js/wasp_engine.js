import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";

const container = document.getElementById("map-container");

if (!container) {
    throw new Error("W.A.S.P map container was not found.");
}

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050b1a);
scene.fog = new THREE.Fog(0x050b1a, 120, 420);

const units = [];
let mapStateEtag = null;
let isApplyingRemoteState = false;
let syncTimerId = null;
const radarRings = [];
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let spawnPosition = null;

let selectedUnit = null;
let placingUnitType = null;
let isMoveMode = false;

const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    1000,
);

camera.position.set(0, 80, 120);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.screenSpacePanning = true;
controls.minDistance = 20;
controls.maxDistance = 400;
controls.maxPolarAngle = Math.PI / 2.1;

/* GRID */
const grid = new THREE.GridHelper(500, 50, 0x00ffff, 0x004444);
scene.add(grid);
grid.material.opacity = 0.25;
grid.material.transparent = true;

/* UNIT FACTORY */
const unitColors = {
    enemy: 0xff0000,
    friendly: 0x00ffff,
    neutral: 0xffff00,
    objective: 0xffff00,
};

const UNIT_ICON_SCALE = 6;

function createIconTexture(type = "infantry") {
    const canvas = document.createElement("canvas");
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");

    if (!ctx) {
        throw new Error("Could not create icon texture context.");
    }

    const centerX = 64;
    const centerY = 64;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(0, 255, 255, 0.55)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(centerX, centerY, 58, 0, Math.PI * 2);
    ctx.stroke();

    ctx.fillStyle = "rgba(225, 245, 255, 0.95)";

    if (type === "aircraft") {
        ctx.beginPath();
        ctx.moveTo(64, 14);
        ctx.lineTo(80, 52);
        ctx.lineTo(112, 64);
        ctx.lineTo(80, 76);
        ctx.lineTo(64, 114);
        ctx.lineTo(48, 76);
        ctx.lineTo(16, 64);
        ctx.lineTo(48, 52);
        ctx.closePath();
        ctx.fill();
    } else if (type === "tank") {
        ctx.fillRect(24, 58, 80, 28);
        ctx.fillRect(34, 44, 54, 18);
        ctx.fillRect(86, 50, 22, 6);
    } else if (type === "missile") {
        ctx.beginPath();
        ctx.moveTo(64, 16);
        ctx.lineTo(80, 40);
        ctx.lineTo(72, 108);
        ctx.lineTo(56, 108);
        ctx.lineTo(48, 40);
        ctx.closePath();
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(48, 40);
        ctx.lineTo(34, 58);
        ctx.lineTo(52, 58);
        ctx.closePath();
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(80, 40);
        ctx.lineTo(94, 58);
        ctx.lineTo(76, 58);
        ctx.closePath();
        ctx.fill();
    } else {
        ctx.beginPath();
        ctx.arc(64, 34, 12, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillRect(56, 46, 16, 42);
        ctx.fillRect(40, 54, 12, 26);
        ctx.fillRect(76, 54, 12, 26);
        ctx.fillRect(52, 88, 10, 22);
        ctx.fillRect(66, 88, 10, 22);
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
}

const icons = {
    aircraft: createIconTexture("aircraft"),
    tank: createIconTexture("tank"),
    infantry: createIconTexture("infantry"),
    missile: createIconTexture("missile"),
};

function resolveUnitColor(side = "enemy") {
    return unitColors[side] ?? unitColors.enemy;
}

function getIconByType(type = "") {
    return icons[type] ?? icons.infantry;
}

function createUnitLabel(name, country) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    canvas.width = 512;
    canvas.height = 128;

    if (!ctx) {
        throw new Error("Could not create label context.");
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(5, 11, 26, 0.62)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(0, 255, 255, 0.72)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);

    ctx.fillStyle = "white";
    ctx.font = "32px monospace";
    ctx.fillText(name, 10, 40);

    ctx.fillStyle = "cyan";
    ctx.fillText(country, 10, 80);

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;

    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
    });

    const sprite = new THREE.Sprite(material);
    sprite.scale.set(15, 4, 1);

    return sprite;
}

function updateUnitVisuals(unit) {
    if (!unit?.mesh?.material) {
        return;
    }

    unit.mesh.material.map = getIconByType(unit.type);
    unit.mesh.material.color.setHex(resolveUnitColor(unit.side));
    unit.mesh.material.needsUpdate = true;
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
        color: resolveUnitColor(unitData.side),
        transparent: true,
    });

    const mesh = new THREE.Sprite(material);
    mesh.scale.set(UNIT_ICON_SCALE, UNIT_ICON_SCALE, 1);
    mesh.position.set(unitData.x, 2, unitData.z);

    const label = createUnitLabel(unitData.name, unitData.country);
    label.position.set(0, 6, 0);
    mesh.add(label);

    scene.add(mesh);

    const unit = {
        id: unitData.id,
        mesh,
        label,
        type: unitData.type,
        name: unitData.name,
        country: unitData.country,
        side: unitData.side,
    };

    mesh.userData = { ...unit };

    units.push(unit);
    return unit;
}

function setSelectedUnit(unit) {
    if (selectedUnit?.mesh?.material?.opacity) {
        selectedUnit.mesh.material.opacity = 1;
    }

    selectedUnit = unit;

    if (selectedUnit?.mesh?.material?.opacity) {
        selectedUnit.mesh.material.opacity = 0.82;
    }

    if (selectedUnit) {
        openUnitPanel(selectedUnit);
    } else {
        openUnitPanel(null);
    }

    updateInteractionStatus();
}

function selectUnitFromClick(intersects) {
    if (intersects.length === 0) {
        setSelectedUnit(null);
        return;
    }

    const mesh = intersects[0].object;
    const unit = units.find((entry) => entry.mesh === mesh);

    if (!unit) {
        return;
    }

    setSelectedUnit(unit);
    console.log("Selected:", unit.name);
}

function toNumber(value, fallback = 0) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : fallback;
}

/* RADAR PULSE */
function createRadarPulse(x, z) {
    const ringGeometry = new THREE.RingGeometry(2, 2.4, 64);

    const ringMaterial = new THREE.MeshBasicMaterial({
        color: 0xff0040,
        transparent: true,
        opacity: 0.9,
        side: THREE.DoubleSide,
    });

    const ring = new THREE.Mesh(ringGeometry, ringMaterial);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(x, 0.1, z);
    ring.userData = {
        scale: 1,
        speed: 0.5,
    };

    scene.add(ring);
    radarRings.push(ring);
    return ring;
}

createRadarPulse(0, 0);

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

const signalMaterial = new THREE.MeshBasicMaterial({
    color: 0xffffff,
});

const signalGeometry = new THREE.SphereGeometry(0.8, 12, 12);
const signals = [];

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
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);

    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const point = new THREE.Vector3();
    const didIntersect = raycaster.ray.intersectPlane(plane, point);

    return didIntersect ? point : null;
}

function setPlacementMode(side = null) {
    placingUnitType = side;
    isMoveMode = false;
    updateInteractionStatus();
}

function enableMoveMode() {
    isMoveMode = selectedUnit !== null;
    placingUnitType = null;
    updateInteractionStatus();
}

function clearInteractionMode() {
    placingUnitType = null;
    isMoveMode = false;
    updateInteractionStatus();
}

function deleteSelectedUnit() {
    if (!selectedUnit) {
        return;
    }

    scene.remove(selectedUnit.mesh);
    const index = units.indexOf(selectedUnit);

    if (index > -1) {
        units.splice(index, 1);
    }

    setSelectedUnit(null);
    clearInteractionMode();
    scheduleStateSync();
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
    if (!selectedUnit) {
        return;
    }

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

function updateInteractionStatus() {
    const selectionNode = document.getElementById("selected-unit");
    const modeNode = document.getElementById("interaction-mode");

    if (selectionNode) {
        selectionNode.textContent = selectedUnit
            ? `${selectedUnit.name} · ${selectedUnit.country} · ${selectedUnit.type}`
            : "None";
    }

    if (modeNode) {
        if (placingUnitType) {
            modeNode.textContent = `Placing ${placingUnitType} units`;
            return;
        }

        if (isMoveMode) {
            modeNode.textContent = "Move selected unit";
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
    if (!spawnPosition) {
        return;
    }

    createUnit({
        type,
        name: `${type.toUpperCase()}-${Math.floor(Math.random() * 100)}`,
        country: "Unknown",
        side: "enemy",
        x: spawnPosition.x,
        z: spawnPosition.z,
    });

    hideSpawnMenu();
    scheduleStateSync();
}

function onMouseClick(event) {
    const clickedInsidePanel = event.target instanceof Element
        && event.target.closest("#admin-panel");

    if (clickedInsidePanel) {
        return;
    }

    const worldPoint = toWorldPointFromMouseClick(event);

    if (!worldPoint) {
        return;
    }

    if (isMoveMode && selectedUnit) {
        selectedUnit.mesh.position.set(worldPoint.x, 2, worldPoint.z);
        isMoveMode = false;
        updateInteractionStatus();
        scheduleStateSync();
        return;
    }

    const meshes = units.map((unit) => unit.mesh);
    const intersects = raycaster.intersectObjects(meshes, false);
    selectUnitFromClick(intersects);

    if (placingUnitType) {
        createUnit({
            type: "infantry",
            name: `${placingUnitType}-unit-${units.length + 1}`,
            country: "Unknown",
            side: placingUnitType,
            x: worldPoint.x,
            z: worldPoint.z,
        });
        scheduleStateSync();
        return;
    }

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

function removeAllUnits() {
    while (units.length) {
        const unit = units.pop();
        if (unit?.mesh) {
            scene.remove(unit.mesh);
        }
    }
    selectedUnit = null;
    isMoveMode = false;
    placingUnitType = null;
    updateInteractionStatus();
}

function applyStateToScene(state) {
    const payloadUnits = Array.isArray(state?.units) ? state.units : [];
    isApplyingRemoteState = true;
    removeAllUnits();
    payloadUnits.forEach((entry) => createUnit(entry));
    isApplyingRemoteState = false;
}

async function fetchSharedState() {
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

    const nextEtag = response.headers.get("ETag");
    const payload = await response.json();
    applyStateToScene(payload);
    mapStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
}

async function persistSharedState() {
    if (isApplyingRemoteState) {
        return;
    }

    const headers = {
        "Content-Type": "application/json",
    };

    if (mapStateEtag) {
        headers["If-Match"] = mapStateEtag;
    }

    const response = await fetch("/api/wasp-map/state", {
        method: "PUT",
        headers,
        body: JSON.stringify({ units: serializeUnits() }),
    });

    const nextEtag = response.headers.get("ETag");

    if (response.status === 409) {
        const conflictPayload = await response.json();
        applyStateToScene(conflictPayload.state);
        mapStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
        return;
    }

    if (!response.ok) {
        throw new Error(`Failed to persist state (${response.status})`);
    }

    mapStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
}

function scheduleStateSync() {
    void persistSharedState().catch((error) => {
        console.error("Unable to persist W.A.S.P shared map state", error);
    });
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
            panelGreeting.textContent = `${timeGreeting}, Operator.`;
        }
    };

    updateClock();
    window.setInterval(updateClock, 1000);
}

updateInteractionStatus();
openUnitPanel(null);

window.addEventListener("contextmenu", (event) => {
    event.preventDefault();

    const clickedInsidePanel = event.target instanceof Element
        && event.target.closest("#admin-panel, #spawn-menu");

    if (clickedInsidePanel) {
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

    menu.style.left = `${event.clientX}px`;
    menu.style.top = `${event.clientY}px`;
    menu.style.display = "block";
});

window.addEventListener("click", (event) => {
    const clickedInsideMenu = event.target instanceof Element
        && event.target.closest("#spawn-menu");

    if (!clickedInsideMenu) {
        hideSpawnMenu();
    }

    onMouseClick(event);
});

void fetchSharedState().catch((error) => {
    console.error("Unable to load shared W.A.S.P map state", error);
});

syncTimerId = window.setInterval(() => {
    void fetchSharedState().catch((error) => {
        console.error("Unable to refresh shared W.A.S.P map state", error);
    });
}, 3000);

createFlightPath(
    { x: -40, z: -20 },
    { x: 40, z: 25 },
);

const signal = new THREE.Mesh(signalGeometry, signalMaterial);
scene.add(signal);

signals.push({
    mesh: signal,
    path: flightPaths[0],
});

/* WORLD MAP LAYER */
async function loadWorldMap() {
    try {
        const response = await fetch("/static/data/world.geo.json");

        if (!response.ok) {
            throw new Error(`Unable to load world map: ${response.status}`);
        }

        const data = await response.json();

        const mapMaterial = new THREE.LineBasicMaterial({
            color: 0x00ffff,
            transparent: true,
            opacity: 0.35,
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
    } catch (error) {
        console.error("World map layer failed to load", error);
    }
}

void loadWorldMap();

/* ANIMATION LOOP */
function animate() {
    requestAnimationFrame(animate);

    units.forEach((unit) => {
        if (unit.label) {
            unit.label.quaternion.copy(camera.quaternion);
        }
    });

    radarRings.forEach((ring) => {
        ring.userData.scale += 0.02;

        ring.scale.set(
            ring.userData.scale,
            ring.userData.scale,
            ring.userData.scale,
        );

        ring.material.opacity = 1 - (ring.userData.scale / 20);

        if (ring.userData.scale > 20) {
            ring.userData.scale = 1;
        }
    });

    signals.forEach((activeSignal) => {
        activeSignal.path.progress += 0.002;

        if (activeSignal.path.progress > 1) {
            activeSignal.path.progress = 0;
        }

        const pos = activeSignal.path.curve.getPoint(activeSignal.path.progress);
        activeSignal.mesh.position.copy(pos);
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
