"""Runtime validation of the Nextcord dependency."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version
import nextcord

_MIN_NEXTCORD_VERSION = Version("2.6.0")


def ensure_nextcord_version() -> None:
    """Abort startup when the installed Nextcord build is too old."""

    try:
        current_version = Version(nextcord.__version__)
    except InvalidVersion as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Unable to parse Nextcord version '{nextcord.__version__}'. "
            "Please install a stable release of 'nextcord'."
        ) from exc

    if current_version < _MIN_NEXTCORD_VERSION:
        raise RuntimeError(
            f"Nextcord {_MIN_NEXTCORD_VERSION}+ is required; "
            f"found {nextcord.__version__}. Please upgrade the 'nextcord' package."
        )


__all__ = ["ensure_nextcord_version", "_MIN_NEXTCORD_VERSION"]
