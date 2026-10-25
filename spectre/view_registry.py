"""Helpers to avoid duplicate persistent view registrations."""

from __future__ import annotations

from typing import Any
from weakref import WeakKeyDictionary

_REGISTERED_VIEW_KEYS: WeakKeyDictionary[object, set[str]] = WeakKeyDictionary()


def _derive_view_key(view: Any) -> str:
    parts = [f"{view.__class__.__module__}.{view.__class__.__qualname__}"]

    guild_id = getattr(view, "guild_id", None)
    if guild_id is not None:
        parts.append(f"guild:{guild_id}")

    report_id = getattr(view, "report_id", None)
    if report_id is not None:
        parts.append(f"report:{report_id}")

    custom_ids: list[str] = []
    for child in getattr(view, "children", ()):
        custom_id = getattr(child, "custom_id", None)
        if custom_id:
            custom_ids.append(str(custom_id))
    if custom_ids:
        parts.append(",".join(sorted(custom_ids)))

    return "|".join(parts)


def register_persistent_view_once(bot: Any, view: Any, *, key: str | None = None) -> bool:
    """Register ``view`` once per process for the given bot instance."""

    registered = _REGISTERED_VIEW_KEYS.setdefault(bot, set())
    registry_key = str(key or _derive_view_key(view))
    if registry_key in registered:
        return False
    bot.add_view(view)
    registered.add(registry_key)
    return True


def clear_registered_views(bot: Any | None = None) -> None:
    """Clear dedupe state for tests and controlled restarts."""

    if bot is None:
        _REGISTERED_VIEW_KEYS.clear()
        return
    _REGISTERED_VIEW_KEYS.pop(bot, None)
