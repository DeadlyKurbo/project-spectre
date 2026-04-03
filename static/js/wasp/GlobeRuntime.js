import { latLonToVector3, greatCirclePoint } from "./geo.js";

function createGlobeRuntime({ THREE, scene, camera, controls }) {
    const root = new THREE.Group();
    root.name = "globe-runtime";
    scene.add(root);

    const earthRadius = 180;
    const oceanMesh = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius * 0.999, 120, 80),
        new THREE.MeshStandardMaterial({
            color: 0x173a52,
            roughness: 0.78,
            metalness: 0.2,
            emissive: 0x07111a,
            emissiveIntensity: 0.4,
        }),
    );
    oceanMesh.name = "earth-ocean";
    root.add(oceanMesh);

    const sphereGeo = new THREE.SphereGeometry(earthRadius, 96, 64);
    const earthMat = new THREE.MeshStandardMaterial({
        color: 0x89a68e,
        roughness: 0.9,
        metalness: 0.04,
        emissive: 0x0c1712,
        emissiveIntensity: 0.36,
        transparent: true,
        opacity: 0.68,
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

    const countryGroup = new THREE.Group();
    countryGroup.name = "country-boundaries";
    root.add(countryGroup);

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

    camera.position.set(0, 260, 420);
    controls.target.set(0, 0, 0);
    controls.minDistance = 220;
    controls.maxDistance = 960;
    controls.maxPolarAngle = Math.PI - 0.16;
    controls.screenSpacePanning = false;

    let tick = 0;
    function update(deltaSeconds = 0.016) {
        tick += deltaSeconds;
        cloudMesh.rotation.y += deltaSeconds * 0.012;
        earthMesh.rotation.y += deltaSeconds * 0.0045;
        oceanMesh.rotation.y += deltaSeconds * 0.0034;
        const pulse = 0.07 + (Math.sin(tick * 0.9) * 0.02);
        atmosphere.material.opacity = pulse;
    }

    function clearCountryBoundaries() {
        while (countryGroup.children.length > 0) {
            const child = countryGroup.children.pop();
            if (!child) {
                continue;
            }
            countryGroup.remove(child);
            child.geometry?.dispose?.();
            child.material?.dispose?.();
        }
    }

    function addBoundaryRing(ring, color = 0x9fd7bd, opacity = 0.55) {
        if (!Array.isArray(ring) || ring.length < 2) {
            return;
        }
        const points = ring
            .filter((entry) => Array.isArray(entry) && entry.length >= 2)
            .map((entry) => {
                const p = latLonToVector3(Number(entry[1]), Number(entry[0]), earthRadius * 1.003);
                return new THREE.Vector3(p.x, p.y, p.z);
            });
        if (points.length < 2) {
            return;
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(
            geometry,
            new THREE.LineBasicMaterial({
                color,
                transparent: true,
                opacity,
            }),
        );
        countryGroup.add(line);
    }

    async function loadCountryBoundaries(url = "/static/data/world.geo.json") {
        try {
            const response = await fetch(url, { cache: "no-store" });
            if (!response.ok) {
                throw new Error(`Boundary fetch failed (${response.status})`);
            }
            const payload = await response.json();
            clearCountryBoundaries();
            const features = Array.isArray(payload?.features) ? payload.features : [];
            features.forEach((feature) => {
                const geometry = feature?.geometry;
                if (!geometry || !geometry.type) {
                    return;
                }
                if (geometry.type === "Polygon") {
                    geometry.coordinates.forEach((ring, index) => {
                        addBoundaryRing(ring, index === 0 ? 0xb8efc8 : 0x86bca2, index === 0 ? 0.62 : 0.35);
                    });
                    return;
                }
                if (geometry.type === "MultiPolygon") {
                    geometry.coordinates.forEach((polygon) => {
                        polygon.forEach((ring, index) => {
                            addBoundaryRing(ring, index === 0 ? 0xb8efc8 : 0x86bca2, index === 0 ? 0.62 : 0.35);
                        });
                    });
                }
            });
        } catch (error) {
            console.error("Unable to load globe country boundaries", error);
        }
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
        loadCountryBoundaries,
        dispose,
    };
}

export { createGlobeRuntime };
