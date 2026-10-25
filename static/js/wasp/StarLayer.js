/**
 * StarLayer – InstancedMesh for thousands of stars.
 * Renders stars efficiently instead of individual meshes.
 */

import * as THREE from "three";

const DEFAULT_MAX_STARS = 10000;

function createStarLayer(starData = [], options = {}) {
    const dataCount = Array.isArray(starData) ? starData.length : starData?.stars?.length ?? 0;
    const maxCount = Math.max(dataCount, options.maxCount ?? DEFAULT_MAX_STARS, 1);
    const size = options.size ?? 1;
    const color = options.color ?? 0xffffff;

    const geometry = new THREE.IcosahedronGeometry(size, 1);
    const material = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: options.opacity ?? 0.9,
    });

    const instancedMesh = new THREE.InstancedMesh(geometry, material, maxCount);
    instancedMesh.count = 0;

    const dummy = new THREE.Object3D();
    const colorObj = new THREE.Color();

    function setStarPosition(index, x, y, z) {
        dummy.position.set(x, y ?? 0, z);
        const randomScale = 0.78 + ((index % 7) * 0.06);
        dummy.scale.setScalar(randomScale);
        dummy.updateMatrix();
        instancedMesh.setMatrixAt(index, dummy.matrix);
    }

    function setStarColor(index, hexColor) {
        colorObj.setHex(hexColor);
        instancedMesh.setColorAt(index, colorObj);
    }

    function buildFromData(data) {
        const stars = Array.isArray(data) ? data : data?.stars ?? [];
        const n = Math.min(stars.length, maxCount);
        instancedMesh.count = n;

        for (let i = 0; i < n; i++) {
            const s = stars[i];
            const x = Number(s?.x ?? s?.position?.x ?? 0);
            const y = Number(s?.y ?? s?.position?.y ?? 0);
            const z = Number(s?.z ?? s?.position?.z ?? 0);
            setStarPosition(i, x, y, z);
            if (s?.color != null) {
                setStarColor(i, s.color);
            } else {
                const t = (i % 10) / 10;
                colorObj.setRGB(0.72 + (t * 0.2), 0.8 + (t * 0.14), 0.9 + (t * 0.1));
                instancedMesh.setColorAt(i, colorObj);
            }
        }

        instancedMesh.instanceMatrix.needsUpdate = true;
        if (instancedMesh.instanceColor) {
            instancedMesh.instanceColor.needsUpdate = true;
        }
    }

    if (dataCount > 0) {
        buildFromData(starData);
    }

    return {
        mesh: instancedMesh,
        setStarPosition,
        setStarColor,
        buildFromData,
        get count() {
            return instancedMesh.count;
        },
    };
}

export { createStarLayer };
