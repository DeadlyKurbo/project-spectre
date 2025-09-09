import asyncio

import section_zero
from constants import (
    ARCHIVIST_ROLE_ID,
    ZERO_OPERATOR_ROLE_ID,
    INQUISITOR_ROLE_ID,
    SECTION_ZERO_ROLE_IDS,
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


def test_denies_archivist_without_section_zero_role():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([ARCHIVIST_ROLE_ID])
    allowed = _run(view.interaction_check(inter))
    assert not allowed


def test_allows_archivist_with_section_zero_role():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([ZERO_OPERATOR_ROLE_ID, ARCHIVIST_ROLE_ID])
    allowed = _run(view.interaction_check(inter))
    assert allowed
    assert inter.response.kwargs is None


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


def test_all_section_zero_roles_allowed():
    view = section_zero.SectionZeroControlView()
    for rid in SECTION_ZERO_ROLE_IDS:
        inter = DummyInteraction([rid])
        allowed = _run(view.interaction_check(inter))
        assert allowed


def test_manage_menu_allows_section_zero_roles():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([ZERO_OPERATOR_ROLE_ID])
    _run(view.open_manage(inter))
    assert inter.response.kwargs["embed"].title == "SECTION ZERO // MANAGE MENU"
    assert isinstance(inter.response.kwargs["view"], section_zero.SectionZeroManageView)


def test_manage_menu_limits_to_section_zero_categories():
    view = section_zero.SectionZeroControlView()
    inter = DummyInteraction([ZERO_OPERATOR_ROLE_ID])
    _run(view.open_manage(inter))
    manage_view = inter.response.kwargs["view"]
    import archivist

    try:
        assert archivist._categories_for_select() == section_zero.SECTION_ZERO_EXTRA_CATEGORIES
    finally:
        manage_view.stop()
