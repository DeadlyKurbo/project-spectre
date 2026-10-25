"""End-to-end moderation flows, run against the in-memory store and, when
MODERATION_TEST_DATABASE_URL points at a PostgreSQL database, against Postgres too."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
import pytest

from app_spectre.services import moderation_service as ms
from spectre.moderation.discord_bridge import DiscordModerationBridge
from spectre.moderation.discord_rest import DiscordRestModerator

PG_URL = os.getenv("MODERATION_TEST_DATABASE_URL", "").strip()
ACTOR = {"id": "1059522006602752150", "name": "DK"}
TABLES = "moderated_subjects, user_identities, moderation_cases, case_events, sanctions, enforcement_actions, appeals, audit_events"


class FakeDiscord:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.executed: list = []
        self.revoked: list = []

    async def execute(self, request):
        self.executed.append(request)
        return {"ok": self.ok, "error": None if self.ok else "The bot is missing permissions."}

    async def revoke(self, request):
        self.revoked.append(request)
        return {"ok": True}


def _run(coro):
    return asyncio.run(coro)


def _flow(service, flow):
    """Run a test flow and close the repository in the same event loop."""

    async def wrapper():
        try:
            await flow()
        finally:
            await service.repository.close()

    _run(wrapper())


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.skipif(not PG_URL, reason="no test database"))])
def service(request):
    discord = FakeDiscord()
    bridge = DiscordModerationBridge(discord.execute, discord.revoke)
    if request.param == "memory":
        repo = ms.InMemoryModerationRepository()
    else:
        repo = ms.PostgresModerationRepository(PG_URL)

        async def reset():
            pool = await repo._pool_conn()
            await pool.execute(f"TRUNCATE {TABLES} CASCADE")
            await repo.close()

        _run(reset())
    svc = ms.ModerationService(repo, bridge)
    svc.fake_discord = discord
    return svc


def test_discord_ban_uses_linked_account_and_can_be_revoked(service):
    async def flow():
        person = await service.create_subject("Rule Breaker", ACTOR, discord_user_id="555000111")
        ban = await service.create_sanction(
            {"subjectId": person["id"], "target": "discord", "sanction": "ban", "reason": "Raiding", "guildId": "42"},
            ACTOR,
        )
        assert ban["status"] == "active"
        sent = service.fake_discord.executed[-1]
        assert sent.target_user_id == "555000111"
        assert sent.guild_id == "42"

        revoked = await service.revoke_sanction(ban["id"], "Served time", ACTOR)
        assert revoked["status"] == "revoked"
        assert service.fake_discord.revoked[-1].target_user_id == "555000111"
        listed = await service.list_sanctions(person["id"])
        assert listed[0]["status"] == "revoked"
        with pytest.raises(ValueError):
            await service.revoke_sanction(ban["id"], "Again", ACTOR)

    _flow(service, flow)


def test_mute_sets_an_end_time_and_failures_are_recorded(service):
    async def flow():
        person = await service.create_subject("Spammer", ACTOR, discord_user_id="777")
        mute = await service.create_sanction(
            {"subjectId": person["id"], "target": "discord", "sanction": "timeout", "reason": "Spam", "guildId": "42"},
            ACTOR,
        )
        assert mute["status"] == "active"
        assert service.fake_discord.executed[-1].metadata["durationSeconds"] == 24 * 3600

        service.fake_discord.ok = False
        kick = await service.create_sanction(
            {"subjectId": person["id"], "target": "discord", "sanction": "kick", "reason": "Spam", "guildId": "42"},
            ACTOR,
        )
        assert kick["status"] == "failed"
        assert "permissions" in kick["error"]

    _flow(service, flow)


def test_sanctions_explain_what_is_missing(service):
    async def flow():
        nobody = await service.create_subject("No accounts", ACTOR)
        with pytest.raises(ValueError, match="Link this person's Discord account"):
            await service.create_sanction(
                {"subjectId": nobody["id"], "target": "discord", "sanction": "ban", "reason": "x" * 5, "guildId": "1"},
                ACTOR,
            )
        person = await service.create_subject("Has account", ACTOR, discord_user_id="9")
        with pytest.raises(ValueError, match="Choose the Discord server"):
            await service.create_sanction(
                {"subjectId": person["id"], "target": "discord", "sanction": "kick", "reason": "x" * 5}, ACTOR
            )
        with pytest.raises(ValueError, match="not available"):
            await service.create_sanction(
                {"subjectId": person["id"], "target": "website", "sanction": "kick", "reason": "x" * 5}, ACTOR
            )

    _flow(service, flow)


def test_website_ban_blocks_linked_account_until_revoked(service):
    async def flow():
        person = await service.create_subject("Site Abuser", ACTOR, discord_user_id="31337")
        ban = await service.create_sanction(
            {"subjectId": person["id"], "target": "website", "sanction": "ban", "reason": "Abuse"}, ACTOR
        )
        assert ban["status"] == "active"
        assert not service.fake_discord.executed
        blocks = await service.website_blocks()
        assert [b["userId"] for b in blocks] == ["31337"]

        await service.revoke_sanction(ban["id"], "Appeal", ACTOR)
        assert await service.website_blocks() == []

    _flow(service, flow)


def test_case_status_and_appeal_approval_lifts_sanction(service):
    async def flow():
        person = await service.create_subject("Appellant", ACTOR, discord_user_id="404")
        case = await service.create_case(
            {"subjectId": person["id"], "title": "Harassment", "description": "Reported in #general", "priority": "high"},
            ACTOR,
        )
        assert case["status"] == "open"
        resolved = await service.update_case_status(case["id"], "resolved", ACTOR, note="Handled")
        assert resolved["status"] == "resolved"
        assert resolved["resolvedAt"]

        ban = await service.create_sanction(
            {"subjectId": person["id"], "caseId": case["id"], "target": "website", "sanction": "suspension", "reason": "Harassment"},
            ACTOR,
        )
        appeal = await service.create_appeal({"sanctionId": ban["id"], "appealReason": "I was hacked."}, ACTOR)
        assert appeal["status"] == "submitted"
        decided = await service.update_appeal(appeal["id"], {"status": "approved", "decisionSummary": "Verified"}, ACTOR)
        assert decided["status"] == "approved"
        assert decided["sanctionLifted"] is True
        assert (await service.list_sanctions(person["id"]))[0]["status"] == "revoked"

        events = await service.list_audit_events(50)
        types = {event["eventType"] for event in events}
        assert {"subject.created", "identity.linked", "case.created", "sanction.imposed", "sanction.revoked", "appeal.decided"} <= types
        assert all(event["metadata"]["actor"]["id"] == ACTOR["id"] for event in events)

    _flow(service, flow)


def test_unknown_ids_are_not_found_instead_of_crashing(service):
    async def flow():
        assert await service.repository.get_subject("not-a-uuid") is None
        with pytest.raises(LookupError):
            await service.update_case_status("not-a-uuid", "resolved", ACTOR)
        with pytest.raises(LookupError):
            await service.revoke_sanction("00000000-0000-0000-0000-000000000000", "x" * 4, ACTOR)

    _flow(service, flow)


def _rest(handler):
    transport = httpx.MockTransport(handler)
    return DiscordRestModerator("bot-token", client_factory=lambda: httpx.AsyncClient(transport=transport))


def _request(action, **kw):
    from spectre.moderation.discord_bridge import DiscordModerationRequest

    return DiscordModerationRequest(
        operation_key="op", subject_id="uuid", action=action, guild_id=kw.pop("guild", "42"),
        reason="Rule 3", target_user_id=kw.pop("user", "555"), metadata=kw,
    )


def test_rest_moderator_calls_the_right_discord_endpoints():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, req.headers.get("authorization"), req.content))
        if req.url.path == "/api/v10/users/@me/channels":
            return httpx.Response(200, json={"id": "9000"})
        return httpx.Response(204)

    mod = _rest(handler)
    assert _run(mod.execute(_request("ban")))["ok"]
    assert _run(mod.execute(_request("timeout", durationSeconds=3600)))["ok"]
    assert _run(mod.execute(_request("kick")))["ok"]
    assert _run(mod.execute(_request("warning", guildName="Section Zero")))["ok"]
    assert _run(mod.revoke(_request("ban")))["ok"]
    paths = [(m, p) for m, p, _a, _c in calls]
    assert paths == [
        ("PUT", "/api/v10/guilds/42/bans/555"),
        ("PATCH", "/api/v10/guilds/42/members/555"),
        ("DELETE", "/api/v10/guilds/42/members/555"),
        ("POST", "/api/v10/users/@me/channels"),
        ("POST", "/api/v10/channels/9000/messages"),
        ("DELETE", "/api/v10/guilds/42/bans/555"),
    ]
    assert all(auth == "Bot bot-token" for _m, _p, auth, _c in calls)
    assert b"communication_disabled_until" in calls[1][3]


def test_rest_moderator_turns_discord_errors_into_plain_language():
    def handler(_req):
        return httpx.Response(403, json={"code": 50013, "message": "Missing Permissions"})

    result = _run(_rest(handler).execute(_request("ban")))
    assert result["ok"] is False
    assert "missing permissions" in result["error"]
    assert _run(_rest(handler).execute(_request("ban", user="")))["error"].startswith("No Discord account")
