from wasp_map_state import default_wasp_map_state, sanitize_wasp_map_state


def test_sanitize_wasp_map_state_falls_back_to_default():
    state = sanitize_wasp_map_state(None)

    assert state == default_wasp_map_state()


def test_sanitize_wasp_map_state_normalizes_units():
    state = sanitize_wasp_map_state(
        {
            "units": [
                {
                    "id": "  alpha  ",
                    "type": " TANK ",
                    "name": "  Spearhead ",
                    "country": "  UEE  ",
                    "side": " FRIENDLY ",
                    "x": "12.5",
                    "z": "-4",
                },
                {"id": "beta", "side": "invalid", "x": "bad", "z": None},
            ]
        }
    )

    assert state["units"][0] == {
        "id": "alpha",
        "type": "tank",
        "name": "Spearhead",
        "country": "UEE",
        "side": "friendly",
        "x": 12.5,
        "z": -4.0,
    }
    assert state["units"][1]["side"] == "enemy"
    assert state["units"][1]["x"] == 0.0
    assert state["units"][1]["z"] == 0.0
