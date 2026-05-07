from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app_spectre.services.identity_link_service import IdentityLinkInput
from app_spectre.services.moderation_service import ModerationService, get_moderation_service

router = APIRouter(prefix="/api/moderation", tags=["moderation"])


class SubjectCreateBody(BaseModel):
    canonicalLabel: str = Field(min_length=2, max_length=200)


class IdentityLinkBody(BaseModel):
    provider: str
    providerUserId: str
    displayName: str | None = None
    providerUsername: str | None = None


class CaseCreateBody(BaseModel):
    subjectId: str
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
    evidence: list[dict[str, Any]] = Field(default_factory=list)


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
    except ImportError as exc:  # pragma: no cover - import safety
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Token decoder unavailable") from exc
    payload = decode_token(token.strip())
    role = str(payload.get("role") or "Admin")
    if role not in {"Admin", "Director"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Restricted access")
    return payload


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


@router.post("/subjects")
async def create_subject(
    body: SubjectCreateBody,
    claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    actor_id = str(claims.get("sub") or "").strip() or None
    try:
        subject = await service.create_subject(body.canonicalLabel, actor_id=actor_id)
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
    actor_id = str(claims.get("sub") or "").strip() or None
    try:
        linked = await service.link_identity(
            subject_id,
            IdentityLinkInput(
                provider=body.provider,
                provider_user_id=body.providerUserId,
                display_name=body.displayName,
                provider_username=body.providerUsername,
                linked_by=actor_id,
            ),
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
                "subjectId": body.subjectId,
                "title": body.title,
                "description": body.description,
                "priority": body.priority,
                "reporterIdentityId": body.reporterIdentityId,
                "assigneeIdentityId": body.assigneeIdentityId,
                "openedByIdentityId": str(claims.get("sub") or "").strip() or None,
            }
        )
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
                "evidence": body.evidence,
                "imposedByIdentityId": str(claims.get("sub") or "").strip() or None,
            }
        )
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
                "appellantIdentityId": body.appellantIdentityId,
                "submittedByIdentityId": str(claims.get("sub") or "").strip() or None,
            }
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
                "decidedByIdentityId": str(claims.get("sub") or "").strip() or None,
            },
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"appeal": updated}


@router.get("/audit-events")
async def list_audit_events(
    limit: int = 100,
    _claims: dict[str, Any] = Depends(_require_moderator),
    service: ModerationService = Depends(get_moderation_service),
):
    return {"events": await service.list_audit_events(limit=limit)}
