import os
import asyncio
import nextcord

os.environ.setdefault("GUILD_ID", "0")

from views import FileErrorReportModal


class DummyUser:
    def __init__(self, name="user", discrim="1234"):
        self.name = name
        self.discriminator = discrim

    def __str__(self):
        return f"{self.name}#{self.discriminator}"


def test_modal_contact_prefilled():
    user = DummyUser("spy", "0001")
    old_loop = asyncio.get_event_loop()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def create():
            return FileErrorReportModal("intel", "file", "link", user)

        modal = loop.run_until_complete(create())
    finally:
        asyncio.set_event_loop(old_loop)
        loop.close()
    contact_fields = [
        item for item in modal.children
        if isinstance(item, nextcord.ui.TextInput) and item.label == "Optional Contact"
    ]
    assert contact_fields[0].default_value == "spy#0001"
