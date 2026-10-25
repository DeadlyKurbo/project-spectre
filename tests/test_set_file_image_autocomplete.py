import main


def test_autocomplete_items(monkeypatch):
    monkeypatch.setattr(main, "list_items_recursive", lambda c, max_items=25: ["alpha", "beta", "alpine"])
    assert main._autocomplete_items("intel", "al") == ["alpha", "alpine"]
    assert main._autocomplete_items("intel", "b") == ["beta"]


def test_autocomplete_items_missing_category(monkeypatch):
    def raiser(c, max_items=25):
        raise FileNotFoundError
    monkeypatch.setattr(main, "list_items_recursive", raiser)
    assert main._autocomplete_items("missing", "") == []


def test_set_file_image_item_autocomplete(monkeypatch):
    monkeypatch.setattr(
        main, "list_items_recursive", lambda c, max_items=25: ["alpha", "beta"]
    )

    class DummyResponse:
        def __init__(self):
            self.choices = None

        async def send_autocomplete(self, choices):
            self.choices = choices

    interaction = type(
        "DummyInteraction",
        (),
        {
            "data": {"options": [{"name": "category", "value": "intel"}]},
            "response": DummyResponse(),
        },
    )()

    import asyncio

    asyncio.run(main.set_file_image_item_autocomplete(interaction, "a"))
    assert interaction.response.choices == ["alpha"]
