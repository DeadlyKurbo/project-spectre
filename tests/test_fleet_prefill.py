import config_app
from fleet_manager import FleetVessel


def test_prefill_spec_entry_uses_vessel_defaults():
    vessel = FleetVessel(
        vessel_id="a1b2",
        name="G.N.V Resolute",
        vessel_type="Command Cruiser",
        armaments="VX Lance Battery",
        speed="900 m/s",
        assignment="Task Force Frost",
        registry_id="HNG-45",
        shipyard="New Babbage Microtech",
        commission_date="2953-08-01",
        assigned_squadron="M-TRI / 17",
        clearance_level="IV",
        status="Active",
        vessel_motto="Hold the Line",
        notes="Flagship of the Frozen Front.",
    )

    entry = config_app._prefill_spec_entry_from_vessel(vessel, "resolute")

    assert entry["slug"] == "resolute"
    assert entry["name"] == "G.N.V Resolute"
    assert entry["call_sign"] == "HNG-45"
    assert entry["role"] == "Command Cruiser"
    assert entry["class_name"] == "M-TRI / 17"
    assert entry["manufacturer"] == "New Babbage Microtech"
    assert entry["badge"] == "Active"
    assert entry["tagline"] == "Hold the Line"
    assert entry["weapons"] == ["VX Lance Battery"]
    assert "Status: Active" in entry["summary"]
    assert "Shipyard: New Babbage Microtech" in entry["systems"][0]
