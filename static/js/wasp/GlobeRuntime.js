import { latLonToVector3, greatCirclePoint, vector3ToLatLon } from "./geo.js";

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
    const countryHighlightGroup = new THREE.Group();
    countryHighlightGroup.name = "country-highlight";
    root.add(countryHighlightGroup);
    const countryIndex = new Map();
    const raycaster = new THREE.Raycaster();
    const ndcPointer = new THREE.Vector2();
    let selectedCountryIso3 = "";

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
        const lineMaterial = new THREE.LineBasicMaterial({
            color,
            transparent: true,
            opacity,
        });
        const line = new THREE.Line(
            geometry,
            lineMaterial,
        );
        return line;
    }

    function clearCountryHighlight() {
        while (countryHighlightGroup.children.length > 0) {
            const child = countryHighlightGroup.children.pop();
            if (!child) {
                continue;
            }
            countryHighlightGroup.remove(child);
            child.geometry?.dispose?.();
            child.material?.dispose?.();
        }
    }

    function clearCountryIndex() {
        countryIndex.clear();
        selectedCountryIso3 = "";
    }

    function pickStatusColor(status = "contested") {
        const normalized = String(status || "").toLowerCase();
        if (normalized === "friendly") {
            return 0x7adf91;
        }
        if (normalized === "enemy") {
            return 0xff6f6f;
        }
        return 0xffd07a;
    }

    function angularDistanceDegrees(aLat, aLon, bLat, bLon) {
        const dLat = (aLat - bLat);
        let dLon = (aLon - bLon);
        if (dLon > 180) dLon -= 360;
        if (dLon < -180) dLon += 360;
        return Math.sqrt((dLat * dLat) + (dLon * dLon));
    }

    function countryCentroidFromRing(ring) {
        if (!Array.isArray(ring) || !ring.length) {
            return { lat: 0, lon: 0 };
        }
        let latSum = 0;
        let lonSum = 0;
        let count = 0;
        ring.forEach((entry) => {
            if (!Array.isArray(entry) || entry.length < 2) {
                return;
            }
            lonSum += Number(entry[0]) || 0;
            latSum += Number(entry[1]) || 0;
            count += 1;
        });
        if (!count) {
            return { lat: 0, lon: 0 };
        }
        return {
            lat: latSum / count,
            lon: lonSum / count,
        };
    }

    async function loadCountryBoundaries(url = "/static/data/world.geo.json") {
        try {
            const response = await fetch(url, { cache: "no-store" });
            if (!response.ok) {
                throw new Error(`Boundary fetch failed (${response.status})`);
            }
            const payload = await response.json();
            clearCountryBoundaries();
            clearCountryHighlight();
            clearCountryIndex();
            const features = Array.isArray(payload?.features) ? payload.features : [];
            features.forEach((feature) => {
                const geometry = feature?.geometry;
                if (!geometry || !geometry.type) {
                    return;
                }
                const iso3 = String(feature?.id || "").trim().toUpperCase();
                const countryName = String(feature?.properties?.name || iso3 || "Unknown").trim();
                if (!iso3) {
                    return;
                }
                const records = countryIndex.get(iso3) || {
                    iso3,
                    name: countryName,
                    centroid: { lat: 0, lon: 0 },
                    centroidCount: 0,
                    lines: [],
                    rings: [],
                };
                if (geometry.type === "Polygon") {
                    geometry.coordinates.forEach((ring, index) => {
                        const line = addBoundaryRing(ring, index === 0 ? 0xb8efc8 : 0x86bca2, index === 0 ? 0.62 : 0.35);
                        if (line) {
                            countryGroup.add(line);
                            records.lines.push(line);
                        }
                        records.rings.push(ring);
                        if (index === 0) {
                            const centroid = countryCentroidFromRing(ring);
                            records.centroid.lat += centroid.lat;
                            records.centroid.lon += centroid.lon;
                            records.centroidCount += 1;
                        }
                    });
                } else if (geometry.type === "MultiPolygon") {
                    geometry.coordinates.forEach((polygon) => {
                        polygon.forEach((ring, index) => {
                            const line = addBoundaryRing(ring, index === 0 ? 0xb8efc8 : 0x86bca2, index === 0 ? 0.62 : 0.35);
                            if (line) {
                                countryGroup.add(line);
                                records.lines.push(line);
                            }
                            records.rings.push(ring);
                            if (index === 0) {
                                const centroid = countryCentroidFromRing(ring);
                                records.centroid.lat += centroid.lat;
                                records.centroid.lon += centroid.lon;
                                records.centroidCount += 1;
                            }
                        });
                    });
                }
                if (records.centroidCount > 0) {
                    records.centroid.lat /= records.centroidCount;
                    records.centroid.lon /= records.centroidCount;
                }
                countryIndex.set(iso3, records);
            });
        } catch (error) {
            console.error("Unable to load globe country boundaries", error);
        }
    }

    function getCountryAtScreenPoint(screenX, screenY, viewportElement) {
        const viewport = viewportElement;
        if (!viewport) {
            return null;
        }
        const bounds = viewport.getBoundingClientRect();
        const withinBounds = screenX >= bounds.left
            && screenX <= bounds.right
            && screenY >= bounds.top
            && screenY <= bounds.bottom;
        if (!withinBounds) {
            return null;
        }
        ndcPointer.x = ((screenX - bounds.left) / bounds.width) * 2 - 1;
        ndcPointer.y = -(((screenY - bounds.top) / bounds.height) * 2 - 1);
        raycaster.setFromCamera(ndcPointer, camera);
        const hits = raycaster.intersectObject(earthMesh, false);
        if (!hits.length) {
            return null;
        }
        const point = hits[0].point;
        const latLon = vector3ToLatLon(point.x, point.y, point.z);
        let nearest = null;
        let nearestDistance = Infinity;
        countryIndex.forEach((entry) => {
            const distance = angularDistanceDegrees(
                latLon.lat,
                latLon.lon,
                Number(entry.centroid?.lat || 0),
                Number(entry.centroid?.lon || 0),
            );
            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearest = entry;
            }
        });
        if (!nearest) {
            return null;
        }
        return {
            iso3: nearest.iso3,
            name: nearest.name,
            lat: Number(nearest.centroid?.lat || 0),
            lon: Number(nearest.centroid?.lon || 0),
        };
    }

    function setSelectedCountry(iso3, status = "contested") {
        const code = String(iso3 || "").trim().toUpperCase();
        selectedCountryIso3 = code;
        clearCountryHighlight();
        countryIndex.forEach((entry, key) => {
            const isSelected = key === code;
            entry.lines.forEach((line) => {
                if (!line?.material) {
                    return;
                }
                line.material.opacity = isSelected ? 0.95 : 0.38;
                line.material.color.setHex(isSelected ? pickStatusColor(status) : 0x96d0b3);
            });
        });
        const selected = countryIndex.get(code);
        if (!selected) {
            return;
        }
        const center = latLonToVector3(selected.centroid.lat, selected.centroid.lon, earthRadius * 1.03);
        const marker = new THREE.Mesh(
            new THREE.RingGeometry(7.8, 9.8, 40),
            new THREE.MeshBasicMaterial({
                color: pickStatusColor(status),
                side: THREE.DoubleSide,
                transparent: true,
                opacity: 0.78,
            }),
        );
        marker.position.set(center.x, center.y, center.z);
        marker.lookAt(0, 0, 0);
        countryHighlightGroup.add(marker);
    }

    function getCountryByIso3(iso3) {
        const code = String(iso3 || "").trim().toUpperCase();
        const entry = countryIndex.get(code);
        if (!entry) {
            return null;
        }
        return {
            iso3: entry.iso3,
            name: entry.name,
            lat: Number(entry.centroid?.lat || 0),
            lon: Number(entry.centroid?.lon || 0),
        };
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
        getCountryAtScreenPoint,
        setSelectedCountry,
        getCountryByIso3,
        dispose,
    };
}

export { createGlobeRuntime };
