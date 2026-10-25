"""End-to-end moderation flows, run against the in-memory store, the stored
fallback (saved to a SQLite file here) and, when MODERATION_TEST_DATABASE_URL
points at a PostgreSQL database, against Postgres too."""

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


class FakeBlacklist:
    """Stands in for ``guild_blacklist`` so the flows never touch storage."""

    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}

    def blacklist_guild(self, guild_id, *, reason, actor, name=None):
        if not reason:
            raise ValueError("Give a reason for blacklisting the server.")
        entry = {"name": name, "reason": reason, "actor": actor, "banned_at": "2026-10-25T08:00:00+00:00"}
        self.entries[str(guild_id)] = entry
        return {"guild_id": str(guild_id), **entry}

    def unblacklist_guild(self, guild_id):
        return self.entries.pop(str(guild_id), None) is not None


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


@pytest.fixture(
    params=["memory", "stored", pytest.param("postgres", marks=pytest.mark.skipif(not PG_URL, reason="no test database"))]
)
def service(request, tmp_path, monkeypatch):
    discord = FakeDiscord()
    bridge = DiscordModerationBridge(discord.execute, discord.revoke)
    if request.param == "memory":
        repo = ms.InMemoryModerationRepository()
    elif request.param == "stored":
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'spectre.db'}")
        repo = ms.StoredModerationRepository()
    else:
        repo = ms.PostgresModerationRepository(PG_URL)

        async def reset():
            pool = await repo._pool_conn()
            await pool.execute(f"TRUNCATE {TABLES} CASCADE")
            await repo.close()

        _run(reset())
    svc = ms.ModerationService(repo, bridge, FakeBlacklist())
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


SERVER = "1189034578123456789"


def test_cases_against_a_server_or_a_website_user(service):
    async def flow():
        server_case = await service.create_case(
            {"subjectType": "server", "serverId": f" {SERVER} ", "serverName": "Bad Place", "title": "Raid hub", "description": "Raids planned there"},
            ACTOR,
        )
        assert (server_case["subjectType"], server_case["subjectId"]) == ("server", None)
        assert (server_case["serverId"], server_case["serverName"]) == (SERVER, "Bad Place")
        assert (await service.update_case_status(server_case["id"], "investigating", ACTOR))["status"] == "investigating"

        # A website user nobody tracks yet becomes a tracked person, once.
        first = await service.create_case(
            {"discordUserId": "555000222", "displayName": "Viper", "title": "Spam", "description": "Links in #general"}, ACTOR
        )
        again = await service.create_case(
            {"subjectType": "person", "discordUserId": "555000222", "displayName": "Viper", "title": "More spam", "description": "Again"},
            ACTOR,
        )
        assert first["subjectType"] == "person" and first["subjectId"] == again["subjectId"]
        (person,) = await service.list_subjects()
        assert (person["canonicalLabel"], person["discordUserId"]) == ("Viper", "555000222")
        assert {case["id"] for case in await service.list_cases()} == {server_case["id"], first["id"], again["id"]}

        events = [event for event in await service.list_audit_events(50) if event["caseId"] == server_case["id"]]
        assert {event["eventType"] for event in events} == {"case.created", "case.status_changed"}
        assert all(event["metadata"]["serverId"] == SERVER and event["subjectId"] is None for event in events)

        for bad, message in (
            ({"subjectType": "server", "serverId": "nope"}, "Choose the server"),
            ({"subjectType": "person"}, "Choose the person"),
            ({"discordUserId": "abc"}, "numbers only"),
            ({"subjectType": "planet"}, "person or a server"),
            ({"subjectType": "server", "serverId": SERVER, "priority": "urgent"}, "Unknown priority"),
        ):
            with pytest.raises(ValueError, match=message):
                await service.create_case({"title": "Bad", "description": "Bad input", **bad}, ACTOR)
        assert len(await service.list_subjects()) == 1

    _flow(service, flow)


def test_server_blacklists_are_sanctions_in_the_audit_log(service):
    async def flow():
        blacklist = service.server_blacklist
        entry = await service.blacklist_server(SERVER, reason="Fraud", name="Bad Place", actor=ACTOR)
        assert entry["actor"] == "DK (1059522006602752150)" and SERVER in blacklist.entries
        (sanction,) = await service.list_sanctions()
        assert (sanction["subjectType"], sanction["serverId"], sanction["serverName"]) == ("server", SERVER, "Bad Place")
        assert (sanction["status"], sanction["reason"], sanction["subjectId"]) == ("active", "Fraud", None)
        assert sanction["startsAt"]
        assert not service.fake_discord.executed

        # Blacklisting it again replaces the sanction.
        await service.blacklist_server(SERVER, reason="Fraud and raids", actor=ACTOR)
        statuses = {item["reason"]: item["status"] for item in await service.list_sanctions()}
        assert statuses == {"Fraud": "revoked", "Fraud and raids": "active"}
        current = next(item for item in await service.list_sanctions() if item["status"] == "active")

        # Lifting the sanction lifts the blacklist the bot enforces.
        revoked = await service.revoke_sanction(current["id"], "Owner removed the raiders", ACTOR)
        assert revoked["status"] == "revoked" and revoked["revokeReason"] == "Owner removed the raiders"
        assert SERVER not in blacklist.entries
        assert not service.fake_discord.revoked
        assert await service.lift_server_blacklist(SERVER, actor=ACTOR) is False

        events = [event for event in await service.list_audit_events(50) if event["eventType"].startswith("server.")]
        assert sorted(event["eventType"] for event in events) == ["server.blacklisted", "server.blacklisted", "server.unblacklisted"]
        lifted = next(event for event in events if event["eventType"] == "server.unblacklisted")
        assert lifted["metadata"]["serverId"] == SERVER and lifted["metadata"]["reason"] == "Owner removed the raiders"

        with pytest.raises(ValueError):
            await service.blacklist_server(SERVER, reason="", actor=ACTOR)

    _flow(service, flow)


def test_approving_a_server_appeal_lifts_the_blacklist(service):
    async def flow():
        await service.blacklist_server(SERVER, reason="Fraud", name="Bad Place", actor=ACTOR)
        (sanction,) = await service.list_sanctions()
        appeal = await service.create_appeal({"sanctionId": sanction["id"], "appealReason": "New owner, new rules."}, ACTOR)
        decided = await service.update_appeal(appeal["id"], {"status": "approved"}, ACTOR)
        assert decided["sanctionLifted"] is True
        assert SERVER not in service.server_blacklist.entries
        decisions = [event for event in await service.list_audit_events(50) if event["eventType"] == "appeal.decided"]
        assert decisions[0]["metadata"]["serverId"] == SERVER

    _flow(service, flow)


def test_server_sanctions_follow_the_blacklist(service):
    async def flow():
        old_ban = {"guild_id": SERVER, "name": "Bad Place", "reason": "Fraud", "actor": "Ada (42)", "banned_at": "2026-10-01T12:00:00+00:00"}
        await service.sync_server_blacklist([old_ban])
        await service.sync_server_blacklist([old_ban])
        (sanction,) = await service.list_sanctions()
        assert (sanction["status"], sanction["serverId"], sanction["reason"]) == ("active", SERVER, "Fraud")
        assert str(sanction["startsAt"]).startswith("2026-10-01")
        assert sanction["metadata"]["actor"]["name"] == "Ada (42)"

        # Off the list (e.g. lifted while recording failed): the sanction ends.
        await service.sync_server_blacklist([])
        assert (await service.list_sanctions())[0]["status"] == "revoked"

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


def test_stored_records_and_audit_log_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'spectre.db'}")

    async def before_restart():
        discord = FakeDiscord()
        service = ms.ModerationService(ms.StoredModerationRepository(), DiscordModerationBridge(discord.execute, discord.revoke))
        person = await service.create_subject("Site Abuser", ACTOR, discord_user_id="31337")
        await service.create_sanction(
            {"subjectId": person["id"], "target": "website", "sanction": "timeout", "reason": "Abuse"}, ACTOR
        )
        return person["id"]

    async def after_restart(person_id):
        service = ms.ModerationService(ms.StoredModerationRepository())
        events = await service.list_audit_events(limit=50)
        assert {"subject.created", "sanction.imposed"} <= {event["eventType"] for event in events}
        assert [s["sanction"] for s in await service.list_sanctions(person_id)] == ["timeout"]
        # The end time was a datetime when written; the block still applies after reloading it.
        assert [block["userId"] for block in await service.website_blocks()] == ["31337"]

    person_id = _run(before_restart())
    _run(after_restart(person_id))


def test_stored_audit_log_keeps_the_newest_events(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'spectre.db'}")
    monkeypatch.setattr(ms.StoredModerationRepository, "AUDIT_EVENT_LIMIT", 3)

    async def flow():
        repo = ms.StoredModerationRepository()
        for minute in range(5):
            await repo.append_audit_event({"eventType": f"e{minute}", "occurredAt": f"2026-01-01T00:0{minute}:00+00:00"})
        reloaded = ms.StoredModerationRepository()
        assert [event["eventType"] for event in await reloaded.list_audit_events(limit=10)] == ["e4", "e3", "e2"]

    _run(flow())


def test_without_postgres_the_shared_service_is_stored(monkeypatch):
    monkeypatch.delenv("MODERATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(ms, "_shared_service", None)
    assert isinstance(ms.get_moderation_service().repository, ms.StoredModerationRepository)
    monkeypatch.setattr(ms, "_shared_service", None)
