/**
 * UnitManager – Unit-specific logic on top of EntityManager.
 * Handles creation, lookup, serialization for tactical units.
 */

function createUnitManager(entityManager) {
    function findById(id) {
        return entityManager.findById(id);
    }

    function getAll() {
        return entityManager.units;
    }

    function serialize() {
        return entityManager.units.map((unit) => ({
            id: unit.id,
            type: unit.type,
            name: unit.name,
            country: unit.country,
            side: unit.side,
            x: Number(unit.mesh?.position?.x?.toFixed(3) ?? 0),
            z: Number(unit.mesh?.position?.z?.toFixed(3) ?? 0),
        }));
    }

    return {
        findById,
        getAll,
        serialize,
    };
}

export { createUnitManager };
