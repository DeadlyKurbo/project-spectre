from fleet_manager import FleetManifest, FleetVessel, _coerce_manifest  # type: ignore[attr-defined]


def test_manifest_copy_is_deep() -> None:
    vessel = FleetVessel(
        vessel_id="abc123",
        name="ISS Spectre",
        vessel_type="Flagship",
        armaments="Railguns",
        speed="3.2 AU/hr",
        assignment="Command",
        registry_id="GNV-001",
        shipyard="Atlas Drydock",
        commission_date="2099-01-01",
        assigned_squadron="Spearhead",
        clearance_level="Theta",
        status="Active",
        vessel_motto="Hold the line",
        notes="Primary asset",
    )
    manifest = FleetManifest(vessels=[vessel], last_updated="2024-01-01T00:00:00+00:00")

    clone = manifest.copy()
    clone.vessels[0].name = "ISS Phantom"
    clone.vessels[0].notes = "Shadow asset"
    clone.vessels[0].registry_id = "GNV-999"

    assert manifest.vessels[0].name == "ISS Spectre"
    assert manifest.vessels[0].notes == "Primary asset"
    assert manifest.vessels[0].registry_id == "GNV-001"


def test_coerce_manifest_filters_invalid_entries() -> None:
    data = {
        "last_updated": " 2024-04-04T04:04:04+00:00 ",
        "vessels": [
            {
                "vessel_id": "a1",
                "name": "Valkyrie",
                "vessel_type": "Frigate",
                "armaments": "Missiles",
                "speed": "2.1 AU/hr",
                "assignment": "Escort",
                "registry_id": "  GNV-777  ",
                "shipyard": "  Orbital Works  ",
                "commission_date": " 2088-05-01 ",
                "assigned_squadron": "  Echo Wing  ",
                "clearance_level": "  Sigma ",
                "status": " active ",
                "vessel_motto": "  Guardians  ",
                "notes": "  Ready ",
            },
            {
                "vessel_id": "",
                "name": "",
            },
        ],
    }

    manifest = _coerce_manifest(data)

    assert manifest.last_updated == "2024-04-04T04:04:04+00:00"
    assert len(manifest.vessels) == 1
    vessel = manifest.vessels[0]
    assert vessel.name == "Valkyrie"
    assert vessel.assignment == "Escort"
    assert vessel.notes == "Ready"
    assert vessel.registry_id == "GNV-777"
    assert vessel.shipyard == "Orbital Works"
    assert vessel.commission_date == "2088-05-01"
    assert vessel.assigned_squadron == "Echo Wing"
    assert vessel.clearance_level == "Sigma"
    assert vessel.status == "Active"
    assert vessel.vessel_motto == "Guardians"
