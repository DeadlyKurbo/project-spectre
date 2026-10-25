/**
 * UIController – Centralizes UI updates for the map.
 * Handles panel visibility, status text, selection display.
 * Extendable for zoom-level UI, minimap, etc.
 */

function createUIController(options = {}) {
    const elements = {
        selectedUnit: options.selectedUnitEl ?? "selected-unit",
        interactionMode: options.interactionModeEl ?? "interaction-mode",
        unitName: options.unitNameEl ?? "unit-name",
        unitPanel: options.unitPanelEl ?? "unit-panel",
    };

    function getElement(id) {
        return typeof id === "string" ? document.getElementById(id) : id;
    }

    function updateSelectionStatus(selectedUnit) {
        const node = getElement(elements.selectedUnit);
        if (node) {
            node.textContent = selectedUnit
                ? `${selectedUnit.name} · ${selectedUnit.country ?? ""} · ${selectedUnit.type ?? ""}`
                : "None";
        }
    }

    function updateModeStatus(mode) {
        const node = getElement(elements.interactionMode);
        if (node) {
            node.textContent = mode ?? "Select";
        }
    }

    function updateUnitPanel(unit) {
        const title = getElement(elements.unitName);
        if (title) {
            title.innerText = unit?.name ?? "No unit selected";
        }
    }

    function updateStatus(selectedUnit, mode) {
        updateSelectionStatus(selectedUnit);
        updateModeStatus(mode);
    }

    return {
        updateSelectionStatus,
        updateModeStatus,
        updateUnitPanel,
        updateStatus,
        getElement,
    };
}

export { createUIController };
