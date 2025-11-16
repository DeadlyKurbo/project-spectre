import gu7_fleet_specs


def _ship_payload(**overrides):
    base = {
        "slug": "custom-alpha",
        "name": "Custom Alpha",
        "call_sign": "CA-01",
        "role": "Command Frigate",
        "class_name": "Alpha-class",
        "manufacturer": "Orbital Works",
        "length_m": 120.5,
        "beam_m": 32.1,
        "height_m": 18.4,
        "mass_tons": "N/A",
        "crew": "12 operators",
        "cargo_tons": 210,
        "max_speed_ms": 305,
        "jump_range_ly": 18,
        "weapons": ["Rail batteries", "Point-defense"],
        "systems": ["Slipstream nav"],
        "summary": "First bespoke hull.",
        "badge": "Spearhead",
        "tagline": "Lead from the front.",
    }
    base.update(overrides)
    return base


def test_get_gu7_ships_returns_dynamic_entries(monkeypatch):
    payload = {"ships": [_ship_payload(), _ship_payload(slug="beta", name="Beta")]}

    def fake_read_json(key):
        assert key == gu7_fleet_specs._SHIP_MANIFEST_KEY
        return payload

    monkeypatch.setattr(gu7_fleet_specs, "read_json", fake_read_json)

    ships = gu7_fleet_specs.get_gu7_ships()
    assert len(ships) == 2
    first = ships[0]
    assert first.slug == "beta"
    assert first.length_m == 120.5
    assert first.mass_tons is None
    assert first.weapons == ("Rail batteries", "Point-defense")


def test_get_gu7_ships_handles_missing_file(monkeypatch):
    def fake_read_json(key):  # pragma: no cover - helper
        raise FileNotFoundError(key)

    monkeypatch.setattr(gu7_fleet_specs, "read_json", fake_read_json)

    ships = gu7_fleet_specs.get_gu7_ships()
    assert ships == ()


def test_get_ship_by_slug_normalizes_input(monkeypatch):
    payload = {"ships": [_ship_payload(slug="gamma", name="Gamma Vessel")]}

    def fake_read_json(key):
        return payload

    monkeypatch.setattr(gu7_fleet_specs, "read_json", fake_read_json)

    ship = gu7_fleet_specs.get_ship_by_slug("  Gamma  ")
    assert ship is not None
    assert ship.slug == "gamma"
    assert ship.name == "Gamma Vessel"


def test_save_gu7_ship_spec_updates_existing_entry(monkeypatch):
    payload = {"ships": [{"slug": "delta", "name": "Delta"}]}
    saved = {}

    def fake_read_json(key):
        assert key == gu7_fleet_specs._SHIP_MANIFEST_KEY
        return payload

    def fake_save_json(key, data):
        saved["key"] = key
        saved["data"] = data

    monkeypatch.setattr(gu7_fleet_specs, "read_json", fake_read_json)
    monkeypatch.setattr(gu7_fleet_specs, "save_json", fake_save_json)

    entry = {"slug": "Delta", "name": "Delta", "crew": "18"}
    result = gu7_fleet_specs.save_gu7_ship_spec(entry)

    assert result["slug"] == "delta"
    assert saved["key"] == gu7_fleet_specs._SHIP_MANIFEST_KEY
    assert saved["data"]["ships"][0]["crew"] == "18"


def test_save_gu7_ship_spec_handles_missing_manifest(monkeypatch):
    saved = {}

    def fake_read_json(key):  # pragma: no cover - helper
        raise FileNotFoundError(key)

    def fake_save_json(key, data):
        saved["key"] = key
        saved["data"] = data

    monkeypatch.setattr(gu7_fleet_specs, "read_json", fake_read_json)
    monkeypatch.setattr(gu7_fleet_specs, "save_json", fake_save_json)

    entry = {"slug": "sigma", "name": "Sigma"}
    gu7_fleet_specs.save_gu7_ship_spec(entry)

    assert saved["data"] == {"ships": [{"slug": "sigma", "name": "Sigma"}]}
