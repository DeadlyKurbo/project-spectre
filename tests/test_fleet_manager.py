from fleet_manager import FleetManifest, FleetVessel, _coerce_manifest  # type: ignore[attr-defined]


def test_manifest_copy_is_deep() -> None:
    vessel = FleetVessel(
        vessel_id="abc123",
        name="ISS Spectre",
        vessel_type="Flagship",
        armaments="Railguns",
        speed="3.2 AU/hr",
        assignment="Command",
        notes="Primary asset",
    )
    manifest = FleetManifest(vessels=[vessel], last_updated="2024-01-01T00:00:00+00:00")

    clone = manifest.copy()
    clone.vessels[0].name = "ISS Phantom"
    clone.vessels[0].notes = "Shadow asset"

    assert manifest.vessels[0].name == "ISS Spectre"
    assert manifest.vessels[0].notes == "Primary asset"


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
