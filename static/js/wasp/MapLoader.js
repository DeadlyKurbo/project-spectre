/**
 * MapLoader – JSON-driven map data.
 * Load galaxy, sector, system, or planet data from static files.
 * Swap universes by loading different JSON files.
 */

const DEFAULT_DATA_PREFIX = "/static/data";

function createMapLoader(options = {}) {
    const prefix = options.dataPrefix ?? DEFAULT_DATA_PREFIX;

    async function load(path) {
        const url = path.startsWith("/") ? path : `${prefix}/${path}`;
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`MapLoader: failed to load ${url} (${response.status})`);
        }
        return response.json();
    }

    async function loadGalaxy(name = "galaxy") {
        return load(`${name}.json`);
    }

    async function loadSector(galaxyId, sectorId) {
        return load(`galaxies/${galaxyId}/sectors/${sectorId}.json`);
    }

    async function loadSystem(galaxyId, sectorId, systemId) {
        return load(`galaxies/${galaxyId}/sectors/${sectorId}/systems/${systemId}.json`);
    }

    async function loadPlanet(galaxyId, sectorId, systemId, planetId) {
        return load(`galaxies/${galaxyId}/sectors/${sectorId}/systems/${systemId}/planets/${planetId}.json`);
    }

    return {
        load,
        loadGalaxy,
        loadSector,
        loadSystem,
        loadPlanet,
    };
}

export { createMapLoader, DEFAULT_DATA_PREFIX };
