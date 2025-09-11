import asyncio
import nextcord

import archive_status
import constants


class DummyMessage:
    def __init__(self):
        self.id = 1

    async def edit(self, *args, **kwargs):
        pass


class DummyChannel:
    def __init__(self):
        self.type = nextcord.ChannelType.text
        self.sent = False

    async def fetch_message(self, msg_id):
        raise Exception("no message")

    async def send(self, *args, **kwargs):
        self.sent = True
        return DummyMessage()


class DummyBot:
    latency = 0

    def __init__(self):
        self.channel = DummyChannel()
        self.last_channel_id = None

    def get_channel(self, channel_id):
        self.last_channel_id = channel_id
        return self.channel


def test_update_status_message_uses_status_channel(monkeypatch):
    bot = DummyBot()
    monkeypatch.setattr(archive_status, "_count_all_files", lambda prefix: 0)
    monkeypatch.setattr(archive_status, "get_build_version", lambda: "v")
    monkeypatch.setattr(archive_status, "get_latest_changelog", lambda: None)
    monkeypatch.setattr(archive_status, "get_system_health", lambda: "ok")
    monkeypatch.setattr(archive_status, "get_status_message_id", lambda: None)
    monkeypatch.setattr(archive_status, "set_status_message_id", lambda mid: None)

    asyncio.run(archive_status.update_status_message(bot))
    assert bot.last_channel_id == constants.STATUS_CHANNEL_ID
    assert bot.channel.sent

