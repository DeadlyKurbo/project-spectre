const container = document.getElementById("map-container");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050b1a);
scene.fog = new THREE.Fog(0x050b1a, 120, 420);

const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    1000
);

camera.position.set(0, 80, 120);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });

renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);

container.appendChild(renderer.domElement);

const controls = new THREE.OrbitControls(camera, renderer.domElement);

controls.enableDamping = true;
controls.dampingFactor = 0.05;

controls.screenSpacePanning = true;

controls.minDistance = 20;
controls.maxDistance = 400;

controls.maxPolarAngle = Math.PI / 2.1;


/* GRID */

const grid = new THREE.GridHelper(
    500,
    50,
    0x00ffff,
    0x004444
);

scene.add(grid);

grid.material.opacity = 0.25;
grid.material.transparent = true;


/* TEST OBJECT (marker prototype) */

const geometry = new THREE.SphereGeometry(1.5, 16, 16);

const material = new THREE.MeshBasicMaterial({
    color: 0xff0040
});

const marker = new THREE.Mesh(geometry, material);

marker.position.set(0, 2, 0);

scene.add(marker);



/* RADAR PULSE */

function createRadarPulse(x, z) {

    const geometry = new THREE.RingGeometry(2, 2.4, 64);

    const material = new THREE.MeshBasicMaterial({
        color: 0xff0040,
        transparent: true,
        opacity: 0.9,
        side: THREE.DoubleSide
    });

    const ring = new THREE.Mesh(geometry, material);

    ring.rotation.x = -Math.PI / 2;

    ring.position.set(x, 0.1, z);

    ring.userData = {
        scale: 1,
        speed: 0.5
    };

    scene.add(ring);

    return ring;
}

const radar = createRadarPulse(0, 0);


/* FLIGHT PATH */

const flightPaths = [];

function createFlightPath(start, end) {

    const mid = new THREE.Vector3(
        (start.x + end.x) / 2,
        10,
        (start.z + end.z) / 2
    );

    const curve = new THREE.QuadraticBezierCurve3(
        new THREE.Vector3(start.x, 0, start.z),
        mid,
        new THREE.Vector3(end.x, 0, end.z)
    );

    const points = curve.getPoints(100);

    const geometry = new THREE.BufferGeometry().setFromPoints(points);

    const material = new THREE.LineBasicMaterial({
        color: 0x00ffff,
        transparent: true,
        opacity: 0.35
    });

    const line = new THREE.Line(geometry, material);

    scene.add(line);

    flightPaths.push({
        curve,
        progress: 0
    });

    return line;
}

const signalMaterial = new THREE.MeshBasicMaterial({
    color: 0xffffff
});

const signalGeometry = new THREE.SphereGeometry(0.8, 12, 12);

const signals = [];

createFlightPath(
    { x: -40, z: -20 },
    { x: 40, z: 25 }
);

const signal = new THREE.Mesh(signalGeometry, signalMaterial);

scene.add(signal);

signals.push({
    mesh: signal,
    path: flightPaths[0]
});


/* WORLD MAP LAYER */

async function loadWorldMap() {

    try {

        const response = await fetch("/static/data/world.geo.json");

        if (!response.ok) {
            throw new Error(`Unable to load world map: ${response.status}`);
        }

        const data = await response.json();

        const material = new THREE.LineBasicMaterial({
            color: 0x00ffff,
            transparent: true,
            opacity: 0.35
        });

        const drawRing = (ring) => {
            const points = ring.map((coord) => {

                const lon = coord[0];
                const lat = coord[1];

                const x = lon * 1.5;
                const z = lat * 1.5;

                return new THREE.Vector3(x, 0.05, -z);

            });

            const geometry = new THREE.BufferGeometry().setFromPoints(points);

            const line = new THREE.Line(geometry, material);

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

loadWorldMap();


/* ANIMATION LOOP */

function animate() {

    requestAnimationFrame(animate);

    marker.rotation.y += 0.01;

    scene.traverse((obj) => {

        if (obj.geometry && obj.geometry.type === "RingGeometry") {

            obj.userData.scale += 0.02;

            obj.scale.set(
                obj.userData.scale,
                obj.userData.scale,
                obj.userData.scale
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
