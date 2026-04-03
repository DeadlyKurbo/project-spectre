/**
 * CameraController – Zoom-based level switching.
 * Galaxy → Sector → System → Planet → Surface
 *
 * Toggle which objects are visible based on zoom distance.
 */

const ZOOM_LEVELS = Object.freeze({
    galaxy: { minDist: 2000, label: "galaxy" },
    sector: { minDist: 800, label: "sector" },
    system: { minDist: 200, label: "system" },
    planet: { minDist: 50, label: "planet" },
    surface: { minDist: 0, label: "surface" },
});

/** Thresholds are camera–target distance; tuned for earthRadius ≈ 4000, default cam ≈ 1.18R (~4720), min ≈ 1.05R. */
const GLOBE_ZOOM_LEVELS = Object.freeze({
    orbital: { minDist: 5600, label: "orbital" },
    theater: { minDist: 4500, label: "theater" },
    regional: { minDist: 4050, label: "regional" },
    tactical: { minDist: 0, label: "tactical" },
});

function createCameraController(camera, controls, options = {}) {
    const mapMode = String(options?.mapMode || "planet").toLowerCase();
    let currentLevel = "surface";

    function getCameraDistance() {
        if (!camera || !controls?.target) {
            return camera?.position?.length() ?? 0;
        }
        return camera.position.distanceTo(controls.target);
    }

    function updateZoomLevel() {
        const z = getCameraDistance();
        if (mapMode === "globe") {
            if (z >= GLOBE_ZOOM_LEVELS.orbital.minDist) {
                currentLevel = "orbital";
            } else if (z >= GLOBE_ZOOM_LEVELS.theater.minDist) {
                currentLevel = "theater";
            } else if (z >= GLOBE_ZOOM_LEVELS.regional.minDist) {
                currentLevel = "regional";
            } else {
                currentLevel = "tactical";
            }
            return currentLevel;
        }
        if (z >= ZOOM_LEVELS.galaxy.minDist) {
            currentLevel = "galaxy";
        } else if (z >= ZOOM_LEVELS.sector.minDist) {
            currentLevel = "sector";
        } else if (z >= ZOOM_LEVELS.system.minDist) {
            currentLevel = "system";
        } else if (z >= ZOOM_LEVELS.planet.minDist) {
            currentLevel = "planet";
        } else {
            currentLevel = "surface";
        }
        return currentLevel;
    }

    function getLevel() {
        return currentLevel;
    }

    function getLevelConfig() {
        if (mapMode === "globe") {
            return GLOBE_ZOOM_LEVELS[currentLevel] ?? GLOBE_ZOOM_LEVELS.tactical;
        }
        return ZOOM_LEVELS[currentLevel] ?? ZOOM_LEVELS.surface;
    }

    function shouldShowStars() {
        if (mapMode === "globe") {
            return currentLevel === "orbital";
        }
        return ["galaxy", "sector", "system"].includes(currentLevel);
    }

    function shouldShowSystemNames() {
        if (mapMode === "globe") {
            return ["orbital", "theater"].includes(currentLevel);
        }
        return ["sector", "system"].includes(currentLevel);
    }

    function shouldShowPlanets() {
        if (mapMode === "globe") {
            return false;
        }
        return ["system", "planet"].includes(currentLevel);
    }

    function shouldShowUnits() {
        if (mapMode === "globe") {
            return ["theater", "regional", "tactical"].includes(currentLevel);
        }
        return ["planet", "surface"].includes(currentLevel);
    }

    return {
        updateZoomLevel,
        getLevel,
        getLevelConfig,
        getCameraDistance,
        shouldShowStars,
        shouldShowSystemNames,
        shouldShowPlanets,
        shouldShowUnits,
        ZOOM_LEVELS,
        GLOBE_ZOOM_LEVELS,
    };
}

export { createCameraController, ZOOM_LEVELS };
