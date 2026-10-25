import asyncio
import types

import nextcord
import pytest

import archivist
import guild_blacklist
import mission_reports
from spectre.bot_factory import create_bot, ensure_event_loop
from spectre.blacklist_gate import APPEAL_URL, BLACKLISTED_NOTICE, install_blacklist_gate
from tasks import deploy_queue

BANNED = 1189034578123456789
ALLOWED = 1059522006602752150


@pytest.fixture(autouse=True)
def blacklist(monkeypatch):
    monkeypatch.setattr(guild_blacklist, "_bot_blacklist", frozenset({BANNED}))


class FakeResponse:
    def __init__(self):
        self.sent = []
        self.autocomplete = None

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def send_autocomplete(self, choices):
        self.autocomplete = choices


def _logger():
    return types.SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None)


def _gated_bot(loop, interaction_type=nextcord.InteractionType.application_command):
    passed = []
    interactions = []

    def get_interaction(data):
        interaction = types.SimpleNamespace(
            type=interaction_type, guild_id=int(data["guild_id"]), response=FakeResponse()
        )
        interactions.append(interaction)
        return interaction

    bot = types.SimpleNamespace(
        _connection=types.SimpleNamespace(parsers={"INTERACTION_CREATE": passed.append}),
        loop=loop,
        get_interaction=get_interaction,
    )
    install_blacklist_gate(bot, _logger())
    return bot, passed, interactions


@pytest.mark.parametrize(
    "interaction_type",
    [
        nextcord.InteractionType.application_command,
        nextcord.InteractionType.component,
        nextcord.InteractionType.modal_submit,
    ],
)
def test_blacklisted_server_gets_the_notice_with_an_appeal_link(interaction_type):
    async def scenario():
        bot, passed, interactions = _gated_bot(asyncio.get_running_loop(), interaction_type)
        bot._connection.parsers["INTERACTION_CREATE"]({"guild_id": str(BANNED), "type": interaction_type.value})
        await asyncio.sleep(0)
        return passed, interactions

    passed, [interaction] = asyncio.run(scenario())
    assert passed == []
    [(content, kwargs)] = interaction.response.sent
    assert content == BLACKLISTED_NOTICE
    assert kwargs["ephemeral"] is True
    [button] = kwargs["view"].children
    assert button.url == APPEAL_URL == "https://discord.gg/rF2CSjzrEd"


def test_autocomplete_in_a_blacklisted_server_gets_no_suggestions():
    async def scenario():
        bot, passed, interactions = _gated_bot(
            asyncio.get_running_loop(), nextcord.InteractionType.application_command_autocomplete
        )
        bot._connection.parsers["INTERACTION_CREATE"]({"guild_id": str(BANNED), "type": 4})
        await asyncio.sleep(0)
        return passed, interactions

    passed, [interaction] = asyncio.run(scenario())
    assert passed == []
    assert interaction.response.autocomplete == []


@pytest.mark.parametrize("data", [{"guild_id": str(ALLOWED), "type": 2}, {"type": 2}])
def test_other_servers_and_dms_pass_through(data):
    async def scenario():
        bot, passed, interactions = _gated_bot(asyncio.get_running_loop())
        bot._connection.parsers["INTERACTION_CREATE"](data)
        return passed, interactions

    passed, interactions = asyncio.run(scenario())
    assert passed == [data]
    assert interactions == []


def test_gate_hooks_into_the_installed_nextcord():
    # Fails loudly if a nextcord upgrade moves the interaction parser.
    ensure_event_loop()
    bot = create_bot()
    original = bot._connection.parsers["INTERACTION_CREATE"]
    install_blacklist_gate(bot, _logger())
    assert bot._connection.parsers["INTERACTION_CREATE"] is not original


def test_archive_menus_are_not_deployed_in_blacklisted_servers(monkeypatch):
    monkeypatch.setattr(archivist, "invalidate_config", lambda _gid: pytest.fail("menu deploy started"))
    assert asyncio.run(archivist.refresh_menus(types.SimpleNamespace(id=BANNED))) is False


def test_mission_report_menus_are_not_deployed_in_blacklisted_servers(monkeypatch):
    monkeypatch.setattr(mission_reports, "invalidate_config", lambda _gid: pytest.fail("menu deploy started"))
    assert asyncio.run(mission_reports.refresh_mission_reports_menu(types.SimpleNamespace(id=BANNED))) is None


def test_queued_deploys_for_blacklisted_servers_are_dropped(monkeypatch):
    deleted = []
    monkeypatch.setattr(deploy_queue, "list_dir", lambda *_a, **_k: ([], [(f"{BANNED}.json", 10)]))
    monkeypatch.setattr(deploy_queue, "delete_file", deleted.append)
    monkeypatch.setattr(deploy_queue, "refresh_menus", lambda *_a, **_k: pytest.fail("menu deployed"))
    bot = types.SimpleNamespace(get_guild=lambda _gid: pytest.fail("guild looked up"))

    asyncio.run(deploy_queue.consume_deploy_queue(bot))
    assert deleted == [f"deploy-queue/{BANNED}.json"]
