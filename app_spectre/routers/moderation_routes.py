from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app_spectre.services.identity_link_service import IdentityLinkInput
from app_spectre.services.moderation_service import (
    ACTION_RULES,
    APPEAL_DECISIONS,
    CASE_STATUSES,
    ModerationService,
    get_moderation_service,
)

router = APIRouter(prefix="/api/moderation", tags=["moderation"])


class SubjectCreateBody(BaseModel):
    canonicalLabel: str = Field(min_length=2, max_length=200)
    discordUserId: str | None = Field(default=None, max_length=32)


class IdentityLinkBody(BaseModel):
    provider: str
    providerUserId: str
    displayName: str | None = None
    providerUsername: str | None = None


class CaseCreateBody(BaseModel):
    # "person": a tracked person (subjectId) or a website user (discordUserId).
    # "server": a Discord server (serverId).
    subjectType: str = Field(default="person")
    subjectId: str | None = None
    discordUserId: str | None = Field(default=None, max_length=32)
    displayName: str | None = Field(default=None, max_length=200)
    serverId: str | None = Field(default=None, max_length=32)
    serverName: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    priority: str = Field(default="normal")
    reporterIdentityId: str | None = None
    assigneeIdentityId: str | None = None


class SanctionCreateBody(BaseModel):
    subjectId: str
    caseId: str | None = None
    target: str
    sanction: str
    reason: str = Field(min_length=3, max_length=2000)
    guildId: str | None = None
    guildName: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class SanctionRevokeBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CaseUpdateBody(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2000)


class AppealCreateBody(BaseModel):
    sanctionId: str
    caseId: str | None = None
    appealReason: str = Field(min_length=5, max_length=3000)
    appellantIdentityId: str | None = None


class AppealDecisionBody(BaseModel):
    status: str
    decisionSummary: str | None = None
    moderatorNotes: str | None = None


async def _require_moderator(request: Request) -> dict[str, Any]:
    auth_header = str(request.headers.get("authorization") or "").strip()
    if not auth_header:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No token")
    prefix, _, token = auth_header.partition(" ")
    if prefix.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No token")

    # Reuse config_app token decoder when available, fallback to local decode.
    try:
        from config_app import _decode_jwt_token as decode_token  # type: ignore
        from config_app import _require_staff_claims as require_staff  # type: ignore
    except ImportError as exc:  # pragma: no cover - import safety
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Token decoder unavailable") from exc
    payload = decode_token(token.strip())
    # Also re-checks that the holder is still an admin, so removing someone
    # from the team cuts off their moderation access straight away.
    return require_staff(payload)


def _actor(claims: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(claims.get("sub") or "").strip() or None, "name": str(claims.get("name") or "").strip() or None}


@router.get("/actions")
async def list_actions(_claims: dict[str, Any] = Depends(_require_moderator)):
    """What each sanction does per platform, so the console's choices match the server."""

    return {
        "actions": {
            target: [{"value": key, **rule} for key, rule in rules.items()]
            for target, rules in ACTION_RULES.items()
        },
        "caseStatuses": list(CASE_STATUSES),
        "appealDecisions": list(APPEAL_DECISIONS),
    }


@router.get("/subjects")
async def list_subjects(
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    return {"subjects": await service.list_subjects()}


@router.get("/website-users")
async def list_website_users(
    limit: int = 100,
    _claims: dict[str, Any] = Depends(_require_moderator),
):
    try:
        from config_app import _recent_site_visitors_snapshot  # type: ignore
    except ImportError as exc:  # pragma: no cover - import safety
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Website user tracker unavailable") from exc
    return {"users": _recent_site_visitors_snapshot(limit=limit)}


@router.get("/registered-users")
async def list_registered_users(_claims: dict[str, Any] = Depends(_require_moderator)):
    """Everyone who has signed in to the website with Discord, to open cases against."""

    try:
        from config_app import _registered_users_snapshot  # type: ignore
    except ImportError as exc:  # pragma: no cover - import safety
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Website user registry unavailable") from exc
    try:
        users = await asyncio.to_thread(_registered_users_snapshot)
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not load the website's users.") from exc
    return {"users": users}


@router.get("/registered-servers")
async def list_registered_servers(_claims: dict[str, Any] = Depends(_require_moderator)):
    """Discord servers the bot is in, plus blacklisted ones, to open cases against."""

    try:
        from config_app import _registered_servers_snapshot  # type: ignore
    except ImportError as exc:  # pragma: no cover - import safety
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Server list unavailable") from exc
    return await _registered_servers_snapshot()


@router.get("/monitored-guild-owners")
async def list_monitored_guild_owners(
    limit: int = 100,
    _claims: dict[str, Any] = Depends(_require_moderator),
):
    try:
        from config_app import _monitored_guild_owners_snapshot  # type: ignore
    except ImportError as exc:  # pragma: no cover - import safety
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Guild owner tracker unavailable") from exc
    return {"owners": await _monitored_guild_owners_snapshot(limit=limit)}


@router.post("/subjects")
async def create_subject(
    body: SubjectCreateBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        subject = await service.create_subject(
            body.canonicalLabel, _actor(claims), discord_user_id=body.discordUserId
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"subject": subject}


@router.get("/subjects/{subject_id}")
async def get_subject_profile(
    subject_id: str,
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        profile = await service.get_subject_profile(subject_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return profile


@router.post("/subjects/{subject_id}/identities")
async def link_identity(
    subject_id: str,
    body: IdentityLinkBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        linked = await service.link_identity(
            subject_id,
            IdentityLinkInput(
                provider=body.provider,
                provider_user_id=body.providerUserId,
                display_name=body.displayName,
                provider_username=body.providerUsername,
            ),
            actor=_actor(claims),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"identity": linked}


@router.get("/cases")
async def list_cases(
    status_value: str | None = None,
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    return {"cases": await service.list_cases(status=status_value)}


@router.post("/cases")
async def create_case(
    body: CaseCreateBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        case_record = await service.create_case(
            {
                "subjectType": body.subjectType,
                "subjectId": body.subjectId,
                "discordUserId": body.discordUserId,
                "displayName": body.displayName,
                "serverId": body.serverId,
                "serverName": body.serverName,
                "title": body.title,
                "description": body.description,
                "priority": body.priority,
            },
            actor=_actor(claims),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"case": case_record}


@router.patch("/cases/{case_id}")
async def update_case(
    case_id: str,
    body: CaseUpdateBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        case_record = await service.update_case_status(case_id, body.status, _actor(claims), note=body.note)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"case": case_record}


@router.get("/sanctions")
async def list_sanctions(
    subject_id: str | None = None,
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    return {"sanctions": await service.list_sanctions(subject_id=subject_id)}


@router.post("/sanctions")
async def create_sanction(
    body: SanctionCreateBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        sanction = await service.create_sanction(
            {
                "subjectId": body.subjectId,
                "caseId": body.caseId,
                "target": body.target,
                "sanction": body.sanction,
                "reason": body.reason,
                "guildId": body.guildId,
                "guildName": body.guildName,
                "evidence": body.evidence,
            },
            actor=_actor(claims),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"sanction": sanction}


@router.post("/sanctions/{sanction_id}/revoke")
async def revoke_sanction(
    sanction_id: str,
    body: SanctionRevokeBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        sanction = await service.revoke_sanction(sanction_id, body.reason.strip(), _actor(claims))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"sanction": sanction}


@router.get("/appeals")
async def list_appeals(
    status_value: str | None = None,
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    return {"appeals": await service.list_appeals(status=status_value)}


@router.post("/appeals")
async def create_appeal(
    body: AppealCreateBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        appeal = await service.create_appeal(
            {
                "sanctionId": body.sanctionId,
                "caseId": body.caseId,
                "appealReason": body.appealReason,
            },
            actor=_actor(claims),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"appeal": appeal}


@router.patch("/appeals/{appeal_id}")
async def decide_appeal(
    appeal_id: str,
    body: AppealDecisionBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    try:
        updated = await service.update_appeal(
            appeal_id,
            {
                "status": body.status,
                "decisionSummary": body.decisionSummary,
                "moderatorNotes": body.moderatorNotes,
            },
            actor=_actor(claims),
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"appeal": updated}


@router.get("/audit-events")
async def list_audit_events(
    limit: int = 100,
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    return {"events": await service.list_audit_events(limit=limit)}
