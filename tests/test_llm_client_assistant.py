import os
os.environ.setdefault("GUILD_ID", "1")
import llm_client


def test_complete_uses_assistant_id(monkeypatch):
    called = {}

    class DummyResp:
        output_text = "resp"

    class DummyClient:
        def __init__(self):
            self.responses = self
        def create(self, **kwargs):
            called.update(kwargs)
            return DummyResp()

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyClient())
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "asst_123")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {"assistant_id": "asst_123", "input": "hi"}


def test_complete_requires_assistant_id(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.responses = self
        def create(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("unexpected call")

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyClient())
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "")
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    import pytest
    with pytest.raises(RuntimeError):
        llm_client.complete("hi")


def test_complete_legacy_chat_completion(monkeypatch):
    called = {}

    class DummyLegacy:
        class ChatCompletion:
            @staticmethod
            def create(**kwargs):
                called.update(kwargs)
                return {"choices": [{"message": {"content": "resp"}}]}

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyLegacy())
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "")
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hi"}]
    }
