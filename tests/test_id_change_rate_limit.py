import asyncio
from types import SimpleNamespace


def test_id_change_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    import importlib
    operator_login = importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))

    # Prepare operator
    operator_login.get_or_create_operator(1)

    modal_log = {}

    async def run():
        rv = views.RootView()

        async def send_modal(modal):
            modal_log["modal"] = modal

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=1, roles=[]),
            response=SimpleNamespace(send_modal=send_modal, send_message=lambda *a, **k: None),
            followup=SimpleNamespace(send_modal=send_modal),
        )

        await rv.handle_id_change_request(interaction)
        assert "modal" in modal_log

        import time
        # Simulate request recorded
        views._last_id_change_request[1] = time.time()

        captured = {}

        async def send_message(content, ephemeral=True):
            captured["content"] = content

        interaction2 = SimpleNamespace(
            user=SimpleNamespace(id=1, roles=[]),
            response=SimpleNamespace(send_message=send_message, send_modal=send_modal),
            followup=SimpleNamespace(send_modal=send_modal),
        )

        await rv.handle_id_change_request(interaction2)
        assert "24 hours" in captured.get("content", "")

    asyncio.run(run())
