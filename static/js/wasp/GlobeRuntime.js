import { latLonToVector3, greatCirclePoint } from "./geo.js";

function createGlobeRuntime({ THREE, scene, camera, controls }) {
    const root = new THREE.Group();
    root.name = "globe-runtime";
    scene.add(root);

    const earthRadius = 120;
    const sphereGeo = new THREE.SphereGeometry(earthRadius, 96, 64);
    const earthMat = new THREE.MeshStandardMaterial({
        color: 0x6f826d,
        roughness: 0.93,
        metalness: 0.04,
        emissive: 0x0a1310,
        emissiveIntensity: 0.32,
    });
    const earthMesh = new THREE.Mesh(sphereGeo, earthMat);
    earthMesh.name = "earth-core";
    root.add(earthMesh);

    const atmosphere = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius * 1.02, 64, 48),
        new THREE.MeshBasicMaterial({
            color: 0x9fd9ff,
            transparent: true,
            opacity: 0.08,
            side: THREE.BackSide,
            depthWrite: false,
        }),
    );
    atmosphere.name = "earth-atmosphere";
    root.add(atmosphere);

    const cloudMesh = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius * 1.01, 64, 48),
        new THREE.MeshPhongMaterial({
            color: 0xe6eef7,
            transparent: true,
            opacity: 0.08,
            shininess: 4,
            depthWrite: false,
        }),
    );
    cloudMesh.name = "earth-clouds";
    root.add(cloudMesh);

    const gridLines = new THREE.Group();
    gridLines.name = "globe-graticule";
    root.add(gridLines);
    for (let lat = -60; lat <= 60; lat += 30) {
        const points = [];
        for (let lon = -180; lon <= 180; lon += 4) {
            const p = latLonToVector3(lat, lon, earthRadius * 1.001);
            points.push(new THREE.Vector3(p.x, p.y, p.z));
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(
            geometry,
            new THREE.LineBasicMaterial({ color: 0x507f66, transparent: true, opacity: 0.27 }),
        );
        gridLines.add(line);
    }
    for (let lon = -150; lon <= 180; lon += 30) {
        const points = [];
        for (let lat = -89; lat <= 89; lat += 3) {
            const p = latLonToVector3(lat, lon, earthRadius * 1.001);
            points.push(new THREE.Vector3(p.x, p.y, p.z));
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(
            geometry,
            new THREE.LineBasicMaterial({ color: 0x507f66, transparent: true, opacity: 0.23 }),
        );
        gridLines.add(line);
    }

    const orbitGroup = new THREE.Group();
    orbitGroup.name = "sat-orbits";
    root.add(orbitGroup);
    const orbitSeeds = [
        [{ lat: 15, lon: -140 }, { lat: 22, lon: 40 }],
        [{ lat: -25, lon: -60 }, { lat: 18, lon: 120 }],
    ];
    orbitSeeds.forEach((pair) => {
        const points = [];
        for (let step = 0; step <= 100; step += 1) {
            const p = greatCirclePoint(pair[0], pair[1], step / 100, earthRadius * 1.24);
            points.push(new THREE.Vector3(p.x, p.y, p.z));
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(
            geometry,
            new THREE.LineDashedMaterial({
                color: 0x8fd2a8,
                dashSize: 2.6,
                gapSize: 2.4,
                transparent: true,
                opacity: 0.62,
            }),
        );
        line.computeLineDistances();
        orbitGroup.add(line);
    });

    const rimLight = new THREE.DirectionalLight(0xaed7ff, 0.36);
    rimLight.position.set(220, 170, 200);
    scene.add(rimLight);

    const keyLight = new THREE.DirectionalLight(0xc2ffd7, 0.5);
    keyLight.position.set(-260, 110, -130);
    scene.add(keyLight);

    camera.position.set(0, 190, 295);
    controls.target.set(0, 0, 0);
    controls.minDistance = 155;
    controls.maxDistance = 620;
    controls.maxPolarAngle = Math.PI - 0.16;
    controls.screenSpacePanning = false;

    let tick = 0;
    function update(deltaSeconds = 0.016) {
        tick += deltaSeconds;
        cloudMesh.rotation.y += deltaSeconds * 0.012;
        earthMesh.rotation.y += deltaSeconds * 0.0045;
        const pulse = 0.07 + (Math.sin(tick * 0.9) * 0.02);
        atmosphere.material.opacity = pulse;
    }

    function dispose() {
        scene.remove(root);
        root.traverse((node) => {
            if (node.geometry) {
                node.geometry.dispose();
            }
            if (node.material) {
                if (Array.isArray(node.material)) {
                    node.material.forEach((m) => m.dispose?.());
                } else {
                    node.material.dispose?.();
                }
            }
        });
        scene.remove(keyLight);
        scene.remove(rimLight);
    }

    return {
        root,
        earthRadius,
        update,
        dispose,
    };
}

export { createGlobeRuntime };
