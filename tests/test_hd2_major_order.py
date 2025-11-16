from __future__ import annotations

from datetime import datetime, timezone

import pytest

from integrations import hd2


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp()


def test_major_order_prefers_recent_active_order_when_state_is_unknown():
    now = _ts("2024-09-15T00:00:00Z")
    payload = [
        {
            "title": "Old order",
            "status": "success",
            "expires_at": "2024-08-01T00:00:00Z",
        },
        {
            "title": "Fresh order",
            "status": "Ongoing",
            "starts_at": "2024-09-10T12:00:00Z",
        },
    ]

    order = hd2._normalise_major_order(payload, now)  # type: ignore[attr-defined]

    assert order is not None
    assert order["title"] == "Fresh order"


def test_major_order_does_not_activate_future_orders():
    now = _ts("2024-09-15T00:00:00Z")
    payload = [
        {
            "title": "Upcoming order",
            "status": "pending",
            "starts_at": "2024-09-20T00:00:00Z",
        },
        {
            "title": "Live order",
            "status": "live",
            "starts_at": "2024-09-10T00:00:00Z",
        },
    ]

    order = hd2._normalise_major_order(payload, now)  # type: ignore[attr-defined]

    assert order is not None
    assert order["title"] == "Live order"


def test_major_order_detects_nested_payloads():
    now = _ts("2024-09-15T00:00:00Z")
    payload = {
        "data": {
            "currentMajorOrder": {
                "name": "Nested order",
                "details": "Hold the line.",
                "expires_at": "2024-09-16T00:00:00Z",
            }
        }
    }

    order = hd2._normalise_major_order(payload, now)  # type: ignore[attr-defined]

    assert order is not None
    assert order["title"] == "Nested order"


def test_major_order_handles_lists_in_nested_payloads():
    now = _ts("2024-09-15T00:00:00Z")
    payload = {
        "data": {
            "majorOrders": {
                "nodes": [
                    {
                        "title": "Archived order",
                        "status": "success",
                        "expires_at": "2024-09-10T00:00:00Z",
                    },
                    {
                        "title": "Node order",
                        "description": "Liberate priority worlds.",
                        "expires_at": "2024-09-18T00:00:00Z",
                    },
                ]
            }
        }
    }

    order = hd2._normalise_major_order(payload, now)  # type: ignore[attr-defined]

    assert order is not None
    assert order["title"] == "Node order"


def test_major_order_extracts_briefing_and_objectives_progress():
    now = _ts("2024-11-16T12:00:00Z")
    payload = {
        "data": {
            "majorOrders": [
                {
                    "briefing": {
                        "title": "Emergency Dispatch",
                        "summary": "Termidon spores threaten multiple colonies.",
                    },
                    "tasks": [
                        {"planetName": "Hesth", "currentValue": 1, "targetValue": 3},
                        {"planetName": "Angel's Venture", "currentValue": 0, "targetValue": 3},
                    ],
                    "end_time": "2024-11-18T18:00:00Z",
                }
            ]
        }
    }

    order = hd2._normalise_major_order(payload, now)  # type: ignore[attr-defined]

    assert order is not None
    assert order["title"] == "Emergency Dispatch"
    assert order["description"] == "Termidon spores threaten multiple colonies."
    assert order["targets"] == ["Hesth", "Angel's Venture"]
    assert order["current"] == pytest.approx(1)
    assert order["target"] == pytest.approx(6)
    assert order["progress"] == pytest.approx((1 / 6) * 100, rel=1e-3)
    assert order["time_remaining"] == pytest.approx(_ts("2024-11-18T18:00:00Z") - now)
