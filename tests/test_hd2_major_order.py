from __future__ import annotations

from datetime import datetime, timezone

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
