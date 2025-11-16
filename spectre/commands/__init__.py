"""Collection of slash command registrations."""

from __future__ import annotations

from ..context import SpectreContext

from . import (
    archivist,
    archive_menu,
    dossier_images,
    links,
    operators,
    protocols,
    requests,
)


def register_all(context: SpectreContext) -> None:
    """Register every command module with the provided context."""

    for module in (
        archivist,
        archive_menu,
        dossier_images,
        links,
        operators,
        protocols,
        requests,
    ):
        module.register(context)


__all__ = ["register_all"]
