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

function createCameraController(camera, controls) {
    let currentLevel = "surface";

    function getCameraDistance() {
        if (!camera || !controls?.target) {
            return camera?.position?.length() ?? 0;
        }
        return camera.position.distanceTo(controls.target);
    }

    function updateZoomLevel() {
        const z = getCameraDistance();
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
        return ZOOM_LEVELS[currentLevel] ?? ZOOM_LEVELS.surface;
    }

    function shouldShowStars() {
        return ["galaxy", "sector", "system"].includes(currentLevel);
    }

    function shouldShowSystemNames() {
        return ["sector", "system"].includes(currentLevel);
    }

    function shouldShowPlanets() {
        return ["system", "planet"].includes(currentLevel);
    }

    function shouldShowUnits() {
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
    };
}

export { createCameraController, ZOOM_LEVELS };
