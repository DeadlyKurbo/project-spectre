from __future__ import annotations

from integrations import hd2


def test_war_snapshot_includes_global_stats_from_status_payload():
    planets = [
        {"enemy": "Terminids", "mission_type": "defense", "liberation": 45.0},
        {"enemy": "Automatons", "mission_type": "strike", "liberation": 82.0},
    ]
    status_payload = {
        "globalStats": {
            "planets_liberated": 24,
            "liberation_percent": 72.5,
            "total_casualties": 1_250_000,
        }
    }

    snapshot = hd2._build_war_snapshot(planets, status_payload)  # type: ignore[attr-defined]

    assert snapshot["active_fronts"] == 2
    assert snapshot["planets_liberated"] == 24
    assert snapshot["current_liberation_percent"] == 72.5
    assert snapshot["total_casualties"] == 1_250_000


def test_war_snapshot_counts_liberated_planets_when_stats_missing():
    planets = [
        {"enemy": "Terminids", "mission_type": "defense", "liberation": 100.0},
        {"enemy": "Automatons", "mission_type": "strike", "liberation": 62.0},
        {"enemy": "Terminids", "mission_type": "strike", "liberation": 101.0},
    ]

    snapshot = hd2._build_war_snapshot(planets, {})  # type: ignore[attr-defined]

    assert snapshot["planets_liberated"] == 2
    assert snapshot["current_liberation_percent"] is None
    assert snapshot["total_casualties"] is None
