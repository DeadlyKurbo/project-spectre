import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";
import { createEntityManager, createMapLoader, createCameraController, createStarLayer } from "./wasp/index.js";

const container = document.getElementById("map-container");

if (!container) {
    throw new Error("W.A.S.P map container was not found.");
}

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050b1a);
scene.fog = new THREE.Fog(0x050b1a, 200, 600);

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
let syncTimerId = null;
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let spawnPosition = null;
const pointerDownPosition = { x: 0, y: 0 };
let pointerDownStartedOnMap = false;
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
let isMoveMode = false;
let suppressUnitPanelSync = false;

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

const mapMode = (typeof window.WASP_MAP_BOOTSTRAP === "object" && window.WASP_MAP_BOOTSTRAP?.mapMode) || "planet";
const cameraController = createCameraController(camera, controls);
let starLayer = null;

/* GRID */
const grid = new THREE.GridHelper(800, 80, 0x00ffff, 0x004444);
scene.add(grid);
grid.material.opacity = 0.25;
grid.material.transparent = true;

if (mapMode === "galaxy") {
    scene.fog = new THREE.Fog(0x050b1a, 800, 3000);
    camera.far = 10000;
    camera.updateProjectionMatrix();
    camera.position.set(0, 400, 600);
    controls.target.set(0, 0, 0);
    controls.minDistance = 100;
    controls.maxDistance = 2500;
    grid.visible = false;
}

/* SELECTION RING */
const ringGeo = new THREE.RingGeometry(3, 3.6, 32);
const ringMat = new THREE.MeshBasicMaterial({
    color: 0x00ffff,
    side: THREE.DoubleSide,
});
const selectionRing = new THREE.Mesh(ringGeo, ringMat);
selectionRing.rotation.x = -Math.PI / 2;
selectionRing.visible = false;
scene.add(selectionRing);

/* UNIT FACTORY */
const unitColors = {
    enemy: 0xff0000,
    friendly: 0x00ffff,
    neutral: 0xffff00,
    objective: 0xffff00,
};

const UNIT_ICON_SCALE = 6;
const HIT_PLANE_SIZE = 12;
const LABEL_VISIBILITY_DISTANCE = 80;
const LABEL_OVERLAP_DISTANCE = 5;
const CLUSTER_RADIUS = 10;
const CLUSTER_ZOOM_THRESHOLD = 120;
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

    ctx.fillStyle = "rgba(4, 10, 24, 0.8)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(0, 255, 255, 0.78)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);

    ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
    ctx.font = "bold 26px monospace";
    ctx.fillText(displayName, 12, 42);

    ctx.fillStyle = "rgba(127, 255, 212, 0.95)";
    ctx.font = "22px monospace";
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
    });
    const sideRing = new THREE.Sprite(sideRingMaterial);
    sideRing.scale.set(UNIT_ICON_SCALE + 1.8, UNIT_ICON_SCALE + 1.8, 1);
    sideRing.position.set(0, 0, -0.01);
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

    if (selectionNode) {
        selectionNode.textContent = selectedUnit
            ? `${selectedUnit.name} · ${selectedUnit.country} · ${selectedUnit.type}`
            : "None";
    }

    if (modeNode) {
        if (placingUnitType) {
            modeNode.textContent = `Place ${placingUnitType}`;
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
        && event.target.closest("#admin-panel, #wasp-map-audio-control");

    if (clickedInsidePanel) {
        return;
    }

    const worldPoint = toWorldPointFromMouseClick(event);

    if (!worldPoint) {
        return;
    }

    const hitTargets = units.map((unit) => unit.hitPlane).filter(Boolean);
    const intersects = raycaster.intersectObjects(hitTargets, true);
    const clickedUnit = resolveUnitFromIntersect(intersects);

    if (isMoveMode && selectedUnit) {
        selectedUnit.mesh.position.set(worldPoint.x, 2, worldPoint.z);
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

    return !activeElement.closest("#admin-panel, #spawn-menu, #wasp-map-audio-control");
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
    removeAllUnits();
    payloadUnits.forEach((entry) => createUnit(entry));

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
}

async function persistSharedState() {
    if (isApplyingRemoteState) {
        return;
    }
    if (isPersistingSharedState) {
        queuedPersistRequest = true;
        return;
    }

    isPersistingSharedState = true;
    hasPendingLocalChanges = true;

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
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
        if (queuedPersistRequest) {
            queuedPersistRequest = false;
            return persistSharedState();
        }
        return;
    }

    if (!response.ok) {
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
        throw new Error(`Failed to persist state (${response.status})`);
    }

    mapStateEtag = nextEtag ? nextEtag.replaceAll('"', "") : null;
    hasPendingLocalChanges = false;
    isPersistingSharedState = false;
    if (queuedPersistRequest) {
        queuedPersistRequest = false;
        return persistSharedState();
    }
}

function scheduleStateSync() {
    localStateRevision += 1;
    hasPendingLocalChanges = true;
    void persistSharedState().catch((error) => {
        hasPendingLocalChanges = false;
        isPersistingSharedState = false;
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
}

function resetCameraView() {
    if (mapMode === "galaxy") {
        camera.position.set(0, 400, 600);
    } else {
        camera.position.set(0, 80, 180);
    }
    controls.target.set(0, 0, 0);
    controls.update();
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

const mapBootstrap = typeof window.WASP_MAP_BOOTSTRAP === "object" && window.WASP_MAP_BOOTSTRAP
    ? window.WASP_MAP_BOOTSTRAP
    : {};

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

window.addEventListener("contextmenu", (event) => {
    event.preventDefault();

    const clickedInsidePanel = event.target instanceof Element
        && event.target.closest("#admin-panel, #spawn-menu, #wasp-map-audio-control");

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

window.addEventListener("pointerdown", (event) => {
    pointerDownPosition.x = event.clientX;
    pointerDownPosition.y = event.clientY;
    pointerDownStartedOnMap = event.target instanceof Element
        && container.contains(event.target)
        && !event.target.closest("#admin-panel, #spawn-menu, #wasp-map-audio-control");
});

window.addEventListener("click", (event) => {
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
        && !event.target.closest("#admin-panel, #spawn-menu, #wasp-map-audio-control");

    if (!clickedOnMap) {
        return;
    }

    onMouseClick(event);
});

window.addEventListener("keydown", (event) => {
    if (event.code === "KeyR" && shouldCaptureMapKeyboardInput()) {
        event.preventDefault();
        resetCameraView();
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
});

if (mapMode !== "galaxy") {
    void fetchSharedState().catch((error) => {
        console.error("Unable to load shared W.A.S.P map state", error);
    });

    syncTimerId = window.setInterval(() => {
        void fetchSharedState().catch((error) => {
            console.error("Unable to refresh shared W.A.S.P map state", error);
        });
    }, 3000);
}

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
    if (mapMode === "galaxy") return;
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
    ctx.fillStyle = "rgba(4, 10, 24, 0.84)";
    ctx.fillRect(4, 6, canvas.width - 8, canvas.height - 12);
    ctx.strokeStyle = "rgba(127, 255, 212, 0.95)";
    ctx.lineWidth = 3;
    ctx.strokeRect(5.5, 7.5, canvas.width - 11, canvas.height - 15);
    ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
    ctx.font = "bold 30px monospace";
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
            unit.label.visible = dist < LABEL_VISIBILITY_DISTANCE;
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
            u.mesh.visible = false;
        });
    });
}

function updateSelectionRing() {
    if (selectedUnit) {
        selectionRing.visible = true;
        selectionRing.position.copy(selectedUnit.mesh.position);
    } else {
        selectionRing.visible = false;
    }
}

/* ANIMATION LOOP */
function animate() {
    requestAnimationFrame(animate);

    const deltaSeconds = keyboardClock.getDelta();
    applyKeyboardMapNavigation(deltaSeconds);
    flushQueuedRemoteStateIfSafe();

    cameraController.updateZoomLevel();
    updateLabels();
    resolveLabelOverlap();
    updateClusterMarkers();
    updateSelectionRing();

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
