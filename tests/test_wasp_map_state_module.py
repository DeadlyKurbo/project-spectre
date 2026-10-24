import pytest

import wasp_map_state as wms
from wasp_map_state import (
    WaspMapConflictError,
    WaspMapOpError,
    apply_wasp_map_ops,
    default_wasp_map_state,
    sanitize_wasp_map_state,
    update_wasp_map_state,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    wms.clear_wasp_map_cache()
    yield
    wms.clear_wasp_map_cache()


def _unit(**overrides):
    item = {"id": "u-1", "name": "1st Armored", "faction": "coalition", "type": "armor", "lat": 50.45, "lng": 30.52}
    item.update(overrides)
    return item


def test_default_state_has_factions_and_empty_theatre():
    state = default_wasp_map_state()

    assert [f["id"] for f in state["factions"]] == ["coalition", "hostile", "neutral"]
    assert state["units"] == state["zones"] == state["lines"] == state["events"] == []
    assert state["meta"]["operation"] == "Unnamed Operation"


def test_legacy_3d_map_state_starts_a_clean_theatre():
    legacy = {"units": [{"id": "seed", "x": 30, "z": 10, "side": "friendly"}], "missionPhase": "recon"}

    assert sanitize_wasp_map_state(legacy) == default_wasp_map_state()


def test_sanitize_cleans_units_and_drops_unusable_ones():
    state = sanitize_wasp_map_state(
        {
            "schema": 2,
            "units": [
                _unit(type=" ARMOR ", echelon="Brigade", status="bogus", strength="250", lng=190, notes="  hold\x07 the bridge "),
                {"id": "no-position", "name": "Ghost"},
                _unit(),  # duplicate id is dropped
                {"id": "x" * 80, "lat": "12.5", "lng": "-4"},
            ],
        }
    )

    first = state["units"][0]
    assert first["type"] == "armor"
    assert first["echelon"] == "brigade"
    assert first["status"] == "active"
    assert first["strength"] == 100
    assert first["lng"] == -170.0
    assert first["notes"] == "hold the bridge"
    assert len(state["units"]) == 2
    assert state["units"][1]["id"] == "x" * 40
    assert state["units"][1]["name"] == "Unnamed Unit"


def test_sanitize_rejects_bad_colors_and_restores_factions():
    state = sanitize_wasp_map_state(
        {"schema": 2, "factions": [{"id": "red", "name": "Red", "color": "red", "stance": "HOSTILE"}]}
    )
    assert state["factions"] == [{"id": "red", "name": "Red", "short": "RED", "color": "#9ca3af", "stance": "hostile"}]

    empty = sanitize_wasp_map_state({"schema": 2, "factions": []})
    assert len(empty["factions"]) == 3


def test_apply_ops_creates_updates_and_deletes_items():
    state = apply_wasp_map_ops(
        default_wasp_map_state(),
        [
            {"op": "upsert", "collection": "units", "item": _unit()},
            {"op": "upsert", "collection": "zones", "item": {"id": "z-1", "name": "AO North", "points": [[51, 30], [52, 31], [51.5, 32]]}},
            {"op": "upsert", "collection": "lines", "item": {"name": "Front", "points": [{"lat": 50, "lng": 35}, {"lat": 48, "lng": 37}]}},
            {"op": "meta", "patch": {"operation": "Operation Hornet", "threatLevel": 9, "status": "active"}},
        ],
        actor="Kurbo",
    )

    assert state["revision"] == 1
    assert state["updatedBy"] == "Kurbo"
    assert state["meta"]["operation"] == "Operation Hornet"
    assert state["meta"]["threatLevel"] == 5
    assert state["lines"][0]["id"].startswith("l-")
    assert state["lines"][0]["points"] == [[50.0, 35.0], [48.0, 37.0]]

    moved = apply_wasp_map_ops(state, [{"op": "upsert", "collection": "units", "item": {"id": "u-1", "lat": 10, "lng": 20}}])
    assert moved["units"][0]["name"] == "1st Armored"  # untouched fields are kept
    assert (moved["units"][0]["lat"], moved["units"][0]["lng"]) == (10.0, 20.0)
    assert moved["revision"] == 2

    deleted = apply_wasp_map_ops(moved, [{"op": "delete", "collection": "zones", "id": "z-1"}])
    assert deleted["zones"] == []


def test_new_events_get_author_and_timestamp_and_sort_newest_first():
    state = apply_wasp_map_ops(
        default_wasp_map_state(),
        [{"op": "upsert", "collection": "events", "item": {"id": "e-old", "title": "Old", "ts": "2026-01-01T00:00:00+00:00"}}],
    )
    state = apply_wasp_map_ops(
        state,
        [{"op": "upsert", "collection": "events", "item": {"id": "e-new", "title": "Strike on depot", "kind": "strike", "lat": 49, "lng": 36}}],
        actor="Kurbo",
    )

    assert [e["id"] for e in state["events"]] == ["e-new", "e-old"]
    assert state["events"][0]["author"] == "Kurbo"
    assert state["events"][0]["ts"]
    assert state["events"][1]["lat"] is None


def test_events_drop_the_oldest_when_full(monkeypatch):
    monkeypatch.setitem(wms._COLLECTION_LIMITS, "events", 2)
    state = default_wasp_map_state()
    for day in (1, 2, 3):
        state = apply_wasp_map_ops(
            state,
            [{"op": "upsert", "collection": "events", "item": {"id": f"e-{day}", "title": str(day), "ts": f"2026-01-0{day}T00:00:00+00:00"}}],
        )

    assert [e["id"] for e in state["events"]] == ["e-3", "e-2"]


@pytest.mark.parametrize(
    "ops, message",
    [
        ([], "non-empty"),
        ([{"op": "explode"}], "Unknown operation"),
        ([{"op": "upsert", "collection": "missions", "item": {}}], "Unknown collection"),
        ([{"op": "upsert", "collection": "units", "item": {"name": "No position"}}], "Invalid unit"),
        ([{"op": "upsert", "collection": "zones", "item": {"points": [[1, 1], [2, 2]]}}], "Invalid zone"),
        ([{"op": "clear", "collection": "factions"}], "cannot be cleared"),
        ([{"op": "delete", "collection": "factions", "id": f} for f in ("coalition", "hostile", "neutral")], "at least one faction"),
    ],
)
def test_bad_ops_raise(ops, message):
    with pytest.raises(WaspMapOpError, match=message):
        apply_wasp_map_ops(default_wasp_map_state(), ops)


def test_replace_imports_a_full_state_but_keeps_revision_counting():
    current = apply_wasp_map_ops(default_wasp_map_state(), [{"op": "upsert", "collection": "units", "item": _unit()}])
    imported = {"meta": {"operation": "Imported"}, "units": [_unit(id="u-9", name="Imported unit")]}

    state = apply_wasp_map_ops(current, [{"op": "replace", "state": imported}])

    assert state["meta"]["operation"] == "Imported"
    assert [u["id"] for u in state["units"]] == ["u-9"]
    assert state["revision"] == current["revision"] + 1


def test_update_retries_when_another_writer_wins(monkeypatch):
    stored = {"data": None, "etag": None, "writes": 0}

    def fake_read(path, with_etag=False):
        return stored["data"], stored["etag"]

    def fake_write(path, data, etag=None):
        stored["writes"] += 1
        if stored["writes"] == 1:
            # Simulate another admin saving first.
            stored["data"] = apply_wasp_map_ops(default_wasp_map_state(), [{"op": "upsert", "collection": "units", "item": _unit(id="theirs")}])
            stored["etag"] = "their-etag"
            return False
        assert etag == stored["etag"]
        stored["data"], stored["etag"] = data, f"etag-{stored['writes']}"
        return True

    monkeypatch.setattr(wms, "read_json", fake_read)
    monkeypatch.setattr(wms, "write_json", fake_write)

    state, etag = update_wasp_map_state([{"op": "upsert", "collection": "units", "item": _unit(id="mine")}], actor="Kurbo")

    assert sorted(u["id"] for u in state["units"]) == ["mine", "theirs"]
    assert etag == "etag-2"


def test_update_gives_up_after_repeated_conflicts(monkeypatch):
    monkeypatch.setattr(wms, "read_json", lambda path, with_etag=False: (None, "e"))
    monkeypatch.setattr(wms, "write_json", lambda path, data, etag=None: False)

    with pytest.raises(WaspMapConflictError):
        update_wasp_map_state([{"op": "meta", "patch": {"operation": "X"}}], attempts=3)


def test_reads_are_cached_briefly(monkeypatch):
    calls = []

    def fake_read(path, with_etag=False):
        calls.append(path)
        return None, None

    monkeypatch.setattr(wms, "read_json", fake_read)
    wms.load_wasp_map_state()
    wms.load_wasp_map_state()
    assert len(calls) == 1

    wms.load_wasp_map_state(use_cache=False)
    assert len(calls) == 2
