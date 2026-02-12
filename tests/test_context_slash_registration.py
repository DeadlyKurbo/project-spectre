from spectre.context import SpectreContext


class DummyLazarus:
    pass


def test_slash_guild_ids_are_global_by_default():
    context = SpectreContext(
        bot=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]
        logger=None,  # type: ignore[arg-type]
        lazarus_ai=DummyLazarus(),
        guild_ids=[111, 222],
    )

    assert context.slash_guild_ids is None
