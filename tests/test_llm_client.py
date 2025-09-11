import os
os.environ.setdefault("GUILD_ID", "1")
import llm_client
import types
import pytest


def test_complete_responses_client(monkeypatch):
    called = {}

    class DummyClient:
        def __init__(self):
            self.responses = self

        def create(self, **kwargs):
            called.update(kwargs)
            class Resp:
                output_text = "resp"

            return Resp()

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyClient())
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {"model": "gpt-test", "input": "hi"}


def test_complete_legacy_chat_completion(monkeypatch):
    called = {}

    class DummyLegacy:
        class ChatCompletion:
            @staticmethod
            def create(**kwargs):
                called.update(kwargs)
                return {"choices": [{"message": {"content": "resp"}}]}

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyLegacy())
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hi"}]
    }


def test_run_assistant_handles_failure(monkeypatch):
    """Run should raise when the assistant reports a failure state."""

    class DummyRuns:
        def create(self, **kwargs):
            return types.SimpleNamespace(id="run")

        def retrieve(self, **kwargs):
            return types.SimpleNamespace(status="failed")

    class DummyThreads:
        def __init__(self):
            self.runs = DummyRuns()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="thread")

        class messages:  # pragma: no cover - should not be called
            @staticmethod
            def list(**kwargs):
                raise AssertionError("messages.list should not be called")

    client = types.SimpleNamespace(beta=types.SimpleNamespace(threads=DummyThreads()))

    monkeypatch.setattr(llm_client, "get_client", lambda: client)
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(llm_client, "time", types.SimpleNamespace(monotonic=lambda: 0, sleep=lambda x: None))

    with pytest.raises(RuntimeError):
        llm_client.run_assistant("hi")


def test_run_assistant_times_out(monkeypatch):
    """Run should time out when the assistant never completes."""

    class DummyRuns:
        def create(self, **kwargs):
            return types.SimpleNamespace(id="run")

        def retrieve(self, **kwargs):
            return types.SimpleNamespace(status="queued")

    class DummyThreads:
        def __init__(self):
            self.runs = DummyRuns()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="thread")

        class messages:  # pragma: no cover - should not be called
            @staticmethod
            def list(**kwargs):
                raise AssertionError("messages.list should not be called")

    client = types.SimpleNamespace(beta=types.SimpleNamespace(threads=DummyThreads()))

    counter = {"t": 0}

    def monotonic():
        counter["t"] += 1
        return counter["t"]

    monkeypatch.setattr(llm_client, "get_client", lambda: client)
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(
        llm_client,
        "time",
        types.SimpleNamespace(monotonic=monotonic, sleep=lambda x: None),
    )

    with pytest.raises(TimeoutError):
        llm_client.run_assistant("hi", timeout=2, poll_interval=1)
