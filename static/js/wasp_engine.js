import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";

const container = document.getElementById("map-container");
const imAudioButtons = document.querySelectorAll("[data-im-audio-control]");
const imAudioStatus = document.getElementById("wasp-im-audio-status");
const imBackgroundAudio = document.getElementById("wasp-im-background-audio");
const waspMusicTracks = Array.isArray(window.waspMusicTracks) ? window.waspMusicTracks : [];
const AUDIO_STATE_KEY = "spectre_wasp_audio_state_v1";

if (!container) {
    throw new Error("W.A.S.P map container was not found.");
}

function initializeAudioControls() {
    if (!imAudioButtons.length || !imAudioStatus || !imBackgroundAudio) {
        return;
    }

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

    const readPersistedAudioState = () => {
        try {
            const raw = localStorage.getItem(AUDIO_STATE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== "object") return null;
            return parsed;
        } catch (_error) {
            return null;
        }
    };

    const persisted = readPersistedAudioState();
    const audioState = {
        volume: clamp(Number(persisted?.volume ?? 50), 0, 100),
        muted: Boolean(persisted?.muted),
        trackIndex: clamp(Number(persisted?.trackIndex ?? 0), 0, Math.max(0, waspMusicTracks.length - 1)),
    };

    const persistAudioState = () => {
        try {
            localStorage.setItem(AUDIO_STATE_KEY, JSON.stringify(audioState));
        } catch (_error) {
            // Ignore storage limits and continue with in-memory state.
        }
    };

    const applyAudioState = () => {
        imBackgroundAudio.volume = audioState.volume / 100;
        imBackgroundAudio.muted = audioState.muted;
    };

    const formatAudioStatus = (extra = "") => {
        if (!waspMusicTracks.length) {
            imAudioStatus.textContent = "Music unavailable · Upload MP3 in Director panel";
            return;
        }

        const currentTrack = waspMusicTracks[audioState.trackIndex];
        const level = audioState.muted ? "Muted" : `${audioState.volume}%`;
        const prettyName = String(currentTrack?.filename || "Track")
            .replace(/\.mp3$/i, "")
            .replace(/[-_]+/g, " ")
            .trim();

        imAudioStatus.textContent = extra
            ? `${prettyName} · ${level} · ${extra}`
            : `${prettyName} · ${level}`;
    };

    const loadCurrentTrack = () => {
        if (!waspMusicTracks.length) {
            imBackgroundAudio.removeAttribute("src");
            return false;
        }

        const activeTrack = waspMusicTracks[audioState.trackIndex];
        if (!activeTrack?.url) {
            return false;
        }

        if (imBackgroundAudio.src !== new URL(activeTrack.url, window.location.origin).href) {
            imBackgroundAudio.src = activeTrack.url;
            imBackgroundAudio.load();
        }
        return true;
    };

    const playCurrentTrack = async () => {
        if (!loadCurrentTrack()) {
            formatAudioStatus();
            return;
        }

        applyAudioState();

        try {
            await imBackgroundAudio.play();
            formatAudioStatus("Playing");
        } catch (_error) {
            formatAudioStatus("Click a control to start");
        }
    };

    const moveToNextTrack = async () => {
        if (!waspMusicTracks.length) return;
        audioState.trackIndex = (audioState.trackIndex + 1) % waspMusicTracks.length;
        persistAudioState();
        await playCurrentTrack();
    };

    const moveToPreviousTrack = async () => {
        if (!waspMusicTracks.length) return;
        audioState.trackIndex = (audioState.trackIndex - 1 + waspMusicTracks.length) % waspMusicTracks.length;
        persistAudioState();
        await playCurrentTrack();
    };

    imBackgroundAudio.addEventListener("ended", () => {
        void moveToNextTrack();
    });

    imBackgroundAudio.addEventListener("error", () => {
        formatAudioStatus("Track error · skipping");
        void moveToNextTrack();
    });

    imAudioButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const control = button.dataset.imAudioControl;

            if (control === "increase") {
                audioState.volume = clamp(audioState.volume + 5, 0, 100);
                if (audioState.volume > 0) audioState.muted = false;
            } else if (control === "decrease") {
                audioState.volume = clamp(audioState.volume - 5, 0, 100);
                if (audioState.volume === 0) audioState.muted = true;
            } else if (control === "next") {
                void moveToNextTrack();
                return;
            } else if (control === "previous") {
                void moveToPreviousTrack();
                return;
            }

            applyAudioState();
            persistAudioState();
            formatAudioStatus(imBackgroundAudio.paused ? "Ready" : "Playing");

            if (imBackgroundAudio.paused && waspMusicTracks.length) {
                void playCurrentTrack();
            }
        });
    });

    applyAudioState();
    formatAudioStatus("Ready");
}

initializeAudioControls();

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050b1a);
scene.fog = new THREE.Fog(0x050b1a, 120, 420);

const markers = [];

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

/* MARKER FACTORY */
function createMarker(x, z, color = 0xff0040, size = 1.5) {
    const geometry = new THREE.SphereGeometry(size, 16, 16);

    const material = new THREE.MeshBasicMaterial({
        color,
    });

    const marker = new THREE.Mesh(geometry, material);
    marker.position.set(x, 1.5, z);

    scene.add(marker);
    markers.push(marker);

    return marker;
}

createMarker(0, 0, 0xff0000);
createMarker(-30, 20, 0x00ffff);
createMarker(50, -10, 0xffff00);

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

    markers.forEach((marker) => {
        marker.rotation.y += 0.01;
    });

    scene.traverse((obj) => {
        if (obj.geometry && obj.geometry.type === "RingGeometry") {
            obj.userData.scale += 0.02;

            obj.scale.set(
                obj.userData.scale,
                obj.userData.scale,
                obj.userData.scale,
            );

            obj.material.opacity = 1 - (obj.userData.scale / 20);

            if (obj.userData.scale > 20) {
                obj.userData.scale = 1;
            }
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
