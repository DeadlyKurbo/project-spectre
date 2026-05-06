"""Collection of slash command registrations."""

from __future__ import annotations

from ..context import SpectreContext

from . import (
    archivist,
    archive_menu,
    dossier_images,
    links,
    operators,
    promote_demote,
    protocols,
    requests,
)

MODERATION_AUDIT_EVENT_KEYS = ("moderation_action",)


def register_all(context: SpectreContext) -> None:
    """Register every command module with the provided context."""

    for module in (
        archivist,
        archive_menu,
        dossier_images,
        links,
        operators,
        promote_demote,
        protocols,
        requests,
    ):
        module.register(context)


__all__ = ["MODERATION_AUDIT_EVENT_KEYS", "register_all"]
