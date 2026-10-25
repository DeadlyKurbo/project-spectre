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

import guild_blacklist
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
    async def find_subject_by_identity(self, provider: str, provider_user_id: str) -> dict[str, Any] | None: ...
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

    async def find_subject_by_identity(self, provider: str, provider_user_id: str) -> dict[str, Any] | None:
        for identity in self.identities.values():
            if identity.get("provider") == provider and identity.get("providerUserId") == provider_user_id:
                return self.subjects.get(identity.get("subjectId"))
        return None

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
        values.sort(key=lambda item: str(item.get("openedAt") or ""), reverse=True)
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
        starts_at = payload.get("startsAt") or _utc_now()
        record = {"id": sanction_id, **payload, "startsAt": starts_at.isoformat()}
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
        values.sort(key=lambda item: str(item.get("startsAt") or ""), reverse=True)
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
            if sanction.get("target") != "website" or sanction.get("status") != "active" or not sanction.get("subjectId"):
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


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _reading(method):
    async def wrapper(self: "StoredModerationRepository", *args: Any, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        return await method(self, *args, **kwargs)

    wrapper.__name__ = method.__name__
    return wrapper


def _saving(method):
    async def wrapper(self: "StoredModerationRepository", *args: Any, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        result = await method(self, *args, **kwargs)
        await self._save()
        return result

    wrapper.__name__ = method.__name__
    return wrapper


class StoredModerationRepository(InMemoryModerationRepository):
    """In-memory repository saved as one JSON document after every change.

    Used when no PostgreSQL database is configured, so moderation records and
    the audit log survive restarts and redeploys. The document goes through
    ``persistent_store``, i.e. the same storage as the rest of the site.
    """

    STORAGE_KEY = "moderation/state.json"
    # Oldest audit events are dropped past this, to keep each save small.
    AUDIT_EVENT_LIMIT = 5000
    _TABLES = (
        "subjects",
        "identities",
        "cases",
        "case_events",
        "sanctions",
        "enforcement_actions",
        "appeals",
        "audit_events",
    )

    def __init__(self, storage_key: str = STORAGE_KEY) -> None:
        super().__init__()
        self.storage_key = storage_key
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            from persistent_store import read_json

            try:
                snapshot = await asyncio.to_thread(read_json, self.storage_key)
            except FileNotFoundError:
                snapshot = {}
            except Exception:
                # Starting empty would overwrite the saved records on the next change.
                logger.exception("Failed to load moderation records from %s", self.storage_key)
                raise
            for table in self._TABLES:
                rows = snapshot.get(table) if isinstance(snapshot, dict) else None
                if isinstance(rows, dict):
                    getattr(self, table).update(rows)
            self._loaded = True

    async def _save(self) -> None:
        from persistent_store import save_json

        async with self._save_lock:
            if len(self.audit_events) > self.AUDIT_EVENT_LIMIT:
                oldest_first = sorted(self.audit_events.values(), key=lambda item: item.get("occurredAt", ""))
                self.audit_events = {row["id"]: row for row in oldest_first[-self.AUDIT_EVENT_LIMIT :]}
            # Round-trip through JSON so datetimes are stored as ISO strings.
            snapshot = json.loads(
                json.dumps({table: getattr(self, table) for table in self._TABLES}, default=_json_default)
            )
            await asyncio.to_thread(save_json, self.storage_key, snapshot)

    create_subject = _saving(InMemoryModerationRepository.create_subject)
    list_subjects = _reading(InMemoryModerationRepository.list_subjects)
    get_subject = _reading(InMemoryModerationRepository.get_subject)
    find_subject_by_identity = _reading(InMemoryModerationRepository.find_subject_by_identity)
    add_identity = _saving(InMemoryModerationRepository.add_identity)
    list_identities = _reading(InMemoryModerationRepository.list_identities)
    create_case = _saving(InMemoryModerationRepository.create_case)
    list_cases = _reading(InMemoryModerationRepository.list_cases)
    update_case = _saving(InMemoryModerationRepository.update_case)
    add_case_event = _saving(InMemoryModerationRepository.add_case_event)
    create_sanction = _saving(InMemoryModerationRepository.create_sanction)
    update_sanction_status = _saving(InMemoryModerationRepository.update_sanction_status)
    list_sanctions = _reading(InMemoryModerationRepository.list_sanctions)
    get_sanction = _reading(InMemoryModerationRepository.get_sanction)
    revoke_sanction = _saving(InMemoryModerationRepository.revoke_sanction)
    active_website_blocks = _reading(InMemoryModerationRepository.active_website_blocks)
    record_enforcement_action = _saving(InMemoryModerationRepository.record_enforcement_action)
    create_appeal = _saving(InMemoryModerationRepository.create_appeal)
    update_appeal = _saving(InMemoryModerationRepository.update_appeal)
    list_appeals = _reading(InMemoryModerationRepository.list_appeals)
    append_audit_event = _saving(InMemoryModerationRepository.append_audit_event)
    list_audit_events = _reading(InMemoryModerationRepository.list_audit_events)


_SANCTION_COLUMNS = """
    id::text AS id, case_id::text AS "caseId", subject_type AS "subjectType", subject_id::text AS "subjectId",
    server_id AS "serverId", server_name AS "serverName", target::text AS target, sanction::text AS sanction, status::text AS status,
    reason, starts_at AS "startsAt", ends_at AS "endsAt", revoked_at AS "revokedAt",
    revoke_reason AS "revokeReason", metadata
"""
_CASE_COLUMNS = """
    id::text AS id, subject_type AS "subjectType", subject_id::text AS "subjectId",
    server_id AS "serverId", server_name AS "serverName", status::text AS status,
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

    async def find_subject_by_identity(self, provider: str, provider_user_id: str) -> dict[str, Any] | None:
        pool = await self._pool_conn()
        row = await pool.fetchrow(
            """
            SELECT s.id::text AS id, s.canonical_label AS "canonicalLabel", s.status::text AS status,
                   s.risk_score AS "riskScore", s.created_at AS "createdAt", s.updated_at AS "updatedAt"
            FROM user_identities i
            JOIN moderated_subjects s ON s.id = i.subject_id
            WHERE i.provider = $1::identity_provider AND i.provider_user_id = $2
            """,
            provider,
            provider_user_id,
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
                opened_by_identity_id, metadata, subject_type, server_id, server_name
            )
            VALUES (
                $1::uuid, $2::case_status, $3::case_priority, $4, $5, $6::uuid, $7::uuid, $8::uuid, $9::jsonb,
                $10, $11, $12
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
            payload["subjectType"],
            payload.get("serverId"),
            payload.get("serverName"),
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
            f"""
            INSERT INTO sanctions (
                case_id, subject_id, target, sanction, status, reason, evidence, imposed_by_identity_id,
                starts_at, ends_at, metadata, subject_type, server_id, server_name
            )
            VALUES (
                $1::uuid, $2::uuid, $3::sanction_target, $4::sanction_type, $5::sanction_status, $6, $7::jsonb,
                $8::uuid, COALESCE($14::timestamptz, NOW()), $9::timestamptz, $10::jsonb, $11, $12, $13
            )
            RETURNING {_SANCTION_COLUMNS}
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
            payload["subjectType"],
            payload.get("serverId"),
            payload.get("serverName"),
            payload.get("startsAt"),
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
CASE_PRIORITIES = ("low", "normal", "high", "critical")
APPEAL_DECISIONS = ("under_review", "approved", "denied")
# What a case or sanction is about. Server sanctions are server blacklists.
SUBJECT_TYPES = ("person", "server")
_NEEDS_SERVER = {"read_only", "quarantine", "timeout", "kick", "ban"}
_SERVER_NAME_MAX_LENGTH = 100


def _clean_actor(actor: dict[str, Any] | None) -> dict[str, Any]:
    actor = actor or {}
    return {"id": str(actor.get("id") or "").strip() or None, "name": str(actor.get("name") or "").strip() or None}


def _actor_label(actor: dict[str, Any] | None) -> str | None:
    cleaned = _clean_actor(actor)
    if cleaned["name"] and cleaned["id"]:
        return f"{cleaned['name']} ({cleaned['id']})"
    return cleaned["name"] or cleaned["id"]


def _clean_server_name(value: Any) -> str | None:
    cleaned = " ".join(str(value or "").split())[:_SERVER_NAME_MAX_LENGTH].rstrip()
    return cleaned or None


def _server_details(record: dict[str, Any] | None) -> dict[str, Any]:
    """Audit metadata naming the server a case or sanction is about, if it is about one."""

    if not record or record.get("subjectType") != "server":
        return {}
    return {"serverId": record.get("serverId"), "serverName": record.get("serverName")}


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
    def __init__(
        self,
        repository: ModerationRepository,
        bridge: DiscordModerationBridge | None = None,
        server_blacklist: Any = None,
    ) -> None:
        self.repository = repository
        self.identity_links = IdentityLinkService()
        self.audit = AuditService()
        self.discord_bridge = bridge or DiscordModerationBridge()
        # The list the bot enforces: anything with ``blacklist_guild`` and
        # ``unblacklist_guild`` like the ``guild_blacklist`` module.
        self.server_blacklist = server_blacklist or guild_blacklist
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

    async def _case_person(self, payload: dict[str, Any], actor: dict[str, Any] | None) -> str:
        """The tracked person a case is about, starting a record for a website user if needed."""

        subject_id = str(payload.get("subjectId") or "").strip()
        if subject_id:
            if await self.repository.get_subject(subject_id) is None:
                raise ValueError("Person not found.")
            return subject_id
        discord_user_id = str(payload.get("discordUserId") or "").strip()
        if not discord_user_id:
            raise ValueError("Choose the person this case is about.")
        if not discord_user_id.isdigit():
            raise ValueError("Discord user IDs are numbers only.")
        existing = await self.repository.find_subject_by_identity("discord", discord_user_id)
        if existing is not None:
            return existing["id"]
        label = str(payload.get("displayName") or "").strip() or f"Discord user {discord_user_id}"
        subject = await self.create_subject(label, actor, discord_user_id=discord_user_id)
        return subject["id"]

    async def create_case(self, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open a case about a person (``subjectId``, or a website user's ``discordUserId``)
        or about a Discord server (``subjectType`` "server" with ``serverId``)."""

        subject_type = str(payload.get("subjectType") or "person").strip().lower()
        if subject_type not in SUBJECT_TYPES:
            raise ValueError("A case is about a person or a server.")
        priority = payload.get("priority", "normal")
        if priority not in CASE_PRIORITIES:
            raise ValueError("Unknown priority.")
        subject_id = server_id = server_name = None
        if subject_type == "server":
            server_id = guild_blacklist.normalise_guild_id(payload.get("serverId"))
            if server_id is None:
                raise ValueError("Choose the server this case is about.")
            server_name = _clean_server_name(payload.get("serverName"))
        else:
            subject_id = await self._case_person(payload, actor)
        case_payload = {
            "subjectType": subject_type,
            "subjectId": subject_id,
            "serverId": server_id,
            "serverName": server_name,
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
            subject_id=subject_id,
            case_id=case_record["id"],
            metadata={"title": case_record["title"], "priority": case_record["priority"], **_server_details(case_record)},
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
            metadata={"status": status, "note": note or "", **_server_details(updated)},
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
                "subjectType": "person",
                "subjectId": subject_id,
                "serverId": None,
                "serverName": None,
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
        if sanction.get("subjectType") == "server":
            await self.lift_server_blacklist(sanction.get("serverId"), reason=reason, actor=actor)
            return await self.repository.get_sanction(sanction_id) or sanction
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

    async def _active_server_sanctions(self, server_id: str | None = None) -> list[dict[str, Any]]:
        return [
            sanction
            for sanction in await self.repository.list_sanctions()
            if sanction.get("subjectType") == "server"
            and sanction.get("status") == "active"
            and (server_id is None or sanction.get("serverId") == server_id)
        ]

    async def _record_server_sanction(
        self, entry: dict[str, Any], actor: dict[str, Any] | None, *, starts_at: datetime | None = None
    ) -> dict[str, Any]:
        return await self.repository.create_sanction(
            {
                "caseId": None,
                "subjectType": "server",
                "subjectId": None,
                "serverId": entry["guild_id"],
                "serverName": entry.get("name"),
                "target": "discord",
                "sanction": "ban",
                "status": "active",
                "reason": entry.get("reason") or "",
                "evidence": [],
                "startsAt": starts_at,
                "endsAt": None,
                "metadata": {"actor": _clean_actor(actor)},
            }
        )

    async def blacklist_server(
        self,
        server_id: Any,
        *,
        reason: str | None,
        name: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Blacklist a Discord server, and record it as a sanction and in the audit log.

        Returns the blacklist entry. Invalid input raises ``ValueError`` and a
        failed save of the blacklist propagates. Once the blacklist is saved
        the ban is in effect, so a failure to record it is only logged:
        ``sync_server_blacklist`` adds the missing sanction later.
        """

        entry = await asyncio.to_thread(
            self.server_blacklist.blacklist_guild, server_id, reason=reason, actor=_actor_label(actor), name=name
        )
        try:
            # Blacklisting a server again replaces its entry, so it replaces the sanction too.
            for previous in await self._active_server_sanctions(entry["guild_id"]):
                await self.repository.revoke_sanction(previous["id"], "Replaced by a new blacklist", _clean_actor(actor))
            sanction = await self._record_server_sanction(entry, actor)
            await self.record_audit(
                event_type="server.blacklisted",
                actor=actor,
                sanction_id=sanction["id"],
                metadata={"serverId": entry["guild_id"], "serverName": entry.get("name"), "reason": entry.get("reason")},
            )
        except Exception:
            logger.exception("Server %s is blacklisted, but recording the sanction failed", entry["guild_id"])
        return entry

    async def lift_server_blacklist(
        self, server_id: Any, *, reason: str | None = None, actor: dict[str, Any] | None = None
    ) -> bool:
        """Lift a server's blacklist and end its sanction.

        Returns ``False`` if the server was not blacklisted. As with
        ``blacklist_server``, only a failure to save the blacklist propagates.
        """

        lifted = await asyncio.to_thread(self.server_blacklist.unblacklist_guild, server_id)
        cleaned_id = guild_blacklist.normalise_guild_id(server_id)
        try:
            sanctions = await self._active_server_sanctions(cleaned_id) if cleaned_id else []
            if not lifted and not sanctions:
                return False
            reason = (reason or "").strip() or "Blacklist lifted"
            for sanction in sanctions:
                await self.repository.revoke_sanction(sanction["id"], reason, _clean_actor(actor))
            await self.record_audit(
                event_type="server.unblacklisted",
                actor=actor,
                sanction_id=sanctions[0]["id"] if sanctions else None,
                metadata={
                    "serverId": cleaned_id,
                    "serverName": next((item.get("serverName") for item in sanctions if item.get("serverName")), None),
                    "reason": reason,
                },
            )
        except Exception:
            logger.exception("Server %s is off the blacklist, but recording it failed", cleaned_id)
        return lifted

    async def sync_server_blacklist(self, entries: list[dict[str, Any]]) -> None:
        """Match the server sanctions to the blacklist the bot enforces.

        Adds sanctions for servers blacklisted before blacklists were recorded
        (or whose sanction failed to save), and ends sanctions for servers that
        are no longer on the list.
        """

        listed = {entry["guild_id"]: entry for entry in entries if entry.get("guild_id")}
        active = {sanction.get("serverId"): sanction for sanction in await self._active_server_sanctions()}
        for server_id, entry in listed.items():
            if server_id not in active:
                await self._record_server_sanction(
                    entry, {"name": entry.get("actor")}, starts_at=_parse_time(entry.get("banned_at"))
                )
        for server_id, sanction in active.items():
            if server_id not in listed:
                await self.repository.revoke_sanction(sanction["id"], "No longer on the server blacklist", _clean_actor(None))

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
            metadata=_server_details(sanction),
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
        sanction = await self.repository.get_sanction(updated["sanctionId"])
        if status == "approved" and sanction and sanction.get("status") in {"active", "pending"}:
            await self.revoke_sanction(sanction["id"], "Appeal approved", actor)
            lifted = True
        await self.record_audit(
            event_type="appeal.decided",
            actor=actor,
            subject_id=(sanction or {}).get("subjectId"),
            appeal_id=appeal_id,
            sanction_id=updated.get("sanctionId"),
            metadata={
                "status": status,
                "decision": payload.get("decisionSummary"),
                "sanctionLifted": lifted,
                **_server_details(sanction),
            },
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
        repository = StoredModerationRepository()
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
