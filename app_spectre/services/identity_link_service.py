from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class IdentityLinkInput:
    provider: str
    provider_user_id: str
    display_name: str | None = None
    provider_username: str | None = None
    linked_by: str | None = None


class IdentityLinkService:
    """Helper logic for linking multiple identities to one moderated subject."""

    def normalise_provider(self, provider: str) -> str:
        cleaned = str(provider or "").strip().lower()
        if cleaned not in {"website", "discord"}:
            raise ValueError("provider must be either 'website' or 'discord'")
        return cleaned

    def build_identity_record(self, subject_id: str, payload: IdentityLinkInput) -> dict[str, str]:
        provider = self.normalise_provider(payload.provider)
        user_id = str(payload.provider_user_id or "").strip()
        if not user_id:
            raise ValueError("provider_user_id is required")
        return {
            "subjectId": str(subject_id),
            "provider": provider,
            "providerUserId": user_id,
            "displayName": str(payload.display_name or "").strip(),
            "providerUsername": str(payload.provider_username or "").strip(),
            "linkedBy": str(payload.linked_by or "").strip(),
            "linkedAt": _utc_now_iso(),
        }
