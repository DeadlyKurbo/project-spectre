import asyncio

import section_zero
from constants import (
    ARCHIVIST_ROLE_ID,
    LEAD_ARCHIVIST_ROLE_ID,
    ZERO_OPERATOR_ROLE_ID,
    INQUISITOR_ROLE_ID,
)


class DummyRole:
    def __init__(self, rid):
        self.id = rid


class DummyResponse:
    def __init__(self):
        self.kwargs = None

    async def send_message(self, content=None, **kwargs):
        self.kwargs = {"content": content, **kwargs}


class DummyInteraction:
    def __init__(self, role_ids):
        self.user = type("User", (), {"roles": [DummyRole(r) for r in role_ids]})
        self.response = DummyResponse()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_denies_without_section_zero_role():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([])
    allowed = _run(view.interaction_check(inter))
    assert not allowed
    assert inter.response.kwargs["content"] == "Access denied."
    assert inter.response.kwargs["ephemeral"]


def test_denies_archivists_even_with_section_zero_role():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([ZERO_OPERATOR_ROLE_ID, ARCHIVIST_ROLE_ID])
    allowed = _run(view.interaction_check(inter))
    assert not allowed


def test_allows_zero_operator():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([ZERO_OPERATOR_ROLE_ID])
    allowed = _run(view.interaction_check(inter))
    assert allowed
    assert inter.response.kwargs is None


def test_denies_inquisitor():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([INQUISITOR_ROLE_ID])
    allowed = _run(view.interaction_check(inter))
    assert not allowed
