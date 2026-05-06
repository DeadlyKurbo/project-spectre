from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

try:
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    asyncpg = None

from app_spectre.services.audit_service import AuditEventInput, AuditService
from app_spectre.services.identity_link_service import IdentityLinkInput, IdentityLinkService
from spectre.moderation.discord_bridge import (
    DiscordModerationBridge,
    DiscordModerationRequest,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class ModerationRepository(Protocol):
    async def create_subject(self, canonical_label: str) -> dict[str, Any]: ...
    async def list_subjects(self) -> list[dict[str, Any]]: ...
    async def get_subject(self, subject_id: str) -> dict[str, Any] | None: ...
    async def add_identity(self, subject_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def list_identities(self, subject_id: str) -> list[dict[str, Any]]: ...
    async def create_case(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def list_cases(self, status: str | None = None) -> list[dict[str, Any]]: ...
    async def add_case_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def create_sanction(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def update_sanction_status(self, sanction_id: str, status: str, error: str | None = None) -> None: ...
    async def list_sanctions(self, subject_id: str | None = None) -> list[dict[str, Any]]: ...
    async def record_enforcement_action(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def create_appeal(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def update_appeal(self, appeal_id: str, payload: dict[str, Any]) -> dict[str, Any] | None: ...
    async def list_appeals(self, status: str | None = None) -> list[dict[str, Any]]: ...
    async def append_audit_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def list_audit_events(self, limit: int) -> list[dict[str, Any]]: ...


class InMemoryModerationRepository:
    """Repository used for tests/dev when PostgreSQL is unavailable."""

    def __init__(self) -> None:
        self.subjects: dict[str, dict[str, Any]] = {}
        self.identities: dict[str, dict[str, Any]] = {}
        self.cases: dict[str, dict[str, Any]] = {}
        self.case_events: dict[str, dict[str, Any]] = {}
        self.sanctions: dict[str, dict[str, Any]] = {}
        self.enforcement_actions: dict[str, dict[str, Any]] = {}
        self.appeals: dict[str, dict[str, Any]] = {}
        self.audit_events: dict[str, dict[str, Any]] = {}

    async def create_subject(self, canonical_label: str) -> dict[str, Any]:
        subject_id = _uuid()
        record = {
            "id": subject_id,
            "canonicalLabel": canonical_label,
            "status": "active",
            "riskScore": 0,
            "createdAt": _utc_now().isoformat(),
            "updatedAt": _utc_now().isoformat(),
        }
        self.subjects[subject_id] = record
        return record

    async def list_subjects(self) -> list[dict[str, Any]]:
        return list(self.subjects.values())

    async def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        return self.subjects.get(subject_id)

    async def add_identity(self, subject_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        identity_id = _uuid()
        record = {"id": identity_id, **payload}
        self.identities[identity_id] = record
        return record

    async def list_identities(self, subject_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self.identities.values() if entry.get("subjectId") == subject_id]

    async def create_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = _uuid()
        record = {"id": case_id, **payload}
        self.cases[case_id] = record
        return record

    async def list_cases(self, status: str | None = None) -> list[dict[str, Any]]:
        values = list(self.cases.values())
        if status:
            values = [entry for entry in values if entry.get("status") == status]
        return values

    async def add_case_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = _uuid()
        record = {"id": event_id, **payload}
        self.case_events[event_id] = record
        return record

    async def create_sanction(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanction_id = _uuid()
        record = {"id": sanction_id, **payload}
        self.sanctions[sanction_id] = record
        return record

    async def update_sanction_status(self, sanction_id: str, status: str, error: str | None = None) -> None:
        sanction = self.sanctions.get(sanction_id)
        if not sanction:
            return
        sanction["status"] = status
        sanction["error"] = error

    async def list_sanctions(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        values = list(self.sanctions.values())
        if subject_id:
            values = [entry for entry in values if entry.get("subjectId") == subject_id]
        return values

    async def record_enforcement_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action_id = _uuid()
        record = {"id": action_id, **payload}
        self.enforcement_actions[action_id] = record
        return record

    async def create_appeal(self, payload: dict[str, Any]) -> dict[str, Any]:
        appeal_id = _uuid()
        record = {"id": appeal_id, **payload}
        self.appeals[appeal_id] = record
        return record

    async def update_appeal(self, appeal_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        appeal = self.appeals.get(appeal_id)
        if not appeal:
            return None
        appeal.update(payload)
        return appeal

    async def list_appeals(self, status: str | None = None) -> list[dict[str, Any]]:
        values = list(self.appeals.values())
        if status:
            values = [entry for entry in values if entry.get("status") == status]
        return values

    async def append_audit_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = _uuid()
        record = {"id": event_id, **payload}
        self.audit_events[event_id] = record
        return record

    async def list_audit_events(self, limit: int) -> list[dict[str, Any]]:
        values = list(self.audit_events.values())
        values.sort(key=lambda item: item.get("occurredAt", ""), reverse=True)
        return values[:limit]


class PostgresModerationRepository:
    """PostgreSQL-backed moderation repository for production storage."""

    def __init__(self, database_url: str) -> None:
        if asyncpg is None:
            raise RuntimeError("asyncpg is required for PostgresModerationRepository")
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def _pool_conn(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=4)
        return self._pool

    async def create_subject(self, canonical_label: str) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO moderated_subjects (canonical_label)
            VALUES ($1)
            RETURNING id::text AS id, canonical_label AS "canonicalLabel", status::text AS status,
                      risk_score AS "riskScore", created_at AS "createdAt", updated_at AS "updatedAt"
            """,
            canonical_label,
        )
        return dict(row)

    async def list_subjects(self) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        rows = await pool.fetch(
            """
            SELECT id::text AS id, canonical_label AS "canonicalLabel", status::text AS status,
                   risk_score AS "riskScore", created_at AS "createdAt", updated_at AS "updatedAt"
            FROM moderated_subjects
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in rows]

    async def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            SELECT id::text AS id, canonical_label AS "canonicalLabel", status::text AS status,
                   risk_score AS "riskScore", created_at AS "createdAt", updated_at AS "updatedAt"
            FROM moderated_subjects
            WHERE id = $1::uuid
            """,
            subject_id,
        )
        return dict(row) if row else None

    async def add_identity(self, subject_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO user_identities (
                subject_id, provider, provider_user_id, display_name, provider_username, linked_by, metadata
            )
            VALUES (
                $1::uuid, $2::identity_provider, $3, NULLIF($4, ''), NULLIF($5, ''), NULLIF($6, ''), $7::jsonb
            )
            ON CONFLICT (provider, provider_user_id) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                provider_username = EXCLUDED.provider_username,
                linked_by = EXCLUDED.linked_by,
                metadata = EXCLUDED.metadata
            RETURNING id::text AS id, subject_id::text AS "subjectId", provider::text AS provider,
                      provider_user_id AS "providerUserId", display_name AS "displayName",
                      provider_username AS "providerUsername", linked_at AS "linkedAt"
            """,
            subject_id,
            payload["provider"],
            payload["providerUserId"],
            payload["displayName"],
            payload["providerUsername"],
            payload["linkedBy"],
            payload.get("metadata", {}),
        )
        return dict(row)

    async def list_identities(self, subject_id: str) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        rows = await pool.fetch(
            """
            SELECT id::text AS id, subject_id::text AS "subjectId", provider::text AS provider,
                   provider_user_id AS "providerUserId", display_name AS "displayName",
                   provider_username AS "providerUsername", linked_at AS "linkedAt"
            FROM user_identities
            WHERE subject_id = $1::uuid
            ORDER BY linked_at DESC
            """,
            subject_id,
        )
        return [dict(row) for row in rows]

    async def create_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO moderation_cases (
                subject_id, status, priority, title, description, reporter_identity_id, assignee_identity_id,
                opened_by_identity_id, metadata
            )
            VALUES (
                $1::uuid, $2::case_status, $3::case_priority, $4, $5, $6::uuid, $7::uuid, $8::uuid, $9::jsonb
            )
            RETURNING id::text AS id, subject_id::text AS "subjectId", status::text AS status,
                      priority::text AS priority, title, description, opened_at AS "openedAt"
            """,
            payload["subjectId"],
            payload["status"],
            payload["priority"],
            payload["title"],
            payload["description"],
            payload.get("reporterIdentityId"),
            payload.get("assigneeIdentityId"),
            payload.get("openedByIdentityId"),
            payload.get("metadata", {}),
        )
        return dict(row)

    async def list_cases(self, status: str | None = None) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        if status:
            rows = await pool.fetch(
                """
                SELECT id::text AS id, subject_id::text AS "subjectId", status::text AS status,
                       priority::text AS priority, title, description, opened_at AS "openedAt"
                FROM moderation_cases
                WHERE status = $1::case_status
                ORDER BY opened_at DESC
                """,
                status,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id::text AS id, subject_id::text AS "subjectId", status::text AS status,
                       priority::text AS priority, title, description, opened_at AS "openedAt"
                FROM moderation_cases
                ORDER BY opened_at DESC
                """
            )
        return [dict(row) for row in rows]

    async def add_case_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO case_events (case_id, event_type, event_summary, event_payload, actor_identity_id)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5::uuid)
            RETURNING id::text AS id, case_id::text AS "caseId", event_type AS "eventType",
                      event_summary AS "eventSummary", created_at AS "createdAt"
            """,
            payload["caseId"],
            payload["eventType"],
            payload["eventSummary"],
            payload.get("eventPayload", {}),
            payload.get("actorIdentityId"),
        )
        return dict(row)

    async def create_sanction(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO sanctions (
                case_id, subject_id, target, sanction, status, reason, evidence, imposed_by_identity_id,
                starts_at, ends_at, metadata
            )
            VALUES (
                $1::uuid, $2::uuid, $3::sanction_target, $4::sanction_type, $5::sanction_status, $6, $7::jsonb,
                $8::uuid, NOW(), $9::timestamptz, $10::jsonb
            )
            RETURNING id::text AS id, case_id::text AS "caseId", subject_id::text AS "subjectId",
                      target::text AS target, sanction::text AS sanction, status::text AS status,
                      reason, starts_at AS "startsAt", ends_at AS "endsAt"
            """,
            payload.get("caseId"),
            payload["subjectId"],
            payload["target"],
            payload["sanction"],
            payload["status"],
            payload["reason"],
            payload.get("evidence", []),
            payload.get("imposedByIdentityId"),
            payload.get("endsAt"),
            payload.get("metadata", {}),
        )
        return dict(row)

    async def update_sanction_status(self, sanction_id: str, status: str, error: str | None = None) -> None:
        pool = await self._pool_conn()
        await pool.execute(
            """
            UPDATE sanctions
            SET status = $2::sanction_status,
                metadata = jsonb_set(metadata, '{error}', to_jsonb($3::text), true)
            WHERE id = $1::uuid
            """,
            sanction_id,
            status,
            error,
        )

    async def list_sanctions(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        if subject_id:
            rows = await pool.fetch(
                """
                SELECT id::text AS id, case_id::text AS "caseId", subject_id::text AS "subjectId",
                       target::text AS target, sanction::text AS sanction, status::text AS status,
                       reason, starts_at AS "startsAt", ends_at AS "endsAt"
                FROM sanctions
                WHERE subject_id = $1::uuid
                ORDER BY starts_at DESC
                """,
                subject_id,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id::text AS id, case_id::text AS "caseId", subject_id::text AS "subjectId",
                       target::text AS target, sanction::text AS sanction, status::text AS status,
                       reason, starts_at AS "startsAt", ends_at AS "endsAt"
                FROM sanctions
                ORDER BY starts_at DESC
                """
            )
        return [dict(row) for row in rows]

    async def record_enforcement_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO enforcement_actions (
                sanction_id, operation_key, provider, provider_scope_id, provider_action, request_payload,
                response_payload, status, error_message, attempted_at, completed_at
            )
            VALUES (
                $1::uuid, $2, $3::identity_provider, $4, $5, $6::jsonb, $7::jsonb,
                $8::sanction_status, $9, $10::timestamptz, $11::timestamptz
            )
            RETURNING id::text AS id, sanction_id::text AS "sanctionId", operation_key AS "operationKey",
                      provider::text AS provider, provider_action AS "providerAction", status::text AS status
            """,
            payload["sanctionId"],
            payload["operationKey"],
            payload["provider"],
            payload.get("providerScopeId"),
            payload["providerAction"],
            payload.get("requestPayload", {}),
            payload.get("responsePayload", {}),
            payload["status"],
            payload.get("errorMessage"),
            payload.get("attemptedAt"),
            payload.get("completedAt"),
        )
        return dict(row)

    async def create_appeal(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO appeals (
                sanction_id, case_id, appellant_identity_id, submitted_by_identity_id, status, appeal_reason
            )
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::appeal_status, $6)
            RETURNING id::text AS id, sanction_id::text AS "sanctionId", case_id::text AS "caseId",
                      status::text AS status, appeal_reason AS "appealReason", submitted_at AS "submittedAt"
            """,
            payload["sanctionId"],
            payload.get("caseId"),
            payload.get("appellantIdentityId"),
            payload.get("submittedByIdentityId"),
            payload["status"],
            payload["appealReason"],
        )
        return dict(row)

    async def update_appeal(self, appeal_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            UPDATE appeals
            SET status = $2::appeal_status,
                moderator_notes = $3,
                decision_summary = $4,
                decided_by_identity_id = $5::uuid,
                decided_at = NOW()
            WHERE id = $1::uuid
            RETURNING id::text AS id, sanction_id::text AS "sanctionId", case_id::text AS "caseId",
                      status::text AS status, appeal_reason AS "appealReason", submitted_at AS "submittedAt",
                      decided_at AS "decidedAt", decision_summary AS "decisionSummary"
            """,
            appeal_id,
            payload["status"],
            payload.get("moderatorNotes"),
            payload.get("decisionSummary"),
            payload.get("decidedByIdentityId"),
        )
        return dict(row) if row else None

    async def list_appeals(self, status: str | None = None) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        if status:
            rows = await pool.fetch(
                """
                SELECT id::text AS id, sanction_id::text AS "sanctionId", case_id::text AS "caseId",
                       status::text AS status, appeal_reason AS "appealReason", submitted_at AS "submittedAt"
                FROM appeals
                WHERE status = $1::appeal_status
                ORDER BY submitted_at DESC
                """,
                status,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id::text AS id, sanction_id::text AS "sanctionId", case_id::text AS "caseId",
                       status::text AS status, appeal_reason AS "appealReason", submitted_at AS "submittedAt"
                FROM appeals
                ORDER BY submitted_at DESC
                """
            )
        return [dict(row) for row in rows]

    async def append_audit_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            INSERT INTO audit_events (
                event_type, actor_identity_id, subject_id, case_id, sanction_id, appeal_id, source, request_id,
                ip_address, metadata
            )
            VALUES (
                $1, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6::uuid, $7, $8, $9, $10::jsonb
            )
            RETURNING id::text AS id, event_type AS "eventType", source, occurred_at AS "occurredAt", metadata
            """,
            payload["eventType"],
            payload.get("actorIdentityId"),
            payload.get("subjectId"),
            payload.get("caseId"),
            payload.get("sanctionId"),
            payload.get("appealId"),
            payload["source"],
            payload.get("requestId"),
            payload.get("ipAddress"),
            payload.get("metadata", {}),
        )
        return dict(row)

    async def list_audit_events(self, limit: int) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        rows = await pool.fetch(
            """
            SELECT id::text AS id, event_type AS "eventType", source, occurred_at AS "occurredAt", metadata
            FROM audit_events
            ORDER BY occurred_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]


class ModerationService:
    def __init__(self, repository: ModerationRepository, bridge: DiscordModerationBridge | None = None) -> None:
        self.repository = repository
        self.identity_links = IdentityLinkService()
        self.audit = AuditService()
        self.discord_bridge = bridge or DiscordModerationBridge()

    async def create_subject(self, canonical_label: str, actor_id: str | None = None) -> dict[str, Any]:
        label = str(canonical_label or "").strip()
        if not label:
            raise ValueError("canonical_label is required")
        subject = await self.repository.create_subject(label)
        await self.record_audit(
            event_type="subject.created",
            source="moderation-api",
            actor_identity_id=actor_id,
            subject_id=subject["id"],
            metadata={"canonicalLabel": label},
        )
        return subject

    async def link_identity(self, subject_id: str, payload: IdentityLinkInput) -> dict[str, Any]:
        subject = await self.repository.get_subject(subject_id)
        if subject is None:
            raise ValueError("subject not found")
        data = self.identity_links.build_identity_record(subject_id, payload)
        identity = await self.repository.add_identity(subject_id, data)
        await self.record_audit(
            event_type="identity.linked",
            source="moderation-api",
            actor_identity_id=data.get("linkedBy"),
            subject_id=subject_id,
            metadata={"provider": data["provider"], "providerUserId": data["providerUserId"]},
        )
        return identity

    async def get_subject_profile(self, subject_id: str) -> dict[str, Any]:
        subject = await self.repository.get_subject(subject_id)
        if subject is None:
            raise ValueError("subject not found")
        identities = await self.repository.list_identities(subject_id)
        sanctions = await self.repository.list_sanctions(subject_id)
        return {"subject": subject, "identities": identities, "sanctions": sanctions}

    async def list_subjects(self) -> list[dict[str, Any]]:
        return await self.repository.list_subjects()

    async def create_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_payload = {
            "subjectId": payload["subjectId"],
            "status": payload.get("status", "open"),
            "priority": payload.get("priority", "normal"),
            "title": payload["title"].strip(),
            "description": payload["description"].strip(),
            "reporterIdentityId": payload.get("reporterIdentityId"),
            "assigneeIdentityId": payload.get("assigneeIdentityId"),
            "openedByIdentityId": payload.get("openedByIdentityId"),
            "metadata": payload.get("metadata", {}),
            "openedAt": _utc_now().isoformat(),
        }
        case_record = await self.repository.create_case(case_payload)
        event = await self.repository.add_case_event(
            {
                "caseId": case_record["id"],
                "eventType": "case.created",
                "eventSummary": "Case created",
                "eventPayload": {"title": case_record["title"], "priority": case_record["priority"]},
                "actorIdentityId": case_payload.get("openedByIdentityId"),
            }
        )
        await self.record_audit(
            event_type="case.created",
            source="moderation-api",
            actor_identity_id=case_payload.get("openedByIdentityId"),
            subject_id=case_payload["subjectId"],
            case_id=case_record["id"],
            metadata={"priority": case_record["priority"], "eventId": event["id"]},
        )
        return case_record

    async def list_cases(self, status: str | None = None) -> list[dict[str, Any]]:
        return await self.repository.list_cases(status=status)

    async def create_sanction(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanction_payload = {
            "caseId": payload.get("caseId"),
            "subjectId": payload["subjectId"],
            "target": payload["target"],
            "sanction": payload["sanction"],
            "status": "pending",
            "reason": payload["reason"].strip(),
            "evidence": payload.get("evidence", []),
            "imposedByIdentityId": payload.get("imposedByIdentityId"),
            "endsAt": payload.get("endsAt"),
            "metadata": payload.get("metadata", {}),
        }
        sanction = await self.repository.create_sanction(sanction_payload)
        result = await self._execute_enforcement(sanction, payload.get("guildId"))
        await self.repository.update_sanction_status(
            sanction["id"],
            result["status"],
            result.get("error"),
        )
        sanction["status"] = result["status"]
        sanction["actionReceipt"] = result["action"]
        await self.record_audit(
            event_type="sanction.imposed",
            source="moderation-api",
            actor_identity_id=sanction_payload.get("imposedByIdentityId"),
            subject_id=sanction_payload["subjectId"],
            case_id=sanction_payload.get("caseId"),
            sanction_id=sanction["id"],
            metadata={"target": sanction["target"], "sanction": sanction["sanction"], "status": sanction["status"]},
        )
        return sanction

    async def list_sanctions(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        return await self.repository.list_sanctions(subject_id=subject_id)

    async def create_appeal(self, payload: dict[str, Any]) -> dict[str, Any]:
        appeal = await self.repository.create_appeal(
            {
                "sanctionId": payload["sanctionId"],
                "caseId": payload.get("caseId"),
                "appellantIdentityId": payload.get("appellantIdentityId"),
                "submittedByIdentityId": payload.get("submittedByIdentityId"),
                "status": "submitted",
                "appealReason": payload["appealReason"].strip(),
            }
        )
        await self.record_audit(
            event_type="appeal.submitted",
            source="moderation-api",
            actor_identity_id=payload.get("submittedByIdentityId"),
            appeal_id=appeal["id"],
            sanction_id=payload["sanctionId"],
            case_id=payload.get("caseId"),
        )
        return appeal

    async def update_appeal(self, appeal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        updated = await self.repository.update_appeal(appeal_id, payload)
        if updated is None:
            raise ValueError("appeal not found")
        await self.record_audit(
            event_type="appeal.decided",
            source="moderation-api",
            actor_identity_id=payload.get("decidedByIdentityId"),
            appeal_id=appeal_id,
            metadata={"status": payload.get("status"), "decision": payload.get("decisionSummary")},
        )
        return updated

    async def list_appeals(self, status: str | None = None) -> list[dict[str, Any]]:
        return await self.repository.list_appeals(status=status)

    async def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        return await self.repository.list_audit_events(limit=bounded)

    async def record_audit(
        self,
        *,
        event_type: str,
        source: str,
        actor_identity_id: str | None = None,
        subject_id: str | None = None,
        case_id: str | None = None,
        sanction_id: str | None = None,
        appeal_id: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.audit.normalise(
            AuditEventInput(
                event_type=event_type,
                source=source,
                actor_identity_id=actor_identity_id,
                subject_id=subject_id,
                case_id=case_id,
                sanction_id=sanction_id,
                appeal_id=appeal_id,
                request_id=request_id,
                ip_address=ip_address,
                metadata=metadata or {},
            )
        )
        return await self.repository.append_audit_event(event)

    async def _execute_enforcement(self, sanction: dict[str, Any], guild_id: str | None) -> dict[str, Any]:
        target = sanction.get("target")
        subject_id = sanction.get("subjectId")
        action_type = sanction.get("sanction")
        provider = "website" if target == "website" else "discord"
        op_key = f"{sanction['id']}:{provider}:{action_type}"
        request_payload = {"guildId": guild_id, "subjectId": subject_id, "action": action_type}

        status_value = "completed"
        response_payload: dict[str, Any] = {"ok": True}
        error_message: str | None = None
        attempted_at = _utc_now().isoformat()
        completed_at = attempted_at

        if target == "discord":
            receipt = await self.discord_bridge.execute(
                DiscordModerationRequest(
                    operation_key=op_key,
                    subject_id=str(subject_id),
                    action=str(action_type),
                    guild_id=str(guild_id or ""),
                    reason=str(sanction.get("reason") or ""),
                )
            )
            status_value = "completed" if receipt.success else "failed"
            response_payload = receipt.response_payload
            error_message = receipt.error

        action_receipt = await self.repository.record_enforcement_action(
            {
                "sanctionId": sanction["id"],
                "operationKey": op_key,
                "provider": provider,
                "providerScopeId": guild_id,
                "providerAction": str(action_type),
                "requestPayload": request_payload,
                "responsePayload": response_payload,
                "status": status_value,
                "errorMessage": error_message,
                "attemptedAt": attempted_at,
                "completedAt": completed_at,
            }
        )
        return {"status": status_value, "error": error_message, "action": action_receipt}


_shared_service: ModerationService | None = None


def get_moderation_service() -> ModerationService:
    global _shared_service
    if _shared_service is not None:
        return _shared_service
    db_url = os.getenv("MODERATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if db_url and asyncpg is not None:
        repository: ModerationRepository = PostgresModerationRepository(db_url)
    else:
        repository = InMemoryModerationRepository()
    _shared_service = ModerationService(repository=repository)
    return _shared_service
