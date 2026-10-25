from __future__ import annotations

from spectre.view_registry import clear_registered_views, register_persistent_view_once


class DummyBot:
    def __init__(self) -> None:
        self.views: list[object] = []

    def add_view(self, view: object) -> None:
        self.views.append(view)


class DummyView:
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.children = []


def test_register_persistent_view_once_deduplicates_by_key():
    bot = DummyBot()
    first = DummyView(123)
    second = DummyView(123)

    assert register_persistent_view_once(bot, first, key="root:123") is True
    assert register_persistent_view_once(bot, second, key="root:123") is False
    assert len(bot.views) == 1


def test_clear_registered_views_resets_state():
    bot = DummyBot()
    assert register_persistent_view_once(bot, DummyView(7), key="root:7") is True
    clear_registered_views(bot)
    assert register_persistent_view_once(bot, DummyView(7), key="root:7") is True
    assert len(bot.views) == 2
