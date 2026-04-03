/**
 * W.A.S.P. Map Engine – Modular exports.
 * EntityManager, UnitManager, MapLoader, CameraController, StarLayer, UIController
 */

export { createEntityManager, ENTITY_TYPES } from "./EntityManager.js";
export { createUnitManager } from "./UnitManager.js";
export { createMapLoader, DEFAULT_DATA_PREFIX } from "./MapLoader.js";
export { createCameraController, ZOOM_LEVELS } from "./CameraController.js";
export { createStarLayer } from "./StarLayer.js";
export { createUIController } from "./UIController.js";
export { createGlobeRuntime } from "./GlobeRuntime.js";
export { latLonToVector3, vector3ToLatLon, greatCirclePoint } from "./geo.js";
