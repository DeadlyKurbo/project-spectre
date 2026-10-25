from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

IdentityProvider = Literal["website", "discord"]
SubjectStatus = Literal["active", "restricted", "suspended", "banned"]
SanctionTarget = Literal["website", "discord"]
SanctionType = Literal[
    "warning",
    "note",
    "read_only",
    "quarantine",
    "timeout",
    "suspension",
    "kick",
    "ban",
]
SanctionStatus = Literal["pending", "active", "completed", "revoked", "failed"]
CaseStatus = Literal["open", "investigating", "actioned", "resolved", "dismissed"]
CasePriority = Literal["low", "normal", "high", "critical"]
AppealStatus = Literal["submitted", "under_review", "approved", "denied", "withdrawn"]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ModeratedSubject:
    id: str
    canonical_label: str
    status: SubjectStatus = "active"
    risk_score: int = 0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class UserIdentity:
    id: str
    subject_id: str
    provider: IdentityProvider
    provider_user_id: str
    display_name: str | None = None
    provider_username: str | None = None
    linked_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    linked_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class ModerationCase:
    id: str
    subject_id: str
    title: str
    description: str
    status: CaseStatus = "open"
    priority: CasePriority = "normal"
    reporter_identity_id: str | None = None
    assignee_identity_id: str | None = None
    opened_by_identity_id: str | None = None
    resolved_by_identity_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    opened_at: datetime = field(default_factory=_now_utc)
    resolved_at: datetime | None = None


@dataclass(slots=True)
class CaseEvent:
    id: str
    case_id: str
    event_type: str
    event_summary: str
    event_payload: dict[str, Any] = field(default_factory=dict)
    actor_identity_id: str | None = None
    created_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class SanctionRecord:
    id: str
    subject_id: str
    target: SanctionTarget
    sanction: SanctionType
    reason: str
    status: SanctionStatus = "pending"
    case_id: str | None = None
    imposed_by_identity_id: str | None = None
    revoked_by_identity_id: str | None = None
    revoke_reason: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    starts_at: datetime = field(default_factory=_now_utc)
    ends_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(slots=True)
class AppealRecord:
    id: str
    sanction_id: str
    appeal_reason: str
    status: AppealStatus = "submitted"
    case_id: str | None = None
    appellant_identity_id: str | None = None
    submitted_by_identity_id: str | None = None
    moderator_notes: str | None = None
    decision_summary: str | None = None
    decided_by_identity_id: str | None = None
    submitted_at: datetime = field(default_factory=_now_utc)
    decided_at: datetime | None = None


@dataclass(slots=True)
class AuditEvent:
    id: str
    event_type: str
    source: str
    actor_identity_id: str | None = None
    subject_id: str | None = None
    case_id: str | None = None
    sanction_id: str | None = None
    appeal_id: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=_now_utc)
