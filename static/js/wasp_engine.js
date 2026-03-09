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

const DEFAULT_UNIT_SIZE = 1.5;

function resolveUnitColor(side = "enemy") {
    return unitColors[side] ?? unitColors.enemy;
}

function createUnitGeometry(type = "unknown", size = DEFAULT_UNIT_SIZE) {
    switch (type) {
        case "aircraft":
            return new THREE.ConeGeometry(size, size * 2.4, 3);
        case "tank":
            return new THREE.BoxGeometry(size * 2, size * 1.2, size * 2);
        case "infantry":
            return new THREE.SphereGeometry(size * 0.8, 14, 14);
        case "missile":
            return new THREE.ConeGeometry(size * 0.8, size * 2.6, 4);
        case "ship":
            return new THREE.OctahedronGeometry(size * 1.2, 0);
        case "radar":
            return new THREE.CylinderGeometry(size, size, size * 0.8, 6);
        default:
            return new THREE.SphereGeometry(size, 16, 16);
    }
}

function createLabel(text) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    canvas.width = 256;
    canvas.height = 64;

    if (!ctx) {
        throw new Error("Could not create label context.");
    }

    ctx.fillStyle = "rgba(5, 11, 26, 0.55)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(0, 255, 255, 0.85)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
    ctx.fillStyle = "white";
    ctx.font = "28px monospace";
    ctx.fillText(text, 10, 40);

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;

    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
    });

    const sprite = new THREE.Sprite(material);
    sprite.scale.set(10, 3, 1);

    return sprite;
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

    const geometry = createUnitGeometry(unitData.type);
    const material = new THREE.MeshBasicMaterial({
        color: resolveUnitColor(unitData.side),
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(unitData.x, DEFAULT_UNIT_SIZE, unitData.z);

    if (unitData.type === "aircraft" || unitData.type === "missile") {
        mesh.rotation.x = Math.PI;
    }

    const label = createLabel(unitData.name);
    label.position.set(0, 5, 0);
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
    if (selectedUnit?.mesh?.material?.emissive) {
        selectedUnit.mesh.material.emissive.setHex(0x000000);
    }

    selectedUnit = unit;

    if (selectedUnit?.mesh?.material?.emissive) {
        selectedUnit.mesh.material.emissive.setHex(0x2a2a2a);
    }

    updateInteractionStatus();
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

function updateInteractionStatus() {
    const selectionNode = document.getElementById("selected-unit");
    const modeNode = document.getElementById("interaction-mode");

    if (selectionNode) {
        selectionNode.textContent = selectedUnit
            ? `${selectedUnit.name} (${selectedUnit.side})`
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
        selectedUnit.mesh.position.set(worldPoint.x, DEFAULT_UNIT_SIZE, worldPoint.z);
        isMoveMode = false;
        updateInteractionStatus();
        scheduleStateSync();
        return;
    }

    const meshes = units.map((unit) => unit.mesh);
    const intersects = raycaster.intersectObjects(meshes);

    if (intersects.length > 0) {
        const clickedMesh = intersects[0].object;
        const clickedUnit = units.find((unit) => unit.mesh === clickedMesh) ?? null;
        setSelectedUnit(clickedUnit);
    } else {
        setSelectedUnit(null);
    }

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

const panelClock = document.getElementById("admin-clock");

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
    };

    updateClock();
    window.setInterval(updateClock, 1000);
}

updateInteractionStatus();
window.addEventListener("click", onMouseClick);

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
        unit.mesh.rotation.y += 0.01;

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
