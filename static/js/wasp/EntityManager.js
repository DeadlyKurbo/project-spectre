/**
 * EntityManager – Central registry for all map entities.
 * Replaces flat arrays with a typed, scalable structure.
 *
 * Entity types: units, stars, planets, sectors, missiles, fleets, etc.
 * Each entity has: id, type, position, and type-specific data.
 */

const ENTITY_TYPES = Object.freeze([
    "unit",
    "star",
    "planet",
    "sector",
    "missile",
    "fleet",
    "objective",
]);

function createEntityManager() {
    const registry = {
        units: [],
        stars: [],
        planets: [],
        sectors: [],
        missiles: [],
        fleets: [],
        objectives: [],
    };

    const byId = new Map();

    function register(entity, type) {
        const normalizedType = (type ?? entity?.type ?? "unit").toLowerCase();
        const key = normalizedType + "s";
        const list = Array.isArray(registry[key]) ? registry[key] : registry.units;
        list.push(entity);
        if (entity?.id != null) {
            byId.set(String(entity.id), entity);
        }
        return entity;
    }

    function unregister(entityOrId, type) {
        const id = typeof entityOrId === "string" ? entityOrId : entityOrId?.id;
        const entity = typeof entityOrId === "object" ? entityOrId : byId.get(String(id));
        if (!entity) return false;

        byId.delete(String(entity.id));

        for (const key of Object.keys(registry)) {
            const list = registry[key];
            const idx = list.indexOf(entity);
            if (idx > -1) {
                list.splice(idx, 1);
                return true;
            }
        }
        return false;
    }

    function findById(id) {
        return byId.get(String(id)) ?? null;
    }

    function findByType(type) {
        const key = (type ?? "unit").toLowerCase() + "s";
        return registry[key] ?? [];
    }

    function clear(type) {
        if (type) {
            const key = (type ?? "unit").toLowerCase() + "s";
            const list = registry[key];
            if (Array.isArray(list)) {
                list.forEach((e) => e?.id != null && byId.delete(String(e.id)));
                list.length = 0;
            }
        } else {
            ENTITY_TYPES.forEach((t) => clear(t));
            byId.clear();
        }
    }

    function getAll() {
        return {
            ...registry,
            all: () =>
                Object.values(registry).flat().filter(Array.isArray).flat(),
        };
    }

    return {
        register,
        unregister,
        findById,
        findByType,
        clear,
        get registry() {
            return registry;
        },
        get units() {
            return registry.units;
        },
        get stars() {
            return registry.stars;
        },
        get planets() {
            return registry.planets;
        },
        get sectors() {
            return registry.sectors;
        },
        get missiles() {
            return registry.missiles;
        },
        get fleets() {
            return registry.fleets;
        },
        get objectives() {
            return registry.objectives;
        },
    };
}

export { createEntityManager, ENTITY_TYPES };
