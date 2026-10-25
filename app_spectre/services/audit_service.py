from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AuditEventInput:
    event_type: str
    source: str
    actor_identity_id: str | None = None
    subject_id: str | None = None
    case_id: str | None = None
    sanction_id: str | None = None
    appeal_id: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] | None = None


class AuditService:
    """Normalises audit event payloads before persistence."""

    def normalise(self, payload: AuditEventInput) -> dict[str, Any]:
        event_type = str(payload.event_type or "").strip()
        if not event_type:
            raise ValueError("event_type is required")
        source = str(payload.source or "").strip()
        if not source:
            raise ValueError("source is required")

        return {
            "eventType": event_type,
            "source": source,
            "actorIdentityId": _clean(payload.actor_identity_id),
            "subjectId": _clean(payload.subject_id),
            "caseId": _clean(payload.case_id),
            "sanctionId": _clean(payload.sanction_id),
            "appealId": _clean(payload.appeal_id),
            "requestId": _clean(payload.request_id),
            "ipAddress": _clean(payload.ip_address),
            "metadata": payload.metadata or {},
            "occurredAt": datetime.now(timezone.utc).isoformat(),
        }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
