from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "moderation_schema.sql"
# Arbitrary constant so concurrent processes don't race while creating the schema.
_SCHEMA_LOCK_KEY = 7_314_220_115


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


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
    async def close(self) -> None: ...


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
        subjects = []
        for subject in self.subjects.values():
            identities = await self.list_identities(subject["id"])
            discord = next((i["providerUserId"] for i in identities if i.get("provider") == "discord"), None)
            subjects.append({**subject, "discordUserId": discord})
        return subjects

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

    async def update_case(self, case_id: str, status: str) -> dict[str, Any] | None:
        case = self.cases.get(case_id)
        if not case:
            return None
        case["status"] = status
        case["resolvedAt"] = _utc_now().isoformat() if status in {"resolved", "dismissed"} else None
        return case

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

    async def get_sanction(self, sanction_id: str) -> dict[str, Any] | None:
        return self.sanctions.get(sanction_id)

    async def revoke_sanction(self, sanction_id: str, reason: str, actor: dict[str, Any]) -> dict[str, Any] | None:
        sanction = self.sanctions.get(sanction_id)
        if not sanction:
            return None
        sanction.update(
            {"status": "revoked", "revokedAt": _utc_now().isoformat(), "revokeReason": reason}
        )
        sanction.setdefault("metadata", {})["revokedBy"] = actor
        return sanction

    async def active_website_blocks(self) -> list[dict[str, Any]]:
        now = _utc_now()
        blocks: dict[str, dict[str, Any]] = {}
        for sanction in self.sanctions.values():
            if sanction.get("target") != "website" or sanction.get("status") != "active":
                continue
            if sanction.get("sanction") not in {"timeout", "suspension", "ban"}:
                continue
            ends_at = sanction.get("endsAt")
            if ends_at and datetime.fromisoformat(str(ends_at)) <= now:
                continue
            for identity in await self.list_identities(sanction["subjectId"]):
                blocks[identity["providerUserId"]] = {
                    "userId": identity["providerUserId"],
                    "sanctionId": sanction["id"],
                    "sanction": sanction["sanction"],
                    "reason": sanction.get("reason"),
                    "endsAt": ends_at,
                }
        return list(blocks.values())

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

    async def close(self) -> None:
        return None


_SANCTION_COLUMNS = """
    id::text AS id, case_id::text AS "caseId", subject_id::text AS "subjectId",
    target::text AS target, sanction::text AS sanction, status::text AS status,
    reason, starts_at AS "startsAt", ends_at AS "endsAt", revoked_at AS "revokedAt",
    revoke_reason AS "revokeReason", metadata
"""
_CASE_COLUMNS = """
    id::text AS id, subject_id::text AS "subjectId", status::text AS status,
    priority::text AS priority, title, description, opened_at AS "openedAt",
    resolved_at AS "resolvedAt", metadata
"""
_AUDIT_COLUMNS = """
    id::text AS id, event_type AS "eventType", source, occurred_at AS "occurredAt",
    subject_id::text AS "subjectId", case_id::text AS "caseId",
    sanction_id::text AS "sanctionId", appeal_id::text AS "appealId", metadata
"""


async def _init_connection(conn: Any) -> None:
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(type_name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def _ensure_schema(pool: Any) -> None:
    """Create the moderation tables on first use; the SQL is idempotent."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = schema.replace('CREATE EXTENSION IF NOT EXISTS "pgcrypto";', "")
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", _SCHEMA_LOCK_KEY)
        try:
            try:
                await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
            except Exception:  # gen_random_uuid() is built in from PostgreSQL 13
                logger.info("pgcrypto extension unavailable; relying on built-in gen_random_uuid()")
            await conn.execute(statements)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _SCHEMA_LOCK_KEY)


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
                pool = await asyncpg.create_pool(
                    self.database_url, min_size=1, max_size=4, init=_init_connection
                )
                await _ensure_schema(pool)
                self._pool = pool
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
            SELECT s.id::text AS id, s.canonical_label AS "canonicalLabel", s.status::text AS status,
                   s.risk_score AS "riskScore", s.created_at AS "createdAt", s.updated_at AS "updatedAt",
                   (SELECT i.provider_user_id FROM user_identities i
                    WHERE i.subject_id = s.id AND i.provider = 'discord'
                    ORDER BY i.linked_at LIMIT 1) AS "discordUserId"
            FROM moderated_subjects s
            ORDER BY s.created_at DESC
            """
        )
        return [dict(row) for row in rows]

    async def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        if not _is_uuid(subject_id):
            return None
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
            f"""
            INSERT INTO moderation_cases (
                subject_id, status, priority, title, description, reporter_identity_id, assignee_identity_id,
                opened_by_identity_id, metadata
            )
            VALUES (
                $1::uuid, $2::case_status, $3::case_priority, $4, $5, $6::uuid, $7::uuid, $8::uuid, $9::jsonb
            )
            RETURNING {_CASE_COLUMNS}
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
        rows = await pool.fetch(
            f"""
            SELECT {_CASE_COLUMNS}
            FROM moderation_cases
            WHERE $1::case_status IS NULL OR status = $1::case_status
            ORDER BY opened_at DESC
            """,
            status,
        )
        return [dict(row) for row in rows]

    async def update_case(self, case_id: str, status: str) -> dict[str, Any] | None:
        if not _is_uuid(case_id):
            return None
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            f"""
            UPDATE moderation_cases
            SET status = $2::case_status,
                resolved_at = CASE WHEN $2 IN ('resolved', 'dismissed') THEN NOW() ELSE NULL END
            WHERE id = $1::uuid
            RETURNING {_CASE_COLUMNS}
            """,
            case_id,
            status,
        )
        return dict(row) if row else None

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
                      reason, starts_at AS "startsAt", ends_at AS "endsAt", metadata
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
                metadata = CASE
                    WHEN $3::text IS NULL THEN metadata - 'error'
                    ELSE jsonb_set(metadata, '{error}', to_jsonb($3::text), true)
                END
            WHERE id = $1::uuid
            """,
            sanction_id,
            status,
            error,
        )

    async def list_sanctions(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        rows = await pool.fetch(
            f"""
            SELECT {_SANCTION_COLUMNS}
            FROM sanctions
            WHERE $1::uuid IS NULL OR subject_id = $1::uuid
            ORDER BY starts_at DESC
            """,
            subject_id,
        )
        return [dict(row) for row in rows]

    async def get_sanction(self, sanction_id: str) -> dict[str, Any] | None:
        if not _is_uuid(sanction_id):
            return None
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            f"SELECT {_SANCTION_COLUMNS} FROM sanctions WHERE id = $1::uuid",
            sanction_id,
        )
        return dict(row) if row else None

    async def revoke_sanction(self, sanction_id: str, reason: str, actor: dict[str, Any]) -> dict[str, Any] | None:
        if not _is_uuid(sanction_id):
            return None
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            f"""
            UPDATE sanctions
            SET status = 'revoked', revoked_at = NOW(), revoke_reason = $2,
                metadata = metadata || jsonb_build_object('revokedBy', $3::jsonb)
            WHERE id = $1::uuid
            RETURNING {_SANCTION_COLUMNS}
            """,
            sanction_id,
            reason,
            actor,
        )
        return dict(row) if row else None

    async def active_website_blocks(self) -> list[dict[str, Any]]:
        pool = await self._pool_conn()
        rows = await pool.fetch(
            """
            SELECT DISTINCT ON (i.provider_user_id)
                   i.provider_user_id AS "userId", s.id::text AS "sanctionId",
                   s.sanction::text AS sanction, s.reason, s.ends_at AS "endsAt"
            FROM sanctions s
            JOIN user_identities i ON i.subject_id = s.subject_id
            WHERE s.target = 'website'
              AND s.status = 'active'
              AND s.sanction IN ('timeout', 'suspension', 'ban')
              AND (s.ends_at IS NULL OR s.ends_at > NOW())
            ORDER BY i.provider_user_id, s.ends_at DESC NULLS FIRST
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
        if not _is_uuid(appeal_id):
            return None
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
        rows = await pool.fetch(
            """
            SELECT id::text AS id, sanction_id::text AS "sanctionId", case_id::text AS "caseId",
                   status::text AS status, appeal_reason AS "appealReason", submitted_at AS "submittedAt",
                   decided_at AS "decidedAt", decision_summary AS "decisionSummary"
            FROM appeals
            WHERE $1::appeal_status IS NULL OR status = $1::appeal_status
            ORDER BY submitted_at DESC
            """,
            status,
        )
        return [dict(row) for row in rows]

    async def append_audit_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            f"""
            INSERT INTO audit_events (
                event_type, actor_identity_id, subject_id, case_id, sanction_id, appeal_id, source, request_id,
                ip_address, metadata
            )
            VALUES (
                $1, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6::uuid, $7, $8, $9, $10::jsonb
            )
            RETURNING {_AUDIT_COLUMNS}
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
            f"""
            SELECT {_AUDIT_COLUMNS}
            FROM audit_events
            ORDER BY occurred_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def close(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None


_HOUR = 3600
_DAY = 24 * _HOUR

# What each sanction means on each platform. ``duration`` sets ``ends_at``;
# ``ongoing`` sanctions stay "active" (and can be revoked) instead of "completed".
ACTION_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "discord": {
        "warning": {"label": "Warning (sent by DM)"},
        "note": {"label": "Note (record only)"},
        "read_only": {"label": "Mute for 1 hour", "duration": _HOUR, "ongoing": True},
        "quarantine": {"label": "Mute for 6 hours", "duration": 6 * _HOUR, "ongoing": True},
        "timeout": {"label": "Mute for 24 hours", "duration": _DAY, "ongoing": True},
        "kick": {"label": "Kick from server"},
        "ban": {"label": "Ban from server", "ongoing": True},
    },
    "website": {
        "warning": {"label": "Warning (record only)"},
        "note": {"label": "Note (record only)"},
        "timeout": {"label": "Block website for 24 hours", "duration": _DAY, "ongoing": True},
        "suspension": {"label": "Block website for 7 days", "duration": 7 * _DAY, "ongoing": True},
        "ban": {"label": "Ban from website", "ongoing": True},
    },
}
CASE_STATUSES = ("open", "investigating", "actioned", "resolved", "dismissed")
APPEAL_DECISIONS = ("under_review", "approved", "denied")
_NEEDS_SERVER = {"read_only", "quarantine", "timeout", "kick", "ban"}


def _clean_actor(actor: dict[str, Any] | None) -> dict[str, Any]:
    actor = actor or {}
    return {"id": str(actor.get("id") or "").strip() or None, "name": str(actor.get("name") or "").strip() or None}


def _target_user_id(identities: list[dict[str, Any]], target: str) -> str | None:
    """Pick the account a sanction applies to. Website logins use Discord accounts,
    so a website sanction falls back to the linked Discord identity."""

    by_provider: dict[str, str] = {}
    for identity in identities:
        by_provider.setdefault(str(identity.get("provider")), str(identity.get("providerUserId") or ""))
    if target == "discord":
        return by_provider.get("discord") or None
    return by_provider.get("website") or by_provider.get("discord") or None


class ModerationService:
    def __init__(self, repository: ModerationRepository, bridge: DiscordModerationBridge | None = None) -> None:
        self.repository = repository
        self.identity_links = IdentityLinkService()
        self.audit = AuditService()
        self.discord_bridge = bridge or DiscordModerationBridge()
        # Bumped whenever a website sanction starts or ends so request
        # middleware can refresh its cached block list straight away.
        self.website_blocks_changed_at = time.monotonic()

    async def create_subject(
        self,
        canonical_label: str,
        actor: dict[str, Any] | None = None,
        *,
        discord_user_id: str | None = None,
    ) -> dict[str, Any]:
        label = str(canonical_label or "").strip()
        if not label:
            raise ValueError("A name is required.")
        discord_user_id = str(discord_user_id or "").strip() or None
        if discord_user_id and not discord_user_id.isdigit():
            raise ValueError("Discord user IDs are numbers only.")
        subject = await self.repository.create_subject(label)
        await self.record_audit(
            event_type="subject.created",
            actor=actor,
            subject_id=subject["id"],
            metadata={"canonicalLabel": label},
        )
        if discord_user_id:
            await self.link_identity(
                subject["id"],
                IdentityLinkInput(provider="discord", provider_user_id=discord_user_id, display_name=label),
                actor=actor,
            )
        return subject

    async def link_identity(
        self, subject_id: str, payload: IdentityLinkInput, actor: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        subject = await self.repository.get_subject(subject_id)
        if subject is None:
            raise ValueError("Person not found.")
        if not payload.linked_by:
            payload.linked_by = _clean_actor(actor)["id"]
        data = self.identity_links.build_identity_record(subject_id, payload)
        if data["provider"] == "discord" and not data["providerUserId"].isdigit():
            raise ValueError("Discord user IDs are numbers only.")
        identity = await self.repository.add_identity(subject_id, data)
        await self.record_audit(
            event_type="identity.linked",
            actor=actor,
            subject_id=subject_id,
            metadata={"provider": data["provider"], "providerUserId": data["providerUserId"]},
        )
        return identity

    async def get_subject_profile(self, subject_id: str) -> dict[str, Any]:
        subject = await self.repository.get_subject(subject_id)
        if subject is None:
            raise ValueError("Person not found.")
        identities = await self.repository.list_identities(subject_id)
        sanctions = await self.repository.list_sanctions(subject_id)
        return {"subject": subject, "identities": identities, "sanctions": sanctions}

    async def list_subjects(self) -> list[dict[str, Any]]:
        return await self.repository.list_subjects()

    async def create_case(self, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        if await self.repository.get_subject(payload["subjectId"]) is None:
            raise ValueError("Person not found.")
        priority = payload.get("priority", "normal")
        if priority not in {"low", "normal", "high", "critical"}:
            raise ValueError("Unknown priority.")
        case_payload = {
            "subjectId": payload["subjectId"],
            "status": "open",
            "priority": priority,
            "title": payload["title"].strip(),
            "description": payload["description"].strip(),
            "metadata": {"actor": _clean_actor(actor)},
            "openedAt": _utc_now().isoformat(),
        }
        case_record = await self.repository.create_case(case_payload)
        await self.repository.add_case_event(
            {
                "caseId": case_record["id"],
                "eventType": "case.created",
                "eventSummary": "Case created",
                "eventPayload": {"title": case_record["title"], "priority": case_record["priority"]},
            }
        )
        await self.record_audit(
            event_type="case.created",
            actor=actor,
            subject_id=case_payload["subjectId"],
            case_id=case_record["id"],
            metadata={"title": case_record["title"], "priority": case_record["priority"]},
        )
        return case_record

    async def update_case_status(
        self, case_id: str, status: str, actor: dict[str, Any] | None = None, note: str | None = None
    ) -> dict[str, Any]:
        if status not in CASE_STATUSES:
            raise ValueError("Unknown case status.")
        updated = await self.repository.update_case(case_id, status)
        if updated is None:
            raise LookupError("Case not found.")
        await self.repository.add_case_event(
            {
                "caseId": case_id,
                "eventType": "case.status_changed",
                "eventSummary": f"Status set to {status}",
                "eventPayload": {"status": status, "note": note or ""},
            }
        )
        await self.record_audit(
            event_type="case.status_changed",
            actor=actor,
            subject_id=updated.get("subjectId"),
            case_id=case_id,
            metadata={"status": status, "note": note or ""},
        )
        return updated

    async def list_cases(self, status: str | None = None) -> list[dict[str, Any]]:
        return await self.repository.list_cases(status=status)

    async def create_sanction(self, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        target = str(payload.get("target") or "").strip().lower()
        action = str(payload.get("sanction") or "").strip().lower()
        rule = ACTION_RULES.get(target, {}).get(action)
        if rule is None:
            raise ValueError(f"'{action}' is not available for {target or 'this'} sanctions.")
        subject_id = payload["subjectId"]
        if await self.repository.get_subject(subject_id) is None:
            raise ValueError("Person not found.")
        target_user_id = _target_user_id(await self.repository.list_identities(subject_id), target)
        if not target_user_id and action != "note":
            raise ValueError(
                "Link this person's Discord account first, so the sanction has someone to apply to."
            )
        if payload.get("caseId") and not _is_uuid(payload["caseId"]):
            raise ValueError("Unknown case.")
        guild_id = str(payload.get("guildId") or "").strip() or None
        if target == "discord" and action in _NEEDS_SERVER and not guild_id:
            raise ValueError("Choose the Discord server to apply this in.")

        duration = rule.get("duration")
        ends_at = _utc_now() + timedelta(seconds=duration) if duration else None
        sanction = await self.repository.create_sanction(
            {
                "caseId": payload.get("caseId") or None,
                "subjectId": subject_id,
                "target": target,
                "sanction": action,
                "status": "pending",
                "reason": payload["reason"].strip(),
                "evidence": payload.get("evidence", []),
                "endsAt": ends_at,
                "metadata": {
                    "actor": _clean_actor(actor),
                    "guildId": guild_id,
                    "guildName": payload.get("guildName"),
                    "targetUserId": target_user_id,
                    "durationSeconds": duration,
                },
            }
        )
        result = await self._execute_enforcement(sanction, rule)
        await self.repository.update_sanction_status(sanction["id"], result["status"], result.get("error"))
        sanction["status"] = result["status"]
        sanction["error"] = result.get("error")
        if target == "website":
            self.website_blocks_changed_at = time.monotonic()
        await self.record_audit(
            event_type="sanction.imposed",
            actor=actor,
            subject_id=subject_id,
            case_id=sanction.get("caseId"),
            sanction_id=sanction["id"],
            metadata={"target": target, "sanction": action, "status": sanction["status"], "error": sanction["error"]},
        )
        return sanction

    async def revoke_sanction(
        self, sanction_id: str, reason: str, actor: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        sanction = await self.repository.get_sanction(sanction_id)
        if sanction is None:
            raise LookupError("Sanction not found.")
        if sanction.get("status") == "revoked":
            raise ValueError("This sanction was already revoked.")
        metadata = sanction.get("metadata") or {}
        if sanction.get("target") == "discord" and sanction.get("status") == "active":
            receipt = await self.discord_bridge.revoke(
                DiscordModerationRequest(
                    operation_key=f"{sanction_id}:discord:revoke",
                    subject_id=str(sanction.get("subjectId")),
                    action=str(sanction.get("sanction")),
                    guild_id=str(metadata.get("guildId") or ""),
                    reason=reason,
                    target_user_id=str(metadata.get("targetUserId") or ""),
                )
            )
            not_applied = receipt.response_payload.get("status") == 404
            if not receipt.success and not not_applied:
                raise ValueError(f"Discord did not lift the sanction: {receipt.error}")
        revoked = await self.repository.revoke_sanction(sanction_id, reason, _clean_actor(actor))
        if sanction.get("target") == "website":
            self.website_blocks_changed_at = time.monotonic()
        await self.record_audit(
            event_type="sanction.revoked",
            actor=actor,
            subject_id=sanction.get("subjectId"),
            sanction_id=sanction_id,
            metadata={"reason": reason, "sanction": sanction.get("sanction"), "target": sanction.get("target")},
        )
        return revoked or sanction

    async def list_sanctions(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        return await self.repository.list_sanctions(subject_id=subject_id)

    async def website_blocks(self) -> list[dict[str, Any]]:
        return await self.repository.active_website_blocks()

    async def create_appeal(self, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        sanction = await self.repository.get_sanction(payload["sanctionId"])
        if sanction is None:
            raise ValueError("Sanction not found.")
        appeal = await self.repository.create_appeal(
            {
                "sanctionId": payload["sanctionId"],
                "caseId": payload.get("caseId") or sanction.get("caseId"),
                "status": "submitted",
                "appealReason": payload["appealReason"].strip(),
            }
        )
        await self.record_audit(
            event_type="appeal.submitted",
            actor=actor,
            subject_id=sanction.get("subjectId"),
            appeal_id=appeal["id"],
            sanction_id=payload["sanctionId"],
            case_id=appeal.get("caseId"),
        )
        return appeal

    async def update_appeal(
        self, appeal_id: str, payload: dict[str, Any], actor: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        status = payload.get("status")
        if status not in APPEAL_DECISIONS:
            raise ValueError("Appeals can be set to under review, approved or denied.")
        updated = await self.repository.update_appeal(
            appeal_id,
            {
                "status": status,
                "decisionSummary": payload.get("decisionSummary"),
                "moderatorNotes": payload.get("moderatorNotes"),
            },
        )
        if updated is None:
            raise LookupError("Appeal not found.")
        lifted = False
        if status == "approved":
            sanction = await self.repository.get_sanction(updated["sanctionId"])
            if sanction and sanction.get("status") in {"active", "pending"}:
                await self.revoke_sanction(sanction["id"], "Appeal approved", actor)
                lifted = True
        await self.record_audit(
            event_type="appeal.decided",
            actor=actor,
            appeal_id=appeal_id,
            sanction_id=updated.get("sanctionId"),
            metadata={"status": status, "decision": payload.get("decisionSummary"), "sanctionLifted": lifted},
        )
        updated["sanctionLifted"] = lifted
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
        source: str = "admin-console",
        actor: dict[str, Any] | None = None,
        subject_id: str | None = None,
        case_id: str | None = None,
        sanction_id: str | None = None,
        appeal_id: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Admins are Discord accounts, not moderated identities, so they go in
        # metadata rather than the identity foreign-key columns.
        event = self.audit.normalise(
            AuditEventInput(
                event_type=event_type,
                source=source,
                subject_id=subject_id,
                case_id=case_id,
                sanction_id=sanction_id,
                appeal_id=appeal_id,
                request_id=request_id,
                ip_address=ip_address,
                metadata={**(metadata or {}), "actor": _clean_actor(actor)},
            )
        )
        return await self.repository.append_audit_event(event)

    async def _execute_enforcement(self, sanction: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
        target = sanction.get("target")
        action_type = str(sanction.get("sanction"))
        metadata = sanction.get("metadata") or {}
        provider = "website" if target == "website" else "discord"
        op_key = f"{sanction['id']}:{provider}:{action_type}"
        success_status = "active" if rule.get("ongoing") else "completed"

        status_value = success_status
        response_payload: dict[str, Any] = {"ok": True}
        error_message: str | None = None
        attempted_at = _utc_now()

        if target == "discord":
            receipt = await self.discord_bridge.execute(
                DiscordModerationRequest(
                    operation_key=op_key,
                    subject_id=str(sanction.get("subjectId")),
                    action=action_type,
                    guild_id=str(metadata.get("guildId") or ""),
                    reason=str(sanction.get("reason") or ""),
                    metadata={
                        "durationSeconds": metadata.get("durationSeconds"),
                        "guildName": metadata.get("guildName"),
                    },
                    target_user_id=str(metadata.get("targetUserId") or ""),
                )
            )
            status_value = success_status if receipt.success else "failed"
            response_payload = receipt.response_payload
            error_message = receipt.error

        action_receipt = await self.repository.record_enforcement_action(
            {
                "sanctionId": sanction["id"],
                "operationKey": op_key,
                "provider": provider,
                "providerScopeId": metadata.get("guildId"),
                "providerAction": action_type,
                "requestPayload": {"guildId": metadata.get("guildId"), "action": action_type},
                "responsePayload": response_payload,
                "status": status_value,
                "errorMessage": error_message,
                "attemptedAt": attempted_at,
                "completedAt": _utc_now(),
            }
        )
        return {"status": status_value, "error": error_message, "action": action_receipt}

    async def close(self) -> None:
        close = getattr(self.repository, "close", None)
        if callable(close):
            await close()


_shared_service: ModerationService | None = None


def get_moderation_service() -> ModerationService:
    global _shared_service
    if _shared_service is not None:
        return _shared_service
    db_url = (os.getenv("MODERATION_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith(("postgres://", "postgresql://")) and asyncpg is not None:
        repository: ModerationRepository = PostgresModerationRepository(db_url)
    else:
        repository = InMemoryModerationRepository()
    _shared_service = ModerationService(repository=repository)
    token = (os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if token:
        from spectre.moderation.discord_rest import DiscordRestModerator

        moderator = DiscordRestModerator(token)
        _shared_service.discord_bridge.bind_executor(moderator.execute)
        _shared_service.discord_bridge.bind_revoker(moderator.revoke)
    return _shared_service


async def reset_moderation_service() -> None:
    global _shared_service
    if _shared_service is None:
        return
    try:
        await _shared_service.close()
    finally:
        _shared_service = None
